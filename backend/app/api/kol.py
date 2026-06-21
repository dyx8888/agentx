"""
KOL Search API (达人搜索 API)

Endpoints:
- POST /api/kol/search - Multi-condition KOL search
- GET /api/kol/{kol_id} - KOL detail
- POST /api/kol/export - Export KOL list
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.core.logging import get_logger
from app.database.models import KolProfile

logger = get_logger(__name__)

router = APIRouter(prefix="/api/kol", tags=["kol"])

# 支持的平台
VALID_PLATFORMS = ["douyin", "xiaohongshu", "kuaishou", "bilibili", "weibo", "all"]

# 支持的排序方式
VALID_SORT_BY = ["followers", "engagement_rate", "relevance"]


# ============================================================
# Pydantic Schemas
# ============================================================

class KolSearchRequest(BaseModel):
    """达人搜索请求"""
    query: str = Field(..., description="搜索关键词")
    platform: str = Field("all", description="平台筛选")
    category: Optional[str] = Field(None, description="分类筛选")
    min_followers: int = Field(0, ge=0, description="最小粉丝数")
    max_followers: Optional[int] = Field(None, description="最大粉丝数")
    min_engagement_rate: float = Field(0, ge=0, description="最低互动率")
    sort_by: str = Field("relevance", description="排序方式")
    limit: int = Field(20, ge=1, le=50, description="返回数量")

    @field_validator('platform')
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if v not in VALID_PLATFORMS:
            raise ValueError(f"不支持的平台: {v}，支持的平台: {VALID_PLATFORMS}")
        return v

    @field_validator('sort_by')
    @classmethod
    def validate_sort_by(cls, v: str) -> str:
        if v not in VALID_SORT_BY:
            raise ValueError(f"不支持的排序方式: {v}，支持的排序: {VALID_SORT_BY}")
        return v


class KolSearchResponse(BaseModel):
    """达人搜索响应"""
    total: int
    results: list[dict]
    search_id: str


class KolExportRequest(BaseModel):
    """达人导出请求"""
    kol_ids: list[int] = Field(..., description="达人 ID 列表")
    format: str = Field("csv", description="导出格式")

    @field_validator('format')
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in ["csv", "pdf"]:
            raise ValueError(f"不支持的导出格式: {v}，支持的格式: csv, pdf")
        return v


# ============================================================
# Helper: format KOL to dict
# ============================================================

def _kol_to_dict(kol: KolProfile) -> dict:
    """将 KolProfile ORM 模型转为字典"""
    return {
        "id": kol.id,
        "name": kol.name,
        "platform": kol.platform,
        "followers": kol.followers,
        "engagement_rate": kol.engagement_rate,
        "category": kol.category,
        "sub_category": kol.sub_category,
        "avg_views": kol.avg_views,
        "avg_likes": kol.avg_likes,
        "avg_comments": kol.avg_comments,
        "price_range": f"{kol.price_range_low}-{kol.price_range_high}" if kol.price_range_low and kol.price_range_high else None,
        "location": kol.location,
        "verified": kol.verified,
        "bio": kol.bio,
        "avatar_url": kol.avatar_url,
    }


# ============================================================
# API Endpoints
# ============================================================

@router.post("/search", response_model=KolSearchResponse)
async def search_kols_endpoint(
    request: KolSearchRequest,
    company_id: str = Query(default="", description="公司 ID"),
    user_id: int = Query(default=0, description="用户 ID"),
):
    """
    达人搜索
    
    支持多条件筛选：平台、分类、粉丝数、互动率
    支持排序：按粉丝数、互动率、相关性
    """
    from app.agents.kol_search import search_kols, save_search_history
    from app.database import db as db_proxy

    try:
        with db_proxy.get_session() as session:
            results = search_kols(
                session=session,
                company_id=int(company_id) if company_id else 0,
                query=request.query,
                platform=request.platform if request.platform != "all" else None,
                category=request.category,
                min_followers=request.min_followers if request.min_followers > 0 else None,
                max_followers=request.max_followers if request.max_followers and request.max_followers > 0 else None,
                min_engagement_rate=request.min_engagement_rate if request.min_engagement_rate > 0 else None,
                sort_by=request.sort_by,
                limit=request.limit,
            )

            # 保存搜索历史
            if user_id > 0:
                try:
                    save_search_history(
                        session=session,
                        user_id=user_id,
                        company_id=int(company_id) if company_id else 0,
                        query=request.query,
                        platform_filter=request.platform if request.platform != "all" else None,
                        category_filter=request.category,
                        result_count=len(results),
                    )
                except Exception as hist_err:
                    logger.warning("kol_search_history_save_failed", error=str(hist_err))

            kol_dicts = [_kol_to_dict(r) for r in results]
            search_id = str(uuid.uuid4())[:8]

            logger.info(
                "kol_search_api",
                query=request.query,
                total=len(results),
                search_id=search_id,
            )

            return KolSearchResponse(
                total=len(results),
                results=kol_dicts,
                search_id=search_id,
            )

    except Exception as e:
        logger.error("kol_search_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.get("/{kol_id}")
async def get_kol_detail(
    kol_id: int,
    company_id: str = Query(default="", description="公司 ID"),
):
    """
    达人详情
    
    获取指定达人的详细信息
    """
    from app.database import db as db_proxy

    try:
        with db_proxy.get_session() as session:
            kol = (
                session.query(KolProfile)
                .filter(
                    KolProfile.id == kol_id,
                    KolProfile.company_id == int(company_id) if company_id else 0,
                )
                .first()
            )

            if not kol:
                raise HTTPException(status_code=404, detail="达人不存在")

            return _kol_to_dict(kol)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("kol_detail_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"获取达人详情失败: {str(e)}")


@router.post("/export")
async def export_kols(
    request: KolExportRequest,
    company_id: str = Query(default="", description="公司 ID"),
):
    """
    导出达人列表
    
    支持 CSV 和 PDF 格式
    """
    from app.database import db as db_proxy
    from fastapi.responses import StreamingResponse
    import csv
    import io

    try:
        with db_proxy.get_session() as session:
            kols = (
                session.query(KolProfile)
                .filter(
                    KolProfile.id.in_(request.kol_ids),
                    KolProfile.company_id == int(company_id) if company_id else 0,
                )
                .all()
            )

            if request.format == "csv":
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["ID", "姓名", "平台", "粉丝数", "互动率", "分类", "报价区间", "所在地"])
                for k in kols:
                    writer.writerow([
                        k.id, k.name, k.platform, k.followers,
                        k.engagement_rate, k.category,
                        f"{k.price_range_low}-{k.price_range_high}" if k.price_range_low else "",
                        k.location or "",
                    ])

                output.seek(0)
                return StreamingResponse(
                    iter([output.getvalue()]),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=kols.csv"},
                )
            else:
                # PDF 导出暂不支持，返回提示
                raise HTTPException(status_code=501, detail="PDF 导出暂未实现")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("kol_export_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")

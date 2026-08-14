"""
KOL Search API (达人搜索 API)

Endpoints:
- POST /api/kol/search - Multi-condition KOL search
- GET /api/kol/{kol_id} - KOL detail
- POST /api/kol/export - Export KOL list
"""

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.database import User
from app.database.models import KolProfile

logger = get_logger(__name__)

router = APIRouter(tags=["kol"])

# 支持的平台
VALID_PLATFORMS = ["douyin", "xiaohongshu", "kuaishou", "bilibili", "weibo", "all"]

# 支持的排序方式
VALID_SORT_BY = ["followers", "engagement_rate", "relevance"]

# 生产可接受的数据来源。mock/demo/seed 只允许测试脚本内部使用，正式导入接口拒绝。
VALID_IMPORT_DATA_SOURCES = {
    "manual_upload",
    "public_web",
    "cached_snapshot",
    "official_api",
    "partner_api",
}

SOURCE_LABELS = {
    "manual": "人工导入",
    "manual_upload": "人工导入",
    "public_web": "公开网页整理",
    "cached_snapshot": "历史缓存快照",
    "official_api": "平台授权数据",
    "partner_api": "平台授权数据",
}

NON_PRODUCTION_DATA_SOURCES = {"mock", "demo", "seed", "sample"}
NON_PRODUCTION_SOURCE_LABEL_TOKENS = {
    "mock",
    "demo",
    "seed",
    "sample",
    "演示",
    "示例",
}


# ============================================================
# Pydantic Schemas
# ============================================================


class KolSearchRequest(BaseModel):
    """达人搜索请求"""

    query: str = Field(..., description="搜索关键词")
    platform: str = Field("all", description="平台筛选")
    category: str | None = Field(None, description="分类筛选")
    min_followers: int = Field(0, ge=0, description="最小粉丝数")
    max_followers: int | None = Field(None, description="最大粉丝数")
    min_engagement_rate: float = Field(0, ge=0, description="最低互动率")
    sort_by: str = Field("relevance", description="排序方式")
    limit: int = Field(20, ge=1, le=50, description="返回数量")

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if v not in VALID_PLATFORMS:
            raise ValueError(f"不支持的平台: {v}，支持的平台: {VALID_PLATFORMS}")
        return v

    @field_validator("sort_by")
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
    data_source_summary: dict[str, int] = Field(
        default_factory=dict, description="结果数据来源统计，如 manual/official_api/import/demo/mock"
    )
    data_source_warning: str | None = Field(
        default=None, description="数据来源风险提示；为空表示未发现明显来源风险"
    )
    source_labels: dict[str, str] = Field(default_factory=dict, description="数据来源可读标签")


class KolExportRequest(BaseModel):
    """达人导出请求"""

    kol_ids: list[int] = Field(default_factory=list, description="达人 ID 列表")
    query: str = Field("", description="不传 kol_ids 时使用的搜索关键词")
    platform: str = Field("all", description="不传 kol_ids 时使用的平台筛选")
    category: str | None = Field(None, description="不传 kol_ids 时使用的分类筛选")
    min_followers: int = Field(0, ge=0, description="最小粉丝数")
    max_followers: int | None = Field(None, description="最大粉丝数")
    min_engagement_rate: float = Field(0, ge=0, description="最低互动率")
    sort_by: str = Field("relevance", description="排序方式")
    limit: int = Field(50, ge=1, le=500, description="按筛选导出时的最大数量")
    format: str = Field("csv", description="导出格式")

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if v not in VALID_PLATFORMS:
            raise ValueError(f"不支持的平台: {v}，支持的平台: {VALID_PLATFORMS}")
        return v

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, v: str) -> str:
        if v not in VALID_SORT_BY:
            raise ValueError(f"不支持的排序方式: {v}，支持的排序: {VALID_SORT_BY}")
        return v

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in ["csv", "pdf"]:
            raise ValueError(f"不支持的导出格式: {v}，支持的格式: csv, pdf")
        return v


class KolImportItem(BaseModel):
    """单条达人导入记录。"""

    name: str = Field(..., min_length=1, max_length=100, description="达人名称")
    platform: str = Field(..., description="平台，如 douyin/xiaohongshu")
    platform_uid: str | None = Field(None, max_length=100, description="平台唯一 ID；为空时按名称生成导入 ID")
    followers: int = Field(0, ge=0, description="粉丝数")
    engagement_rate: float = Field(0, ge=0, description="互动率，百分比数值")
    category: str = Field("其他", min_length=1, max_length=50, description="内容分类")
    sub_category: str | None = Field(None, max_length=50, description="细分分类")
    avg_views: int = Field(0, ge=0)
    avg_likes: int = Field(0, ge=0)
    avg_comments: int = Field(0, ge=0)
    avg_shares: int = Field(0, ge=0)
    price_range_low: int | None = Field(None, ge=0)
    price_range_high: int | None = Field(None, ge=0)
    location: str | None = Field(None, max_length=100)
    verified: bool = False
    bio: str | None = None
    avatar_url: str | None = Field(None, max_length=500)
    contact_info: str | None = None
    data_source: str = Field(
        "manual_upload",
        description="数据来源：manual_upload/public_web/cached_snapshot/official_api/partner_api",
    )
    source_label: str | None = Field(None, max_length=100, description="数据来源可读标签")
    source_url: str | None = Field(None, max_length=1000, description="公开网页或外部来源 URL")
    source_note: str | None = Field(None, max_length=1000, description="来源备注")
    is_active: bool = True

    @field_validator("platform")
    @classmethod
    def validate_import_platform(cls, v: str) -> str:
        if v not in VALID_PLATFORMS or v == "all":
            raise ValueError(f"不支持的平台: {v}，支持的平台: {VALID_PLATFORMS[:-1]}")
        return v

    @field_validator("data_source")
    @classmethod
    def validate_data_source(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        if normalized not in VALID_IMPORT_DATA_SOURCES:
            raise ValueError(
                "不支持的数据来源；正式导入只允许 "
                f"{sorted(VALID_IMPORT_DATA_SOURCES)}，不允许 mock/demo/seed 静默进入生产数据。"
            )
        return normalized

    @field_validator("source_label")
    @classmethod
    def validate_source_label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        label = v.strip()
        if not label:
            return None
        if _is_non_production_source_label(label):
            raise ValueError("source_label 不允许标记为 mock/demo/seed/sample")
        return label


class KolImportRequest(BaseModel):
    """达人批量导入请求。"""

    items: list[KolImportItem] = Field(..., min_length=1, max_length=200)
    dry_run: bool = Field(False, description="只校验不写入")


class KolImportResponse(BaseModel):
    """达人导入响应。"""

    imported: int
    updated: int
    skipped: int
    dry_run: bool
    data_source_summary: dict[str, int]
    data_source_warning: str | None = None
    source_labels: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


# ============================================================
# Helper: format KOL to dict
# ============================================================


def _source_to_label(source: str | None, explicit_label: str | None = None) -> str:
    if explicit_label and explicit_label.strip():
        return explicit_label.strip()
    normalized = (source or "").strip().lower()
    return SOURCE_LABELS.get(normalized, normalized or "未知来源")


def _is_non_production_source(source: str | None) -> bool:
    normalized = (source or "").strip().lower()
    return normalized in NON_PRODUCTION_DATA_SOURCES


def _is_non_production_source_label(label: str | None) -> bool:
    normalized = (label or "").strip().lower()
    return any(token in normalized for token in NON_PRODUCTION_SOURCE_LABEL_TOKENS)


def _source_labels_for_summary(summary: dict[str, int]) -> dict[str, str]:
    return {source: _source_to_label(source) for source in summary}


def _kol_to_dict(kol: KolProfile) -> dict:
    """将 KolProfile ORM 模型转为字典"""
    data_source = getattr(kol, "data_source", "manual")
    if not isinstance(data_source, str) or not data_source:
        data_source = "manual"
    data_source = data_source.strip().lower()
    source_label = _source_to_label(data_source)
    followers = getattr(kol, "followers", 0) or 0
    source_available_for_search = not _is_non_production_source(data_source)
    last_synced_at = getattr(kol, "last_synced_at", None)
    if hasattr(last_synced_at, "isoformat"):
        last_synced_at = last_synced_at.isoformat()
    elif not isinstance(last_synced_at, str):
        last_synced_at = None

    return {
        "id": kol.id,
        "name": kol.name,
        "platform": kol.platform,
        "followers": followers,
        "follower_count": followers,
        "followers_count": followers,
        "engagement_rate": kol.engagement_rate,
        "category": kol.category,
        "sub_category": kol.sub_category,
        "avg_views": kol.avg_views,
        "avg_likes": kol.avg_likes,
        "avg_comments": kol.avg_comments,
        "price_range": f"{kol.price_range_low}-{kol.price_range_high}"
        if kol.price_range_low and kol.price_range_high
        else None,
        "location": kol.location,
        "verified": kol.verified,
        "bio": kol.bio,
        "avatar_url": kol.avatar_url,
        "source": data_source,
        "data_source": data_source,
        "source_label": source_label,
        "source_available_for_search": source_available_for_search,
        "source_url": getattr(kol, "source_url", None),
        "source_note": getattr(kol, "source_note", None),
        "last_synced_at": last_synced_at,
    }


def _resolve_company_id(current_user: User | None, explicit_company_id: str | None = None):
    """Prefer authenticated user company_id; allow explicit value for direct/internal calls."""
    authenticated_company_id = getattr(current_user, "company_id", None)
    if authenticated_company_id is not None:
        return authenticated_company_id
    if explicit_company_id in (None, ""):
        return None
    try:
        return int(explicit_company_id)
    except (TypeError, ValueError):
        return explicit_company_id


def _stable_platform_uid(item: KolImportItem) -> str:
    """Return a stable platform UID for manual/public imports without native IDs."""
    if item.platform_uid:
        return item.platform_uid.strip()
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", item.name.strip()).strip("-")
    slug = slug[:70] or uuid.uuid4().hex[:12]
    return f"{item.data_source}:{slug}"


def _import_summary(items: list[KolImportItem]) -> tuple[dict[str, int], str | None]:
    summary: dict[str, int] = {}
    for item in items:
        summary[item.data_source] = summary.get(item.data_source, 0) + 1

    if summary and not any(source == "official_api" for source in summary):
        return (
            summary,
            "imported_non_official_sources: 当前导入数据不是官方平台 API 直连，结果可用于业务测试和人工运营，但上线报告需标明来源。",
        )
    return summary, None


def _summarize_kol_data_sources(kol_dicts: list[dict]) -> tuple[dict[str, int], str | None]:
    """Summarize KOL data provenance so callers can tell real data from placeholders."""
    summary: dict[str, int] = {}
    for item in kol_dicts:
        source = item.get("data_source") or "unknown"
        if not isinstance(source, str):
            source = "unknown"
        summary[source] = summary.get(source, 0) + 1

    if not kol_dicts:
        return (
            summary,
            "no_kol_data_found: 当前公司没有匹配达人数据；这不是官方 API 成功，只表示需要接入平台 API 或导入达人数据。",
        )

    risky_sources = {"mock", "demo", "seed", "sample"}
    risky = sorted(set(summary) & risky_sources)
    if risky:
        return (
            summary,
            f"non_production_data_source: 结果包含 {', '.join(risky)} 数据源，不能当作真实业务数据验收。",
        )

    return summary, None


def _pdf_escape(value) -> str:
    text = "" if value is None else str(value)
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_simple_kol_pdf(kols: list[KolProfile]) -> bytes:
    lines = ["KOL Export", f"Total: {len(kols)}", ""]
    for idx, kol in enumerate(kols, start=1):
        price = ""
        if getattr(kol, "price_range_low", None):
            price = f" price {kol.price_range_low}-{getattr(kol, 'price_range_high', '')}"
        lines.append(
            (
                f"{idx}. {getattr(kol, 'name', '')} | {getattr(kol, 'platform', '')} | "
                f"followers {getattr(kol, 'followers', 0) or 0} | "
                f"engagement {getattr(kol, 'engagement_rate', 0) or 0}% | "
                f"{getattr(kol, 'category', '')}{price}"
            )[:115]
        )
        if len(lines) >= 44:
            lines.append("... truncated")
            break

    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for line in lines:
        content_lines.append(f"({_pdf_escape(line)}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


# ============================================================
# API Endpoints
# ============================================================


@router.post("/import", response_model=KolImportResponse)
async def import_kols_endpoint(
    request: KolImportRequest,
    company_id: str | None = Query(default=None, include_in_schema=False),
    current_user: User = Depends(get_current_active_user),
):
    """
    批量导入达人数据。

    用于没有企业 API 权限时的正式替代入口：支持人工整理、公开网页、缓存快照、
    合作方 API 或官方 API 导入。接口会保留 data_source，并拒绝 mock/demo/seed
    作为正式导入来源，避免生产环境静默使用演示数据。
    """
    from app.database import db as db_proxy

    resolved_company_id = _resolve_company_id(current_user, company_id)
    if resolved_company_id is None:
        raise HTTPException(status_code=400, detail="无法确定 company_id")

    imported = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    data_source_summary, data_source_warning = _import_summary(request.items)

    try:
        with db_proxy.get_session() as session:
            for idx, item in enumerate(request.items, start=1):
                if (
                    item.price_range_low is not None
                    and item.price_range_high is not None
                    and item.price_range_low > item.price_range_high
                ):
                    skipped += 1
                    errors.append(f"items[{idx}]: price_range_low 不能大于 price_range_high")
                    continue

                platform_uid = _stable_platform_uid(item)
                existing = (
                    session.query(KolProfile)
                    .filter(
                        KolProfile.company_id == resolved_company_id,
                        KolProfile.platform == item.platform,
                        KolProfile.platform_uid == platform_uid,
                    )
                    .first()
                )

                if request.dry_run:
                    if existing:
                        updated += 1
                    else:
                        imported += 1
                    continue

                payload = {
                    "company_id": resolved_company_id,
                    "name": item.name.strip(),
                    "platform": item.platform,
                    "platform_uid": platform_uid,
                    "followers": item.followers,
                    "engagement_rate": item.engagement_rate,
                    "category": item.category.strip(),
                    "sub_category": item.sub_category,
                    "avg_views": item.avg_views,
                    "avg_likes": item.avg_likes,
                    "avg_comments": item.avg_comments,
                    "avg_shares": item.avg_shares,
                    "price_range_low": item.price_range_low,
                    "price_range_high": item.price_range_high,
                    "location": item.location,
                    "verified": item.verified,
                    "bio": item.bio.strip() if item.bio else None,
                    "avatar_url": item.avatar_url,
                    "contact_info": item.contact_info,
                    "data_source": item.data_source,
                    "source_url": item.source_url,
                    "source_note": item.source_note,
                    "last_synced_at": datetime.utcnow(),
                    "is_active": item.is_active,
                    "updated_at": datetime.utcnow(),
                }

                if existing:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                    updated += 1
                else:
                    session.add(KolProfile(**payload))
                    imported += 1

            if not request.dry_run:
                session.commit()

        logger.info(
            "kol_import_api",
            imported=imported,
            updated=updated,
            skipped=skipped,
            dry_run=request.dry_run,
            data_source_summary=data_source_summary,
            data_source_warning=data_source_warning,
        )
        return KolImportResponse(
            imported=imported,
            updated=updated,
            skipped=skipped,
            dry_run=request.dry_run,
            data_source_summary=data_source_summary,
            data_source_warning=data_source_warning,
            source_labels=_source_labels_for_summary(data_source_summary),
            errors=errors,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("kol_import_api_error")
        raise HTTPException(status_code=500, detail="达人导入失败")


@router.post("/search", response_model=KolSearchResponse)
async def search_kols_endpoint(
    request: KolSearchRequest,
    company_id: str | None = Query(default=None, include_in_schema=False),
    user_id: int = Query(default=0, description="用户 ID"),
    current_user: User = Depends(get_current_active_user),
):
    """
    达人搜索

    支持多条件筛选：平台、分类、粉丝数、互动率
    支持排序：按粉丝数、互动率、相关性
    """
    from app.agents.kol_search import save_search_history, search_kols
    from app.database import db as db_proxy

    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = _resolve_company_id(current_user, company_id)

    # user_id 校验：FastAPI 已做 int 转换，这里防御性校验非负整数
    if not isinstance(user_id, int) or user_id < 0:
        raise HTTPException(status_code=400, detail="user_id 必须为非负整数")

    try:
        with db_proxy.get_session() as session:
            results = search_kols(
                session=session,
                company_id=company_id,
                query=request.query,
                platform=request.platform if request.platform != "all" else None,
                category=request.category,
                min_followers=request.min_followers if request.min_followers > 0 else None,
                max_followers=request.max_followers
                if request.max_followers and request.max_followers > 0
                else None,
                min_engagement_rate=request.min_engagement_rate
                if request.min_engagement_rate > 0
                else None,
                sort_by=request.sort_by,
                limit=request.limit,
            )

            kol_dicts = [
                item
                for item in (_kol_to_dict(r) for r in results)
                if item.get("source_available_for_search") is not False
            ]

            # 保存搜索历史
            if user_id > 0:
                try:
                    save_search_history(
                        session=session,
                        user_id=user_id,
                        company_id=company_id,
                        query=request.query,
                        platform_filter=request.platform if request.platform != "all" else None,
                        category_filter=request.category,
                        result_count=len(kol_dicts),
                    )
                except Exception as hist_err:
                    logger.warning("kol_search_history_save_failed", error=str(hist_err))

            data_source_summary, data_source_warning = _summarize_kol_data_sources(kol_dicts)
            search_id = str(uuid.uuid4())[:8]

            logger.info(
                "kol_search_api",
                query=request.query,
                total=len(kol_dicts),
                search_id=search_id,
                data_source_summary=data_source_summary,
                data_source_warning=data_source_warning,
            )

            return KolSearchResponse(
                total=len(kol_dicts),
                results=kol_dicts,
                search_id=search_id,
                data_source_summary=data_source_summary,
                data_source_warning=data_source_warning,
                source_labels=_source_labels_for_summary(data_source_summary),
            )

    except Exception:
        logger.exception("kol_search_api_error")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/{kol_id:int}")
async def get_kol_detail(
    kol_id: int,
    company_id: str | None = Query(default=None, include_in_schema=False),
    current_user: User = Depends(get_current_active_user),
):
    """
    达人详情

    获取指定达人的详细信息
    """
    from app.database import db as db_proxy

    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = _resolve_company_id(current_user, company_id)

    try:
        with db_proxy.get_session() as session:
            kol = (
                session.query(KolProfile)
                .filter(
                    KolProfile.id == kol_id,
                    KolProfile.company_id == company_id,
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
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/export")
async def export_kols(
    request: KolExportRequest,
    company_id: str | None = Query(default=None, include_in_schema=False),
    current_user: User = Depends(get_current_active_user),
):
    """
    导出达人列表

    支持 CSV 和 PDF 格式
    """
    import csv
    import io

    from fastapi.responses import StreamingResponse

    from app.database import db as db_proxy

    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = _resolve_company_id(current_user, company_id)

    try:
        with db_proxy.get_session() as session:
            if request.kol_ids:
                from app.agents.kol_search import NON_PRODUCTION_DATA_SOURCES

                kols = (
                    session.query(KolProfile)
                    .filter(
                        KolProfile.id.in_(request.kol_ids),
                        KolProfile.company_id == company_id,
                        KolProfile.is_active.is_(True),
                        ~KolProfile.data_source.in_(NON_PRODUCTION_DATA_SOURCES),
                    )
                    .all()
                )
            else:
                from app.agents.kol_search import search_kols

                kols = search_kols(
                    session=session,
                    company_id=company_id,
                    query=request.query,
                    platform=request.platform if request.platform != "all" else None,
                    category=request.category,
                    min_followers=request.min_followers if request.min_followers > 0 else None,
                    max_followers=request.max_followers
                    if request.max_followers and request.max_followers > 0
                    else None,
                    min_engagement_rate=request.min_engagement_rate
                    if request.min_engagement_rate > 0
                    else None,
                    sort_by=request.sort_by,
                    limit=request.limit,
                )

            if request.format == "csv":
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(
                    ["ID", "姓名", "平台", "粉丝数", "互动率", "分类", "报价区间", "所在地"]
                )
                for k in kols:
                    writer.writerow(
                        [
                            k.id,
                            k.name,
                            k.platform,
                            k.followers,
                            k.engagement_rate,
                            k.category,
                            f"{k.price_range_low}-{k.price_range_high}"
                            if k.price_range_low
                            else "",
                            k.location or "",
                        ]
                    )

                output.seek(0)
                return StreamingResponse(
                    iter([output.getvalue()]),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=kols.csv"},
                )
            else:
                pdf_bytes = _build_simple_kol_pdf(kols)
                return StreamingResponse(
                    iter([pdf_bytes]),
                    media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=kols.pdf"},
                )

    except HTTPException:
        raise
    except Exception:
        logger.exception("kol_export_api_error")
        raise HTTPException(status_code=500, detail="内部服务器错误")

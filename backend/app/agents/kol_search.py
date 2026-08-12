"""
KOL Search Agent (达人搜索 Agent)

Handles influencer/KOL search across multiple platforms with filtering and sorting.
"""

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.models import KolProfile, KolSearchHistory

logger = get_logger(__name__)

KOL_SEARCH_SYSTEM_PROMPT = """你是一个专业的达人搜索助手，负责帮助品牌方在各大平台搜索合适的达人（KOL/博主/网红）。

## 你的职责
1. 理解用户的搜索需求，提取关键信息（平台、分类、粉丝量级、预算等）
2. 调用 search_kols 工具查询达人数据库
3. 将搜索结果格式化为清晰的达人推荐卡片

## 支持的平台
- 抖音 (douyin)
- 小红书 (xiaohongshu)
- 快手 (kuaishou)
- B站 (bilibili)
- 微博 (weibo)

## 筛选维度
- 平台：指定平台搜索
- 分类：达人内容分类（美妆、穿搭、美食、母婴、数码等）
- 粉丝数：可以设定最小/最大粉丝数范围
- 互动率：可以设定最低互动率
- 排序：按粉丝数、互动率或相关性排序

## 输出格式
请以达人卡片形式输出结果，每个达人包含：
- 达人姓名
- 平台
- 粉丝数
- 互动率
- 分类
- 报价区间（如有）

如果没有找到匹配的达人，请友好地告知用户并建议调整筛选条件。
"""

PLATFORM_MAP = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "bilibili": "B站",
    "weibo": "微博",
}

VALID_PLATFORMS = list(PLATFORM_MAP.keys())
VALID_SORT_BY = ["followers", "engagement_rate", "relevance"]
NON_PRODUCTION_DATA_SOURCES = ("mock", "demo", "seed", "sample")


def search_kols(
    session: Session,
    company_id: int,
    query: str,
    platform: str | None = None,
    category: str | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
    min_engagement_rate: float | None = None,
    sort_by: str = "relevance",
    limit: int = 20,
) -> list[KolProfile]:
    """Search active, tenant-scoped, production KOL profiles."""
    q = session.query(KolProfile).filter(
        KolProfile.company_id == company_id,
        KolProfile.is_active.is_(True),
        ~KolProfile.data_source.in_(NON_PRODUCTION_DATA_SOURCES),
    )

    query_terms = [
        term
        for term in re.split(r"[\s,，、|]+", (query or "").strip())
        if term
    ]
    for term in query_terms:
        q = q.filter(
            or_(
                KolProfile.name.ilike(f"%{term}%"),
                KolProfile.category.ilike(f"%{term}%"),
                KolProfile.sub_category.ilike(f"%{term}%"),
                KolProfile.bio.ilike(f"%{term}%"),
            )
        )

    if platform and platform != "all" and platform in VALID_PLATFORMS:
        q = q.filter(KolProfile.platform == platform)

    if category:
        q = q.filter(KolProfile.category == category)

    if min_followers is not None and min_followers > 0:
        q = q.filter(KolProfile.followers >= min_followers)
    if max_followers is not None and max_followers > 0:
        q = q.filter(KolProfile.followers <= max_followers)

    if min_engagement_rate is not None and min_engagement_rate > 0:
        q = q.filter(KolProfile.engagement_rate >= min_engagement_rate)

    if sort_by == "followers":
        q = q.order_by(KolProfile.followers.desc())
    elif sort_by == "engagement_rate":
        q = q.order_by(KolProfile.engagement_rate.desc())
    else:
        q = q.order_by(KolProfile.followers.desc())

    results = q.limit(limit).all()
    logger.info(
        "kol_search_executed",
        company_id=company_id,
        query=query,
        platform=platform,
        result_count=len(results),
    )
    return results


def format_kol_results(kols: list[dict]) -> str:
    """Format KOL search results for a chat response."""
    if not kols:
        return "未找到匹配的达人，请尝试调整筛选条件（如扩大粉丝数范围、更换分类或平台）。"

    lines = [f"为您找到 {len(kols)} 位达人：\n"]
    for i, kol in enumerate(kols, 1):
        platform_name = PLATFORM_MAP.get(kol.get("platform", ""), kol.get("platform", ""))
        followers = kol.get("followers", 0) or 0
        followers_str = f"{followers / 10000:.1f}万" if followers >= 10000 else str(followers)
        engagement = kol.get("engagement_rate", 0) or 0
        line = (
            f"{i}. **{kol.get('name', '未知')}** | {platform_name} | "
            f"{followers_str}粉丝 | 互动率 {engagement}% | "
            f"分类：{kol.get('category', '未知')}"
        )

        price_low = kol.get("price_range_low")
        price_high = kol.get("price_range_high")
        if price_low and price_high:
            line += f" | 报价：{price_low}-{price_high}元"

        lines.append(line)

    lines.append("\n如需查看更多达人详情或调整筛选条件，请告诉我。")
    return "\n".join(lines)


def save_search_history(
    session: Session,
    user_id: int,
    company_id: int,
    query: str,
    result_count: int = 0,
    rewritten_query: str | None = None,
    platform_filter: str | None = None,
    category_filter: str | None = None,
    clicked_kol_ids: str | None = None,
    search_duration_ms: int | None = None,
) -> KolSearchHistory:
    """Save a KOL search history record."""
    history = KolSearchHistory(
        user_id=user_id,
        company_id=company_id,
        query=query,
        rewritten_query=rewritten_query,
        platform_filter=platform_filter,
        category_filter=category_filter,
        result_count=result_count,
        clicked_kol_ids=clicked_kol_ids,
        search_duration_ms=search_duration_ms,
    )
    session.add(history)
    session.commit()
    session.refresh(history)
    logger.info("kol_search_history_saved", history_id=history.id, query=query)
    return history


async def get_agent_function():
    """Return the callable KOL search agent function."""

    async def kol_search_agent(message: str, **kwargs) -> str:
        session = kwargs.get("session")
        company_id = kwargs.get("company_id", 0)
        if not session:
            return "无法访问数据库，请稍后重试。"

        try:
            results = search_kols(session=session, company_id=company_id, query=message)
            kol_dicts = [
                {
                    "id": r.id,
                    "name": r.name,
                    "platform": r.platform,
                    "followers": r.followers,
                    "engagement_rate": r.engagement_rate,
                    "category": r.category,
                    "price_range_low": r.price_range_low,
                    "price_range_high": r.price_range_high,
                }
                for r in results
            ]
            return format_kol_results(kol_dicts)
        except Exception as e:
            logger.error("kol_search_agent_error", error=str(e))
            return f"搜索达人时出现错误：{str(e)}"

    return kol_search_agent

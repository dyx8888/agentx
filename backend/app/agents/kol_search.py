"""
KOL Search Agent (达人搜索 Agent)

Handles influencer/KOL search across multiple platforms with filtering and sorting.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.models import KolProfile, KolSearchHistory

logger = get_logger(__name__)


# ============================================================
# KOL Search System Prompt
# ============================================================

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

# 平台中文映射
PLATFORM_MAP = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "bilibili": "B站",
    "weibo": "微博",
}

# 支持的平台列表
VALID_PLATFORMS = list(PLATFORM_MAP.keys())

# 支持的排序方式
VALID_SORT_BY = ["followers", "engagement_rate", "relevance"]


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
    """
    搜索达人
    
    Args:
        session: 数据库会话
        company_id: 公司 ID（租户隔离）
        query: 搜索关键词
        platform: 平台筛选
        category: 分类筛选
        min_followers: 最小粉丝数
        max_followers: 最大粉丝数
        min_engagement_rate: 最低互动率
        sort_by: 排序方式
        limit: 返回数量限制
        
    Returns:
        达人列表
    """
    q = session.query(KolProfile).filter(
        KolProfile.company_id == company_id,
    )

    # 关键词搜索：匹配名称和分类
    if query:
        q = q.filter(
            or_(
                KolProfile.name.ilike(f"%{query}%"),
                KolProfile.category.ilike(f"%{query}%"),
                KolProfile.sub_category.ilike(f"%{query}%"),
                KolProfile.bio.ilike(f"%{query}%"),
            )
        )

    # 平台筛选
    if platform and platform != "all" and platform in VALID_PLATFORMS:
        q = q.filter(KolProfile.platform == platform)

    # 分类筛选
    if category:
        q = q.filter(KolProfile.category == category)

    # 粉丝数范围
    if min_followers is not None and min_followers > 0:
        q = q.filter(KolProfile.followers >= min_followers)
    if max_followers is not None and max_followers > 0:
        q = q.filter(KolProfile.followers <= max_followers)

    # 互动率
    if min_engagement_rate is not None and min_engagement_rate > 0:
        q = q.filter(KolProfile.engagement_rate >= min_engagement_rate)

    # 排序
    if sort_by == "followers":
        q = q.order_by(KolProfile.followers.desc())
    elif sort_by == "engagement_rate":
        q = q.order_by(KolProfile.engagement_rate.desc())
    # relevance 默认按粉丝数排序
    else:
        q = q.order_by(KolProfile.followers.desc())

    q = q.limit(limit)

    results = q.all()
    logger.info(
        "kol_search_executed",
        company_id=company_id,
        query=query,
        platform=platform,
        result_count=len(results),
    )
    return results


def format_kol_results(kols: list[dict]) -> str:
    """
    格式化达人搜索结果
    
    Args:
        kols: 达人列表（字典格式）
        
    Returns:
        格式化后的文本
    """
    if not kols:
        return "未找到匹配的达人，请尝试调整筛选条件（如扩大粉丝数范围、更换分类或平台）。"

    lines = [f"为您找到 {len(kols)} 位达人：\n"]

    for i, kol in enumerate(kols, 1):
        platform_name = PLATFORM_MAP.get(kol.get("platform", ""), kol.get("platform", ""))
        followers = kol.get("followers", 0)
        if followers >= 10000:
            followers_str = f"{followers / 10000:.1f}万"
        else:
            followers_str = str(followers)

        engagement = kol.get("engagement_rate", 0)
        line = (
            f"{i}. **{kol.get('name', '未知')}** | {platform_name} | "
            f"{followers_str}粉丝 | 互动率 {engagement}% | "
            f"分类：{kol.get('category', '未知')}"
        )

        # 如果有报价信息
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
    """
    保存搜索历史
    
    Args:
        session: 数据库会话
        user_id: 用户 ID
        company_id: 公司 ID
        query: 搜索关键词
        result_count: 结果数量
        rewritten_query: 改写后的查询
        platform_filter: 平台筛选
        category_filter: 分类筛选
        clicked_kol_ids: 点击的达人 ID
        search_duration_ms: 搜索耗时（毫秒）
        
    Returns:
        创建的搜索历史记录
    """
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
    logger.info(
        "kol_search_history_saved",
        history_id=history.id,
        query=query,
    )
    return history


# ============================================================
# Agent Function
# ============================================================

async def get_agent_function():
    """
    返回 KOL 搜索 Agent 的可调用函数
    
    Returns:
        async callable: 接受 message 和 **kwargs 的异步函数
    """
    async def kol_search_agent(message: str, **kwargs) -> str:
        """
        KOL 搜索 Agent 入口
        
        Args:
            message: 用户消息
            **kwargs: 额外参数（company_id, session 等）
            
        Returns:
            格式化后的搜索结果
        """
        # 从 kwargs 中获取上下文
        session = kwargs.get("session")
        company_id = kwargs.get("company_id", 0)

        if not session:
            return "无法访问数据库，请稍后重试。"

        try:
            # 执行搜索
            results = search_kols(
                session=session,
                company_id=company_id,
                query=message,
            )

            # 格式化为字典列表
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

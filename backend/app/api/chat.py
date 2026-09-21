# ==========================================
# 流式聊天 API
# ==========================================
"""
Streaming Chat API for AgentX Platform.

The production chat surface exposes only user-visible answer events. Internal
routing, planning, action, observation, delegation, and reflection events are
logged but not streamed to the browser or persisted in conversation history.
"""

import asyncio
import json
import os
import re
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

from app.api.conversation_tasks import router as conversation_tasks_router
from app.auth import get_current_active_user
from app.core.high_risk_actions import detect_high_risk_action
from app.core.logging import get_logger
from app.database import User
from app.middleware.input_filter import InputFilter
from app.perception.pipeline import PerceptionPipeline
from app.services.conversation_tasks import TaskContext, run_admitted_tasks

logger = get_logger(__name__)
router = APIRouter(tags=["chat"])
router.include_router(conversation_tasks_router)

_perception_pipeline: PerceptionPipeline | None = None
_master_router = None
_SMOKE_TRUE_VALUES = {"1", "true", "yes"}


async def _stream_with_heartbeat(source, interval: float = 10.0):
    """Keep idle SSE connections active without cancelling model work on timeout.

    At most one anext task exists. Client disconnect closes/cancels that task;
    heartbeats are SSE comments, not assistant content or persisted messages.
    """
    iterator = source.__aiter__()
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(iterator))
            ready, _ = await asyncio.wait({pending}, timeout=interval)
            if not ready:
                yield ": keepalive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            finally:
                pending = None
            yield chunk
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending
        await iterator.aclose()


def _get_perception_pipeline() -> PerceptionPipeline:
    global _perception_pipeline
    if _perception_pipeline is None:
        _perception_pipeline = PerceptionPipeline()
    return _perception_pipeline


def _get_master_router():
    """Return a lazily-created MasterAgentRouter instance."""
    global _master_router
    if _master_router is None:
        try:
            from app.agents.master_router import MasterAgentRouter

            _master_router = MasterAgentRouter()
        except Exception as e:
            logger.error("master_router_init_failed", error=str(e))
    return _master_router


def _smoke_rag_preretrieval_disabled() -> bool:
    return (
        os.getenv("AGENTX_SMOKE_DISABLE_RAG_PRERETRIEVAL", "").strip().lower()
        in _SMOKE_TRUE_VALUES
    )


def _json_loads(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _db_execute_first(cursor, sql: str, params: tuple[Any, ...]):
    """Execute SQL against either sqlite-style or psycopg-style adapters."""
    try:
        cursor.execute(sql, params)
    except Exception:
        cursor.execute(sql.replace("?", "%s"), params)
    return cursor.fetchone()


def _is_knowledge_only_request(message: str) -> bool:
    """Detect requests that explicitly require knowledge-base-only answers."""
    normalized = re.sub(r"\s+", "", (message or "").lower())
    # Users commonly insert scope qualifiers such as "当前" or "本企业"
    # between the grounding verb and "企业知识库". Keep this detector
    # tolerant while retaining the explicit knowledge-only requirement.
    knowledge_patterns = (
        r"只根据(?:当前|本|公司)?企业知识库",
        r"仅根据(?:当前|本|公司)?企业知识库",
        r"只基于(?:当前|本|公司)?企业知识库",
        r"仅基于(?:当前|本|公司)?企业知识库",
        r"只根据知识库",
        r"仅根据知识库",
        r"只基于知识库",
        r"仅基于知识库",
        r"知识库没有",
        r"knowledgebase",
        r"retrievedreferences",
    )
    return any(re.search(pattern, normalized) for pattern in knowledge_patterns)


_KOL_PLATFORM_ALIASES = {
    "xiaohongshu": ("小红书", "xhs", "rednote", "red note", "xiaohongshu"),
    "douyin": ("抖音", "douyin", "巨量星图", "星图"),
    "kuaishou": ("快手", "kuaishou"),
    "bilibili": ("B站", "b站", "bilibili", "哔哩哔哩"),
    "weibo": ("微博", "weibo"),
}

_KOL_CATEGORY_KEYWORDS = (
    "护肤",
    "美妆",
    "彩妆",
    "母婴",
    "食品",
    "美食",
    "穿搭",
    "时尚",
    "数码",
    "家居",
    "健身",
    "宠物",
)

_KOL_SEARCH_SIGNALS = (
    "达人",
    "达人库",
    "候选达人",
    "找达人",
    "搜索达人",
    "博主",
    "网红",
    "kol",
    "influencer",
    "creator",
)

_LOGISTICS_QUERY_SIGNALS = (
    "查物流",
    "查询物流",
    "查快递",
    "查询快递",
    "物流查询",
    "物流信息",
    "物流记录",
    "物流状态",
    "物流进度",
    "物流轨迹",
    "物流异常",
    "订单物流",
    "订单的物流",
    "快递",
    "运单",
    "查询运单",
    "运输状态",
    "运输轨迹",
    "到哪了",
    "配送状态",
    "配送进度",
    "delivery status",
    "tracking",
)
_SALES_DATA_REQUEST_PHRASES = (
    "销售分析",
    "销售业绩",
    "经营分析",
    "投放数据",
    "广告数据",
)
_SALES_METRIC_TERMS = (
    "销售额",
    "销量",
    "成交额",
    "gmv",
    "营收",
    "营业额",
    "订单量",
)
_SALES_GENERIC_DATA_TERMS = ("销售数据",)
_SALES_DATA_QUERY_TERMS = (
    "分析",
    "查询",
    "查看",
    "统计",
    "报告",
    "复盘",
    "趋势",
    "表现",
    "情况",
    "多少",
    "同比",
    "环比",
    "本周",
    "本月",
    "今天",
    "昨日",
    "最近",
)
_SALES_ADVISORY_TERMS = (
    "如何",
    "怎么",
    "建议",
    "策略",
    "优化",
    "提升",
    "方法",
    "方案",
)
_EXPLICIT_SALES_NUMBER_PATTERN = (
    r"([+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+))\s*(亿|万|千|百|k|K)?"
)
_EXPLICIT_SALES_METRIC_ALIASES = {
    "orders": ("订单数量", "订单量", "订单数", "订单", "销量"),
    "gmv": ("销售额", "成交额", "营业额", "营收", "GMV"),
    "ad_spend": (
        "广告费用",
        "广告花费",
        "广告费",
        "广告投放",
        "投放费用",
        "投放费",
        "投放成本",
        "广告成本",
    ),
    "refund_amount": ("退款金额", "退款额", "退款"),
}
_EXPLICIT_SALES_TEST_MARKERS = ("合成", "虚构", "模拟", "测试数据", "示例数据")
_LOGISTICS_WRITE_SIGNALS = (
    "补发",
    "改地址",
    "修改地址",
    "寄样",
    "创建发货",
    "发货单",
)
_LOGISTICS_STATUS_ALIASES = {
    "pending": ("待发货", "未发货"),
    "shipped": ("已发货",),
    "in_transit": ("运输中",),
    "out_for_delivery": ("派送中", "派送"),
    "delivered": ("已签收", "已送达"),
    "returned": ("已退回", "退回"),
    "lost": ("丢失",),
}
_LOGISTICS_TRACKING_PATTERN = re.compile(r"\b[A-Za-z]{2}\d{8,}\b")

_KOL_EXPLICIT_TERM_PATTERNS = (
    r"(?:名称|名字|昵称|达人名称)\s*(?:包含|含有|为|是|叫|匹配)\s*[“\"'`]?([A-Za-z0-9_\-\u4e00-\u9fff]{2,40})",
    r"(?:包含|含有)\s*[“\"'`]?([A-Za-z0-9_\-\u4e00-\u9fff]{2,40})\s*(?:的)?(?:达人|博主|网红|kol|KOL)",
)

_KOL_SOURCE_LABELS = {
    "manual": "人工导入",
    "manual_upload": "人工导入",
    "public_web": "公开网页",
    "cached_snapshot": "缓存快照",
    "official_api": "官方 API",
    "partner_api": "合作方 API",
}


def _is_kol_search_request(message: str) -> bool:
    """Return True when the user asks to search the company KOL library."""
    text = (message or "").strip().lower()
    if not text:
        return False
    return any(signal.lower() in text for signal in _KOL_SEARCH_SIGNALS)


def _is_logistics_query_request(message: str) -> bool:
    """Return True for read-only company logistics queries.

    Side-effect requests are rejected by the high-risk guard before this route
    is reached. This branch only handles status/list/look-up requests so a
    missing tenant record produces an explicit no-data answer instead of a
    generic model/tool failure.
    """
    text = (message or "").strip().lower()
    if not text:
        return False
    if any(signal.lower() in text for signal in _LOGISTICS_WRITE_SIGNALS):
        return False
    return any(signal.lower() in text for signal in _LOGISTICS_QUERY_SIGNALS)


def _is_sales_analysis_request(message: str) -> bool:
    """Return True for read-only sales or advertising data requests."""
    text = re.sub(r"\s+", "", (message or "").lower())
    if not text:
        return False
    if any(term in text for term in _SALES_ADVISORY_TERMS) and not any(
        query_term in text for query_term in _SALES_DATA_QUERY_TERMS
    ):
        return False
    if any(phrase in text for phrase in _SALES_DATA_REQUEST_PHRASES):
        return True
    if any(term in text for term in _SALES_GENERIC_DATA_TERMS) and any(
        query_term in text for query_term in _SALES_DATA_QUERY_TERMS
    ):
        return True
    return any(metric in text for metric in _SALES_METRIC_TERMS) and any(
        query_term in text for query_term in _SALES_DATA_QUERY_TERMS
    )


def _parse_explicit_sales_number(raw_value: str, unit: str | None) -> float:
    value = float(raw_value.replace(",", ""))
    multiplier = {"百": 100, "千": 1_000, "万": 10_000, "亿": 100_000_000}.get(
        unit or "", 1
    )
    if unit in {"k", "K"}:
        multiplier = 1_000
    return round(value * multiplier, 2)


def _extract_explicit_sales_metrics(message: str) -> dict[str, float]:
    """Extract only metric-number pairs explicitly written in the user message.

    The parser intentionally ignores 'company_context' and all database data.
    Multiple product rows are aggregated by metric, while unrelated numbers in
    prose are not treated as sales data.
    """
    metrics: dict[str, float] = {}
    text = message or ""
    for metric_name, aliases in _EXPLICIT_SALES_METRIC_ALIASES.items():
        label_pattern = "(?:" + "|".join(
            re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)
        ) + ")"
        prefix_pattern = re.compile(
            rf"{label_pattern}\s*(?:(?:约|大约|合计|共|为|是)\s*)*[:：=]?\s*"
            rf"{_EXPLICIT_SALES_NUMBER_PATTERN}",
            flags=re.IGNORECASE,
        )
        suffix_pattern = re.compile(
            rf"{_EXPLICIT_SALES_NUMBER_PATTERN}\s*(?:元|件|单|笔)?\s*{label_pattern}",
            flags=re.IGNORECASE,
        )
        values = [
            _parse_explicit_sales_number(match.group(1), match.group(2))
            for match in prefix_pattern.finditer(text)
        ]
        values.extend(
            _parse_explicit_sales_number(match.group(1), match.group(2))
            for match in suffix_pattern.finditer(text)
        )
        if values:
            metrics[metric_name] = round(sum(values), 2)
    return metrics


def _explicit_sales_source_label(message: str) -> str:
    lowered = (message or "").lower()
    if any(marker.lower() in lowered for marker in _EXPLICIT_SALES_TEST_MARKERS):
        return "用户提供的合成/测试数据（未连接平台）"
    return "用户在本条消息中提供的数据（未经平台核验）"


def _extract_logistics_search_params(message: str) -> dict[str, Any]:
    """Extract only deterministic, non-sensitive read-only logistics filters."""
    text = message or ""
    tracking_match = _LOGISTICS_TRACKING_PATTERN.search(text)
    status = None
    for status_key, aliases in _LOGISTICS_STATUS_ALIASES.items():
        if any(alias in text for alias in aliases):
            status = status_key
            break
    return {
        "tracking_number": tracking_match.group(0) if tracking_match else None,
        "status": status,
    }


def _logistics_record_to_dict(record: Any) -> dict[str, Any]:
    """Convert an ORM logistics row to the fields supported by the formatter."""
    return {
        "id": record.id,
        "tracking_number": record.tracking_number,
        "carrier": record.carrier,
        "status": record.status,
        "status_detail": record.status_detail,
        "origin": record.origin,
        "destination": record.destination,
        "kol_name": record.kol_name,
        "sample_name": record.sample_name,
    }


def _query_company_logistics_for_chat(message: str, company_id: str) -> dict[str, Any]:
    """Query only the authenticated user's company logistics records."""
    from app.agents.logistics import query_logistics
    from app.database import db as db_proxy

    params = _extract_logistics_search_params(message)
    try:
        company_id_int = int(company_id)
    except (TypeError, ValueError):
        company_id_int = 0

    if company_id_int <= 0:
        return {
            "results": [],
            "params": params,
            "code": "missing_company_context",
        }

    try:
        with db_proxy.get_session() as session:
            results = query_logistics(
                session=session,
                company_id=company_id_int,
                tracking_number=params["tracking_number"],
                status=params["status"],
            )
            return {
                "results": [_logistics_record_to_dict(record) for record in results],
                "params": params,
                "code": "ok" if results else "requires_logistics_data",
            }
    except Exception as exc:
        logger.warning(
            "chat_logistics_search_failed",
            error=str(exc),
            company_id=company_id_int,
        )
        return {
            "results": [],
            "params": params,
            "code": "logistics_unavailable",
        }


def _format_company_logistics_response(payload: dict[str, Any]) -> str:
    """Build a deterministic, tenant-scoped user-visible logistics response."""
    code = payload.get("code") or "requires_logistics_data"
    if code == "missing_company_context":
        return "无法确认当前企业，已拒绝查询跨租户物流数据。"
    if code == "logistics_unavailable":
        return "当前企业物流数据暂时不可用，请稍后重试；本次没有使用 mock/demo 物流数据。"

    results = payload.get("results") or []
    if not results:
        return "当前企业暂无匹配的物流记录；本次没有使用 mock/demo 物流数据。"

    from app.agents.logistics import format_logistics_result

    return (
        format_logistics_result(results)
        + "\n以上结果仅来自当前企业物流记录，未使用 mock/demo/fallback 数据。"
    )


def _extract_explicit_kol_query_terms(message: str) -> list[str]:
    """Extract user-specified KOL name/keyword constraints from natural language."""
    terms: list[str] = []
    for pattern in _KOL_EXPLICIT_TERM_PATTERNS:
        for match in re.finditer(pattern, message or "", flags=re.IGNORECASE):
            term = match.group(1).strip(" \t\r\n，。；;、,.!！?？“”\"'`")
            if term and term not in terms:
                terms.append(term)
    return terms


def _extract_kol_search_params(message: str) -> dict[str, Any]:
    """Extract deterministic KOL filters from a natural-language request."""
    text = message or ""
    lowered = text.lower()

    platform = None
    for platform_key, aliases in _KOL_PLATFORM_ALIASES.items():
        if any(alias.lower() in lowered for alias in aliases):
            platform = platform_key
            break

    category = None
    for keyword in _KOL_CATEGORY_KEYWORDS:
        if keyword in text:
            category = keyword
            break

    limit = 5
    count_match = re.search(r"(\d{1,2})\s*(?:位|个|名|条)", text)
    if count_match:
        limit = max(1, min(10, int(count_match.group(1))))

    query_terms = []
    if category:
        query_terms.append(category)
    for term in _extract_explicit_kol_query_terms(text):
        if term not in query_terms:
            query_terms.append(term)

    return {
        "platform": platform,
        "query": " ".join(query_terms),
        "category_label": category or "",
        "limit": limit,
    }


def _format_followers(value: int | None) -> str:
    followers = int(value or 0)
    if followers >= 10000:
        return f"{followers / 10000:.1f}万"
    return str(followers)


def _format_kol_source(source: str | None) -> str:
    normalized = (source or "unknown").strip()
    return _KOL_SOURCE_LABELS.get(normalized, normalized or "unknown")


def _platform_label(platform: str | None) -> str:
    aliases = _KOL_PLATFORM_ALIASES.get(platform or "")
    return aliases[0] if aliases else (platform or "-")


def _format_company_kol_search_response(payload: dict[str, Any]) -> str:
    """Build the user-visible KOL answer from company database search results."""
    params = payload.get("params") or {}
    platform = params.get("platform")
    category = params.get("category_label")
    filters = []
    if category:
        filters.append(category)
    if platform:
        filters.append(_platform_label(platform))
    filter_text = "、".join(filters) if filters else "当前条件"

    results = payload.get("results") or []
    if not results:
        code = payload.get("code") or "requires_kol_data"
        return (
            f"没有在当前企业达人库中找到匹配“{filter_text}”的达人；"
            f"当前企业达人库无匹配数据（{code}）。\n\n"
            "我没有使用 mock、demo 或通用知识库结果补齐；"
            "请先在“设置 - 达人数据”导入或接入真实数据源后再搜索。"
        )

    lines = [
        f"已基于当前企业达人库找到 {len(results)} 位匹配“{filter_text}”的达人：",
        "",
        "| # | 达人名称 | 平台 | 粉丝数 | 互动率 | 分类 | 数据来源 |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for idx, kol in enumerate(results, 1):
        lines.append(
            "| {idx} | {name} | {platform} | {followers} | {engagement}% | "
            "{category} | {source} |".format(
                idx=idx,
                name=kol.get("name") or "未知",
                platform=_platform_label(kol.get("platform")),
                followers=_format_followers(kol.get("followers")),
                engagement=kol.get("engagement_rate", 0) or 0,
                category=kol.get("category") or "-",
                source=_format_kol_source(kol.get("data_source")),
            )
        )

    source_warning = payload.get("data_source_warning")
    if source_warning:
        lines.extend(["", f"数据来源提示：{source_warning}"])
    else:
        lines.extend(["", "以上结果均来自当前企业达人库，未使用 mock/demo/fallback 数据。"])

    message = payload.get("message") or ""
    if "外发" in message or "邀约" in message or "发送" in message:
        lines.append("我不会自动发送外联消息；如需邀约，只能生成待人工审核的邀约草稿。")
    else:
        lines.append("需要的话，我可以继续基于这些候选达人生成待人工审核的邀约草稿。")
    return "\n".join(lines)


def _search_company_kols_for_chat(
    message: str, company_id: str, user_id: int = 0
) -> dict[str, Any]:
    """Search the same tenant-scoped KolProfile table used by /api/kol/search."""
    from app.agents.kol_search import save_search_history, search_kols
    from app.api.kol import _kol_to_dict, _summarize_kol_data_sources
    from app.database import db as db_proxy

    params = _extract_kol_search_params(message)
    try:
        company_id_int = int(company_id)
    except (TypeError, ValueError):
        company_id_int = 0

    if company_id_int <= 0:
        return {
            "message": message,
            "params": params,
            "results": [],
            "data_source_summary": {},
            "code": "requires_kol_data",
            "data_source_warning": (
                "missing_company_context: 无法确认当前企业，已拒绝跨租户达人搜索。"
            ),
        }

    with db_proxy.get_session() as session:
        results = search_kols(
            session=session,
            company_id=company_id_int,
            query=params["query"],
            platform=params["platform"],
            category=params["category_label"] or None,
            limit=params["limit"],
        )
        kol_dicts = [_kol_to_dict(kol) for kol in results]
        if user_id:
            try:
                save_search_history(
                    session=session,
                    user_id=user_id,
                    company_id=company_id_int,
                    query=params["query"] or message[:200],
                    platform_filter=params["platform"],
                    category_filter=params["category_label"] or None,
                    result_count=len(results),
                )
            except Exception as hist_err:
                logger.warning("chat_kol_search_history_save_failed", error=str(hist_err))

    data_source_summary, data_source_warning = _summarize_kol_data_sources(kol_dicts)
    return {
        "message": message,
        "params": params,
        "results": kol_dicts,
        "data_source_summary": data_source_summary,
        "code": "ok" if kol_dicts else "requires_kol_data",
        "data_source_warning": data_source_warning,
    }


def _inject_rag_context(
    message: str, company_id: str, agent_name: str
) -> tuple[str, list[dict]]:
    """Inject RAG context into a message, returning (augmented_message, references)."""
    if not company_id:
        return message, []

    try:
        from app.perception.rag_retriever import RagRetriever

        retriever = RagRetriever()
        rag_result = retriever.retrieve(
            query=message,
            company_id=company_id,
            agent_name=agent_name,
            intent_type="chat",
        )
        if getattr(rag_result, "context", None):
            refs = getattr(rag_result, "references", []) or []
            return retriever.augment_message(message, rag_result), refs
    except Exception as e:
        logger.warning(
            "rag_injection_failed", error=str(e), agent=agent_name, company_id=company_id
        )

    return message, []


def _build_company_context_from_db(company_id: str) -> dict[str, Any]:
    """Build company context from the current database adapter."""
    if not company_id:
        return {}

    conn = None
    try:
        from app.database import db as db_proxy

        conn = db_proxy.get_connection()
        cursor = conn.cursor()
        row = _db_execute_first(
            cursor,
            "SELECT name, brand_name, category, platforms_json FROM companies WHERE id = ?",
            (int(company_id),),
        )
        if not row:
            return {}

        name, brand_name, category, platforms_json = row[:4]
        return {
            "company_name": name,
            "brand_name": brand_name,
            "category": category,
            "platforms": _json_loads(platforms_json, []),
        }
    except Exception as e:
        logger.warning("build_company_context_error", error=str(e), company_id=company_id)
        return {}
    finally:
        if conn:
            try:
                conn.close()
            except Exception as close_err:
                logger.warning(
                    "build_company_context_connection_close_failed",
                    error=str(close_err),
                    company_id=company_id,
                )


def _find_company_default_agent(company_id: str):
    """Find the default agent for a company."""
    if not company_id:
        return None

    conn = None
    try:
        from app.database import db as db_proxy

        conn = db_proxy.get_connection()
        cursor = conn.cursor()
        row = _db_execute_first(
            cursor,
            "SELECT id, name, tools_json FROM agents WHERE company_id = ? ORDER BY id LIMIT 1",
            (int(company_id),),
        )
        if row:
            return {"id": str(row[0]), "name": row[1], "tools_json": row[2]}
    except Exception as e:
        logger.warning(
            "find_company_default_agent_error", error=str(e), company_id=company_id
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception as close_err:
                logger.warning(
                    "find_company_default_agent_connection_close_failed",
                    error=str(close_err),
                    company_id=company_id,
                )

    return None


def _persist_assistant_reply(
    *,
    conversation_id: int,
    content: str,
    metadata: dict[str, Any] | None = None,
    references: list[dict] | None = None,
) -> None:
    """Persist a clean assistant reply and update conversation stats."""
    from app.database import db as db_proxy
    from app.database.models import Conversation as ORMConversation
    from app.services.message_persistence import (
        save_assistant_message,
        update_conversation_stats,
    )

    with db_proxy.get_session() as persist_session:
        conv_fresh = (
            persist_session.query(ORMConversation)
            .filter(ORMConversation.id == conversation_id)
            .first()
        )
        next_seq = (conv_fresh.message_count + 1) if conv_fresh else 2
        save_assistant_message(
            session=persist_session,
            conversation_id=conversation_id,
            content=content,
            metadata=metadata or {},
            references=references,
            sequence_num=next_seq,
        )
        update_conversation_stats(
            session=persist_session,
            conversation_id=conversation_id,
            last_message=content,
        )


class ChatRequest(BaseModel):
    message: str
    company_context: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None
    agent_name: str | None = None
    model_provider: str | None = None
    session_id: str | None = None
    company_id: str | None = None
    conversation_id: int | None = None
    mode: str | None = None

    @field_validator("message")
    @classmethod
    def filter_message(cls, v: str) -> str:
        return InputFilter.validate_message(v)

    @field_validator("model_provider")
    @classmethod
    def filter_model_provider(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = str(v).strip()
        if not value:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("Invalid model_provider")
        return value


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chat_error_payload_from_exception(exc: Exception) -> dict[str, Any]:
    if getattr(exc, "code", "") == "model_api_key_missing":
        if hasattr(exc, "to_public_payload"):
            payload = exc.to_public_payload()
        else:
            payload = {
                "code": "model_api_key_missing",
                "message": str(exc),
                "requires_config": True,
                "config_target": "llm_api_key",
            }
        message = str(payload.get("message") or "模型 API Key 未配置。")
        return {
            "type": "error",
            "code": "model_api_key_missing",
            "message": message,
            "content": message,
            "requires_config": bool(payload.get("requires_config", True)),
            "config_target": payload.get("config_target", "llm_api_key"),
            "provider": payload.get("provider", ""),
            "model": payload.get("model", ""),
            "env_keys": payload.get("env_keys", []),
        }

    message = f"Stream error: {str(exc)}"
    return {
        "type": "error",
        "code": "chat_stream_error",
        "message": message,
        "content": message,
    }


def _chat_error_payload_from_event(event: dict[str, Any]) -> dict[str, Any]:
    message = str(
        event.get("message")
        or event.get("content")
        or event.get("data")
        or "聊天处理失败"
    )
    return {
        "type": "error",
        "code": event.get("code", "chat_stream_error"),
        "message": message,
        "content": message,
        "requires_config": bool(event.get("requires_config", False)),
        "config_target": event.get("config_target", ""),
        "provider": event.get("provider", ""),
        "model": event.get("model", ""),
        "env_keys": event.get("env_keys", []),
    }


@router.post("", include_in_schema=False)
@router.post("/")
async def chat_stream(
    request: ChatRequest,
    req: Request,
    current_user: User = Depends(get_current_active_user),
):
    """Stream a chat response from the production master route."""

    task_contexts = []

    async def complete_admitted_tasks():
        for task_context in task_contexts:
            await run_admitted_tasks(task_context)

    async def generate_events():
        source_message_id = None
        conversation_id = None
        assistant_response_parts: list[str] = []
        context_package = None
        rag_refs: list[dict] = []
        stream_error_payload: dict[str, Any] | None = None

        try:
            request.company_id = str(current_user.company_id) if current_user.company_id else ""

            guard_decision = detect_high_risk_action(request.message, "master")
            if guard_decision:
                yield _sse(
                    {
                        "type": "content",
                        "content": guard_decision.response,
                        "guarded": True,
                        "requires_human_review": guard_decision.requires_human_review,
                    }
                )
                yield _sse({"type": "done", "guarded": True})
                return

            if request.company_id and not request.company_context:
                request.company_context = _build_company_context_from_db(request.company_id)

            if request.agent_name or request.agent_id:
                logger.info(
                    "chat_deprecated_agent_param_ignored",
                    agent_name=request.agent_name,
                    agent_id=request.agent_id,
                )

            try:
                from app.database import db as db_proxy
                from app.services.message_persistence import (
                    get_or_create_conversation,
                    save_user_message,
                )

                with db_proxy.get_session() as persist_session:
                    conv = get_or_create_conversation(
                        session=persist_session,
                        user_id=current_user.id,
                        company_id=current_user.company_id if current_user.company_id else 0,
                        conversation_id=request.conversation_id,
                        title=request.message,
                    )
                    conversation_id = conv.id
                    source_message = save_user_message(
                        session=persist_session,
                        conversation_id=conversation_id,
                        user_id=current_user.id,
                        content=request.message,
                        metadata={"intent_type": None, "agent_name": "master"},
                        sequence_num=conv.message_count + 1,
                    )
                    source_message_id = source_message.id
                    logger.info(
                        "chat_message_persistence_user_saved",
                        conversation_id=conversation_id,
                    )
            except Exception as persist_err:
                logger.warning("chat_message_persistence_init_failed", error=str(persist_err))

            if _is_kol_search_request(request.message):
                yield _sse({"type": "thinking", "content": "正在查询当前企业达人库..."})
                kol_payload = _search_company_kols_for_chat(
                    message=request.message,
                    company_id=request.company_id or "",
                    user_id=getattr(current_user, "id", 0) or 0,
                )
                kol_response = _format_company_kol_search_response(kol_payload)
                assistant_response_parts.append(kol_response)
                yield _sse({"type": "content", "content": kol_response})
                if conversation_id:
                    try:
                        _persist_assistant_reply(
                            conversation_id=conversation_id,
                            content=kol_response,
                            metadata={
                                "agent_name": "master",
                                "intent_type": "kol_search",
                                "data_source_summary": kol_payload.get(
                                    "data_source_summary", {}
                                ),
                                "code": kol_payload.get("code", ""),
                            },
                        )
                    except Exception as persist_err:
                        logger.warning(
                            "chat_kol_search_persistence_failed", error=str(persist_err)
                        )
                done_payload = {"type": "done"}
                if conversation_id:
                    done_payload["conversation_id"] = conversation_id
                yield _sse(done_payload)
                return

            if _is_logistics_query_request(request.message):
                yield _sse({"type": "thinking", "content": "正在查询当前企业物流记录..."})
                logistics_payload = _query_company_logistics_for_chat(
                    message=request.message,
                    company_id=request.company_id or "",
                )
                logistics_response = _format_company_logistics_response(logistics_payload)
                assistant_response_parts.append(logistics_response)
                yield _sse({"type": "content", "content": logistics_response})
                if conversation_id:
                    try:
                        _persist_assistant_reply(
                            conversation_id=conversation_id,
                            content=logistics_response,
                            metadata={
                                "agent_name": "master",
                                "intent_type": "logistics_search",
                                "code": logistics_payload.get("code", ""),
                                "result_count": len(logistics_payload.get("results") or []),
                            },
                        )
                    except Exception as persist_err:
                        logger.warning(
                            "chat_logistics_search_persistence_failed", error=str(persist_err)
                        )
                done_payload = {"type": "done"}
                if conversation_id:
                    done_payload["conversation_id"] = conversation_id
                yield _sse(done_payload)
                return

            if _is_sales_analysis_request(request.message):
                explicit_metrics = _extract_explicit_sales_metrics(request.message)
                if explicit_metrics:
                    from app.agents.data_analysis import (
                        calculate_sales_summary,
                        format_sales_analysis_report,
                    )

                    source_label = _explicit_sales_source_label(request.message)
                    sales_summary = calculate_sales_summary(
                        orders=explicit_metrics.get("orders", 0),
                        gmv=explicit_metrics.get("gmv", 0),
                        ad_spend=explicit_metrics.get("ad_spend", 0),
                        refund_amount=explicit_metrics.get("refund_amount", 0),
                    )
                    sales_response = format_sales_analysis_report(
                        sales_summary,
                        source_label=source_label,
                        provided_fields=set(explicit_metrics),
                    )
                    yield _sse({"type": "thinking", "content": "正在计算你提供的销售数据..."})
                    assistant_response_parts.append(sales_response)
                    yield _sse({"type": "content", "content": sales_response})
                    if conversation_id:
                        try:
                            _persist_assistant_reply(
                                conversation_id=conversation_id,
                                content=sales_response,
                                metadata={
                                    "agent_name": "data_analysis",
                                    "intent_type": "sales_analysis",
                                    "data_source_status": "user_provided_unverified",
                                    "data_source_label": source_label,
                                    "metric_keys": sorted(explicit_metrics),
                                },
                            )
                        except Exception as persist_err:
                            logger.warning(
                                "chat_sales_analysis_persistence_failed", error=str(persist_err)
                            )
                    done_payload = {"type": "done"}
                    if conversation_id:
                        done_payload["conversation_id"] = conversation_id
                    yield _sse(done_payload)
                    return

                from app.agents.data_analysis import NO_REAL_DATA_MESSAGE

                yield _sse({"type": "thinking", "content": "正在检查当前企业销售数据..."})
                assistant_response_parts.append(NO_REAL_DATA_MESSAGE)
                yield _sse({"type": "content", "content": NO_REAL_DATA_MESSAGE})
                if conversation_id:
                    try:
                        _persist_assistant_reply(
                            conversation_id=conversation_id,
                            content=NO_REAL_DATA_MESSAGE,
                            metadata={
                                "agent_name": "data_analysis",
                                "intent_type": "sales_analysis",
                                "data_source_status": "missing",
                            },
                        )
                    except Exception as persist_err:
                        logger.warning(
                            "chat_sales_analysis_persistence_failed", error=str(persist_err)
                        )
                done_payload = {"type": "done"}
                if conversation_id:
                    done_payload["conversation_id"] = conversation_id
                yield _sse(done_payload)
                return

            yield _sse({"type": "thinking", "content": "正在分析请求..."})

            pipeline = _get_perception_pipeline()
            thread_id = request.session_id or (str(conversation_id) if conversation_id else None)
            skip_rag_preretrieval = _smoke_rag_preretrieval_disabled()
            if skip_rag_preretrieval:
                logger.info("smoke_rag_preretrieval_skipped")
            context_package = await pipeline.build_context_package(
                raw_input=request.message,
                company_id=request.company_id or "",
                thread_id=thread_id,
                agent_name="master",
                skip_rag=skip_rag_preretrieval,
            )
            task_context = TaskContext(
                company_id=current_user.company_id, user_id=current_user.id,
                conversation_id=conversation_id, source_message_id=source_message_id,
                model_key=request.model_provider or None,
            )
            context_package.task_context = task_context
            task_contexts.append(task_context)
            if request.model_provider:
                context_package.intent_entities["model_provider"] = request.model_provider

            rag_refs = (
                context_package.rag_references
                if context_package.rag_references
                else context_package.rag_chunks
            )
            rag_evidence = getattr(context_package, "rag_evidence_chunks", []) or []
            has_rag_context = bool(rag_refs or rag_evidence)
            if not has_rag_context and _is_knowledge_only_request(request.message):
                context_package.cache_hit = True
                context_package.direct_return = (
                    "当前知识库没有找到可引用的匹配内容。"
                    "我不会仅凭通用模型或 mock/fallback 数据补齐答案；"
                    "请补充企业知识库资料后再试。"
                )

            if context_package.cache_hit and context_package.direct_return:
                cached_content = context_package.direct_return
                assistant_response_parts.append(cached_content)
                yield _sse(
                    {"type": "content", "content": cached_content, "cache_hit": True}
                )
            else:
                if rag_refs:
                    yield _sse({"type": "sources", "sources": rag_refs})

                master_router = _get_master_router()
                if master_router is None:
                    stream_error_payload = {
                        "type": "error",
                        "code": "agent_runtime_unavailable",
                        "message": "MasterAgentRouter 未初始化",
                        "content": "MasterAgentRouter 未初始化",
                    }
                    yield _sse(stream_error_payload)
                    done_payload = {"type": "done"}
                    if conversation_id:
                        done_payload["conversation_id"] = conversation_id
                    yield _sse(done_payload)
                    return

                async for event in master_router.execute(context_package):
                    event_type = event.get("type", "")
                    if event_type in {
                        "routing",
                        "plan",
                        "action",
                        "observation",
                        "delegation",
                        "reflection",
                    }:
                        logger.info("chat_internal_event_filtered", event_type=event_type)
                        continue
                    if event_type == "result":
                        final_result = event.get("data", "")
                        assistant_response_parts.append(final_result)
                        yield _sse({"type": "content", "content": final_result})
                    elif event_type == "warning":
                        yield _sse(
                            {
                                "type": "warning",
                                "code": event.get("code", "warning"),
                                "message": event.get(
                                    "message",
                                    event.get("data", event.get("content", "")),
                                ),
                                "from_model": event.get("from_model", ""),
                                "to_model": event.get("to_model", ""),
                            }
                        )
                    elif event_type == "error":
                        stream_error_payload = _chat_error_payload_from_event(event)
                        yield _sse(stream_error_payload)
                    elif event_type == "done":
                        # The public terminal event follows persistence below.
                        continue

            history_saved = False
            if conversation_id:
                try:
                    if stream_error_payload and not assistant_response_parts:
                        assistant_content = stream_error_payload["message"]
                    else:
                        assistant_content = (
                            "\n".join(assistant_response_parts)
                            if assistant_response_parts
                            else "任务已完成"
                        )
                    metadata = {"agent_name": "master"}
                    if stream_error_payload:
                        metadata.update(
                            {
                                "status": "error",
                                "error_code": stream_error_payload.get("code", "chat_stream_error"),
                                "requires_config": stream_error_payload.get("requires_config", False),
                            }
                        )
                    if context_package is not None:
                        metadata.update(
                            {
                                "intent_type": context_package.intent_type,
                                "cache_hit": context_package.cache_hit,
                            }
                        )
                    _persist_assistant_reply(
                        conversation_id=conversation_id,
                        content=assistant_content,
                        metadata=metadata,
                        references=rag_refs if rag_refs else None,
                    )
                    history_saved = True
                except Exception as persist_err:
                    logger.warning(
                        "chat_message_persistence_save_failed", error=str(persist_err)
                    )

            done_payload = {"type": "done", "history_saved": history_saved}
            if conversation_id:
                done_payload["conversation_id"] = conversation_id
            yield _sse(done_payload)

        except Exception as e:
            logger.error("chat_stream_error", error=str(e))
            yield _sse(_chat_error_payload_from_exception(e))

    return StreamingResponse(
        _stream_with_heartbeat(generate_events()),
        media_type="text/event-stream",
        background=BackgroundTask(complete_admitted_tasks),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/health")
async def health_check(req: Request):
    try:
        state = req.app.state
        runtime = getattr(state, "runtime", None)
        runtime_initialized = getattr(runtime, "initialized", None) if runtime is not None else None
        if isinstance(runtime_initialized, bool):
            agent_initialized = runtime_initialized
            source = "runtime"
        else:
            agent_app = getattr(state, "agent_app", None)
            agent_initialized = agent_app is not None
            source = "agent_app"
        return {
            "status": "healthy" if agent_initialized else "degraded",
            "agent_initialized": agent_initialized,
            "source": source,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e), "agent_initialized": False}

"""
物流跟踪 Agent - 样品物流查询与状态跟踪
负责：物流查询、状态跟踪、配送进度监控
"""

import structlog
from sqlalchemy.orm import Session

from app.database.models import LogisticsTracking

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "1.0.0"
PROMPT_UPDATED = "2026-06-21"

LOGISTICS_SYSTEM_PROMPT = """你是物流跟踪数字员工，负责为品牌方提供样品物流查询与状态跟踪服务。

## 核心职责
1. **物流查询**：根据运单号查询物流状态和轨迹
2. **状态跟踪**：实时监控样品配送进度
3. **异常预警**：物流异常（滞留、退回、丢失）自动告警
4. **配送统计**：按达人/样品汇总物流状态

## 物流状态说明
- pending: 待发货
- shipped: 已发货
- in_transit: 运输中
- out_for_delivery: 派送中
- delivered: 已签收
- returned: 已退回
- lost: 丢失

## 输出规范
- 查询结果包含：运单号、快递公司、当前状态、发件地、目的地、达人名称、样品名称
- 多条结果按状态排序（未完成优先）
- 异常状态高亮提醒
"""

STATUS_MAP: dict[str, str] = {
    "pending": "待发货",
    "shipped": "已发货",
    "in_transit": "运输中",
    "out_for_delivery": "派送中",
    "delivered": "已签收",
    "returned": "已退回",
    "lost": "丢失",
}


def query_logistics(
    session: Session,
    company_id: int,
    tracking_number: str | None = None,
    status: str | None = None,
    kol_name: str | None = None,
    limit: int = 20,
) -> list[LogisticsTracking]:
    """查询物流记录

    Args:
        session: 数据库会话
        company_id: 公司 ID（多租户隔离）
        tracking_number: 运单号（可选）
        status: 物流状态（可选）
        kol_name: 达人名称（可选）
        limit: 返回数量限制

    Returns:
        list[LogisticsTracking]: 物流记录列表
    """
    q = session.query(LogisticsTracking).filter(
        LogisticsTracking.company_id == company_id,
    )

    if tracking_number:
        q = q.filter(LogisticsTracking.tracking_number == tracking_number)

    if status:
        q = q.filter(LogisticsTracking.status == status)

    if kol_name:
        q = q.filter(LogisticsTracking.kol_name.ilike(f"%{kol_name}%"))

    # 按创建时间倒序，未完成状态优先
    q = q.order_by(
        LogisticsTracking.status.in_(
            ["pending", "shipped", "in_transit", "out_for_delivery"]
        ).desc(),
        LogisticsTracking.created_at.desc(),
    )

    return q.limit(limit).all()


def format_logistics_result(logistics: list[dict]) -> str:
    """格式化物流查询结果

    Args:
        logistics: 物流记录字典列表

    Returns:
        str: 格式化后的物流状态文本
    """
    if not logistics:
        return "未找到相关物流记录，请确认运单号是否正确，或尝试调整筛选条件。"

    lines = [f"为您找到 {len(logistics)} 条物流记录：\n"]

    for i, item in enumerate(logistics, 1):
        status_cn = STATUS_MAP.get(item.get("status", ""), item.get("status", ""))
        status_icon = "📦" if item.get("status") == "delivered" else "🚚"

        lines.append(f"{status_icon} **{i}. {item.get('tracking_number', 'N/A')}**")
        lines.append(f"   - 快递公司: {item.get('carrier', 'N/A')}")
        lines.append(f"   - 当前状态: {status_cn}")

        status_detail = item.get("status_detail")
        if status_detail:
            lines.append(f"   - 状态详情: {status_detail}")

        lines.append(
            f"   - 发件地: {item.get('origin', 'N/A')} → 目的地: {item.get('destination', 'N/A')}"
        )

        kol_name = item.get("kol_name")
        if kol_name:
            lines.append(f"   - 达人: {kol_name}")

        sample_name = item.get("sample_name")
        if sample_name:
            lines.append(f"   - 样品: {sample_name}")

        lines.append("")

    return "\n".join(lines)


async def get_agent_function():
    """返回物流跟踪 Agent 的可调用函数"""

    async def logistics_agent(message: str, **kwargs) -> str:
        """物流跟踪 Agent 主入口

        Args:
            message: 用户消息
            **kwargs: 额外参数（session, company_id 等）

        Returns:
            str: 物流查询结果
        """
        logger.info(
            "logistics_agent_called",
            message=message[:100],
        )

        session = kwargs.get("session")
        company_id = kwargs.get("company_id", 0)

        # 尝试从消息中提取运单号
        import re

        tracking_match = re.search(r"[A-Za-z]{2}\d{8,}", message)

        if session and company_id:
            if tracking_match:
                tracking_number = tracking_match.group(0)
                results = query_logistics(
                    session=session,
                    company_id=company_id,
                    tracking_number=tracking_number,
                )
            else:
                results = query_logistics(
                    session=session,
                    company_id=company_id,
                )

            formatted = format_logistics_result(
                [
                    {
                        "id": r.id,
                        "tracking_number": r.tracking_number,
                        "carrier": r.carrier,
                        "status": r.status,
                        "status_detail": r.status_detail,
                        "origin": r.origin,
                        "destination": r.destination,
                        "kol_name": r.kol_name,
                        "sample_name": r.sample_name,
                    }
                    for r in results
                ]
            )
            return formatted

        # 无 session 时返回提示
        return "物流查询功能需要数据库连接支持。请确保已登录并重新尝试。"

    return logistics_agent

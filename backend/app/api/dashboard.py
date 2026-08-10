"""
老板驾驶舱 API
提供统计卡片、Agent 状态面板、审核管理、数据看板图表、告警面板的后端数据接口

数据来源说明：
- 统计卡片 / 任务趋势 / Token 消耗：从 PostgreSQL 真实表查询（users / conversations /
  cost_records / tasks），查询失败时降级返回 0 或空列表
- 审核列表：从 evolution_reviews 表查真实待审核记录
- Agent 状态：返回已配置内置 Agent，并叠加真实任务/成本表推断的运行态
- 告警：从失败任务和待审核进化建议生成真实运营告警
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.agents import get_active_agents
from app.auth import get_current_active_user  # 需要认证才能查看驾驶舱数据
from app.core.logging import get_logger
from app.database import User, db

logger = get_logger(__name__)

router = APIRouter(tags=["dashboard"])


class StatCard(BaseModel):
    label: str
    value: int | float
    unit: str | None = None  # 可选单位，用于前端格式化显示
    trend: float | None = None  # 趋势百分比，正数表示上升，负数表示下降
    sub_label: str | None = None  # 副标签，如"较昨日"、"含3个强制审核"


class DashboardOverview(BaseModel):
    stats: list[StatCard]
    agent_statuses: list["AgentStatusCard"]  # 字符串形式的类型引用，解决前向引用问题
    recent_alerts: list["AlertItem"]
    task_trend: list["TrendPoint"]


class AgentStatusCard(BaseModel):
    agent_key: str  # 内部标识符，对应 agent 类型
    display_name: str  # 前端展示名称
    status: str  # working / idle / error
    agent_type: str  # growth(增长) / operations(运营)，用于分组展示
    current_task: str | None = None  # 当前正在执行的任务描述
    token_consumed_today: int = 0
    current_model: str = "default"  # 当前使用的 LLM 模型名称
    last_active: str | None = None


class AlertItem(BaseModel):
    id: int
    agent_key: str  # 关联的 Agent 标识
    alert_type: str  # 告警类型：库存告警、投流异常等
    level: str  # critical / warning / info
    message: str
    company_id: int
    is_read: bool = False  # 是否已读，用于前端高亮显示
    is_handled: bool = False  # 是否已处理，用于区分待处理告警
    created_at: str


class TrendPoint(BaseModel):
    date: str
    completed: int  # 已完成任务数
    created: int  # 新建任务数
    failed: int  # 失败任务数


class ReviewStats(BaseModel):
    mandatory_pending: int = 0  # 强制审核待处理数
    recommended_pending: int = 0  # 推荐审核待处理数
    total_pending: int = 0
    approved_today: int = 0
    rejected_today: int = 0
    timeout_count: int = 0  # 超时未审核数


class ReviewItemResponse(BaseModel):
    id: int
    agent_key: str
    task_type: str  # kol_invite / content_publish / customer_reply / ad_campaign
    title: str
    review_level: str  # mandatory / recommended
    status: str  # pending / approved / rejected
    submitter_id: int
    created_at: str
    timeout_at: str | None = None  # 超时时间，超过后需自动升级


class ReviewListResponse(BaseModel):
    items: list[ReviewItemResponse]
    total: int
    stats: ReviewStats


class TokenConsumptionSummary(BaseModel):
    total_tokens: int
    total_cost: float
    by_agent: list[dict]  # 按 Agent 分组统计
    by_model: list[dict]  # 按模型分组统计
    daily_breakdown: list[dict]  # 每日消耗明细


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(current_user: User = Depends(get_current_active_user)):
    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = current_user.company_id
    return DashboardOverview(
        stats=_get_real_stats(company_id),
        agent_statuses=_get_configured_agent_statuses(company_id),
        recent_alerts=_get_real_alerts(company_id, 10),
        task_trend=_get_real_task_trend(company_id, 30),
    )


def _agent_type_for_role(role: str) -> str:
    growth_roles = {"bd", "content", "kol", "analyst"}
    if role in growth_roles:
        return "growth"
    return "operations"


_RUNNING_TASK_STATUSES = {"pending", "processing", "running", "in_progress", "queued"}
_FAILED_TASK_STATUSES = {"failed", "error"}


def _row_value(row, index: int, default=None):
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


def _timestamp_text(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _latest_timestamp(*values) -> str | None:
    serialized = [_timestamp_text(value) for value in values if value is not None]
    return max(serialized) if serialized else None


def _latest_agent_tasks(company_id: int) -> dict[str, dict]:
    rows = _safe_query(
        """
        SELECT COALESCE(target_agent_name, '') AS agent_key,
               COALESCE(status, '') AS status,
               COALESCE(task_description, '') AS task_description,
               created_at
        FROM tasks
        WHERE company_id = :cid
          AND target_agent_name IS NOT NULL
          AND target_agent_name != ''
        ORDER BY created_at DESC
        LIMIT 200
        """,
        {"cid": company_id},
    )
    latest: dict[str, dict] = {}
    for row in rows:
        agent_key = str(_row_value(row, 0, "") or "").strip()
        if not agent_key or agent_key in latest:
            continue
        latest[agent_key] = {
            "status": str(_row_value(row, 1, "") or "").lower(),
            "task": str(_row_value(row, 2, "") or "")[:180],
            "created_at": _row_value(row, 3),
        }
    return latest


def _today_agent_usage(company_id: int) -> dict[str, dict]:
    today = date.today().isoformat()
    usage_rows = _safe_query(
        """
        SELECT COALESCE(agent_key, '') AS agent_key,
               COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens,
               MAX(created_at) AS last_active
        FROM cost_records
        WHERE company_id = :cid
          AND DATE(created_at) = :today
          AND agent_key IS NOT NULL
          AND agent_key != ''
        GROUP BY agent_key
        """,
        {"cid": company_id, "today": today},
    )
    usage: dict[str, dict] = {}
    for row in usage_rows:
        agent_key = str(_row_value(row, 0, "") or "").strip()
        if not agent_key:
            continue
        usage[agent_key] = {
            "tokens": int(_row_value(row, 1, 0) or 0),
            "last_active": _row_value(row, 2),
            "model": "no_recent_usage",
        }

    model_rows = _safe_query(
        """
        SELECT COALESCE(agent_key, '') AS agent_key,
               COALESCE(model_name, '') AS model_name,
               created_at
        FROM cost_records
        WHERE company_id = :cid
          AND DATE(created_at) = :today
          AND agent_key IS NOT NULL
          AND agent_key != ''
        ORDER BY created_at DESC
        LIMIT 200
        """,
        {"cid": company_id, "today": today},
    )
    for row in model_rows:
        agent_key = str(_row_value(row, 0, "") or "").strip()
        if not agent_key:
            continue
        info = usage.setdefault(
            agent_key,
            {"tokens": 0, "last_active": _row_value(row, 2), "model": "no_recent_usage"},
        )
        if info["model"] == "no_recent_usage":
            info["model"] = str(_row_value(row, 1, "") or "unknown")
            info["last_active"] = _latest_timestamp(info.get("last_active"), _row_value(row, 2))
    return usage


def _status_from_runtime(task: dict | None, usage: dict | None) -> str:
    if task:
        task_status = task.get("status")
        if task_status in _RUNNING_TASK_STATUSES:
            return "working"
        if task_status in _FAILED_TASK_STATUSES:
            return "error"
        return "idle"
    if usage and usage.get("tokens", 0) > 0:
        return "idle"
    return "configured"


def _agent_status_card(
    agent_key: str,
    info: dict,
    task: dict | None,
    usage: dict | None,
) -> AgentStatusCard:
    role = str(info.get("role", "agent"))
    return AgentStatusCard(
        agent_key=agent_key,
        display_name=info.get("name_display") or agent_key,
        status=_status_from_runtime(task, usage),
        agent_type=_agent_type_for_role(role),
        current_task=(task.get("task") if task else None) or None,
        token_consumed_today=int((usage or {}).get("tokens", 0) or 0),
        current_model=str((usage or {}).get("model") or "no_recent_usage"),
        last_active=_latest_timestamp(
            task.get("created_at") if task else None,
            (usage or {}).get("last_active"),
        ),
    )


def _get_configured_agent_statuses(company_id: int) -> list[AgentStatusCard]:
    """Return configured built-in agents enriched with real runtime evidence when available."""
    latest_tasks = _latest_agent_tasks(company_id)
    today_usage = _today_agent_usage(company_id)
    statuses = []
    active_agents = get_active_agents()
    for agent_key, info in active_agents.items():
        statuses.append(
            _agent_status_card(
                agent_key,
                info,
                latest_tasks.get(agent_key),
                today_usage.get(agent_key),
            )
        )

    for agent_key in sorted((set(latest_tasks) | set(today_usage)) - set(active_agents)):
        statuses.append(
            _agent_status_card(
                agent_key,
                {"role": "agent", "name_display": agent_key},
                latest_tasks.get(agent_key),
                today_usage.get(agent_key),
            )
        )
    return statuses


def _get_real_stats(company_id: int) -> list[StatCard]:
    """从数据库查询真实统计数据，查询失败降级返回 0。

    数据源：
    - 在线 Agent 数：AGENT_REGISTRY 中 active=True 的条目数
    - 用户数：users 表按 company_id 过滤 COUNT
    - 对话数：conversations 表按 company_id 过滤 COUNT
    - 今日 Token：cost_records 表按 company_id + 今日 SUM(input_tokens + output_tokens)
    - 今日消耗：cost_records 表按 company_id + 今日 SUM(cost_usd)
    """

    def _safe_scalar(query: str, params: dict, default: int | float = 0):
        """执行聚合查询，失败时降级返回 default（不抛异常）"""
        session = None
        try:
            session = db.get_session()
            result = session.execute(text(query), params)
            row = result.fetchone()
            if row and row[0] is not None:
                return row[0]
            return default
        except Exception as e:
            logger.warning("dashboard_stat_query_failed", error=str(e), company_id=company_id)
            return default
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as e:
                    logger.warning("session_close_failed", error=str(e))

    # 1. 在线 Agent 数：从 AGENT_REGISTRY 统计 active=True
    active_agent_count = len(get_active_agents())

    # 2. 用户数：从 users 表 COUNT（按公司过滤）
    user_count = _safe_scalar(
        "SELECT COUNT(*) FROM users WHERE company_id = :cid",
        {"cid": company_id},
    )

    # 3. 对话数：从 conversations 表 COUNT（按公司过滤）
    conversation_count = _safe_scalar(
        "SELECT COUNT(*) FROM conversations WHERE company_id = :cid",
        {"cid": company_id},
    )

    # 4. 今日 Token 消耗：从 cost_records 表 SUM(input_tokens + output_tokens)
    token_today = _safe_scalar(
        "SELECT COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) "
        "FROM cost_records WHERE company_id = :cid AND DATE(created_at) = CURRENT_DATE",
        {"cid": company_id},
    )

    # 5. 今日消耗（美元）：从 cost_records 表 SUM(cost_usd)
    cost_today = _safe_scalar(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_records "
        "WHERE company_id = :cid AND DATE(created_at) = CURRENT_DATE",
        {"cid": company_id},
    )

    # 6. 待审核数：从 evolution_reviews 表 COUNT status='pending'
    pending_count = _safe_scalar(
        "SELECT COUNT(*) FROM evolution_reviews WHERE company_id = :cid AND status = 'pending'",
        {"cid": company_id},
    )

    return [
        StatCard(label="在线 Agent", value=active_agent_count, unit="个"),
        StatCard(label="用户数", value=int(user_count), unit="人"),
        StatCard(label="对话数", value=int(conversation_count), unit="个"),
        StatCard(label="今日 Token", value=int(token_today), unit="tokens"),
        StatCard(label="今日消耗", value=round(float(cost_today), 2), unit="USD"),
        StatCard(label="待审核", value=int(pending_count), unit="个"),
    ]


@router.get("/reviews", response_model=ReviewListResponse)
async def get_review_list(
    level: str = Query(None),  # 可选过滤：按审核级别筛选
    status: str = Query(None),  # 可选过滤：按审核状态筛选
    page: int = Query(1, ge=1),  # 分页，最小为 1
    page_size: int = Query(20, ge=1, le=100),  # 每页条目，限制 1-100 防止恶意请求
    current_user: User = Depends(get_current_active_user),
):
    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = current_user.company_id
    items, total = _get_real_reviews(company_id, level, status, page, page_size)
    return ReviewListResponse(
        items=items,
        total=total,
        stats=_get_real_review_stats(company_id),
    )


@router.get("/agents", response_model=list[AgentStatusCard])
async def get_agent_statuses(current_user: User = Depends(get_current_active_user)):
    return _get_configured_agent_statuses(current_user.company_id)


@router.get("/alerts", response_model=list[AlertItem])
async def get_alerts(
    limit: int = Query(20, ge=1, le=100),  # 限制返回条数，避免数据量过大
    current_user: User = Depends(get_current_active_user),
):
    return _get_real_alerts(current_user.company_id, limit)


@router.get("/token-consumption", response_model=TokenConsumptionSummary)
async def get_token_consumption(
    days: int = Query(7, ge=1, le=90),  # 可查询 1-90 天的数据
    current_user: User = Depends(get_current_active_user),
):
    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = current_user.company_id
    return _get_real_token_consumption(company_id, days)


@router.get("/task-trend", response_model=list[TrendPoint])
async def get_task_trend(
    days: int = Query(30, ge=1, le=90),
    current_user: User = Depends(get_current_active_user),
):
    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = current_user.company_id
    return _get_real_task_trend(company_id, days)


# ============================================================
# 真实数据查询辅助函数
# 所有函数均通过 SQLAlchemy text() 执行参数化 SQL，查询失败时降级返回空值
# ============================================================


def _safe_query(query: str, params: dict) -> list:
    """执行查询返回所有行，失败时返回空列表。

    供 dashboard 内部多次复用，确保异常不会冒泡到路由层。
    """
    session = None
    try:
        session = db.get_session()
        result = session.execute(text(query), params)
        return result.fetchall()
    except Exception as e:
        logger.warning("dashboard_query_failed", error=str(e))
        return []
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as e:
                logger.warning("session_close_failed", error=str(e))


def _safe_scalar(query: str, params: dict, default: int | float = 0):
    """执行聚合查询返回单值，失败时降级返回 default。"""
    session = None
    try:
        session = db.get_session()
        result = session.execute(text(query), params)
        row = result.fetchone()
        if row and row[0] is not None:
            return row[0]
        return default
    except Exception as e:
        logger.warning("dashboard_scalar_query_failed", error=str(e))
        return default
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as e:
                logger.warning("session_close_failed", error=str(e))



def _get_real_alerts(company_id: int, limit: int) -> list[AlertItem]:
    """Build dashboard alerts from real failed tasks and pending evolution reviews."""
    alerts: list[AlertItem] = []
    failed_task_rows = _safe_query(
        """
        SELECT id, COALESCE(target_agent_name, 'task') AS agent_key,
               COALESCE(task_description, '') AS task_description, created_at
        FROM tasks
        WHERE company_id = :cid AND status = 'failed'
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"cid": company_id, "limit": limit},
    )
    for row in failed_task_rows:
        alerts.append(
            AlertItem(
                id=int(row[0]),
                agent_key=str(row[1] or "task"),
                alert_type="task_failed",
                level="warning",
                message=(str(row[2] or "Task failed")[:180] or "Task failed"),
                company_id=company_id,
                created_at=str(row[3]),
            )
        )

    remaining = max(limit - len(alerts), 0)
    if remaining:
        review_rows = _safe_query(
            """
            SELECT id, COALESCE(tool_name, 'evolution') AS agent_key,
                   COALESCE(suggestion_text, '') AS suggestion_text, created_at
            FROM evolution_reviews
            WHERE company_id = :cid AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"cid": company_id, "limit": remaining},
        )
        for row in review_rows:
            alerts.append(
                AlertItem(
                    id=-int(row[0]),
                    agent_key=str(row[1] or "evolution"),
                    alert_type="review_pending",
                    level="info",
                    message=(str(row[2] or "Evolution review pending")[:180] or "Evolution review pending"),
                    company_id=company_id,
                    created_at=str(row[3]),
                )
            )

    return alerts[:limit]
def _get_real_task_trend(company_id: int, days: int) -> list[TrendPoint]:
    """从 tasks 表按天聚合任务趋势。

    指标：
    - completed: status='completed' 的任务数
    - created: 当天创建的任务总数（含所有状态）
    - failed: status='failed' 的任务数

    按 created_at 日期分组，仅返回有数据的日子；无数据时返回空列表。
    """
    start_date = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = _safe_query(
        """
        SELECT
            DATE(created_at) AS d,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
            COUNT(*) AS created,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
        FROM tasks
        WHERE company_id = :cid AND DATE(created_at) >= :start
        GROUP BY DATE(created_at)
        ORDER BY d
        """,
        {"cid": company_id, "start": start_date},
    )
    return [
        TrendPoint(
            date=str(r[0]),
            completed=int(r[1] or 0),
            created=int(r[2] or 0),
            failed=int(r[3] or 0),
        )
        for r in rows
    ]


def _get_real_token_consumption(company_id: int, days: int) -> TokenConsumptionSummary:
    """从 cost_records 表查询真实成本数据。

    无数据时返回全零的 summary，前端显示空状态。
    """
    start_date = (date.today() - timedelta(days=days - 1)).isoformat()
    params = {"cid": company_id, "start": start_date}

    # 1. 汇总 token 与成本
    total_rows = _safe_query(
        """
        SELECT
            COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0),
            COALESCE(SUM(cost_usd), 0)
        FROM cost_records
        WHERE company_id = :cid AND DATE(created_at) >= :start
        """,
        params,
    )
    total_tokens = int(total_rows[0][0]) if total_rows else 0
    total_cost = round(float(total_rows[0][1]), 2) if total_rows else 0.0

    # 2. 按 agent 分组
    agent_rows = _safe_query(
        """
        SELECT
            COALESCE(agent_key, 'unknown') AS agent_key,
            COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens,
            COALESCE(SUM(cost_usd), 0) AS cost
        FROM cost_records
        WHERE company_id = :cid AND DATE(created_at) >= :start
        GROUP BY agent_key
        ORDER BY tokens DESC
        """,
        params,
    )
    by_agent = [
        {"agent_key": r[0], "tokens": int(r[1]), "cost": round(float(r[2]), 2)} for r in agent_rows
    ]

    # 3. 按 model 分组
    model_rows = _safe_query(
        """
        SELECT
            model_name,
            COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens,
            COALESCE(SUM(cost_usd), 0) AS cost
        FROM cost_records
        WHERE company_id = :cid AND DATE(created_at) >= :start
        GROUP BY model_name
        ORDER BY tokens DESC
        """,
        params,
    )
    by_model = [
        {"model": r[0], "tokens": int(r[1]), "cost": round(float(r[2]), 2)} for r in model_rows
    ]

    # 4. 每日明细
    daily_rows = _safe_query(
        """
        SELECT
            DATE(created_at) AS d,
            COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens,
            COALESCE(SUM(cost_usd), 0) AS cost
        FROM cost_records
        WHERE company_id = :cid AND DATE(created_at) >= :start
        GROUP BY DATE(created_at)
        ORDER BY d
        """,
        params,
    )
    daily_breakdown = [
        {"date": str(r[0]), "tokens": int(r[1]), "cost": round(float(r[2]), 2)} for r in daily_rows
    ]

    return TokenConsumptionSummary(
        total_tokens=total_tokens,
        total_cost=total_cost,
        by_agent=by_agent,
        by_model=by_model,
        daily_breakdown=daily_breakdown,
    )


def _get_real_reviews(
    company_id: int, level: str | None, status: str | None, page: int, page_size: int
) -> tuple[list[ReviewItemResponse], int]:
    """从 evolution_reviews 表查询真实待审核列表。

    表字段：id, agent_id, company_id, tool_name, suggestion_text, status, reviewed_by, created_at
    映射到 ReviewItemResponse：
    - agent_key 通过 LEFT JOIN agents.name 获取，找不到时回退为 agent_id 字符串
    - review_level 统一映射为 "recommended"（进化建议默认推荐审核级别）
    - submitter_id 用 agent_id（Agent 即建议提交者）
    - timeout_at 恒为 None（evolution_reviews 表无超时机制）

    level 过滤：若 level 指定且不是 "recommended"，则无匹配项返回空。
    """
    params: dict = {"cid": company_id}
    # evolution_reviews 表无 review_level 字段，所有记录统一为 "recommended"
    if level and level != "recommended":
        return [], 0

    if status:
        params["status"] = status
        count_sql = (
            "SELECT COUNT(*) FROM evolution_reviews er "
            "WHERE er.company_id = :cid AND er.status = :status"
        )
        reviews_sql = """
        SELECT
            er.id,
            COALESCE(a.name, CAST(er.agent_id AS TEXT)) AS agent_key,
            COALESCE(er.tool_name, 'evolution') AS task_type,
            er.suggestion_text,
            er.status,
            COALESCE(er.agent_id, 0) AS submitter_id,
            er.created_at
        FROM evolution_reviews er
        LEFT JOIN agents a ON a.id = er.agent_id
        WHERE er.company_id = :cid AND er.status = :status
        ORDER BY er.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    else:
        count_sql = "SELECT COUNT(*) FROM evolution_reviews er WHERE er.company_id = :cid"
        reviews_sql = """
        SELECT
            er.id,
            COALESCE(a.name, CAST(er.agent_id AS TEXT)) AS agent_key,
            COALESCE(er.tool_name, 'evolution') AS task_type,
            er.suggestion_text,
            er.status,
            COALESCE(er.agent_id, 0) AS submitter_id,
            er.created_at
        FROM evolution_reviews er
        LEFT JOIN agents a ON a.id = er.agent_id
        WHERE er.company_id = :cid
        ORDER BY er.created_at DESC
        LIMIT :limit OFFSET :offset
        """

    # 1. 查询总数
    total = int(_safe_scalar(count_sql, params) or 0)
    if total == 0:
        return [], 0

    # 2. 分页查询（LEFT JOIN agents 获取 agent 名称作为 agent_key）
    offset = (page - 1) * page_size
    paging_params = {**params, "limit": page_size, "offset": offset}
    rows = _safe_query(reviews_sql, paging_params)

    items = []
    for r in rows:
        suggestion = r[3] or ""
        title = suggestion[:100] if len(suggestion) > 100 else (suggestion or f"进化建议 #{r[0]}")
        created_at_val = r[6]
        items.append(
            ReviewItemResponse(
                id=int(r[0]),
                agent_key=str(r[1]),
                task_type=str(r[2]),
                title=title,
                review_level="recommended",
                status=str(r[4]),
                submitter_id=int(r[5]),
                created_at=str(created_at_val) if created_at_val is not None else "",
                timeout_at=None,
            )
        )
    return items, total


def _get_real_review_stats(company_id: int) -> ReviewStats:
    """从 evolution_reviews 表查询真实审核统计。

    evolution_reviews 表无 mandatory/recommended 级别区分，所有 pending 统一计入
    recommended_pending；无超时机制，timeout_count 恒为 0。
    """
    recommended_pending = int(
        _safe_scalar(
            "SELECT COUNT(*) FROM evolution_reviews WHERE company_id = :cid AND status = 'pending'",
            {"cid": company_id},
        )
        or 0
    )
    approved_today = int(
        _safe_scalar(
            "SELECT COUNT(*) FROM evolution_reviews "
            "WHERE company_id = :cid AND status = 'approved' "
            "AND DATE(reviewed_at) = CURRENT_DATE",
            {"cid": company_id},
        )
        or 0
    )
    rejected_today = int(
        _safe_scalar(
            "SELECT COUNT(*) FROM evolution_reviews "
            "WHERE company_id = :cid AND status = 'rejected' "
            "AND DATE(reviewed_at) = CURRENT_DATE",
            {"cid": company_id},
        )
        or 0
    )
    return ReviewStats(
        mandatory_pending=0,  # evolution_reviews 无 mandatory 级别
        recommended_pending=recommended_pending,
        total_pending=recommended_pending,
        approved_today=approved_today,
        rejected_today=rejected_today,
        timeout_count=0,  # 无超时机制
    )

"""
老板驾驶舱 API
提供统计卡片、Agent 状态面板、审核管理、数据看板图表、告警面板的后端数据接口
"""

import random  # 目前使用 mock 数据，随机生成模拟数据用于演示
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import get_current_active_user  # 需要认证才能查看驾驶舱数据

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
async def get_dashboard_overview(company_id: int = Query(...), _user=Depends(get_current_active_user)):
    # TODO: Replace mock data with real data source
    # 使用 Query(...) 强制要求 company_id，实现多租户数据隔离
    return DashboardOverview(
        stats=[
            StatCard(label="在线 Agent", value=6, unit="个", trend=20.0, sub_label="较昨日"),
            StatCard(label="进行中任务", value=23, unit="个", trend=15.0, sub_label="较昨日"),
            StatCard(label="今日完成", value=47, unit="个", trend=-5.0, sub_label="较昨日"),
            StatCard(label="待审核", value=12, unit="个", sub_label="含3个强制审核"),
            StatCard(label="今日 Token", value=285000, unit="tokens", trend=8.5),
            StatCard(label="今日消耗", value=12.50, unit="元", trend=8.3),
        ],
        agent_statuses=_mock_agent_statuses(),
        recent_alerts=_mock_recent_alerts(company_id),
        task_trend=_mock_task_trend(30),
    )


@router.get("/reviews", response_model=ReviewListResponse)
async def get_review_list(
    company_id: int = Query(...),
    level: str = Query(None),  # 可选过滤：按审核级别筛选
    status: str = Query(None),  # 可选过滤：按审核状态筛选
    page: int = Query(1, ge=1),  # 分页，最小为 1
    page_size: int = Query(20, ge=1, le=100),  # 每页条目，限制 1-100 防止恶意请求
    _user=Depends(get_current_active_user),
):
    items = _mock_review_items(level, status, page, page_size)
    return ReviewListResponse(
        items=items,
        total=len(items) * (page if page > 1 else 3),  # 模拟分页总数，非第一页时乘以页码
        stats=ReviewStats(
            mandatory_pending=3,
            recommended_pending=9,
            total_pending=12,
            approved_today=15,
            rejected_today=2,
            timeout_count=1,
        ),
    )


@router.get("/agents", response_model=list[AgentStatusCard])
async def get_agent_statuses(company_id: int = Query(...), _user=Depends(get_current_active_user)):
    return _mock_agent_statuses()


@router.get("/alerts", response_model=list[AlertItem])
async def get_alerts(
    company_id: int = Query(...),
    limit: int = Query(20, ge=1, le=100),  # 限制返回条数，避免数据量过大
    _user=Depends(get_current_active_user),
):
    return _mock_recent_alerts(company_id)[:limit]


@router.get("/token-consumption", response_model=TokenConsumptionSummary)
async def get_token_consumption(
    company_id: int = Query(...),
    days: int = Query(7, ge=1, le=90),  # 可查询 1-90 天的数据
    _user=Depends(get_current_active_user),
):
    agents = ["brand_bd", "content_ops", "data_analyst", "customer_service",
              "warehouse_logistics", "visual_designer", "product_selector", "ad_delivery"]
    models = ["deepseek-chat", "gpt-4o", "doubao-pro", "qwen-max"]
    daily = []
    for d in range(days):
        day = (date.today() - timedelta(days=d)).isoformat()  # 生成每日日期，从今天往前推
        daily.append({"date": day, "tokens": random.randint(80000, 350000), "cost": round(random.uniform(4, 18), 2)})
    return TokenConsumptionSummary(
        total_tokens=sum(d["tokens"] for d in daily),  # 汇总所有天数的 token
        total_cost=round(sum(d["cost"] for d in daily), 2),
        by_agent=[{"agent_key": a, "tokens": random.randint(30000, 120000),
                    "cost": round(random.uniform(1.5, 8), 2)} for a in agents],
        by_model=[{"model": m, "tokens": random.randint(50000, 200000),
                    "cost": round(random.uniform(3, 12), 2)} for m in models],
        daily_breakdown=daily,
    )


@router.get("/task-trend", response_model=list[TrendPoint])
async def get_task_trend(
    company_id: int = Query(...),
    days: int = Query(30, ge=1, le=90),
    _user=Depends(get_current_active_user),
):
    return _mock_task_trend(days)


def _mock_agent_statuses() -> list[AgentStatusCard]:
    agents = [
        ("brand_bd", "品牌商务", "working"),
        ("content_ops", "内容运营", "idle"),
        ("data_analyst", "数据分析", "working"),
        ("customer_service", "客服专员", "working"),
        ("warehouse_logistics", "仓储物流", "idle"),
        ("visual_designer", "视觉设计", "working"),
        ("product_selector", "供应链选品", "idle"),
        ("ad_delivery", "智能投流", "working"),
    ]
    return [
        AgentStatusCard(
            agent_key=a[0],
            display_name=a[1],
            status=a[2],
            agent_type="growth" if a[0] in ("product_selector", "ad_delivery") else "operations",  # 选品和投流属于增长类，其余为运营类
            current_task="处理中..." if a[2] == "working" else None,  # 工作中的 Agent 显示占位任务
            token_consumed_today=random.randint(5000, 50000),
            current_model=random.choice(["deepseek-chat", "doubao-pro", "qwen-max"]),
            last_active="2026-05-28T14:30:00",
        )
        for a in agents
    ]


def _mock_recent_alerts(company_id: int) -> list[AlertItem]:
    alert_types = ["库存告警", "投流异常", "客服风险", "订单异常", "数据异常"]
    levels = ["critical", "warning", "info"]
    return [
        AlertItem(
            id=company_id * 1000 + i,  # 基于 company_id 生成唯一 ID
            agent_key=random.choice(["brand_bd", "data_analyst", "customer_service", "warehouse_logistics", "ad_delivery"]),
            alert_type=random.choice(alert_types),
            level=random.choice(levels),
            message=f"示例告警消息 #{i+1}: 检测到{random.choice(alert_types)}",
            company_id=company_id,
            is_read=i > 2,  # 前 3 条未读，其余已读，模拟真实场景
            is_handled=i > 4,  # 前 5 条未处理，其余已处理
            created_at="2026-05-28T10:00:00",
        )
        for i in range(10)
    ]


def _mock_task_trend(days: int) -> list[TrendPoint]:
    trend = []
    for d in range(days):
        day = (date.today() - timedelta(days=d)).isoformat()
        trend.append(TrendPoint(
            date=day,
            completed=random.randint(20, 60),
            created=random.randint(25, 65),
            failed=random.randint(0, 5),
        ))
    return list(reversed(trend))  # 反转列表，使日期从早到晚排列


def _mock_review_items(level: str | None, status: str | None,
                         page: int, page_size: int) -> list[ReviewItemResponse]:
    items = []
    for i in range(page_size * page):  # 生成足够多的数据以支持分页
        item = ReviewItemResponse(
            id=8000 + i,
            agent_key=random.choice(["brand_bd", "content_ops", "customer_service", "ad_delivery"]),
            task_type=random.choice(["kol_invite", "content_publish", "customer_reply", "ad_campaign"]),
            title=f"审核项 #{8000+i}",
            review_level=random.choice(["mandatory", "recommended"]),
            status=random.choice(["pending", "approved", "rejected"]),
            submitter_id=1000 + i,
            created_at="2026-05-28T09:00:00",
            timeout_at="2026-05-28T21:00:00" if random.random() > 0.7 else None,  # 30% 概率设置超时时间
        )
        if level and item.review_level != level:  # 按审核级别过滤
            continue
        if status and item.status != status:  # 按审核状态过滤
            continue
        items.append(item)
    return items[:page_size]  # 截取当前页所需的数据量

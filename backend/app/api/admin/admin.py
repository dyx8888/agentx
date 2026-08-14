# 管理员后台 API 接口文件
# 这个文件提供了管理后台需要的各种接口，用来管理公司、用户、订阅和用量
# 通俗地说：这是"管理员专用的后台管理工具"
"""
平台管理员后台 API
公司列表管理、用户管理、订阅管理、用量监控
"""

import os

# FastAPI 框架的核心工具
# APIRouter: 创建路由对象，用来注册 API 接口
# Depends: 依赖注入，在执行接口函数前自动执行一些前置操作（比如验证登录）
# HTTPException: 抛出 HTTP 错误（比如 403 无权限）
# Query: 从 URL 参数中获取数据（比如 ?days=30）
from fastapi import APIRouter, Depends, HTTPException, Query
# Pydantic 的数据模型基类，用来定义 API 请求和响应的数据格式
# 就像一份"数据合同"，规定了数据长什么样子
from pydantic import BaseModel

# 导入用户认证功能，用来验证当前用户是否已登录
from app.auth import get_current_active_user
from app.core.logging import get_logger

# 创建路由对象，tags=["admin"] 表示这个路由在 API 文档中归入 "admin" 分组
router = APIRouter(tags=["admin"])
logger = get_logger(__name__)


def _is_production_env() -> bool:
    return os.getenv("ENVIRONMENT", "").lower() == "production" or os.getenv("ENV", "").lower() in {
        "prod",
        "production",
    }


def _allow_mock_admin_fallback() -> bool:
    return not _is_production_env()


# 提示词版本信息的数据模型
# 用来描述一个提示词模块的版本信息
class PromptVersionItem(BaseModel):
    module: str      # 模块名称（比如 "agent"、"chat"）
    version: str     # 版本号（比如 "1.0.0"）
    updated: str     # 更新时间（比如 "2026-06-01"）


# 提示词版本查询的响应格式
# 返回一个提示词版本列表
class PromptVersionResponse(BaseModel):
    prompts: list[PromptVersionItem]  # 提示词版本列表


# 公司信息的数据模型
# 描述一个公司的基本信息，用于在列表中展示
class CompanyListItem(BaseModel):
    id: int                     # 公司 ID（唯一标识）
    name: str                   # 公司名称
    status: str                 # 公司状态（active=正常, inactive=停用）
    agent_count: int            # 该公司的 Agent 数量
    user_count: int             # 该公司的用户数量
    created_at: str             # 公司创建时间
    subscription_plan: str      # 订阅计划（starter=初创版, professional=专业版, enterprise=企业版）


# 公司列表查询的响应格式
class CompanyListResponse(BaseModel):
    companies: list[CompanyListItem]  # 公司列表
    total: int                         # 公司总数


# 用户信息的数据模型
# 描述一个用户的基本信息
class UserListItem(BaseModel):
    id: int                 # 用户 ID（唯一标识）
    username: str           # 用户名
    email: str              # 邮箱
    company_id: int         # 所属公司 ID
    company_name: str       # 所属公司名称
    is_active: bool          # 是否活跃（True=正常, False=已禁用）
    is_admin: bool           # 是否是管理员
    created_at: str          # 用户创建时间


# 用户列表查询的响应格式
class UserListResponse(BaseModel):
    users: list[UserListItem]  # 用户列表
    total: int                  # 用户总数


# 订阅计划的数据模型
# 描述一个付费计划包含哪些内容
class SubscriptionPlan(BaseModel):
    id: str                 # 计划 ID（starter/professional/enterprise）
    name: str               # 计划名称（初创版/专业版/企业版）
    agent_limit: int        # 最多可以创建多少个 Agent
    price_monthly: float    # 月付价格（元）
    price_yearly: float     # 年付价格（元）
    features: list[str]     # 功能列表


# 公司当前订阅情况的数据模型
class CompanySubscription(BaseModel):
    company_id: int                 # 公司 ID
    company_name: str               # 公司名称
    plan_id: str                    # 订阅的计划 ID
    plan_name: str                  # 订阅的计划名称
    status: str                     # 订阅状态（active=正常, expired=已过期）
    current_period_start: str       # 当前计费周期开始时间
    current_period_end: str         # 当前计费周期结束时间
    agents_used: int                # 已使用的 Agent 数量
    agents_limit: int               # 允许的最大 Agent 数量


# 订阅列表查询的响应格式
class SubscriptionListResponse(BaseModel):
    subscriptions: list[CompanySubscription]  # 各公司的订阅情况列表
    total: int                                # 订阅总数
    available_plans: list[SubscriptionPlan]   # 所有可选的计划


# 用量数据的数据模型
# 记录每个公司的每个 Agent 使用了多少 Token（AI 模型的计算单位）
class UsageItem(BaseModel):
    company_id: int             # 公司 ID
    company_name: str           # 公司名称
    agent_key: str              # Agent 的英文标识（如 brand_bd）
    agent_display_name: str     # Agent 的中文名称（如 品牌商务）
    total_tokens: int           # 消耗的 Token 总数（Token 是 AI 的"字数"单位）
    total_cost: float           # 产生的费用（美元）
    period_days: int            # 统计周期（多少天）


# 用量列表查询的响应格式
class UsageListResponse(BaseModel):
    usages: list[UsageItem]   # 用量明细列表
    total_tokens_all: int      # 所有公司的总 Token 消耗
    total_cost_all: float      # 所有公司的总费用


# 系统提供的三个订阅计划
# 就像一个产品的三个档位：基础版、进阶版、旗舰版
AVAILABLE_PLANS = [
    SubscriptionPlan(id="starter", name="初创版", agent_limit=3,
                      price_monthly=299, price_yearly=2990,
                      features=["3个Agent职位", "基础RAG知识库", "社区支持"]),
    SubscriptionPlan(id="professional", name="专业版", agent_limit=8,
                      price_monthly=999, price_yearly=9990,
                      features=["8个Agent全职位", "高级RAG知识库", "LoRA微调",
                                 "多平台API对接", "优先技术支持"]),
    SubscriptionPlan(id="enterprise", name="企业版", agent_limit=20,
                      price_monthly=2999, price_yearly=29990,
                      features=["自定义Agent", "私有化部署选项", "专属客户经理",
                                 "SLA保障", "API定制开发"]),
]


# 模拟公司列表数据
# 函数名前加下划线 _ 表示"私有函数"，只在本文件内部使用
# 这些数据是写死在代码里的，不是从数据库读取的
# 作用有两点：1) 开发测试时使用  2) 数据库不可用时作为备用方案
# 就像商店里展示的"样品"，不是真正的商品
def _mock_companies() -> list[CompanyListItem]:
    return [
        CompanyListItem(
            id=1, name="示例电商公司", status="active",
            agent_count=8, user_count=5,
            created_at="2025-06-01", subscription_plan="professional",
        ),
        CompanyListItem(
            id=2, name="测试店铺", status="active",
            agent_count=3, user_count=2,
            created_at="2025-08-15", subscription_plan="starter",
        ),
    ]


# 模拟用户列表数据：用于演示或数据库不可用时作为降级方案
def _mock_users() -> list[UserListItem]:
    return [
        UserListItem(
            id=101, username="admin", email="admin@example.com",
            company_id=1, company_name="示例电商公司",
            is_active=True, is_admin=True, created_at="2025-06-01",
        ),
        UserListItem(
            id=102, username="operator1", email="op1@example.com",
            company_id=1, company_name="示例电商公司",
            is_active=True, is_admin=False, created_at="2025-06-10",
        ),
    ]


# 模拟订阅数据：用于演示或数据库不可用时作为降级方案
def _mock_subscriptions() -> list[CompanySubscription]:
    return [
        CompanySubscription(
            company_id=1, company_name="示例电商公司",
            plan_id="professional", plan_name="专业版",
            status="active",
            current_period_start="2026-05-01",
            current_period_end="2026-06-01",
            agents_used=8, agents_limit=8,
        ),
        CompanySubscription(
            company_id=2, company_name="测试店铺",
            plan_id="starter", plan_name="初创版",
            status="active",
            current_period_start="2026-05-01",
            current_period_end="2026-06-01",
            agents_used=3, agents_limit=3,
        ),
    ]


# 从数据库获取真实的公司列表
# 这段代码有点复杂，因为要兼容两种数据格式：
# 1) dict 类型（字典，用 c.get("字段名") 取值）
# 2) 对象类型（用 c.字段名 取值）
# 这么做是为了适配不同版本的数据库查询结果
def _get_real_companies() -> list[CompanyListItem]:
    try:
        # 从 app.database 导入数据库操作对象
        # 放在函数内部导入（延迟导入），避免在文件顶部导入时出错
        from app.database import db
        # 查询所有公司
        companies = db.get_all_companies()
        if not companies:
            return []
        return [
            CompanyListItem(
                # 兼容 dict 和对象两种数据格式
                # hasattr(c, 'id') 检查 c 是否有 id 属性（对象格式）
                # 如果是 dict 格式，用 c.get("id") 取值
                id=c.get("id") or c.id if hasattr(c, 'id') else c.get("id", 0),
                name=c.get("name") or c.name if hasattr(c, 'name') else c.get("name", ""),
                status="active",
                agent_count=db.count_agents_by_company(c.get("id") or c.id if hasattr(c, 'id') else 1) or 0,
                user_count=db.count_users_by_company(c.get("id") or c.id if hasattr(c, 'id') else 1) or 1,
                created_at=c.get("created_at") or getattr(c, 'created_at', "2025-01-01"),
                subscription_plan="professional",
            )
            for c in companies
        ]
    except Exception:
        return []


def _get_real_users(company_id: int = None) -> list[UserListItem]:
    try:
        from app.database import db
        users = db.get_all_users()
        if not users:
            return []
        result = []
        for u in users:
            uid = u.get("id") or u.id if hasattr(u, 'id') else 0
            cid = u.get("company_id") or u.company_id if hasattr(u, 'company_id') else 0
            if company_id and cid != company_id:
                continue
            result.append(UserListItem(
                id=uid,
                username=u.get("username") or u.username if hasattr(u, 'username') else "",
                email=u.get("email") or getattr(u, 'email', ""),
                company_id=cid,
                company_name="",
                is_active=not (u.get("disabled") or getattr(u, 'disabled', False)),
                is_admin=u.get("is_admin", False) or getattr(u, 'is_admin', False),
                created_at=u.get("created_at") or getattr(u, 'created_at', "2025-01-01"),
            ))
        return result
    except Exception:
        return []


# API 接口：获取提示词版本列表
# GET /prompts/versions
# @router.get 表示这是一个 GET 请求
# response_model 指定了返回的数据格式
@router.get("/prompts/versions", response_model=PromptVersionResponse)
async def admin_get_prompt_versions(
    current_user=Depends(get_current_active_user),  # 自动验证用户是否已登录
):
    # 检查用户是否是管理员，不是则返回 403 错误
    # 403 的意思是"禁止访问"（Forbidden）
    if not current_user.is_admin:
        raise HTTPException(403, "Admin access required")
    try:
        # 从提示词加载器获取版本信息
        from app.core.prompt_loader import prompt_registry
        return prompt_registry.get_version_summary()
    except Exception as e:
        # 如果失败了，返回 500 服务器错误
        raise HTTPException(500, f"Failed to fetch prompt versions: {str(e)}")


# API 接口：获取公司列表
# GET /companies
# 管理员查看所有注册的公司
@router.get("/companies", response_model=CompanyListResponse)
async def admin_list_companies(
    current_user=Depends(get_current_active_user),  # 自动验证用户是否已登录
):
    # 检查用户是否是管理员
    if not current_user.is_admin:
        raise HTTPException(403, "Admin access required")
    # 先尝试从数据库获取真实数据
    companies = _get_real_companies()
    # 如果数据库没有数据，开发环境可以使用模拟数据；生产环境必须避免假后台数据。
    if not companies and _allow_mock_admin_fallback():
        companies = _mock_companies()
    return CompanyListResponse(companies=companies, total=len(companies))


# API 接口：获取用户列表
# GET /users?company_id=1（可选：只查看某个公司的用户）
@router.get("/users", response_model=UserListResponse)
async def admin_list_users(
    company_id: int = Query(None),  # Query(None) 表示这是个可选的 URL 参数
    current_user=Depends(get_current_active_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "Admin access required")
    # 先尝试从数据库获取真实数据
    users = _get_real_users(company_id)
    # 如果数据库没有数据，开发环境可以使用模拟数据；生产环境必须避免假后台用户。
    if not users and _allow_mock_admin_fallback():
        users = _mock_users()
    # 如果指定了公司 ID，只返回该公司的用户
    if company_id:
        users = [u for u in users if u.company_id == company_id]
    return UserListResponse(users=users, total=len(users))


# API 接口：获取所有公司的订阅情况
# GET /subscriptions
# 管理员可以查看每个公司买了什么套餐、用了多少 Agent
@router.get("/subscriptions", response_model=SubscriptionListResponse)
async def admin_list_subscriptions(
    current_user=Depends(get_current_active_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "Admin access required")
    # 先尝试从数据库获取公司数据
    companies = _get_real_companies()
    if not companies and _allow_mock_admin_fallback():
        # 数据库无数据时使用模拟数据
        subs = _mock_subscriptions()
    elif not companies:
        subs = []
    else:
        # 有真实公司数据时，为每个公司生成订阅信息
        # 这里目前是写死的专业版，未来会从数据库读取真实的订阅信息
        subs = [
            CompanySubscription(
                company_id=c.id, company_name=c.name,
                plan_id="professional", plan_name="专业版",
                status="active",
                current_period_start="2026-05-01",
                current_period_end="2026-06-01",
                agents_used=c.agent_count, agents_limit=8,
            )
            for c in companies
        ]
    return SubscriptionListResponse(
        subscriptions=subs,
        total=len(subs),
        available_plans=AVAILABLE_PLANS,  # 同时返回所有可选的计划，方便前端展示
    )


# API 接口：获取用量统计
# GET /usage?days=30（可选：统计最近多少天，默认30天，至少1天，最多90天）
# 管理员可以查看各公司各 Agent 的 Token 消耗和费用
@router.get("/usage", response_model=UsageListResponse)
async def admin_get_usage(
    days: int = Query(30, ge=1, le=90),  # Query(30) 默认30天，ge=1至少1天，le=90最多90天
    current_user=Depends(get_current_active_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "Admin access required")

    from app.database import db
    from app.tracking.cost_tracker import CostTracker

    def _field(item, name: str, default=None):
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    try:
        companies = db.get_all_companies()
    except Exception as exc:
        logger.warning("admin_usage_companies_unavailable", error=str(exc))
        companies = []

    if not companies:
        return UsageListResponse(usages=[], total_tokens_all=0, total_cost_all=0.0)

    company_map = {_field(company, "id"): company for company in companies if _field(company, "id") is not None}
    all_agents = []
    for company_id in company_map:
        try:
            for agent in db.get_agents_by_company(company_id):
                agent_id = _field(agent, "id")
                if agent_id is not None:
                    all_agents.append((company_id, agent))
        except Exception as exc:
            logger.warning("admin_usage_agents_unavailable", company_id=company_id, error=str(exc))

    if not all_agents:
        return UsageListResponse(usages=[], total_tokens_all=0, total_cost_all=0.0)

    agent_ids = [_field(agent, "id") for _, agent in all_agents]
    summary = CostTracker.get_cost_summary_by_agents(agent_ids, days)

    usages: list[UsageItem] = []
    total_tokens = 0
    total_cost = 0.0

    for company_id, agent in all_agents:
        agent_id = _field(agent, "id")
        row = summary.get(agent_id)
        if not row:
            continue
        tokens = int(row.get("total_tokens") or 0)
        cost = float(row.get("total_cost") or 0.0)
        if tokens == 0 and cost == 0:
            continue
        company = company_map.get(company_id)
        agent_name = _field(agent, "name", "")
        display_name = _field(agent, "display_name", agent_name)
        usages.append(UsageItem(
            company_id=company_id,
            company_name=_field(company, "name", ""),
            agent_key=agent_name,
            agent_display_name=display_name,
            total_tokens=tokens,
            total_cost=round(cost, 2),
            period_days=days,
        ))
        total_tokens += tokens
        total_cost += cost

    return UsageListResponse(usages=usages, total_tokens_all=total_tokens,
                               total_cost_all=round(total_cost, 2))

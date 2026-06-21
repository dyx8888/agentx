"""
Subscription Management API
Provides endpoints for subscription plans, hiring, renewal, and cancellation
"""


from fastapi import APIRouter, Depends, HTTPException  # FastAPI 核心：路由管理、依赖注入、HTTP 异常处理
from pydantic import BaseModel  # Pydantic 基类：为订阅相关的请求/响应提供自动验证

from app.auth import get_current_active_user  # 订阅操作需要认证：确保只有登录用户才能雇佣/续约/解约
from app.database import db  # 数据库访问层：所有订阅相关的 CRUD 操作都通过 db 对象完成

router = APIRouter(prefix="/subscription", tags=["subscription"])  # 使用 prefix 统一管理路由前缀

# Pydantic models for API requests/responses — 遵循"定义清楚输入输出"原则，用 Pydantic 做类型安全边界
class HireRequest(BaseModel):  # 雇佣请求：用户选择某个计划雇佣一个数字员工
    plan_id: int  # 订阅计划 ID，对应不同价格/能力等级的套餐（如 basic/pro/enterprise）
    agent_name: str  # 雇佣的 Agent 职位名称（如 "客服专员"），同一公司不能重复雇佣同名职位

class RenewRequest(BaseModel):  # 续约请求
    subscription_id: int  # 要续约的订阅记录 ID
    months: int  # 续约月数，用于延长 end_date

class CancelRequest(BaseModel):  # 解约请求
    subscription_id: int  # 要取消的订阅记录 ID

class SubscriptionPlanResponse(BaseModel):  # 订阅计划展示模型
    id: int
    name: str  # 计划名称（如 "初级客服套餐"）
    description: str | None  # 计划描述，可为空
    price_per_month: float  # 月单价，用于前端展示和计费
    capabilities: str | None  # 该计划包含的能力说明（如 "自动回复+智能分流"），JSON 字符串格式
    is_active: bool  # 是否激活：关闭的计划不可订阅，保留历史数据

class HireResponse(BaseModel):  # 雇佣响应模型
    subscription_id: int  # 创建后返回的订阅记录 ID
    company_id: int  # 所属公司 ID
    plan_id: int  # 所选计划 ID
    agent_name: str  # 职位名称
    status: str  # 订阅状态：active / cancelled / expired
    start_date: str  # 订阅开始日期
    end_date: str | None  # 订阅结束日期：None 表示无限期（如试用期暂未设置）

class ErrorResponse(BaseModel):  # 统一错误响应格式
    detail: str  # 错误详情字符串

@router.get("/plans", response_model=list[SubscriptionPlanResponse])  # 公开端点：无需认证，允许未登录用户浏览订阅计划
async def get_subscription_plans():
    """
    获取所有可用订阅计划（职位列表）
    无需认证（公开市场）
    """
    try:
        # 从数据库获取所有激活的订阅计划
        plans = db.get_subscription_plans()  # 底层会过滤 is_active=True 的计划

        # 转换为响应格式 — 逐个字段映射，避免直接透传数据库字段造成前端暴露
        plan_responses = []
        for plan in plans:
            plan_responses.append(SubscriptionPlanResponse(
                id=plan['id'],
                name=plan['name'],
                description=plan.get('description'),  # 使用 .get() 安全获取可选字段，防止 KeyError
                price_per_month=plan['price_per_month'],
                capabilities=plan.get('capabilities'),
                is_active=plan['is_active']
            ))

        return plan_responses  # FastAPI 自动将 Pydantic 列表序列化为 JSON 数组

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching subscription plans: {str(e)}")

@router.post("/hire", response_model=HireResponse)  # 雇佣端点：需要认证，创建公司订阅记录
async def hire_employee(
    request: HireRequest,
    current_user=Depends(get_current_active_user)
):
    """
    公司雇佣一个数字员工（创建订阅）
    需要登录，且用户必须有所属公司
    """
    try:
        # 校验当前用户是否有公司 — 双重验证：user 对象存在 + company_id 不为空
        if not current_user or not current_user.company_id:
            raise HTTPException(status_code=401, detail="User not authenticated or no company assigned")

        # 检查该公司是否已订阅同名的 active 雇工 — 防止重复雇佣同一职位
        existing_subscription = db.get_company_subscription_by_agent(current_user.company_id, request.agent_name)
        if existing_subscription and existing_subscription['status'] == 'active':  # 只有 active 状态才算冲突
            raise HTTPException(status_code=400, detail=f"The position '{request.agent_name}' is already hired")

        # 验证订阅计划是否存在 — 防止用不存在的 plan_id 创建订阅
        plan = db.get_subscription_plan(request.plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Subscription plan not found")

        # 在 CompanySubscription 表创建记录
        subscription_id = db.create_company_subscription(
            company_id=current_user.company_id,
            plan_id=request.plan_id,
            agent_name=request.agent_name,
            status="active",  # 新创建的订阅直接激活
            # 试用期30天
            end_date=None  # 由数据库默认设置（如当前时间+30天）
        )

        # 更新 Company 表的 subscription_status 为 "subscribed" — 同步公司级别的订阅状态
        db.update_company_subscription_status(current_user.company_id, "subscribed")

        return HireResponse(
            subscription_id=subscription_id,
            company_id=current_user.company_id,
            plan_id=request.plan_id,
            agent_name=request.agent_name,
            status="active",
            start_date="now",  # 实际时间由数据库触发器设置
            end_date=None  # 试用期未设置结束日期
        )

    except HTTPException:
        raise  # 重新抛出 HTTPException：保持原有的状态码和错误信息
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error hiring employee: {str(e)}")

@router.post("/renew")  # 续约端点：延长订阅有效期并开启自动续费
async def renew_subscription(
    request: RenewRequest,
    current_user=Depends(get_current_active_user)
):
    """
    续约员工
    需要登录且有所属公司
    """
    try:
        # 校验当前用户 — 没有公司无法续约
        if not current_user or not current_user.company_id:
            raise HTTPException(status_code=401, detail="User not authenticated or no company assigned")

        # 获取订阅信息
        subscription = db.get_company_subscription(request.subscription_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # 校验订阅是否属于当前用户的公司 — 租户隔离：不能续约其他公司的订阅
        if subscription['company_id'] != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # 更新订阅的 end_date 往后延长 months 个月 — 在数据库层面做日期计算
        db.extend_subscription_end_date(request.subscription_id, request.months)

        # 设置 auto_renew=true — 续约后自动开启自动续费，减少用户手动操作
        db.update_subscription_auto_renew(request.subscription_id, True)

        return {"message": f"Subscription renewed for {request.months} months"}

    except HTTPException:
        raise  # 保持 HTTPException 原有的状态码透传
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error renewing subscription: {str(e)}")

@router.post("/cancel")  # 解约端点：取消订阅并同步公司状态
async def cancel_subscription(
    request: CancelRequest,
    current_user=Depends(get_current_active_user)
):
    """
    解约员工
    需要登录且有所属公司
    """
    try:
        # 校验当前用户 — 没有公司无法解约
        if not current_user or not current_user.company_id:
            raise HTTPException(status_code=401, detail="User not authenticated or no company assigned")

        # 获取订阅信息
        subscription = db.get_company_subscription(request.subscription_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # 校验订阅是否属于当前用户的公司 — 租户隔离
        if subscription['company_id'] != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # 将对应订阅的 status 改为 "cancelled" — 软删除，保留历史记录
        db.update_subscription_status(request.subscription_id, "cancelled")

        # 检查该公司是否还有其他 active 订阅 — 如果全部取消则公司状态变为 inactive
        active_subscriptions = db.get_company_active_subscriptions(current_user.company_id)
        if not active_subscriptions:
            # 如果没有其他 active 订阅，则改为 "inactive" — 防止公司状态与订阅状态不一致
            db.update_company_subscription_status(current_user.company_id, "inactive")

        return {"message": "Subscription cancelled successfully"}

    except HTTPException:
        raise  # 保持 HTTPException 透传
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling subscription: {str(e)}")

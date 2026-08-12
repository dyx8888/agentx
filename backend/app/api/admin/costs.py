# 成本管理 API 接口文件
# 这个文件提供了查看 API 调用费用的功能
# 通俗地说：这是"看账单"的功能，管理员可以查看花了多少钱
"""
Cost management API endpoints for admin users
"""

# datetime 模块：处理日期和时间，比如获取今天的日期
from datetime import datetime

# FastAPI 核心工具
from fastapi import APIRouter, Depends, HTTPException, Query
# Pydantic 数据模型基类，定义数据的格式和规范
from pydantic import BaseModel

# 用户认证：获取当前登录的用户信息
from app.auth import get_current_active_user
from app.core.logging import get_logger
# 成本追踪器：专门用来计算和统计 API 调用费用的工具
from app.tracking.cost_tracker import CostTracker

# 创建路由对象
# prefix="/admin/costs" 表示所有接口都以 /admin/costs 开头
# 比如 /admin/costs/summary、/admin/costs/today
# tags=["costs"] 表示在 API 文档中归入 "costs" 分组
router = APIRouter(tags=["costs"])
logger = get_logger(__name__)


# 成本汇总的数据模型
# 描述了成本统计报告的数据格式
class CostSummaryResponse(BaseModel):
    total_cost: float           # 总费用（美元）
    total_requests: int         # 总请求次数
    total_input_tokens: int     # 输入 Token 总数（用户发给 AI 的"字数"）
    total_output_tokens: int    # 输出 Token 总数（AI 回复的"字数"）
    period_days: int            # 统计周期（多少天）
    cost_by_model: list[dict]   # 按 AI 模型分组的费用（比如 deepseek-chat 花了多少）
    cost_by_agent: list[dict]   # 按 Agent 分组的费用（比如 品牌商务 Agent 花了多少）


# 每日成本的数据模型
# 描述某一天的成本详情
class DailyCostResponse(BaseModel):
    date: str               # 日期（如 "2026-06-01"）
    daily_cost: float        # 当天的费用（美元）
    daily_requests: int      # 当天的请求次数
    daily_input_tokens: int  # 当天的输入 Token 数
    daily_output_tokens: int # 当天的输出 Token 数


# 成本趋势的响应格式
# 返回连续多天的成本数据，方便前端画折线图
class CostTrendResponse(BaseModel):
    trend: list[DailyCostResponse]  # 每日成本列表
    period_days: int                 # 统计周期（多少天）


# API 接口：获取成本汇总报告
# GET /admin/costs/summary?days=30
# 管理员查看最近 N 天的总费用、总请求数等
@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    days: int = Query(30, description="Number of days to analyze"),  # 默认统计最近30天
    current_user = Depends(get_current_active_user)  # 自动验证登录
):
    """
    Get cost summary for the specified period
    """
    try:
        # 检查用户是否是管理员，不是则返回 403 错误
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # 获取指定天数内的总费用和 Token 使用量
        total_cost_data = CostTracker.get_total_cost(days)

        # 按 AI 模型分类统计费用（比如 deepseek-chat 花了多少，gpt-4 花了多少）
        cost_by_model = CostTracker.get_cost_by_model(days)

        # 按 Agent 分类统计费用（预留，还没实现）
        cost_by_agent = []  # 未来可以扩展为按公司查看

        return CostSummaryResponse(
            total_cost=total_cost_data["total_cost"],          # 总费用
            total_requests=total_cost_data["total_requests"],  # 总请求次数
            total_input_tokens=total_cost_data["total_input_tokens"],    # 输入 Token 总数
            total_output_tokens=total_cost_data["total_output_tokens"],  # 输出 Token 总数
            period_days=days,         # 统计周期
            cost_by_model=cost_by_model,  # 按模型统计
            cost_by_agent=cost_by_agent    # 按 Agent 统计（暂空）
        )

    except HTTPException:
        raise  # 如果是已知的 HTTP 错误，直接抛出
    except Exception:
        logger.exception(get_cost_summary_failed)
        raise HTTPException(status_code=500, detail=内部服务器错误)


# API 接口：获取成本趋势（每日数据）
# GET /admin/costs/history?days=30
# 返回每天的费用数据，前端可以用这些数据画折线图
# 比如：6月1日花了 $10，6月2日花了 $12，可以看出费用变化趋势
@router.get("/history", response_model=CostTrendResponse)
async def get_cost_history(
    days: int = Query(30, description="Number of days to analyze"),
    current_user = Depends(get_current_active_user)
):
    """
    Get daily cost trend for charting
    """
    try:
        # 检查管理员权限
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # 获取每天的详细成本数据
        daily_trend = CostTracker.get_daily_cost_trend(days)

        return CostTrendResponse(
            trend=[
                DailyCostResponse(
                    date=item["date"],                    # 日期
                    daily_cost=item["daily_cost"],        # 当天费用
                    daily_requests=item["daily_requests"],# 当天请求数
                    daily_input_tokens=item["daily_input_tokens"],    # 当天输入 Token
                    daily_output_tokens=item["daily_output_tokens"]  # 当天输出 Token
                )
                for item in daily_trend
            ],
            period_days=days
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("get_cost_history_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# API 接口：按 AI 模型查看成本
# GET /admin/costs/models/30（查看最近30天按模型统计的费用）
# 返回值示例：[{"model": "deepseek-chat", "cost": 12.5}, {"model": "gpt-4", "cost": 8.3}]
@router.get("/models/{days:int}", response_model=list[dict])
async def get_cost_by_model_endpoint(
    days: int,  # 天数，从 URL 路径中获取（比如 /models/30 中的 30）
    current_user = Depends(get_current_active_user)
):
    """
    Get cost breakdown by model for specified period
    """
    try:
        # 检查管理员权限
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # 获取按模型分类的费用数据
        cost_by_model = CostTracker.get_cost_by_model(days)

        return cost_by_model

    except HTTPException:
        raise
    except Exception:
        logger.exception("get_cost_by_model_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# API 接口：按 Agent 查看成本
# GET /admin/costs/agents/1/30（查看ID为1的Agent在最近30天的费用）
# 管理员可以查看某个 Agent 具体花了多少钱
@router.get("/agents/{agent_id:int}/{days:int}", response_model=list[dict])
async def get_cost_by_agent_endpoint(
    agent_id: int,  # Agent 的 ID，从 URL 路径获取
    days: int,      # 统计天数，从 URL 路径获取
    current_user = Depends(get_current_active_user)
):
    """
    Get cost breakdown by agent for specified period
    """
    try:
        # 检查管理员权限
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # 获取该 Agent 在指定天数内的费用
        cost_by_agent = CostTracker.get_cost_by_agent(agent_id, days)

        return cost_by_agent

    except HTTPException:
        raise
    except Exception:
        logger.exception("get_cost_by_agent_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# API 接口：获取今日成本
# GET /admin/costs/today
# 管理员查看今天花了多少钱
@router.get("/today")
async def get_today_cost(
    current_user = Depends(get_current_active_user)
):
    """
    Get today's cost summary
    """
    try:
        # 检查管理员权限
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # 获取今天的成本（最近1天）
        today_cost = CostTracker.get_total_cost(1)

        return {
            "date": datetime.now().strftime('%Y-%m-%d'),  # 今天的日期，格式如 "2026-06-17"
            "total_cost": today_cost["total_cost"],          # 今天的总费用
            "total_requests": today_cost["total_requests"],  # 今天的请求总数
            "total_input_tokens": today_cost["total_input_tokens"],    # 今天的输入 Token 数
            "total_output_tokens": today_cost["total_output_tokens"]  # 今天的输出 Token 数
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("get_today_cost_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")

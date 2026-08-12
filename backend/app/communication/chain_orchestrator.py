"""
协作链编排器 - 将任务队列、协作引擎、审核流程串联为完整的链式执行
处理: 链启动→任务分发→进度追踪→上下文回写→WebSocket推送→审核升级
"""

import asyncio  # 链式执行本质上是异步的，每个步骤需要等待 Agent 返回结果

from app.communication.collaboration import CollaborationEngine  # 协作引擎负责链的定义和任务分发
from app.communication.review_workflow import (  # 审核引擎用于链中需要人工确认的节点
    ReviewLevel,
    ReviewWorkflowEngine,
)
from app.core.logging import get_logger  # 统一日志，便于追踪链执行全链路

logger = get_logger(__name__)


class ChainOrchestrator:
    _instance = None  # 单例模式：整个应用只需一个编排器管理所有活跃链

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记位，防止 __init__ 被多次调用时重复初始化
        return cls._instance

    def __init__(self):
        if not self._initialized:  # 单例的 __init__ 防护：确保初始化逻辑只执行一次
            self._initialized = True
            self.collaboration = CollaborationEngine()  # 复用协作引擎单例，避免重复创建
            self.review = ReviewWorkflowEngine()  # 复用审核引擎单例
            self._active_chains: dict[
                str, dict
            ] = {}  # 内存中追踪活跃链，key 为 chain_key，用于进度查询
            logger.info("chain_orchestrator_initialized")

    async def launch_chain(
        self,
        chain_name: str,
        company_id: int,
        initiator_agent: str = "system",
        extra_context: dict = None,
    ) -> dict:
        chain = self.collaboration.get_chain(chain_name)  # 从协作引擎获取预定义的链配置
        if not chain:
            return {"error": f"协作链 '{chain_name}' 不存在"}  # 链不存在时直接返回错误，不抛异常

        chain_key = f"{company_id}_{chain_name}_{asyncio.get_event_loop().time()}"  # 用时间戳确保每次启动的链 key 唯一，支持同一链多次并发执行
        self._active_chains[chain_key] = {  # 在内存中注册活跃链，后续通过 WebSocket 推送进度
            "chain_name": chain_name,
            "company_id": company_id,
            "initiator": initiator_agent,
            "steps": chain["steps"],
            "total_steps": len(chain["steps"]),
            "completed_steps": 0,
            "current_step_index": 0,
            "task_ids": [],
            "status": "running",
        }

        task_ids = await self.collaboration.trigger_chain(  # 委托协作引擎创建实际的任务记录
            chain_name=chain_name,
            company_id=company_id,
            initiator_agent=initiator_agent,
            extra_context=extra_context,
        )

        self._active_chains[chain_key]["task_ids"] = (
            task_ids  # 回填任务 ID，供后续 on_task_completed 匹配
        )

        self.collaboration.track_chain_progress(chain_name, company_id)  # 初始化进度追踪器

        from app.ws import (
            ws_manager,  # 延迟导入避免循环依赖：ws_manager 可能依赖 communication 模块
        )

        await ws_manager.broadcast_to_company(
            company_id,
            {  # 实时推送链启动事件，前端可据此展示进度条
                "type": "chain_started",
                "chain": chain_name,
                "chainName": chain["name"],
                "totalSteps": len(chain["steps"]),
                "taskIds": task_ids,
                "initiator": initiator_agent,
            },
        )

        logger.info(
            "chain_launched", chain=chain_name, company=company_id, task_count=len(task_ids)
        )

        return {
            "chain_key": chain_key,  # 返回 chain_key 供调用方后续查询进度
            "chain_name": chain_name,
            "task_ids": task_ids,
            "total_steps": len(chain["steps"]),
        }

    async def on_task_completed(
        self,
        agent_key: str,
        company_id: int,
        task_id: int,
        result_summary: str,
        task_output: dict = None,
    ):
        await self.collaboration.on_agent_task_completed(  # 先完成上下文回写和 WebSocket 通知
            agent_key=agent_key,
            company_id=company_id,
            task_id=task_id,
            result_summary=result_summary,
            agent_output=task_output,
        )

        for chain_key, chain_data in list(
            self._active_chains.items()
        ):  # list() 复制避免迭代中删除导致 RuntimeError
            if chain_data["company_id"] == company_id and task_id in chain_data.get("task_ids", []):
                await self.collaboration.mark_chain_step_completed(  # 标记该步骤完成，推进进度条
                    chain_data["chain_name"], company_id, agent_key
                )
                chain_data["completed_steps"] += 1

                if chain_data["completed_steps"] >= chain_data["total_steps"]:  # 所有步骤完成
                    chain_data["status"] = "completed"
                    del self._active_chains[chain_key]  # 从活跃链中移除，释放内存
                break  # 每个 task_id 只属于一个链，找到后立即退出

    async def get_chain_status(self, company_id: int) -> list[dict]:
        return [  # 列表推导式简洁返回当前公司所有活跃链状态
            {
                "chain_key": k,
                "chain_name": d["chain_name"],
                "status": d["status"],
                "total_steps": d["total_steps"],
                "completed_steps": d["completed_steps"],
                "task_ids": d["task_ids"],
            }
            for k, d in self._active_chains.items()
            if d["company_id"] == company_id  # 仅返回指定公司的链，实现数据隔离
        ]

    async def submit_for_review(
        self, task_id: int, agent_key: str, company_id: int, result: dict, task_type: str = None
    ) -> dict:
        review_level = self.review.determine_review_level(
            agent_key, task_type
        )  # 根据 agent 和任务类型自动判定审核级别

        if review_level == ReviewLevel.AUTO:  # 自动审核级别：直接通过，无需人工介入
            review_id = await self.review.submit_for_review(
                task_id, agent_key, company_id, result, review_level, task_type
            )
            return {"review_id": review_id, "status": "auto_approved", "level": "auto"}

        review_id = await self.review.submit_for_review(  # 推荐或强制审核：创建审核记录
            task_id, agent_key, company_id, result, review_level, task_type
        )

        from app.ws import ws_manager  # 延迟导入避免循环依赖

        await ws_manager.broadcast_review_notification(  # 推送审核通知到前端，提醒审核人员
            company_id, review_id, agent_key, review_level.value
        )

        return {
            "review_id": review_id,
            "status": "pending_review",  # 返回 pending 状态，前端据此展示审核等待图标
            "level": review_level.value,
        }

    async def process_review_decision(
        self, review_id: int, company_id: int, decision: str, reviewer_id: int, comment: str = None
    ) -> dict:
        if decision == "approve":
            success = await self.review.approve(review_id, reviewer_id, comment)
            return {"review_id": review_id, "status": "approved", "success": success}
        elif decision == "reject":
            success = await self.review.reject(
                review_id, reviewer_id, comment or "驳回"
            )  # 默认驳回理由
            return {"review_id": review_id, "status": "rejected", "success": success}
        elif decision == "modify":
            success = await self.review.request_modification(  # 修改请求：任务退回 Agent 重新执行
                review_id, reviewer_id, comment or "需要修改"
            )
            return {"review_id": review_id, "status": "modification_requested", "success": success}
        else:
            return {"error": f"无效的审核决策: {decision}"}  # 前端传入非法决策值的防御

    async def get_pending_reviews(self, company_id: int, level: str = None) -> list[dict]:
        return self.review.get_pending_reviews(company_id, level)  # 直接委托给审核引擎


chain_orchestrator = ChainOrchestrator()  # 模块级单例，全局复用，避免重复创建

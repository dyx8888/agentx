"""
三级审核流程引擎
实现：审核级别分配、审核状态机、审批/修改/拒绝、超时升级
"""

import asyncio  # 超时检查使用 asyncio.sleep 和 asyncio.create_task 调度
from contextlib import suppress
from enum import StrEnum  # 字符串枚举，状态值可直接序列化

from app.core.logging import get_logger

logger = get_logger(__name__)


class ReviewStatus(StrEnum):
    PENDING = "pending"  # 等待审核：审核请求已提交，等待人工决策
    APPROVED = "approved"  # 已通过：审核者批准
    REJECTED = "rejected"  # 已驳回：审核者拒绝
    MODIFIED = "modified"  # 需修改：审核者要求修改后重新提交
    TIMEOUT_ESCALATED = "timeout_escalated"  # 超时升级：审核超时自动升级处理


class ReviewLevel(StrEnum):
    MANDATORY = "mandatory"  # 强制审核：必须人工确认后才能执行
    RECOMMENDED = "recommended"  # 推荐审核：自动执行但可被撤回
    AUTO = "auto"  # 自动通过：无需人工审核


class ReviewWorkflowEngine:
    """三级审核流程引擎"""

    _instance = None  # 单例模式

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记位，防止重复初始化
        return cls._instance

    def __init__(self):
        if not self._initialized:  # 单例防护
            self._initialized = True
            logger.info("review_workflow_engine_initialized")

    def determine_review_level(self, agent_key: str, task_type: str = None) -> ReviewLevel:
        from app.agents import get_agent_definition  # 延迟导入
        from app.communication.collaboration import REVIEW_LEVEL_RULES  # 复用协作引擎的审核规则

        mandatory_rules = REVIEW_LEVEL_RULES.get("mandatory", {})
        for entry in mandatory_rules.get("applies_to", []):  # 检查强制审核白名单
            parts = entry.split(" ")
            if (
                len(parts) >= 2
                and parts[0] == agent_key
                and (task_type and parts[1] == task_type or not task_type)
            ):  # 精确或模糊匹配
                return ReviewLevel.MANDATORY

        agent_info = get_agent_definition(agent_key)
        if agent_info:
            level = agent_info.get("review_level", "recommended")  # Agent 定义中可配置默认审核级别
            return ReviewLevel(level)  # 字符串转枚举

        return ReviewLevel.RECOMMENDED  # 兜底为推荐审核

    async def submit_for_review(
        self,
        task_id: int,
        agent_key: str,
        company_id: int,
        result: dict,
        review_level: ReviewLevel = None,
        task_type: str = None,
    ) -> int:
        from app.database import db  # 延迟导入

        if review_level is None:
            review_level = self.determine_review_level(agent_key, task_type)  # 未指定时自动判定

        try:
            review_id = db.create_review(  # 数据库持久化审核记录
                task_id=task_id,
                company_id=company_id,
                agent_key=agent_key,
                result_json=str(result),  # 序列化结果
                review_level=review_level.value,
                status=ReviewStatus.PENDING.value,
            )
            logger.info("review_submitted", review_id=review_id, level=review_level.value)

            if review_level == ReviewLevel.AUTO:
                await self.auto_approve(review_id, company_id)  # 自动级别直接通过
            elif review_level == ReviewLevel.RECOMMENDED:
                await self._notify_review_available(
                    review_id, company_id, agent_key, review_level
                )  # 通知但不阻塞
            elif review_level == ReviewLevel.MANDATORY:
                await self._notify_review_required(review_id, company_id, agent_key)  # 强制通知
                self._schedule_timeout_check(
                    review_id, company_id, agent_key, 240
                )  # 4 小时超时检查

            return review_id
        except Exception as e:
            logger.error("review_submit_failed", task_id=task_id, error=str(e))
            raise  # 审核提交失败应抛出异常，让上层感知

    async def approve(self, review_id: int, reviewer_id: int, comment: str = None) -> bool:
        from app.database import db

        try:
            db.update_review_status(
                review_id, ReviewStatus.APPROVED.value, reviewer_id=reviewer_id, comment=comment
            )  # 更新数据库状态
            logger.info("review_approved", review_id=review_id, reviewer=reviewer_id)
            await self._notify_review_result(review_id, "approved")  # 通知审核结果
            return True
        except Exception as e:
            logger.error("review_approve_failed", review_id=review_id, error=str(e))
            return False

    async def reject(self, review_id: int, reviewer_id: int, reason: str) -> bool:
        from app.database import db

        try:
            db.update_review_status(
                review_id, ReviewStatus.REJECTED.value, reviewer_id=reviewer_id, comment=reason
            )
            logger.info(
                "review_rejected", review_id=review_id, reason=reason[:100]
            )  # 截断日志中的驳回理由
            await self._notify_review_result(review_id, "rejected")
            return True
        except Exception as e:
            logger.error("review_reject_failed", review_id=review_id, error=str(e))
            return False

    async def request_modification(
        self, review_id: int, reviewer_id: int, modification_note: str
    ) -> bool:
        from app.database import db

        try:
            db.update_review_status(
                review_id,
                ReviewStatus.MODIFIED.value,
                reviewer_id=reviewer_id,
                comment=modification_note,
            )
            logger.info("review_modification_requested", review_id=review_id)
            await self._notify_review_result(review_id, "modification_requested")
            return True
        except Exception as e:
            logger.error("review_modify_failed", review_id=review_id, error=str(e))
            return False

    async def auto_approve(self, review_id: int, company_id: int) -> bool:
        from app.database import db

        try:
            db.update_review_status(
                review_id, ReviewStatus.APPROVED.value, comment="自动通过"
            )  # 自动通过标记
            logger.info("review_auto_approved", review_id=review_id)
            return True
        except Exception as e:
            logger.error("review_auto_approve_failed", review_id=review_id, error=str(e))
            return False

    def get_pending_reviews(self, company_id: int, level: str = None) -> list[dict]:
        from app.database import db

        try:
            return db.get_pending_reviews(company_id, level)  # 委托数据库查询
        except Exception as e:
            logger.error("get_pending_reviews_failed", error=str(e))
            return []  # 查询失败返回空列表，不影响前端渲染

    async def escalate_timeout(self, review_id: int, company_id: int, agent_key: str):
        from app.database import db

        try:
            db.update_review_status(
                review_id, ReviewStatus.TIMEOUT_ESCALATED.value, comment="审核超时自动升级"
            )  # 标记为超时升级
            from app.communication.collaboration import collaboration_engine  # 延迟导入

            await collaboration_engine.create_alert(  # 创建告警通知管理员
                company_id=company_id,
                alert_type="review_timeout",
                title=f"审核超时升级 - {agent_key}",
                message=f"审核ID {review_id} 已超过4小时未处理，已自动升级",
                severity="warning",
                related_agents=[agent_key],
            )
            logger.info("review_timeout_escalated", review_id=review_id)
        except Exception as e:
            logger.error("review_escalate_failed", review_id=review_id, error=str(e))

    def _schedule_timeout_check(
        self, review_id: int, company_id: int, agent_key: str, timeout_minutes: int
    ):
        async def _check():
            await asyncio.sleep(timeout_minutes * 60)  # 等待超时时长（分钟转秒）
            from app.database import db

            try:
                status = db.get_review_status(review_id)
                if status == ReviewStatus.PENDING.value:  # 仅在仍为 pending 时才升级
                    await self.escalate_timeout(review_id, company_id, agent_key)
            except Exception as exc:  # 超时检查失败不影响主流程，但要记录诊断线索
                logger.warning(
                    "review_timeout_check_failed",
                    review_id=review_id,
                    company_id=company_id,
                    error=str(exc),
                )

        with suppress(RuntimeError):
            asyncio.create_task(_check())  # 创建后台任务，不阻塞当前请求

    async def _notify_review_available(
        self, review_id: int, company_id: int, agent_key: str, level: ReviewLevel
    ):
        try:
            from app.ws import ws_manager  # 延迟导入

            await ws_manager.broadcast_to_company(
                company_id,
                {
                    "type": "review_available",
                    "reviewId": review_id,
                    "agent": agent_key,
                    "level": level.value,
                },
            )
        except Exception as exc:  # WebSocket 推送失败不影响审核流程
            logger.warning(
                "review_available_notify_failed",
                review_id=review_id,
                company_id=company_id,
                agent_key=agent_key,
                error=str(exc),
            )

    async def _notify_review_required(self, review_id: int, company_id: int, agent_key: str):
        try:
            from app.ws import ws_manager

            await ws_manager.broadcast_to_company(
                company_id,
                {
                    "type": "review_required",
                    "reviewId": review_id,
                    "agent": agent_key,
                    "level": ReviewLevel.MANDATORY.value,
                    "message": f"{agent_key} 的任务需要强制审核",  # 明确告知需要人工审核
                },
            )
        except Exception as exc:  # WebSocket 推送失败不影响审核流程
            logger.warning(
                "review_required_notify_failed",
                review_id=review_id,
                company_id=company_id,
                agent_key=agent_key,
                error=str(exc),
            )

    async def _notify_review_result(self, review_id: int, result: str, company_id: int = None):
        try:
            from app.ws import ws_manager

            target_company = company_id or 0  # 未指定公司 ID 时使用 0 作为默认值
            await ws_manager.broadcast_to_company(
                target_company,
                {
                    "type": "review_result",
                    "reviewId": review_id,
                    "result": result,
                },
            )
        except Exception as exc:  # WebSocket 推送失败不影响审核流程
            logger.warning(
                "review_result_notify_failed",
                review_id=review_id,
                company_id=target_company,
                result=result,
                error=str(exc),
            )


review_engine = ReviewWorkflowEngine()  # 模块级单例，全局复用

# 模块文档：Scheduler 是进化系统的"定时器"——按固定周期触发睡眠巩固、Prompt 优化等自动化流程
# 它是单例模式，因为定时任务只需要一个调度器实例，多个实例会导致重复执行
"""
Evolution Scheduler v2 - 定时触发的自动进化
整合：睡眠巩固 + 反馈驱动进化 + Prompt优化
"""

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__)


class EvolutionScheduler:
    """自动进化定时调度器"""

    # 使用单例模式的原因与 FeedbackDrivenEvolution 相同：全局唯一调度器防止重复任务
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str = None):
        # 单例保护：避免重复初始化覆盖已有任务
        if self._initialized:
            return
        self._initialized = True
        self._running = False  # 运行状态标志，用于控制循环的启停
        # 用 dict 管理任务引用，方便按名称查找和取消特定任务
        self._tasks: dict[str, asyncio.Task] = {}
        logger.info("evolution_scheduler_v2_initialized")

    async def start(self, company_id: int = None):
        """启动调度器，创建每日睡眠循环任务"""
        if self._running:
            return  # 防止重复启动
        self._running = True

        # 为每个 company_id 创建独立任务，因为不同租户的数据不能混在一起做 consolidation
        task_id = f"daily_sleep_{company_id or 'all'}"
        if task_id not in self._tasks:
            # asyncio.create_task 而非 await，是为了让调度器启动后立即返回，不阻塞调用方
            self._tasks[task_id] = asyncio.create_task(self._daily_sleep_loop(company_id))

        logger.info("evolution_scheduler_started", company=company_id)

    async def stop(self):
        """停止调度器，取消所有正在运行的任务"""
        self._running = False
        for _task_name, task in self._tasks.items():
            task.cancel()  # 发送 CancelledError 让循环优雅退出
        self._tasks.clear()
        logger.info("evolution_scheduler_stopped")

    async def _daily_sleep_loop(self, company_id: int = None):
        """每日睡眠循环：每小时执行一次睡眠巩固"""
        while self._running:
            try:
                await self._run_sleep_cycle(company_id)
                # 每小时执行一次，而非每天一次，因为需要及时处理新产生的反馈数据
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break  # 任务被取消时优雅退出
            except Exception as e:
                logger.error("sleep_loop_error", error=str(e))
                # 出错后等待 5 分钟再重试，避免短时间内重复失败
                await asyncio.sleep(300)

    async def _run_sleep_cycle(self, company_id: int = None):
        """执行一次睡眠巩固周期"""
        try:
            from app.runtime.memory import memory_manager

            if company_id:
                # 指定了 company_id，只对该租户执行巩固
                result = await memory_manager.sleep_consolidation(str(company_id))
                logger.info("sleep_cycle_complete", company=company_id, result=result)
            else:
                # 未指定 company_id，对所有活跃租户执行巩固
                # 注意：不再回退到 [1]，避免对错误租户执行巩固造成数据越权
                try:
                    from app.database import db

                    company_ids = db.get_active_company_ids()
                except Exception as e:
                    logger.error("get_active_company_ids_failed", error=str(e))
                    company_ids = []

                for cid in company_ids:
                    try:
                        result = await memory_manager.sleep_consolidation(str(cid))
                        logger.info("sleep_cycle_complete", company=cid, result=result)
                    except Exception as e:
                        # 单个租户失败不影响其他租户的巩固，用 try/except 隔离
                        logger.error("sleep_cycle_company_error", company=cid, error=str(e))
        except Exception as e:
            logger.error("sleep_cycle_run_error", error=str(e))

    async def trigger_memory_consolidation(self, company_id: int) -> dict:
        """手动触发记忆巩固（供 API 调用）"""
        from app.runtime.memory import memory_manager

        return await memory_manager.sleep_consolidation(str(company_id))

    async def trigger_prompt_evolution(self, agent_key: str, company_id: int) -> dict:
        """手动触发 Prompt 进化（供 API 调用）"""
        # 延迟导入反馈进化引擎，避免循环依赖
        from app.evolution.feedback_evolution import feedback_evolution

        return await feedback_evolution.trigger_stage2_evolution(agent_key, company_id)

    def get_evolution_report(self, company_id: int) -> dict:
        """获取进化报告——汇总所有 Agent 的进化状态"""
        report = {
            "company_id": company_id,
            "last_consolidation": None,
            "total_feedbacks": 0,
            "agents": {},
        }

        try:
            from app.evolution.feedback_evolution import feedback_evolution

            # 硬编码的 Agent 列表，因为系统中 Agent 的种类是固定的，不需要动态发现
            agent_keys = [
                "brand_bd",
                "content_operation",
                "data_analysis",
                "customer_service",
                "warehouse_logistics",
                "visual_designer",
                "product_selector",
                "smart_ad_delivery",
            ]

            for ak in agent_keys:
                status = feedback_evolution.get_evolution_status(ak, company_id)
                report["agents"][ak] = status
                # 累加所有 Agent 的反馈数，得到租户级别的总反馈量
                report["total_feedbacks"] += status.get("feedback_count", 0)

        except Exception as e:
            logger.error("evolution_report_error", error=str(e))

        return report


# 模块级单例，确保全局只有一个调度器
evolution_scheduler = EvolutionScheduler()

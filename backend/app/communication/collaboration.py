"""
跨职位协作引擎 (Enhanced)
实现：协作链配置、CompanyContextBus自动回写、任务路由、三级审核路由
"""

from app.core.logging import get_logger

logger = get_logger(__name__)

# 预定义协作链：硬编码的业务流程模板，而非数据库存储，因为链步骤是业务逻辑的一部分，不应频繁变更
DEFAULT_COLLABORATION_CHAINS = {
    "new_product_launch": {
        "name": "新品上市协作链",
        "steps": [
            {
                "agent": "product_selector",
                "task": "选品确认与利润测算",
                "review": "recommended",
            },  # 第一步选品，利润测算影响后续所有决策
            {
                "agent": "brand_bd",
                "task": "达人筛选与寄样",
                "review": "recommended",
            },  # 依赖选品结果，需要寄样给达人
            {
                "agent": "visual_designer",
                "task": "主图与详情页设计",
                "review": "recommended",
            },  # 设计依赖产品确认
            {
                "agent": "content_operation",
                "task": "短视频脚本+直播脚本",
                "review": "recommended",
            },  # 内容依赖设计素材
            {
                "agent": "smart_ad_delivery",
                "task": "投放策略与预算",
                "review": "recommended",
            },  # 投放依赖内容和达人矩阵
            {
                "agent": "data_analysis",
                "task": "全链路数据监控接入",
                "review": "auto",
            },  # 最后一步监控接入，自动完成
        ],
    },
    "daily_sales": {
        "name": "日常销售协作链",
        "steps": [
            {
                "agent": "customer_service",
                "task": "售前咨询自动回复监控",
                "review": "auto",
            },  # 日常监控自动执行，无需人工审核
            {
                "agent": "warehouse_logistics",
                "task": "备货库存巡检",
                "review": "auto",
            },  # 库存巡检也是自动化的
        ],
    },
    "campaign_preparation": {
        "name": "大促筹备协作链",
        "steps": [
            {
                "agent": "data_analysis",
                "task": "历史大促数据复盘",
                "review": "auto",
            },  # 数据分析先行，为后续决策提供依据
            {
                "agent": "product_selector",
                "task": "大促选品与备货量建议",
                "review": "recommended",
            },  # 选品依赖复盘数据
            {
                "agent": "brand_bd",
                "task": "达人矩阵预约与锁价",
                "review": "recommended",
            },  # 达人预约需提前锁定
            {"agent": "content_operation", "task": "大促内容排期产出", "review": "recommended"},
            {"agent": "visual_designer", "task": "大促视觉素材批量生成", "review": "recommended"},
            {"agent": "smart_ad_delivery", "task": "大促投放策略制定", "review": "recommended"},
            {
                "agent": "warehouse_logistics",
                "task": "备货入仓确认",
                "review": "recommended",
            },  # 备货确认是最后一道物理环节
            {
                "agent": "customer_service",
                "task": "大促话术准备",
                "review": "recommended",
            },  # 话术最后准备，确保参数时效
        ],
    },
    "anomaly_response": {
        "name": "异常响应协作链",
        "steps": [
            {
                "agent": "data_analysis",
                "task": "异常检测与归因分析",
                "review": "auto",
            },  # 异常检测自动触发
            {"agent": "brand_bd", "task": "评估投放影响", "review": "auto"},  # 影响评估自动执行
            {
                "agent": "smart_ad_delivery",
                "task": "止损策略执行",
                "review": "recommended",
            },  # 止损涉及资金，推荐审核
            {
                "agent": "customer_service",
                "task": "客诉应对准备",
                "review": "mandatory",
            },  # 客诉应对必须人工确认，避免机械回复引发舆情
        ],
    },
}

# 审核级别规则：定义了三级审核体系的行为差异
REVIEW_LEVEL_RULES = {
    "mandatory": {
        "description": "强制人工审核 - 结果必须经过老板或管理员确认后才能执行",
        "auto_action": "hold",  # 强制审核的任务必须阻塞等待人工决策
        "timeout_minutes": 240,  # 4 小时超时：平衡审核及时性和人工响应时间
        "timeout_action": "escalate",  # 超时后自动升级通知，避免无限期等待
        "applies_to": [  # 白名单：哪些 agent+task_type 组合需要强制审核
            "customer_service review_management",
            "customer_service after_sales_handling",
            "smart_ad_delivery campaign_create",
        ],
    },
    "recommended": {
        "description": "推荐审核 - 自动执行但同步展示在审核列表，可随时撤回",
        "auto_action": "proceed_with_notification",  # 先执行再通知，不阻塞流程
        "timeout_minutes": 480,  # 8 小时超时：推荐审核可以更宽松
        "timeout_action": "auto_approve",  # 超时自动通过，避免流程卡死
    },
    "auto": {
        "description": "自动执行 - 无需人工审核，仅在日报中汇总展示",
        "auto_action": "proceed",  # 直接执行，无需任何等待
        "timeout_minutes": None,  # 无超时概念
        "timeout_action": None,
    },
}


class CollaborationEngine:
    _instance = None  # 单例模式：全局只有一个协作引擎实例

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记位，防止重复初始化
            cls._instance._agent_capabilities = {}  # 运行时注册的 Agent 能力映射
            cls._instance._chains = {}  # 协作链定义存储
            cls._instance._context_bus = None  # 延迟加载 CompanyContextBus
        return cls._instance

    def __init__(self):
        if not self._initialized:  # 单例防护：__init__ 只执行一次
            self._initialized = True
            self._load_default_chains()  # 加载预定义的协作链模板
            logger.info("collaboration_engine_v2_initialized", chain_count=len(self._chains))

    def _load_default_chains(self):
        self._chains = dict(DEFAULT_COLLABORATION_CHAINS)  # 浅拷贝，防止外部修改影响原始定义

    def _get_context_bus(self):
        if self._context_bus is None:
            from app.rag.company_context_bus import CompanyContextBus  # 延迟导入，避免循环依赖
        return CompanyContextBus  # 返回类而非实例，因为每个公司需要独立的 Bus 实例

    def register_agent_capabilities(
        self, agent_name: str, capabilities: list[str], next_agent: str = None
    ):
        self._agent_capabilities[agent_name] = {  # 运行时注册，支持动态添加 Agent 能力
            "capabilities": capabilities,
            "next_agent": next_agent,  # 链式调用的下一个 Agent 提示
        }
        logger.info("collaboration_registered", agent=agent_name, caps=len(capabilities))

    def get_agent_capabilities(self, agent_name: str) -> list[str]:
        agent_info = self._agent_capabilities.get(
            agent_name, {}
        )  # 未注册时返回空字典，避免 KeyError
        return agent_info.get("capabilities", [])  # 返回该 Agent 的能力列表，未注册时为空列表

    def get_next_agent(self, agent_name: str) -> str | None:
        agent_info = self._agent_capabilities.get(
            agent_name, {}
        )  # 未注册时返回空字典，避免 KeyError
        return agent_info.get("next_agent")  # 返回链式调用的下一个 Agent 名称，未配置时返回 None

    def trigger_collaboration(
        self, task_id: int, completed_agent_name: str, company_id: int
    ) -> int | None:
        """触发跨职位协作：为下一个接力 Agent 创建任务。

        同步方法，供 TaskWorker 在任务完成后直接调用。根据已注册的能力链
        查找下一个 Agent，校验目标 Agent 是否存在于公司内，然后创建接力任务。
        """
        next_agent = self.get_next_agent(completed_agent_name)
        if next_agent is None:
            logger.info("collaboration_no_next_agent", completed_agent=completed_agent_name)
            return None

        from app.database import db  # 延迟导入数据库模块

        try:
            # 先确认公司内存在目标 Agent，再创建接力任务，避免留下无法执行的孤儿任务。
            agents = db.get_agents_by_company(company_id)
            agent_names = [getattr(agent, "name", None) for agent in agents]
            if next_agent not in agent_names:
                logger.warning(
                    "collaboration_target_not_found", next_agent=next_agent, company_id=company_id
                )
                return None

            task_description = (
                f"协作任务：承接来自 {completed_agent_name} 的工作，请继续执行后续流程。"
            )
            new_task_id = db.create_task(
                company_id=company_id,
                source_agent_id=None,
                target_agent_name=next_agent,
                task_description=task_description,
            )

            logger.info(
                "collaboration_triggered",
                task_id=task_id,
                next_agent=next_agent,
                new_task_id=new_task_id,
            )
            return new_task_id
        except Exception as e:
            logger.error("collaboration_trigger_failed", error=str(e))
            return None

    def get_chain(self, chain_name: str) -> dict | None:
        return self._chains.get(chain_name)  # 安全获取，不存在时返回 None

    def list_chains(self) -> list[dict]:
        return [
            {"name": k, "title": v["name"], "step_count": len(v["steps"])}  # 仅返回摘要信息
            for k, v in self._chains.items()
        ]

    def add_chain(self, chain_name: str, chain_def: dict):
        self._chains[chain_name] = chain_def  # 支持运行时动态添加自定义协作链
        logger.info("collaboration_chain_added", chain=chain_name)

    def get_review_level(self, agent_key: str, task_type: str = None) -> str:
        agent_def = REVIEW_LEVEL_RULES.get("mandatory", {})
        for entry in agent_def.get("applies_to", []):  # 先检查是否在强制审核白名单中
            parts = entry.split(" ")  # 格式: "agent_key task_type"，用空格分隔
            if (
                len(parts) >= 2
                and parts[0] == agent_key
                and ((task_type and parts[1] == task_type) or not task_type)
            ):  # 精确匹配或模糊匹配
                return "mandatory"

        from app.agents import get_agent_definition  # 延迟导入，避免循环依赖

        agent_info = get_agent_definition(agent_key)
        if agent_info:
            return agent_info.get("review_level", "recommended")  # Agent 定义中可配置默认审核级别
        return "recommended"  # 兜底为推荐审核

    async def trigger_chain(
        self, chain_name: str, company_id: int, initiator_agent: str, extra_context: dict = None
    ) -> list[int]:
        chain = self.get_chain(chain_name)
        if not chain:
            logger.error("collaboration_chain_not_found", chain=chain_name)
            return []  # 返回空列表而非抛异常，让调用方优雅处理

        task_ids = []
        for step in chain["steps"]:
            try:
                from app.database import db  # 延迟导入数据库模块

                review_level = step.get(
                    "review", self.get_review_level(step["agent"])
                )  # 步骤级审核级别优先于 Agent 默认级别
                task_id = db.create_task(  # 为每个步骤创建数据库任务记录
                    company_id=company_id,
                    source_agent_id=None,  # 链式任务由系统触发，无源 Agent
                    target_agent_name=step["agent"],
                    task_description=step["task"],
                    status="pending",
                    review_level=review_level,
                )
                task_ids.append(task_id)
                logger.info(
                    "collaboration_chain_step_created",
                    chain=chain_name,
                    step=step["agent"],
                    task_id=task_id,
                )
            except Exception as e:
                logger.error(
                    "collaboration_chain_step_failed",
                    chain=chain_name,
                    step=step["agent"],
                    error=str(e),
                )

        await self._publish_chain_started(
            chain_name, company_id, task_ids
        )  # 通知 WebSocket 链已启动
        return task_ids

    async def on_agent_task_completed(
        self,
        agent_key: str,
        company_id: int,
        task_id: int,
        result_summary: str,
        agent_output: dict = None,
    ):
        """Agent任务完成后的自动回写和通知"""
        try:
            await self._write_to_context_bus(
                agent_key, company_id, result_summary, agent_output
            )  # 先回写上下文，确保数据持久化
            await self._notify_websocket(
                company_id, agent_key, task_id, result_summary
            )  # 再推送通知，前端可据此更新 UI
            logger.info("collaboration_task_completed_handled", agent=agent_key, task_id=task_id)
        except Exception as e:
            logger.error(
                "collaboration_task_completed_handler_error", agent=agent_key, error=str(e)
            )

    async def _write_to_context_bus(
        self, agent_key: str, company_id: int, result_summary: str, agent_output: dict = None
    ):
        """将Agent任务产出写入CompanyContextBus Layer 3（经验记忆层）"""
        try:
            ContextBusClass = self._get_context_bus()
            bus = ContextBusClass(str(company_id))  # 每个公司独立的 Bus 实例，实现数据隔离

            summary_data = {
                "agent": agent_key,
                "summary": result_summary[:500],  # 截断至 500 字符，避免经验记忆层膨胀
                "timestamp": None,
            }
            if agent_output:
                summary_data["output"] = agent_output

            await bus.add_experience(  # 写入经验记忆层，供后续 Agent 检索历史上下文
                experience_type=agent_key,
                content=result_summary[:500],
                metadata=summary_data,
            )
            logger.debug("context_bus_layer3_written", agent=agent_key, company=company_id)
        except Exception as e:
            logger.warning(
                "context_bus_write_failed", agent=agent_key, error=str(e)
            )  # 上下文写入失败不阻塞主流程

    async def _notify_websocket(self, company_id: int, agent_key: str, task_id: int, summary: str):
        try:
            from app.ws import ws_manager  # 延迟导入避免循环依赖

            await ws_manager.broadcast_to_company(
                company_id,
                {
                    "type": "agent_task_completed",
                    "agent": agent_key,
                    "taskId": task_id,
                    "summary": summary[:200],  # 截断至 200 字符，减少 WebSocket 消息体积
                },
            )
        except Exception:  # WebSocket 推送失败不影响业务流程
            pass

    async def _publish_chain_started(self, chain_name: str, company_id: int, task_ids: list[int]):
        try:
            from app.ws import ws_manager

            await ws_manager.broadcast_to_company(
                company_id,
                {
                    "type": "collaboration_chain_started",
                    "chain": chain_name,
                    "taskIds": task_ids,
                },
            )
        except Exception:  # WebSocket 推送失败不影响业务流程
            pass

    async def create_alert(
        self,
        company_id: int,
        alert_type: str,
        title: str,
        message: str,
        severity: str = "warning",
        related_agents: list[str] = None,
    ):
        from app.database import db  # 延迟导入

        try:
            alert_id = db.create_alert(
                company_id, alert_type, title, message, severity
            )  # 数据库持久化告警
            from app.ws import ws_manager

            await ws_manager.broadcast_to_company(  # 实时推送告警到前端
                company_id,
                {
                    "type": "alert",
                    "alertId": alert_id,
                    "alertType": alert_type,
                    "title": title,
                    "message": message,
                    "severity": severity,
                    "relatedAgents": related_agents or [],
                },
            )
            logger.info(
                "collaboration_alert_created", alert_id=alert_id, type=alert_type, severity=severity
            )
            return alert_id
        except Exception as e:
            logger.error("collaboration_alert_failed", error=str(e))
            return None  # 告警失败返回 None，不阻塞主流程

    def track_chain_progress(self, chain_name: str, company_id: int):
        if not hasattr(self, "_chain_progress"):  # 惰性初始化，避免 __init__ 中创建
            self._chain_progress: dict[str, dict] = {}
        key = f"{company_id}_{chain_name}"  # 复合 key 确保不同公司同名链的进度隔离
        if key not in self._chain_progress:
            chain = self.get_chain(chain_name)
            total = len(chain["steps"]) if chain else 0
            self._chain_progress[key] = {
                "chain_name": chain_name,
                "company_id": company_id,
                "total_steps": total,
                "completed_steps": 0,
                "completed_agents": [],  # 记录已完成的 Agent，防止重复计数
            }
        return self._chain_progress[key]

    async def mark_chain_step_completed(self, chain_name: str, company_id: int, agent_key: str):
        progress = self.track_chain_progress(chain_name, company_id)
        if agent_key not in progress["completed_agents"]:  # 同一 Agent 可能被多次调用，仅计数一次
            progress["completed_agents"].append(agent_key)
            progress["completed_steps"] = len(progress["completed_agents"])

        from app.ws import ws_manager

        await ws_manager.broadcast_chain_progress(  # 推送进度更新，前端实时展示进度条
            company_id,
            chain_name,
            progress["completed_steps"],
            progress["total_steps"],
            agent_key,
        )

        all_done = progress["completed_steps"] >= progress["total_steps"]
        if all_done:  # 链完成时推送完成事件并记录日志
            await ws_manager.broadcast_to_company(
                company_id,
                {
                    "type": "chain_completed",
                    "chain": chain_name,
                    "completedSteps": progress["completed_steps"],
                    "totalSteps": progress["total_steps"],
                },
            )
            logger.info("collaboration_chain_completed", chain=chain_name, company=company_id)


collaboration_engine = CollaborationEngine()  # 模块级单例，全局复用

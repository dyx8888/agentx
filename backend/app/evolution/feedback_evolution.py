# 模块文档：FeedbackDrivenEvolution 是进化引擎的核心——实现"反馈→分析→进化"的双层闭环
# 双层进化设计对应不同数据量级和时机：
#   Stage1: 即时——每条审核通过/拒绝都实时更新 few-shot 缓存，零延迟
#   Stage2: 周级——累积 50 条后触发 Prompt 规则提取，需要 sleeping consolidation
# 注：Stage3 LoRA 微调已移除（T2.6），保留表结构与历史数据，企业版/未来再启用
"""
反馈驱动进化引擎

双层进化:
1. 即时反馈 (Few-shot更新) - 审核结果即时加入Few-shot缓存
2. 周期性优化 (Prompt规则) - 睡眠巩固提取规则 → Agent Prompt自动更新
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class EvolutionStage(StrEnum):
    """用 StrEnum 而非普通 Enum，因为阶段值需要序列化为 JSON key，字符串类型兼容性更好"""

    STAGE1_FEWSHOT = "few_shot"
    STAGE2_PROMPT = "prompt_optimization"


@dataclass
class FeedbackRecord:
    """每条审核决策的标准数据格式，统一了不同来源反馈的结构"""

    task_id: int
    agent_key: (
        str  # 用 agent_key（字符串）而非 agent_id（整数），因为反馈来源于多系统，key 更具通用性
    )
    original_output: str
    human_decision: str  # "approved" 或 "rejected"，决定了走正向强化还是负向学习路径
    human_comment: str | None = None
    task_type: str | None = None  # 任务类型区分，用于分开缓存不同类型任务的 few-shot 示例
    company_id: int = 1
    # 使用 field(default_factory) 而非直接赋值 datetime.now()，因为 Python 默认参数在模块加载时求值，会导致所有记录共享同一时间戳
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class FeedbackDrivenEvolution:
    """反馈驱动的进化引擎"""

    # 使用单例模式（__new__ + _instance），因为进化引擎需要全局唯一实例来维护反馈计数的跨请求一致性
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记是否已执行 __init__，防止单例重复初始化
        return cls._instance

    def __init__(self):
        # 单例模式的关键：第二次调用 __init__ 时直接返回，避免重置已累积的状态
        if self._initialized:
            return
        self._initialized = True
        # 阈值配置：50 条触发 Stage2。该数字基于经验估算：
        #   50条≈管理员1周的审核量，足以提取有统计意义的 Prompt 规则
        self._feedback_threshold = {
            EvolutionStage.STAGE2_PROMPT: 50,
        }
        # evolution 数据目录独立于 feedback.db，存储 Prompt 规则文件
        self._data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
            "evolution",
        )
        # 使用 exist_ok=True 避免并发创建目录时抛异常
        os.makedirs(self._data_dir, exist_ok=True)
        logger.info("feedback_evolution_engine_initialized")

    async def on_review_decision(
        self,
        task_id: int,
        agent_key: str,
        original_output: str,
        decision: str,
        comment: str = None,
        company_id: int = 1,
        task_type: str = None,
    ) -> dict:
        """审核决策时触发进化检查"""
        try:
            # 构建 FeedbackRecord 统一数据格式，确保后续处理不需要关心数据来源
            record = FeedbackRecord(
                task_id=task_id,
                agent_key=agent_key,
                original_output=original_output,
                human_decision=decision,
                human_comment=comment,
                task_type=task_type,
                company_id=company_id,
            )
            self._store_feedback(record)

            # 根据审核结果分别走不同的学习路径：通过→正向强化，拒绝→负向学习
            if decision == "approved":
                self._update_few_shot_cache(agent_key, company_id, original_output, task_type)
            elif decision == "rejected":
                self._update_negative_example(
                    agent_key, company_id, original_output, comment, task_type
                )

            # 获取当前累计反馈数，用于判断是否触发更高阶段的进化
            feedback_count = self._get_feedback_count(agent_key, company_id)

            result = {
                "processed": True,
                "feedback_count": feedback_count,
                "evolution_triggers": [],  # 记录触发了哪些阶段，便于前端展示进化进度
            }

            # 阈值检查：达到 Stage2 阈值时异步触发 Prompt 规则优化
            if feedback_count >= self._feedback_threshold[EvolutionStage.STAGE2_PROMPT]:
                await self.trigger_stage2_evolution(agent_key, company_id)
                result["evolution_triggers"].append("stage2_prompt")

            return result
        except Exception as e:
            logger.error("feedback_evolution_error", error=str(e))
            return {"processed": False, "error": str(e)}

    def _store_feedback(self, record: FeedbackRecord):
        """将反馈记录持久化到 evolution_log 表，用于后续统计和审计"""
        try:
            from app.database import db

            # 延迟导入 db 避免循环依赖：feedback_evolution 是核心模块，被多个模块引用
            db.create_evolution_log(
                company_id=record.company_id,
                agent_id=None,  # agent_id 为 None 因为这里用 agent_key 字符串标识
                change_type="feedback_decision",
                changes=json.dumps(
                    {
                        "task_id": record.task_id,
                        "agent": record.agent_key,
                        "decision": record.human_decision,
                        "comment": record.human_comment,
                        "task_type": record.task_type,
                    },
                    ensure_ascii=False,
                ),  # ensure_ascii=False 保留中文评论原文
            )
        except Exception:
            # 存储失败不阻塞主流程，因为反馈数据丢失不影响 Agent 的核心功能
            pass

    def _update_few_shot_cache(
        self, agent_key: str, company_id: int, approved_output: str, task_type: str = None
    ):
        """将审核通过的输出加入 Redis few-shot 缓存，供后续任务参考"""
        try:
            import redis as rds  # 延迟导入，避免 Redis 不可用时整个模块无法加载

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = rds.from_url(
                redis_url, decode_responses=True
            )  # decode_responses=True 自动将 bytes 解码为 str

            task_type = task_type or "general"  # 未指定任务类型时归入 "general" 分类
            # Redis key 设计：memory:fewshot:{company_id}:{agent_key}:{task_type}，保证多租户隔离和任务类型隔离
            key = f"memory:fewshot:{company_id}:{agent_key}:{task_type}"

            existing = r.get(key)
            examples = json.loads(existing) if existing else []

            examples.append(
                {
                    "output": approved_output[:500],  # 截断到500字符，防止超长输出撑爆 Redis 内存
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "human_approved",  # 标记来源，方便后续区分"人类审核通过"和"系统自动生成"的示例
                }
            )

            examples = examples[-10:]  # 只保留最近 10 条，因为太久远的示例可能已过时
            # setex 设置 30 天过期，防止冷数据无限累积
            r.setex(key, 86400 * 30, json.dumps(examples, ensure_ascii=False))
            r.close()
            logger.debug("few_shot_cache_updated", agent=agent_key, count=len(examples))
        except Exception:
            # Redis 不可用时静默跳过，因为 few-shot 缓存是锦上添花，不是核心功能
            pass

    def _update_negative_example(
        self,
        agent_key: str,
        company_id: int,
        output: str,
        rejection_reason: str = None,
        task_type: str = None,
    ):
        """将审核拒绝的输出存入负向示例缓存，用于后续避免犯同样的错误"""
        try:
            import redis as rds

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = rds.from_url(redis_url, decode_responses=True)
            task_type = task_type or "general"
            # 负向示例独立 key，与正向缓存分开，避免混淆
            key = f"memory:negative:{company_id}:{agent_key}:{task_type}"

            existing = r.get(key)
            examples = json.loads(existing) if existing else []

            examples.append(
                {
                    "output": output[:300],  # 负向示例截断更短（300字符），因为只需要知道模式即可
                    "reason": rejection_reason,  # 保存拒绝原因，帮助 Agent 理解"为什么错了"
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            examples = examples[
                -20:
            ]  # 负向保留 20 条（比正向多），因为"不要做什么"的规则比"做什么"更多样
            r.setex(key, 86400 * 30, json.dumps(examples, ensure_ascii=False))
            r.close()
            logger.debug("negative_example_stored", agent=agent_key)
        except Exception:
            pass

    def _get_feedback_count(self, agent_key: str, company_id: int) -> int:
        """从数据库查询累计反馈数，用于阈值判断"""
        try:
            from app.database import db

            return db.count_evolution_logs(
                company_id=company_id,
                change_type="feedback_decision",
            )
        except Exception:
            return 0  # 查询失败返回 0，不会错误触发进化，是安全的默认值

    async def trigger_stage2_evolution(self, agent_key: str, company_id: int) -> dict:
        """触发阶段2: Prompt规则优化——从记忆管理器中提取经验规则并应用到 Agent Prompt"""
        try:
            from app.runtime.memory import memory_manager

            # 检索最近的 50 条情景记忆，数量足够覆盖近期模式但不会过载 LLM 上下文
            memories = memory_manager.retrieve_episodic(str(company_id), agent_key, limit=50)
            # _extract_prompt_rules 是 sleeping consolidation 的核心，用 LLM 从记忆中提取可泛化的规则
            optimized_rules = await memory_manager._extract_prompt_rules(memories, str(company_id))

            if not optimized_rules:
                return {"status": "skipped", "reason": "no_rules_extracted"}

            # 应用规则到文件系统，供 Agent 运行时读取
            self._apply_prompt_rules(agent_key, company_id, optimized_rules)

            # 记录进化日志，用于审计和回溯
            from app.database import db

            db.create_evolution_log(
                company_id=company_id,
                agent_id=None,
                change_type="prompt_optimization",
                changes=json.dumps(
                    {
                        "agent": agent_key,
                        "rules": optimized_rules,
                        "source": "feedback_driven_stage2",
                    },
                    ensure_ascii=False,
                ),
            )

            logger.info(
                "stage2_evolution_complete", agent=agent_key, rules_count=len(optimized_rules)
            )
            return {"status": "success", "rules_applied": len(optimized_rules)}
        except Exception as e:
            logger.error("stage2_evolution_failed", error=str(e))
            return {"status": "error", "error": str(e)}

    def _apply_prompt_rules(self, agent_key: str, company_id: int, rules: list[str]):
        """应用Prompt规则到Agent的System Prompt"""
        try:
            from app.agents import get_agent_definition

            agent_def = get_agent_definition(agent_key)
            if not agent_def:
                return

            # 将规则格式化为 Markdown 列表，方便嵌入 System Prompt 的附录
            rules_text = "\n".join(f"- {rule}" for rule in rules)
            optimized_appendix = f"\n\n## 经验优化规则（自动进化）\n{rules_text}"

            # 写入独立文件而非直接修改 System Prompt，因为文件方式更易于版本控制和回滚
            evolution_file = os.path.join(
                self._data_dir, f"prompt_rules_{company_id}_{agent_key}.txt"
            )
            with open(evolution_file, "w", encoding="utf-8") as f:
                f.write(optimized_appendix)

            logger.info("prompt_rules_applied", agent=agent_key, file=evolution_file)
        except Exception:
            pass

    def get_evolution_status(self, agent_key: str, company_id: int) -> dict:
        """获取Agent进化状态——用于管理面板展示进化进度"""
        feedback_count = self._get_feedback_count(agent_key, company_id)

        stages = {}
        for stage, threshold in self._feedback_threshold.items():
            # 计算每个阶段的进度百分比，上限 100%
            stages[stage.value] = {
                "current": feedback_count,
                "threshold": threshold,
                "progress_pct": min(100.0, feedback_count / threshold * 100),
                "activated": feedback_count >= threshold,
            }

        return {
            "agent": agent_key,
            "feedback_count": feedback_count,
            "stages": stages,
        }


# 模块级单例实例，确保全局只有一个进化引擎
# 在模块导入时创建，保证所有导入方共享同一个实例
feedback_evolution = FeedbackDrivenEvolution()

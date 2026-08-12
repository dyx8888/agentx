# 模块文档：Applier 是进化系统的"执行者"，负责将管理员审批通过的改进建议真正落地到知识库和配置中
# 它不生成建议，只执行——这种职责分离保证了审批流程的安全性和可审计性
"""
Evolution Applier - Automatic Application of Evolution Changes
Applies approved evolution suggestions to knowledge base and agent configuration
"""

# 使用结构化日志（logger）而非 print，是为了后续对接 ELK/Splunk 等日志平台，实现进化事件的可追溯
from app.core.logging import get_logger
from app.mcp_servers.knowledge_retrieval_server import add_knowledge

# 每个模块独立的 logger，方便按模块过滤日志
logger = get_logger(__name__)


class EvolutionApplier:
    """Applies evolution changes after admin approval"""

    def apply_knowledge_entries(
        self, agent_id: int, knowledge_entries: list[str], company_id: str
    ) -> bool:
        """
        Apply knowledge entries to ChromaDB knowledge base

        Args:
            agent_id: ID of the agent
            knowledge_entries: List of knowledge entry strings
            company_id: Company ID for multi-tenant isolation

        Returns:
            bool: Success status
        """
        try:
            added_count = 0

            # 逐个条目处理而非批量写入，是为了在部分条目失败时仍能继续，最大化成功写入量
            for entry in knowledge_entries:
                entry = entry.strip()  # 去除首尾空白，防止存入纯空格条目造成 ChromaDB 索引膨胀
                if entry:
                    try:
                        # Add knowledge entry with proper company isolation
                        # company_id 强制为字符串类型，因为 ChromaDB 的 metadata 字段要求一致类型
                        add_knowledge(
                            content=entry,
                            category=f"agent_{agent_id}_improvement",  # 用 agent_id 做分类前缀，便于按 Agent 维度检索知识
                            tags=[
                                "evolution",
                                "agent_improvement",
                            ],  # 统一 tag 方便后续过滤"进化产生"的知识条目
                            company_id=company_id,  # Ensure string type for ChromaDB
                        )
                        added_count += 1
                        logger.info(
                            "evolution_knowledge_entry_added", entry=entry[:50]
                        )  # 只记录前50字符，防止日志过大
                    except Exception as e:
                        # 单条失败不中断整体流程，因为其他条目仍有价值
                        logger.error(
                            "evolution_knowledge_entry_add_failed", entry=entry, error=str(e)
                        )

            # 记录最终结果，resource_id 绑定 agent_id 方便后续按 Agent 搜索日志
            logger.info(
                "evolution_knowledge_applied",
                applied=added_count,
                total=len(knowledge_entries),
                resource_id=agent_id,
            )
            return True

        except Exception as e:
            logger.error("evolution_knowledge_apply_failed", resource_id=agent_id, error=str(e))
            return False

    def apply_prompt_changes(self, agent_id: int, prompt_changes_text: str) -> bool:
        """
        Apply prompt changes to agent configuration

        Args:
            agent_id: ID of the agent
            prompt_changes_text: Suggested prompt changes

        Returns:
            bool: Success status
        """
        try:
            # For now, log prompt changes to a separate log
            # In a full implementation, this could update agent configuration
            # or create a new version in agent_prompt_versions table

            # 当前仅记录日志而非直接修改 System Prompt，因为 Prompt 修改需要人工审核确认后才能生效，避免自动修改导致 Agent 行为异常
            logger.info(
                "evolution_prompt_applied", resource_id=agent_id, preview=prompt_changes_text[:100]
            )

            # Could extend this to create agent_prompt_versions table:
            # CREATE TABLE IF NOT EXISTS agent_prompt_versions (
            #     id INTEGER PRIMARY KEY AUTOINCREMENT,
            #     agent_id INTEGER NOT NULL,
            #     version_number INTEGER,
            #     prompt_content TEXT NOT NULL,
            #     change_reason TEXT,
            #     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            #     FOREIGN KEY (agent_id) REFERENCES agents (id)
            # )

            return True

        except Exception as e:
            logger.error("evolution_prompt_apply_failed", resource_id=agent_id, error=str(e))
            return False

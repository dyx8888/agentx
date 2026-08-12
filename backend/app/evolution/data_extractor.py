# 模块文档：TrainingDataExtractor 是微调数据管线的前端——从反馈数据中提取"原始输出→人工修正"的训练对
# DEPRECATED: LoRA 微调已移除（T2.6），此模块暂无调用方，保留以备企业版/未来再启用
"""
Training Data Extractor
Extracts training pairs from feedback data for model fine-tuning
"""

import json
import os
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.database import db

logger = get_logger(__name__)


def _db_method(name: str):
    try:
        method = getattr(db, name)
    except (AttributeError, RuntimeError):
        return None
    return method if callable(method) else None


class TrainingDataExtractor:
    """Extracts and processes training data from feedback entries"""

    def __init__(self):
        # 训练数据目录独立于 feedback.db，因为训练数据文件可能很大（JSONL格式），需要独立管理
        self.training_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "training"
        )
        # Ensure training directory exists
        # 在 __init__ 中创建目录而非懒加载，是为了尽早暴露权限问题，避免运行到一半才发现无法写入
        os.makedirs(self.training_dir, exist_ok=True)

    def extract_training_pairs(
        self, agent_id: int, tool_name: str | None = None, days: int = 7, min_samples: int = 3
    ) -> list[dict]:
        """
        Extract training pairs from feedback entries

        Args:
            agent_id: Agent ID to extract data for
            tool_name: Optional tool name filter
            days: Number of days to look back
            min_samples: Minimum samples required to proceed

        Returns:
            List of training pairs with original and edited outputs
        """
        try:
            # Calculate date threshold
            # 使用 datetime 对象而非字符串比较，因为 SQLite 的 datetime 比较更精确
            threshold_date = datetime.now() - timedelta(days=days)

            # Query feedback entries
            # 通过 hasattr 检测数据库模式，因为系统支持 SQLite 和 SQLAlchemy 双模式
            get_session = _db_method('get_session')
            if get_session:
                from app.database.models import Agent, Feedback

                with get_session() as session:
                    query = (
                        session.query(Feedback, Agent)
                        .join(Agent, Feedback.agent_id == Agent.id)
                        .filter(
                            Feedback.agent_id == agent_id,
                            Feedback.status == 'modified',
                            Feedback.human_edited_output.isnot(None),
                            Feedback.human_edited_output != '',
                            Feedback.created_at >= threshold_date,
                        )
                    )
                    if tool_name:
                        query = query.filter(Feedback.tool_name == tool_name)
                    rows = query.order_by(Feedback.created_at.desc()).all()

                pairs = [
                    {
                        'id': feedback.id,
                        'tool_name': feedback.tool_name,
                        'original_output': feedback.original_output,
                        'human_edited_output': feedback.human_edited_output,
                        'status': feedback.status,
                        'created_at': feedback.created_at,
                        'agent_name': agent.name,
                        'company_id': agent.company_id,
                    }
                    for feedback, agent in rows
                ]

            elif hasattr(db, 'get_connection'):
                # SQLite mode
                conn = db.get_connection()
                cursor = conn.cursor()

                # 只查询 status='modified' 且有实际编辑内容的记录，因为未经人工修改的反馈不能作为训练数据
                query = """
                    SELECT f.id, f.tool_name, f.original_output, f.human_edited_output,
                           f.status, f.created_at, a.name as agent_name, a.company_id
                    FROM feedback f
                    JOIN agents a ON f.agent_id = a.id
                    WHERE f.agent_id = ?
                    AND f.status = 'modified'
                    AND f.human_edited_output IS NOT NULL
                    AND f.human_edited_output != ''
                    AND f.created_at >= ?
                """
                params = [agent_id, threshold_date]

                if tool_name:
                    query += " AND f.tool_name = ?"
                    params.append(tool_name)

                query += " ORDER BY f.created_at DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                conn.close()

                # Convert to list of dicts
                # 用字段名索引而非数字索引，增加代码可读性，减少列顺序变化导致的 bug
                pairs = []
                for row in rows:
                    pairs.append(
                        {
                            "id": row[0],
                            "tool_name": row[1],
                            "original_output": row[2],
                            "human_edited_output": row[3],
                            "status": row[4],
                            "created_at": row[5],
                            "agent_name": row[6],
                            "company_id": row[7],
                        }
                    )

            else:
                logger.warning("training_data_extraction_backend_unavailable")
                return []

            # Check minimum samples
            # 样本量不足时直接返回空列表，因为过少的训练数据会导致过拟合，反而降低模型质量
            if len(pairs) < min_samples:
                logger.info(
                    f"Insufficient training samples: {len(pairs)} < {min_samples}",
                    agent_id=agent_id,
                    tool_name=tool_name,
                )
                return []

            logger.info(
                f"Extracted {len(pairs)} training pairs",
                agent_id=agent_id,
                tool_name=tool_name,
                days=days,
            )

            return pairs

        except Exception as e:
            logger.error(
                f"Error extracting training pairs: {e}", agent_id=agent_id, tool_name=tool_name
            )
            return []

    def generate_training_summary(self, pairs: list[dict], agent_name: str, tool_name: str) -> str:
        """
        Generate training summary in JSONL format

        Args:
            pairs: List of training pairs
            agent_name: Name of the agent
            tool_name: Name of the tool

        Returns:
            JSONL formatted string
        """
        try:
            training_data = []

            for pair in pairs:
                # Create training example
                # 使用 prompt/completion 格式而非 messages 格式，因为这是 OpenAI 微调 API 的标准格式
                example = {
                    "prompt": pair["original_output"],
                    "completion": pair["human_edited_output"],
                    "metadata": {  # 元数据用于后续分析训练数据质量，不会被模型直接消费
                        "agent_name": agent_name,
                        "tool_name": tool_name,
                        "feedback_id": pair["id"],
                        "created_at": pair["created_at"],
                        "company_id": pair["company_id"],
                    },
                }
                training_data.append(example)

            # Convert to JSONL format
            # ensure_ascii=False 保留中文字符，避免微调模型学习到 Unicode 转义序列
            jsonl_lines = [json.dumps(example, ensure_ascii=False) for example in training_data]
            summary = "\n".join(jsonl_lines)

            # Add header comment
            # 以 # 开头的注释行不是合法 JSON，但方便人工阅读；微调工具会自动忽略这些行
            header = f"# Training data for {agent_name} - {tool_name}\n"
            header += f"# Generated: {datetime.now().isoformat()}\n"
            header += f"# Total samples: {len(training_data)}\n\n"

            return header + summary

        except Exception as e:
            logger.error(
                f"Error generating training summary: {e}",
                agent_name=agent_name,
                tool_name=tool_name,
            )
            return ""

    def save_training_data(self, agent_id: int, tool_name: str, summary_jsonl: str) -> str:
        """
        Save training data to file

        Args:
            agent_id: Agent ID
            tool_name: Tool name
            summary_jsonl: JSONL formatted training data

        Returns:
            File path of saved training data
        """
        try:
            # Generate filename
            # 文件名包含时间戳，保证每次导出的训练数据不会互相覆盖，方便追溯和对比
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 替换路径分隔符，防止 tool_name 中包含 / 或 \ 导致文件写入错误路径
            safe_tool_name = tool_name.replace("/", "_").replace("\\", "_")
            filename = f"agent_{agent_id}_{safe_tool_name}_{timestamp}.jsonl"
            filepath = os.path.join(self.training_dir, filename)

            # Save to file
            # 使用 UTF-8 编码保证中文内容不丢失
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(summary_jsonl)

            logger.info(
                f"Training data saved to {filepath}",
                agent_id=agent_id,
                tool_name=tool_name,
                file_size=len(summary_jsonl),
            )

            return filepath

        except Exception as e:
            logger.error(f"Error saving training data: {e}", agent_id=agent_id, tool_name=tool_name)
            return ""

    def extract_and_save_training_data(
        self, agent_id: int, tool_name: str | None = None, days: int = 7, min_samples: int = 3
    ) -> str | None:
        """
        Complete workflow: extract pairs, generate summary, and save

        Args:
            agent_id: Agent ID
            tool_name: Optional tool name
            days: Number of days to look back
            min_samples: Minimum samples required

        Returns:
            File path if successful, None otherwise
        """
        try:
            # Extract training pairs
            pairs = self.extract_training_pairs(agent_id, tool_name, days, min_samples)

            # 样本不足时提前返回 None 而非抛异常，让调用方可以优雅处理（如显示"暂无足够数据"提示）
            if not pairs:
                logger.info(
                    "No training data extracted - insufficient samples",
                    agent_id=agent_id,
                    tool_name=tool_name,
                )
                return None

            # Get agent name
            # 通过 db.get_agent 获取 Agent 名称，用于生成有意义的训练数据文件名
            agent_info = db.get_agent(agent_id)
            if not agent_info:
                logger.error(f"Agent not found: {agent_id}")
                return None

            agent_name = agent_info.name

            # Generate training summary
            summary = self.generate_training_summary(pairs, agent_name, tool_name)

            if not summary:
                logger.error("Failed to generate training summary")
                return None

            # Save training data
            filepath = self.save_training_data(agent_id, tool_name, summary)

            if filepath:
                # 全流程成功的日志，记录关键指标用于监控和告警
                logger.info(
                    "Training data workflow completed successfully",
                    agent_id=agent_id,
                    tool_name=tool_name,
                    filepath=filepath,
                    samples_count=len(pairs),
                )

            return filepath

        except Exception as e:
            logger.error(
                f"Error in training data workflow: {e}", agent_id=agent_id, tool_name=tool_name
            )
            return None

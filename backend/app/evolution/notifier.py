# 模块文档：Notifier 是进化系统与管理员的"沟通桥梁"——当进化事件发生时通知管理员审查
# 目前以日志形式通知，但架构预留了邮件/Slack 等扩展点
"""
Evolution Notifier
Handles admin notifications for evolution events and training data
"""

import os
from datetime import datetime

from app.core.logging import get_logger
from app.database import db

logger = get_logger(__name__)

class EvolutionNotifier:
    """Handles notifications for evolution events"""

    def __init__(self):
        # 暂时无初始化参数，但保留 __init__ 为未来扩展（如配置邮件客户端）留接口
        pass

    def notify_admin(
        self,
        agent_id: int,
        suggestion: str,
        training_data_path: str | None = None
    ) -> bool:
        """
        Notify admin about evolution events
        
        Args:
            agent_id: Agent ID
            suggestion: Evolution suggestion text
            training_data_path: Path to generated training data
            
        Returns:
            True if notification successful, False otherwise
        """
        try:
            # Get agent info for context
            # 先获取 Agent 信息，因为通知需要包含 Agent 名称和归属企业，让管理员一目了然
            agent_info = db.get_agent(agent_id)
            if not agent_info:
                logger.error(f"Agent not found for notification: {agent_id}")
                return False

            # Log evolution event with training data path
            # 先保存进化日志再发送通知，确保即使通知失败，事件也有记录
            evolution_log_id = self._save_evolution_log(
                agent_id,
                suggestion,
                training_data_path
            )

            if not evolution_log_id:
                logger.error(f"Failed to save evolution log for agent {agent_id}")
                return False

            # Send notification (currently using logger, can be extended to email)
            self._send_notification(
                agent_info,
                suggestion,
                training_data_path,
                evolution_log_id
            )

            logger.info(
                f"Evolution notification sent for agent {agent_info.name}",
                agent_id=agent_id,
                evolution_log_id=evolution_log_id,
                training_data_path=training_data_path
            )

            return True

        except Exception as e:
            logger.error(f"Error sending evolution notification: {e}", agent_id=agent_id)
            return False

    def _save_evolution_log(
        self,
        agent_id: int,
        suggestion: str,
        training_data_path: str | None
    ) -> int | None:
        """
        Save evolution log with training data path
        
        Args:
            agent_id: Agent ID
            suggestion: Evolution suggestion
            training_data_path: Path to training data file
            
        Returns:
            Evolution log ID if successful, None otherwise
        """
        try:
            # 通过 hasattr 检测数据库模式，兼容 SQLite 和 SQLAlchemy 双模式
            if hasattr(db, 'get_connection'):
                # SQLite mode
                conn = db.get_connection()
                cursor = conn.cursor()

                # applied 默认为 False，因为新建议需要管理员审核后才能应用
                cursor.execute("""
                    INSERT INTO evolution_log 
                    (agent_id, suggestion_text, created_at, applied, training_data_path)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    agent_id,
                    suggestion,
                    datetime.now().isoformat(),
                    False,
                    training_data_path
                ))

                evolution_id = cursor.lastrowid  # 获取自增 ID，用于后续更新和关联
                conn.commit()
                conn.close()

                return evolution_id
            else:
                # SQLAlchemy mode - not implemented yet
                logger.warning("SQLAlchemy mode not implemented for evolution log saving")
                return None

        except Exception as e:
            logger.error(f"Error saving evolution log: {e}", agent_id=agent_id)
            return None

    def _send_notification(
        self,
        agent_info,
        suggestion: str,
        training_data_path: str | None,
        evolution_log_id: int
    ):
        """
        Send notification to admin
        
        Args:
            agent_info: Agent information
            suggestion: Evolution suggestion
            training_data_path: Training data file path
            evolution_log_id: Evolution log ID
        """
        try:
            # Create notification message
            # 使用 emoji 和格式化文本是为了让日志消息在 Slack/钉钉等通知渠道中更醒目
            message = f"""
🚀 EVOLUTION NOTIFICATION 🚀

Agent: {agent_info.name} (ID: {agent_info.id})
Company ID: {agent_info.company_id}

Evolution Suggestion:
{suggestion}

Training Data: {training_data_path or 'Not generated'}
Evolution Log ID: {evolution_log_id}
Timestamp: {datetime.now().isoformat()}

Action Required:
1. Review the evolution suggestion
2. Check training data quality
3. Approve or reject the evolution
4. Apply changes if approved

This is an automated notification from AgentX Evolution System.
            """.strip()

            # Currently using logger.warning for admin notification
            # In production, this could be email, Slack, etc.
            # 使用 WARNING 级别而非 INFO，因为通知需要引起管理员注意，在日志监控中更容易被过滤出来
            logger.warning(
                "EVOLUTION NOTIFICATION",
                agent_name=agent_info.name,
                agent_id=agent_info.id,
                company_id=agent_info.company_id,
                evolution_log_id=evolution_log_id,
                training_data_path=training_data_path,
                # 截断建议内容防止日志过长
                suggestion_preview=suggestion[:200] + "..." if len(suggestion) > 200 else suggestion
            )

            # TODO: Implement email notification
            # self._send_email_notification(agent_info, message)

        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    def _send_email_notification(self, agent_info, message: str):
        """
        Send email notification (placeholder for future implementation)
        
        Args:
            agent_info: Agent information
            message: Notification message
        """
        # TODO: Implement email notification
        # This could use SMTP, SendGrid, AWS SES, etc.
        # 预留方法保留接口，防止未来对接邮件服务时需要改动调用方代码
        logger.info("Email notification not implemented yet")
        pass

    def get_training_data_files(self, agent_id: int) -> list:
        """
        Get list of training data files for an agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            List of training data file information
        """
        try:
            if hasattr(db, 'get_connection'):
                # SQLite mode
                conn = db.get_connection()
                cursor = conn.cursor()

                # 只查询有 training_data_path 的记录，因为无路径的记录不包含可下载的训练数据文件
                cursor.execute("""
                    SELECT id, agent_id, suggestion_text, training_data_path, 
                           created_at, applied
                    FROM evolution_log
                    WHERE agent_id = ? 
                    AND training_data_path IS NOT NULL
                    ORDER BY created_at DESC
                """, (agent_id,))

                rows = cursor.fetchall()
                conn.close()

                files = []
                for row in rows:
                    files.append({
                        'evolution_log_id': row[0],
                        'agent_id': row[1],
                        'suggestion_preview': row[2][:100] + "..." if len(row[2]) > 100 else row[2],
                        'training_data_path': row[3],
                        'created_at': row[4],
                        'applied': row[5],
                        # 检查文件是否仍存在，因为训练数据可能被手动清理过
                        'file_exists': os.path.exists(row[3]) if row[3] else False
                    })

                return files
            else:
                # SQLAlchemy mode - not implemented yet
                logger.warning("SQLAlchemy mode not implemented for training data listing")
                return []

        except Exception as e:
            logger.error(f"Error getting training data files: {e}", agent_id=agent_id)
            return []

    def mark_evolution_applied(self, evolution_log_id: int) -> bool:
        """
        Mark evolution as applied in database
        
        Args:
            evolution_log_id: Evolution log ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if hasattr(db, 'get_connection'):
                # SQLite mode
                conn = db.get_connection()
                cursor = conn.cursor()

                # 只用 UPDATE 而非 INSERT OR REPLACE，因为只需要更新 applied 字段，不应覆盖其他字段
                cursor.execute("""
                    UPDATE evolution_log
                    SET applied = TRUE
                    WHERE id = ?
                """, (evolution_log_id,))

                conn.commit()
                conn.close()

                logger.info(f"Evolution marked as applied: {evolution_log_id}")
                return True
            else:
                # SQLAlchemy mode - not implemented yet
                logger.warning("SQLAlchemy mode not implemented for evolution update")
                return False

        except Exception as e:
            logger.error(f"Error marking evolution as applied: {e}", evolution_log_id=evolution_log_id)
            return False

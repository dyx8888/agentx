# 模块文档：Notifier 是进化系统与管理员的"沟通桥梁"——当进化事件发生时通知管理员审查
# 目前以日志形式通知，但架构预留了邮件/Slack 等扩展点
"""
Evolution Notifier
Handles admin notifications for evolution events and training data
"""

import asyncio
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.logging import get_logger
from app.database import db

logger = get_logger(__name__)


def _db_method(name: str):
    try:
        method = getattr(db, name)
    except (AttributeError, RuntimeError):
        return None
    return method if callable(method) else None


class EvolutionNotifier:
    """Handles notifications for evolution events"""

    def __init__(self):
        # 暂时无初始化参数，但保留 __init__ 为未来扩展（如配置邮件客户端）留接口
        pass

    def notify_admin(
        self, agent_id: int, suggestion: str, training_data_path: str | None = None
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
            evolution_log_id = self._save_evolution_log(agent_id, suggestion, training_data_path)

            if not evolution_log_id:
                logger.error(f"Failed to save evolution log for agent {agent_id}")
                return False

            # Send notification (currently using logger, can be extended to email)
            self._send_notification(agent_info, suggestion, training_data_path, evolution_log_id)

            logger.info(
                f"Evolution notification sent for agent {agent_info.name}",
                agent_id=agent_id,
                evolution_log_id=evolution_log_id,
                training_data_path=training_data_path,
            )

            return True

        except Exception as e:
            logger.error(f"Error sending evolution notification: {e}", agent_id=agent_id)
            return False

    def _save_evolution_log(
        self, agent_id: int, suggestion: str, training_data_path: str | None
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
            create_log = _db_method("create_evolution_log")
            if create_log:
                return create_log(
                    agent_id=agent_id,
                    suggestion_text=suggestion,
                    training_data_path=training_data_path,
                )

            # Legacy SQLite manager path.
            if hasattr(db, "get_connection"):
                conn = db.get_connection()
                cursor = conn.cursor()

                # applied 默认为 False，因为新建议需要管理员审核后才能应用
                cursor.execute(
                    """
                    INSERT INTO evolution_log
                    (agent_id, suggestion_text, created_at, applied, training_data_path)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (agent_id, suggestion, datetime.now().isoformat(), False, training_data_path),
                )

                evolution_id = cursor.lastrowid  # 获取自增 ID，用于后续更新和关联
                conn.commit()
                conn.close()

                return evolution_id

            logger.warning("evolution_log_store_unavailable")
            return None

        except Exception as e:
            logger.error(f"Error saving evolution log: {e}", agent_id=agent_id)
            return None

    def _send_notification(
        self, agent_info, suggestion: str, training_data_path: str | None, evolution_log_id: int
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

Training Data: {training_data_path or "Not generated"}
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
                suggestion_preview=suggestion[:200] + "..."
                if len(suggestion) > 200
                else suggestion,
            )

            # 通过邮件通知管理员（fire-and-forget，不阻塞通知流程）
            # _send_email_notification 是 async 方法，这里根据事件循环状态选择派发策略
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 已有运行中的事件循环（如 FastAPI 请求上下文）：派发后台任务
                    asyncio.ensure_future(self._send_email_notification(agent_info, message))
                else:
                    # 有事件循环但未运行：直接运行至完成
                    loop.run_until_complete(self._send_email_notification(agent_info, message))
            except RuntimeError:
                # 没有事件循环（如同步脚本/Celery worker）：新建临时循环运行
                asyncio.run(self._send_email_notification(agent_info, message))

        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    async def _send_email_notification(self, agent_info, message: str):
        """发送邮件通知给管理员

        从环境变量 ADMIN_EMAIL 读取收件人，调用 send_email 发送。
        未配置 ADMIN_EMAIL 时静默跳过（不抛异常）。

        Args:
            agent_info: Agent 信息
            message: 通知正文
        """
        admin_email = os.getenv("ADMIN_EMAIL")
        if not admin_email:
            # 未配置管理员邮箱时静默跳过——日志通知已在上层完成
            logger.info(
                "email_notification_skipped_no_admin_email",
                agent_id=getattr(agent_info, "id", None),
            )
            return

        subject = f"[AgentX 进化通知] Agent {getattr(agent_info, 'name', 'Unknown')} 有新的进化建议"
        success = await self.send_email(
            to=admin_email,
            subject=subject,
            body=message,
        )
        if success:
            logger.info(
                "email_notification_sent",
                to=admin_email,
                agent_id=getattr(agent_info, "id", None),
            )
        else:
            logger.warning(
                "email_notification_failed",
                to=admin_email,
                agent_id=getattr(agent_info, "id", None),
            )

    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """异步发送邮件，用 run_in_executor 包装同步 smtplib 调用。

        SMTP 配置从环境变量读取：SMTP_HOST、SMTP_PORT、SMTP_USER、SMTP_PASSWORD、SMTP_FROM。
        未配置时记 warning 并返回 False（不抛异常）。

        Args:
            to: 收件人邮箱
            subject: 邮件主题
            body: 邮件正文（纯文本）

        Returns:
            True 发送成功，False 发送失败或未配置 SMTP
        """
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")
        smtp_from = os.getenv("SMTP_FROM")

        # SMTP 未配置时降级返回 False（不抛异常）
        if not all([smtp_host, smtp_user, smtp_password, smtp_from]):
            logger.warning("email_send_skipped_no_smtp_config", to=to)
            return False

        def _send_sync() -> bool:
            """同步发送邮件（在 executor 线程中运行）"""
            msg = MIMEMultipart()
            msg["From"] = smtp_from
            msg["To"] = to
            msg["Subject"] = subject
            # 显式指定 utf-8 编码，避免中文正文乱码
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                # starttls 升级为加密连接，防止凭证被中间人截获
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from, [to], msg.as_string())
            return True

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _send_sync)
        except Exception as e:
            logger.error("email_send_failed", error=str(e), to=to, subject=subject)
            return False

    def get_training_data_files(self, agent_id: int) -> list:
        """
        Get list of training data files for an agent

        Args:
            agent_id: Agent ID

        Returns:
            List of training data file information
        """
        try:
            get_logs = _db_method("get_evolution_logs_by_agent")
            if get_logs:
                files = []
                for log in get_logs(agent_id):
                    path = getattr(log, "training_data_path", None)
                    if not path:
                        continue
                    suggestion = getattr(log, "suggestion_text", "") or ""
                    created_at = getattr(log, "created_at", "")
                    if hasattr(created_at, "isoformat"):
                        created_at = created_at.isoformat()
                    files.append(
                        {
                            "evolution_log_id": getattr(log, "id", None),
                            "agent_id": getattr(log, "agent_id", agent_id),
                            "suggestion_preview": suggestion[:100] + "..."
                            if len(suggestion) > 100
                            else suggestion,
                            "training_data_path": path,
                            "created_at": created_at,
                            "applied": bool(getattr(log, "applied", False)),
                            "file_exists": os.path.exists(path),
                        }
                    )
                return files

            if hasattr(db, "get_connection"):
                # SQLite mode
                conn = db.get_connection()
                cursor = conn.cursor()

                # 只查询有 training_data_path 的记录，因为无路径的记录不包含可下载的训练数据文件
                cursor.execute(
                    """
                    SELECT id, agent_id, suggestion_text, training_data_path,
                           created_at, applied
                    FROM evolution_log
                    WHERE agent_id = ?
                    AND training_data_path IS NOT NULL
                    ORDER BY created_at DESC
                """,
                    (agent_id,),
                )

                rows = cursor.fetchall()
                conn.close()

                files = []
                for row in rows:
                    files.append(
                        {
                            "evolution_log_id": row[0],
                            "agent_id": row[1],
                            "suggestion_preview": row[2][:100] + "..."
                            if len(row[2]) > 100
                            else row[2],
                            "training_data_path": row[3],
                            "created_at": row[4],
                            "applied": bool(row[5]),
                            # 检查文件是否仍存在，因为训练数据可能被手动清理过
                            "file_exists": os.path.exists(row[3]) if row[3] else False,
                        }
                    )

                return files

            logger.warning("evolution_training_data_listing_unavailable")
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
            update_applied = _db_method("update_evolution_applied")
            if update_applied:
                return bool(update_applied(evolution_log_id))

            if hasattr(db, "get_connection"):
                # SQLite mode
                conn = db.get_connection()
                cursor = conn.cursor()

                # 只用 UPDATE 而非 INSERT OR REPLACE，因为只需要更新 applied 字段，不应覆盖其他字段
                cursor.execute(
                    """
                    UPDATE evolution_log
                    SET applied = TRUE
                    WHERE id = ?
                """,
                    (evolution_log_id,),
                )

                conn.commit()
                conn.close()

                logger.info(f"Evolution marked as applied: {evolution_log_id}")
                return True

            logger.warning("evolution_update_unavailable")
            return False

        except Exception as e:
            logger.error(
                f"Error marking evolution as applied: {e}", evolution_log_id=evolution_log_id
            )
            return False

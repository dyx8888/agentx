"""
Message Persistence Service
Handles saving/loading chat messages and updating conversation statistics

集成到 /api/chat 流式处理中：
- 对话开始时自动创建或复用 conversation
- 每条用户消息和 Master 回复写入 messages 表
- 自动更新 conversation 的 message_count 和 last_message
"""

import json
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.models import Conversation, Message

logger = get_logger(__name__)

# 标题最大长度
MAX_TITLE_LENGTH = 50

_INTERNAL_EVENT_LINE_RE = re.compile(
    r"^\s*\[(?:Action|Observation|Plan|Reflection|Delegation|Tool|Debug|Review)\].*$",
    re.IGNORECASE | re.MULTILINE,
)
_INTERNAL_TEXT_MARKERS = (
    "RAG answer from knowledge base",
    "\u5ba1\u67e5\u901a\u8fc7",
    "\u5ba1\u67e5\u672a\u901a\u8fc7",
    "\u5ba1\u6838\u901a\u8fc7",
    "\u53cd\u601d",
    "\u9a73\u56de",
)


def sanitize_user_visible_text(content: str | None) -> str:
    """Remove internal execution traces before storing user-visible chat text."""
    text = content or ""
    text = _INTERNAL_EVENT_LINE_RE.sub("", text)
    cleaned_lines = [
        line
        for line in text.splitlines()
        if not any(marker in line for marker in _INTERNAL_TEXT_MARKERS)
    ]
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or "\u4efb\u52a1\u5df2\u5b8c\u6210"


def truncate_title(message: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    """
    从消息内容截取标题

    Args:
        message: 用户消息内容
        max_length: 最大标题长度

    Returns:
        截取后的标题
    """
    if not message or not message.strip():
        return "新对话"

    stripped = message.strip()
    if len(stripped) <= max_length:
        return stripped
    return stripped[:max_length]


def get_or_create_conversation(
    session: Session,
    user_id: int,
    company_id: int,
    conversation_id: int | None = None,
    title: str = "新对话",
) -> Conversation:
    """
    获取或创建对话

    如果传入了 conversation_id，先尝试查找已有对话；
    如果不存在或未传入，则创建新对话。

    Args:
        session: 数据库会话
        user_id: 用户 ID
        company_id: 公司 ID
        conversation_id: 可选的已有对话 ID
        title: 对话标题（仅新建时使用）

    Returns:
        Conversation 实例
    """
    if conversation_id:
        conv = (
            session.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.company_id == company_id,
            )
            .first()
        )
        if conv and conv.status == "active":
            logger.info(
                "conversation_reused",
                conversation_id=conversation_id,
                user_id=user_id,
            )
            return conv

    # 创建新对话
    conv = Conversation(
        user_id=user_id,
        company_id=company_id,
        title=truncate_title(title),
        status="active",
        message_count=0,
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    logger.info(
        "conversation_created",
        conversation_id=conv.id,
        user_id=user_id,
        company_id=company_id,
    )
    return conv


def save_user_message(
    session: Session,
    conversation_id: int,
    user_id: int,
    content: str,
    metadata: dict | None = None,
    references: dict | None = None,
    sequence_num: int = 0,
) -> Message:
    """
    保存用户消息

    Args:
        session: 数据库会话
        conversation_id: 对话 ID
        user_id: 用户 ID
        content: 消息内容
        metadata: 结构化元数据（如意图识别结果）
        references: RAG 引用数据
        sequence_num: 消息序号

    Returns:
        创建的 Message 实例
    """
    msg = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="user",
        content=content,
        content_type="text",
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        references_json=json.dumps(references, ensure_ascii=False) if references else None,
        sequence_num=sequence_num,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    logger.info(
        "user_message_saved",
        message_id=msg.id,
        conversation_id=conversation_id,
    )
    return msg


def save_assistant_message(
    session: Session,
    conversation_id: int,
    content: str,
    metadata: dict | None = None,
    references: dict | None = None,
    sequence_num: int = 0,
) -> Message:
    """
    保存助手（Master/Agent）回复

    Args:
        session: 数据库会话
        conversation_id: 对话 ID
        content: 回复内容
        metadata: 结构化元数据（如达人列表、分析报告）
        references: 引用数据
        sequence_num: 消息序号

    Returns:
        创建的 Message 实例
    """
    cleaned_content = sanitize_user_visible_text(content)
    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=cleaned_content,
        content_type="text",
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        references_json=json.dumps(references, ensure_ascii=False) if references else None,
        sequence_num=sequence_num,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    logger.info(
        "assistant_message_saved",
        message_id=msg.id,
        conversation_id=conversation_id,
    )
    return msg


def update_conversation_stats(
    session: Session,
    conversation_id: int,
    last_message: str,
) -> None:
    """
    更新对话统计信息

    Args:
        session: 数据库会话
        conversation_id: 对话 ID
        last_message: 最后一条消息内容（用于更新 last_message 字段）
    """
    conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.message_count += 1
        conv.last_message = truncate_title(sanitize_user_visible_text(last_message))
        conv.updated_at = datetime.now(UTC)
        session.commit()
        logger.info(
            "conversation_stats_updated",
            conversation_id=conversation_id,
            message_count=conv.message_count,
        )

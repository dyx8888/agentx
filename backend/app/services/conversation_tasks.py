"""Durable chat task lifecycle. No legacy tasks/Redis/A2A queue is consumed."""
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, update

from app.database import db
from app.database.models import Conversation, ConversationTask, Message, User

EXECUTION_SECONDS = 90
MAX_TASKS_PER_MESSAGE = 4
_capacity = asyncio.Semaphore(1)


def _owner(session, company_id, user_id, conversation_id):
    # Check live membership as well as conversation ownership on every operation.
    conv = session.query(Conversation).join(User, User.id == Conversation.user_id).filter(
        Conversation.id == conversation_id, Conversation.company_id == company_id,
        Conversation.user_id == user_id, Conversation.status == "active",
        User.company_id == company_id, User.disabled.is_(False), User.is_active.is_(True),
    ).with_for_update().first()
    if conv is None:
        raise PermissionError("conversation_not_found")
    return conv


@dataclass
class TaskContext:
    company_id: int
    user_id: int
    conversation_id: int | None
    source_message_id: int | None
    model_key: str | None
    task_ids: list[str] = field(default_factory=list)

    def enqueue(self, agent_name, description, company_id):
        if company_id != self.company_id or not self.conversation_id or not self.source_message_id:
            raise PermissionError("task_context_missing")
        from app.agent import _resolve_registered_agent_key
        from app.agents import AGENT_REGISTRY
        from app.services.model_gateway import get_global_model_gateway

        name = _resolve_registered_agent_key(agent_name)
        if not name or not AGENT_REGISTRY.get(name, {}).get("active"):
            raise ValueError("task_agent_unavailable")
        description = str(description or "").strip()
        if not description or len(description) > 12000:
            raise ValueError("task_description_invalid")
        task_id = hashlib.sha256(json.dumps([
            self.company_id, self.user_id, self.source_message_id, name, description,
        ], ensure_ascii=False).encode()).hexdigest()
        with db.get_session() as session:
            _owner(session, self.company_id, self.user_id, self.conversation_id)
            source = session.query(Message.id).filter(
                Message.id == self.source_message_id, Message.conversation_id == self.conversation_id,
                Message.user_id == self.user_id, Message.role == "user",
            ).first()
            if source is None:
                raise PermissionError("task_source_message_invalid")
            existing = session.get(ConversationTask, task_id)
            if existing is None:
                count = session.query(ConversationTask).filter_by(source_message_id=self.source_message_id).count()
                if count >= MAX_TASKS_PER_MESSAGE:
                    raise ValueError("task_limit_exceeded")
                # Resolve at admission, not when a later preference has changed.
                model = get_global_model_gateway().get_llm(model_key=self.model_key, company_id=self.company_id)
                resolved = model.model_key
                if not isinstance(resolved, str) or not resolved:
                    raise ValueError("task_model_unresolved")
                now = datetime.utcnow()
                existing = ConversationTask(
                    id=task_id, company_id=self.company_id, user_id=self.user_id,
                    conversation_id=self.conversation_id, source_message_id=self.source_message_id,
                    agent_name=name, description=description, model_key=resolved,
                    status="pending", created_at=now, expires_at=now + timedelta(minutes=10),
                )
                session.add(existing)
                session.commit()
            state = existing.status
        if task_id not in self.task_ids:
            self.task_ids.append(task_id)
        return {"success": True, "task_id": task_id, "status": state, "queued": True}


def list_tasks(company_id, user_id, conversation_id):
    with db.get_session() as session:
        _owner(session, company_id, user_id, conversation_id)
        rows = session.query(ConversationTask).filter_by(
            company_id=company_id, user_id=user_id, conversation_id=conversation_id,
        ).order_by(ConversationTask.created_at.desc()).limit(50).all()
        now = datetime.utcnow()
        items = []
        for row in rows:
            state = row.status
            if state == "running" and row.started_at and row.started_at < now - timedelta(seconds=EXECUTION_SECONDS + 30):
                state = "interrupted"
            elif state == "pending" and row.expires_at <= now:
                state = "expired"
            items.append({"id": row.id, "conversation_id": row.conversation_id, "agent_name": row.agent_name,
                          "status": state, "result": row.result, "error_code": row.error_code,
                          "result_message_id": row.result_message_id})
        return items


def claim_task(task_id, company_id, user_id, conversation_id):
    with db.get_session() as session:
        _owner(session, company_id, user_id, conversation_id)
        now = datetime.utcnow()
        claimed = session.execute(update(ConversationTask).where(
            ConversationTask.id == task_id, ConversationTask.company_id == company_id,
            ConversationTask.user_id == user_id, ConversationTask.conversation_id == conversation_id,
            ConversationTask.status == "pending", ConversationTask.expires_at > now,
        ).values(status="running", started_at=now))
        if claimed.rowcount != 1:
            return None
        session.commit()
        row = session.get(ConversationTask, task_id)
        return {key: getattr(row, key) for key in (
            "id", "company_id", "user_id", "conversation_id", "agent_name", "description", "model_key",
        )}


def prepare_task_resume(task_id, company_id, user_id, conversation_id):
    """Return a resumable task, atomically recovering only stale running work."""
    with db.get_session() as session:
        _owner(session, company_id, user_id, conversation_id)
        now = datetime.utcnow()
        stale_before = now - timedelta(seconds=EXECUTION_SECONDS + 30)
        recovered = session.execute(update(ConversationTask).where(
            ConversationTask.id == task_id,
            ConversationTask.company_id == company_id,
            ConversationTask.user_id == user_id,
            ConversationTask.conversation_id == conversation_id,
            ConversationTask.status == "running",
            ConversationTask.started_at < stale_before,
            ConversationTask.expires_at > now,
        ).values(status="pending", started_at=None, error_code=None))
        if recovered.rowcount:
            session.commit()

        row = session.query(ConversationTask).filter_by(
            id=task_id,
            company_id=company_id,
            user_id=user_id,
            conversation_id=conversation_id,
        ).first()
        if row is None:
            return None
        if row.expires_at <= now:
            if row.status == "pending":
                row.status = "expired"
                session.commit()
            return None
        return row.id if row.status == "pending" else None


def finish_task(task, status, result=None, error_code=None):
    """Terminal status + result message commit together; a second finish is a no-op."""
    if status not in {"completed", "failed", "timeout", "blocked"}:
        raise ValueError("task_status_invalid")
    if status == "completed" and (not isinstance(result, str) or not result.strip()):
        raise ValueError("task_result_incomplete")
    with db.get_session() as session:
        conv = _owner(session, task["company_id"], task["user_id"], task["conversation_id"])
        changed = session.execute(update(ConversationTask).where(
            ConversationTask.id == task["id"], ConversationTask.company_id == task["company_id"],
            ConversationTask.user_id == task["user_id"], ConversationTask.conversation_id == task["conversation_id"],
            ConversationTask.status == "running",
        ).values(status=status, result=result, error_code=error_code, completed_at=datetime.utcnow()))
        if changed.rowcount != 1:
            return False
        if status == "completed":
            sequence = (session.query(func.max(Message.sequence_num)).filter_by(conversation_id=conv.id).scalar() or 0) + 1
            message = Message(conversation_id=conv.id, role="assistant", content=result,
                              content_type="text", sequence_num=sequence,
                              metadata_json=json.dumps({"conversation_task_id": task["id"], "readonly": True}))
            session.add(message)
            session.flush()
            session.execute(update(ConversationTask).where(ConversationTask.id == task["id"]).values(result_message_id=message.id))
            conv.message_count = session.query(Message).filter_by(conversation_id=conv.id).count()
            conv.last_message = result[:500]
            conv.updated_at = datetime.utcnow()
        session.commit()
        return True


async def run_task(task_id, company_id, user_id, conversation_id, executor=None, timeout=EXECUTION_SECONDS):
    from app.services.conversation_task_executor import execute_readonly_task

    async with _capacity:
        task = await asyncio.to_thread(claim_task, task_id, company_id, user_id, conversation_id)
        if task is None:
            return False
        result, code = None, None
        try:
            result = await asyncio.wait_for((executor or execute_readonly_task)(task), timeout=timeout)
            if not isinstance(result, str) or not result.strip():
                raise ValueError("task_result_incomplete")
            status = "completed"
        except TimeoutError:
            status, code = "timeout", "task_timeout"
        except PermissionError:
            status, code = "blocked", "task_tool_not_approved"
        except asyncio.CancelledError:
            await asyncio.to_thread(finish_task, task, "failed", None, "task_interrupted")
            raise
        except Exception:
            # Do not persist provider exception text: it may contain credentials.
            status, code = "failed", "task_execution_failed"
        changed = await asyncio.to_thread(finish_task, task, status, result if status == "completed" else None, code)
        if changed:
            try:
                from app.ws import ws_manager
                await ws_manager.send_to_user(str(user_id), {
                    "type": "task_status", "taskId": task_id, "conversation_id": conversation_id,
                    "status": status, "agent": task["agent_name"],
                })
            except Exception:
                pass  # Durable polling is the source of truth, not this hint.
        return changed


async def run_admitted_tasks(context):
    for task_id in list(context.task_ids):
        try:
            await run_task(task_id, context.company_id, context.user_id, context.conversation_id)
        except Exception:
            # Pending rows survive interruption; never switch to a legacy queue.
            continue

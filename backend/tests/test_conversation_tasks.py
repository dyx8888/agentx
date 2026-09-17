"""Synthetic, local-only tests for the durable conversation task path."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Company, Conversation, ConversationTask, Message, User
from app.services import conversation_task_executor as executor_module
from app.services import conversation_tasks as task_module


@pytest.fixture
def harness(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def get_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    db = SimpleNamespace(get_session=get_session)
    monkeypatch.setattr(task_module, "db", db)
    monkeypatch.setattr(executor_module, "db", db)
    with get_session() as session:
        session.add_all([
            Company(id=65, name="fixture", brand_name="fixture", category="test", platforms_json="[]"),
            Company(id=66, name="other", brand_name="other", category="test", platforms_json="[]"),
            User(id=7, username="fixture-user", password_hash="test", company_id=65, disabled=False, is_active=True),
            User(id=8, username="other-user", password_hash="test", company_id=66, disabled=False, is_active=True),
            Conversation(id=11, user_id=7, company_id=65, title="fixture", status="active", message_count=1),
            Message(id=13, conversation_id=11, user_id=7, role="user", content="analyze fixture", content_type="text", sequence_num=1),
        ])
        session.commit()

    resolved = SimpleNamespace(model_key="resolved-custom")
    gateway = SimpleNamespace(get_llm=lambda **kwargs: resolved)
    monkeypatch.setattr("app.services.model_gateway.get_global_model_gateway", lambda: gateway)
    context = task_module.TaskContext(company_id=65, user_id=7, conversation_id=11, source_message_id=13, model_key="custom-provider")
    return SimpleNamespace(session=get_session, context=context)


def test_enqueue_persists_owner_conversation_and_resolved_model_once(harness):
    first = harness.context.enqueue("brand_bd", "read company evidence", 65)
    second = harness.context.enqueue("brand_bd", "read company evidence", 65)
    assert first == second and harness.context.task_ids == [first["task_id"]]
    with harness.session() as session:
        row = session.get(ConversationTask, first["task_id"])
        assert (row.company_id, row.user_id, row.conversation_id, row.source_message_id) == (65, 7, 11, 13)
        assert row.model_key == "resolved-custom"


@pytest.mark.parametrize("changed", [{"company_id": 66}, {"user_id": 8}, {"conversation_id": 999}, {"source_message_id": 999}])
def test_enqueue_rejects_cross_owner_or_invalid_source(harness, changed):
    for key, value in changed.items():
        setattr(harness.context, key, value)
    with pytest.raises(PermissionError):
        harness.context.enqueue("brand_bd", "read company evidence", harness.context.company_id)


def test_atomic_claim_allows_only_one_executor(harness):
    task_id = harness.context.enqueue("brand_bd", "read company evidence", 65)["task_id"]
    assert task_module.claim_task(task_id, 65, 7, 11)
    assert task_module.claim_task(task_id, 65, 7, 11) is None


def test_expired_task_is_not_claimed(harness):
    task_id = harness.context.enqueue("brand_bd", "read company evidence", 65)["task_id"]
    with harness.session() as session:
        session.query(ConversationTask).filter_by(id=task_id).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
        session.commit()
    assert task_module.claim_task(task_id, 65, 7, 11) is None
    assert task_module.list_tasks(65, 7, 11)[0]["status"] == "expired"


def test_stale_running_task_can_be_recovered_once(harness):
    task_id = harness.context.enqueue("brand_bd", "read company evidence", 65)["task_id"]
    assert task_module.claim_task(task_id, 65, 7, 11)
    with harness.session() as session:
        session.query(ConversationTask).filter_by(id=task_id).update({
            "started_at": datetime.utcnow() - timedelta(seconds=task_module.EXECUTION_SECONDS + 31),
        })
        session.commit()

    assert task_module.list_tasks(65, 7, 11)[0]["status"] == "interrupted"
    assert task_module.prepare_task_resume(task_id, 65, 7, 11) == task_id
    assert task_module.prepare_task_resume(task_id, 65, 7, 11) == task_id
    assert task_module.claim_task(task_id, 65, 7, 11)
    assert task_module.claim_task(task_id, 65, 7, 11) is None


def test_fresh_running_or_expired_task_cannot_be_resumed(harness):
    running_id = harness.context.enqueue("brand_bd", "read running evidence", 65)["task_id"]
    assert task_module.claim_task(running_id, 65, 7, 11)
    assert task_module.prepare_task_resume(running_id, 65, 7, 11) is None

    expired_id = harness.context.enqueue("brand_bd", "read expired evidence", 65)["task_id"]
    with harness.session() as session:
        session.query(ConversationTask).filter_by(id=expired_id).update({
            "expires_at": datetime.utcnow() - timedelta(seconds=1),
        })
        session.commit()
    assert task_module.prepare_task_resume(expired_id, 65, 7, 11) is None
    assert task_module.list_tasks(65, 7, 11)[0]["status"] == "expired"


def test_resume_rejects_cross_owner(harness):
    task_id = harness.context.enqueue("brand_bd", "read company evidence", 65)["task_id"]
    with pytest.raises(PermissionError):
        task_module.prepare_task_resume(task_id, 66, 8, 11)


def test_finish_is_atomic_and_writes_one_assistant_message(harness):
    task_id = harness.context.enqueue("brand_bd", "read company evidence", 65)["task_id"]
    task = task_module.claim_task(task_id, 65, 7, 11)
    assert task_module.finish_task(task, "completed", "grounded fixture result")
    assert task_module.finish_task(task, "completed", "duplicate") is False
    with harness.session() as session:
        row = session.get(ConversationTask, task_id)
        messages = session.query(Message).filter_by(conversation_id=11, role="assistant").all()
        assert row.status == "completed" and row.result_message_id == messages[0].id
        assert [message.content for message in messages] == ["grounded fixture result"]


@pytest.mark.asyncio
async def test_run_task_returns_result_to_conversation_and_empty_result_fails(harness):
    first = harness.context.enqueue("brand_bd", "read first evidence", 65)["task_id"]
    assert await task_module.run_task(first, 65, 7, 11, executor=AsyncMock(return_value="answer"))
    second = harness.context.enqueue("brand_bd", "read second evidence", 65)["task_id"]
    assert await task_module.run_task(second, 65, 7, 11, executor=AsyncMock(return_value=""))
    states = {row["id"]: row for row in task_module.list_tasks(65, 7, 11)}
    assert states[first]["status"] == "completed" and states[second]["status"] == "failed"
    assert states[second]["error_code"] == "task_execution_failed"


@pytest.mark.asyncio
async def test_unapproved_model_tool_is_blocked_before_invocation(harness, monkeypatch):
    model = SimpleNamespace()
    model.bind_tools = lambda tools: model
    model.ainvoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[{"name": "send_message", "args": {}, "id": "unsafe"}]))
    monkeypatch.setattr("app.services.model_gateway.get_global_model_gateway", lambda: SimpleNamespace(get_llm=lambda **kwargs: model))
    task = {"company_id": 65, "user_id": 7, "conversation_id": 11, "agent_name": "brand_bd", "description": "analyze fixture", "model_key": "resolved-custom"}
    with pytest.raises(PermissionError, match="task_tool_not_approved"):
        await executor_module.execute_readonly_task(task)


def test_list_tasks_rejects_other_user_and_company(harness):
    harness.context.enqueue("brand_bd", "read evidence", 65)
    with pytest.raises(PermissionError):
        task_module.list_tasks(65, 8, 11)
    with pytest.raises(PermissionError):
        task_module.list_tasks(66, 7, 11)

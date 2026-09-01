from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import chat
from app.auth import get_current_active_user
from app.main import app
from app.perception.context_package import ContextPackage


class _FakePipeline:
    async def build_context_package(self, **kwargs):
        return ContextPackage(
            rewritten_query=kwargs["raw_input"],
            raw_input=kwargs["raw_input"],
            intent_type="general",
            company_id=kwargs["company_id"],
            memory_context=[],
            similar_answers=[],
        )


class _FakeRouter:
    async def execute(self, _context_package):
        yield {"type": "result", "data": "ok"}
        yield {"type": "done"}


class _DummySession:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


class _DummyDB:
    def get_session(self):
        return _DummySession()


def _install_chat_fakes(monkeypatch):
    import app.database as database_module
    import app.services.message_persistence as persistence_module

    monkeypatch.setattr(chat, "_get_perception_pipeline", lambda: _FakePipeline())
    monkeypatch.setattr(chat, "_get_master_router", lambda: _FakeRouter())
    monkeypatch.setattr(chat, "_build_company_context_from_db", lambda _company_id: {})
    monkeypatch.setattr(chat, "_persist_assistant_reply", lambda **_kwargs: None)
    monkeypatch.setattr(database_module, "db", _DummyDB())
    monkeypatch.setattr(
        persistence_module,
        "get_or_create_conversation",
        lambda **_kwargs: SimpleNamespace(id=123, message_count=0),
    )
    monkeypatch.setattr(persistence_module, "save_user_message", lambda **_kwargs: None)


def _current_user():
    return SimpleNamespace(id=7, company_id=65, is_active=True, disabled=False)


def _post_chat(monkeypatch, path):
    _install_chat_fakes(monkeypatch)
    app.dependency_overrides[get_current_active_user] = _current_user
    client = TestClient(app)
    try:
        return client.post(path, json={"message": "hello"})
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        client.close()


def test_chat_accepts_no_trailing_slash(monkeypatch):
    response = _post_chat(monkeypatch, "/api/chat")

    assert response.status_code == 200
    assert "ok" in response.text


def test_chat_accepts_trailing_slash(monkeypatch):
    response = _post_chat(monkeypatch, "/api/chat/")

    assert response.status_code == 200
    assert "ok" in response.text

import asyncio
from types import SimpleNamespace

from fastapi import WebSocketDisconnect

import app.ws as ws_api


class FakeWebSocket:
    def __init__(self):
        self.query_params = {}
        self.cookies = {}
        self.accepted = False
        self.closed = None
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.closed = {"code": code, "reason": reason}

    async def receive_text(self):
        raise WebSocketDisconnect()

    async def send_json(self, payload):
        self.sent.append(payload)


def _user(*, user_id=7, company_id=42):
    return SimpleNamespace(id=user_id, company_id=company_id, username=f"user-{user_id}", disabled=False)


def test_connect_websocket_rejects_unauthenticated_user(monkeypatch):
    monkeypatch.setattr(ws_api, "_authenticate_ws", lambda _websocket: None)
    websocket = FakeWebSocket()

    asyncio.run(ws_api.websocket_endpoint(websocket, company_id=42))

    assert websocket.accepted is False
    assert websocket.closed == {"code": 4001, "reason": "Unauthorized"}


def test_connect_websocket_rejects_company_mismatch(monkeypatch):
    monkeypatch.setattr(ws_api, "_authenticate_ws", lambda _websocket: _user(company_id=99))
    websocket = FakeWebSocket()

    asyncio.run(ws_api.websocket_endpoint(websocket, company_id=42))

    assert websocket.accepted is False
    assert websocket.closed == {"code": 4001, "reason": "Unauthorized"}


def test_connect_websocket_allows_matching_company(monkeypatch):
    calls = []

    class FakeManager:
        async def connect(self, websocket, company_id, user_id=None):
            await websocket.accept()
            calls.append(("connect", company_id, user_id))

        async def disconnect(self, websocket, company_id, user_id=None):
            calls.append(("disconnect", company_id, user_id))

    monkeypatch.setattr(ws_api, "_authenticate_ws", lambda _websocket: _user(user_id=8, company_id=42))
    monkeypatch.setattr(ws_api, "ws_manager", FakeManager())
    websocket = FakeWebSocket()

    asyncio.run(ws_api.websocket_endpoint(websocket, company_id=42))

    assert websocket.accepted is True
    assert calls == [("connect", 42, "8"), ("disconnect", 42, "8")]
    assert websocket.closed is None


def test_task_status_websocket_rejects_unauthenticated_user(monkeypatch):
    monkeypatch.setattr(ws_api, "_authenticate_ws", lambda _websocket: None)
    websocket = FakeWebSocket()

    asyncio.run(ws_api.task_status_websocket(websocket, task_id=123))

    assert websocket.accepted is False
    assert websocket.closed == {"code": 4001, "reason": "Unauthorized"}


def test_legacy_chat_websocket_rejects_unauthenticated_user(monkeypatch):
    monkeypatch.setattr(ws_api, "_authenticate_ws", lambda _websocket: None)
    websocket = FakeWebSocket()

    asyncio.run(ws_api.chat_websocket(websocket, agent_name="brand_bd"))

    assert websocket.accepted is False
    assert websocket.closed == {"code": 4001, "reason": "Unauthorized"}

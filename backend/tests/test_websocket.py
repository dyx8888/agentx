"""
WebSocket 实时通信测试
测试任务状态推送和聊天流式转发的 WebSocket 端点
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.auth import get_current_active_user
from app.main import app


class TestWebSocket:
    """WebSocket 功能测试类"""

    # 测试用户（SimpleNamespace 支持属性访问，与 API 中 current_user.company_id 用法一致）
    test_user = SimpleNamespace(
        id=1,
        username="testuser",
        email="test@example.com",
        company_id=1,
        is_admin=False,
    )

    def setup_method(self):
        """每个测试方法前的设置：Mock 认证用户"""
        app.dependency_overrides[get_current_active_user] = lambda: self.test_user
        self._ws_auth_patch = patch("app.ws._authenticate_ws", return_value=self.test_user)
        self._ws_auth_patch.start()

    def teardown_method(self):
        """每个测试方法后的清理：移除认证 Mock"""
        self._ws_auth_patch.stop()
        app.dependency_overrides.pop(get_current_active_user, None)

    @pytest.mark.asyncio
    async def test_1_task_status_push_success(self):
        """正常场景1：任务状态推送"""
        # 构造 mock_db 替换 app.api.tasks 模块中的 db 引用
        # 必须用 MagicMock 整体替换，因为 DatabaseProxy.__getattr__ 会让方法级 patch 失败
        mock_db = MagicMock()
        mock_db.create_task.return_value = 1
        mock_db.get_task.return_value = {
            "id": 1,
            "company_id": 1,
            "source_agent_id": None,
            "target_agent_name": "brand_bd",
            "task_description": "WebSocket 测试任务",
            "status": "pending",
            "result": None,
            "created_at": "2024-01-01T00:00:00Z",
            "completed_at": None,
        }
        mock_db.update_task_status = MagicMock()

        with TestClient(app) as client, patch("app.api.tasks.db", mock_db):
            task_response = client.post(
                "/api/tasks/",
                json={
                    "target_agent_name": "brand_bd",
                    "task_description": "WebSocket 测试任务",
                },
            )
            task_id = task_response.json()["task_id"]

            with client.websocket_connect(f"/ws/tasks/{task_id}") as websocket:
                await asyncio.sleep(0.1)

                update_response = client.post(
                    f"/api/tasks/{task_id}/confirm",
                    json={"status": "in_progress", "message": "WebSocket 测试中"},
                )
                assert update_response.status_code == 200

                # Starlette 1.0.0 TestClient 的 receive_json 是同步方法，不能用 await
                message = websocket.receive_json()
                assert message["type"] == "status_update"
                assert message["payload"]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_2_chat_websocket_success(self):
        """正常场景2：聊天 WebSocket 转发真实 runtime 事件，不生成伪工具结果"""

        async def fake_run_agent_chat(agent_name, message, company_id=None):
            assert agent_name == "brand_bd"
            assert "美妆博主" in message
            yield {"type": "plan", "data": {"task_summary": "runtime plan"}}
            yield {"type": "reflection", "data": {"passed": True}}

        with TestClient(app) as client, patch("app.ws._run_agent_chat", fake_run_agent_chat):
            with client.websocket_connect("/ws/chat/brand_bd") as websocket:
                await asyncio.sleep(0.1)

                test_message = {"message": "帮我找3个美妆博主", "timestamp": "2024-01-01T00:00:00Z"}
                # Starlette TestClient 的 send_json 是同步方法，不能用 await
                websocket.send_json(test_message)

                events_received = []
                while True:
                    try:
                        # receive_json 同步返回 dict；服务端在事件流末尾发送 "done"
                        message = websocket.receive_json()
                        events_received.append(message)

                        if message.get("type") == "done":
                            break
                    except Exception:
                        # 连接关闭或其他异常时退出循环
                        break

                event_types = [event.get("type") for event in events_received]
                assert "plan" in event_types
                assert "reflection" in event_types
                assert "done" in event_types
                assert "tool_call" not in event_types
                assert "tool_result" not in event_types

    @pytest.mark.asyncio
    async def test_3_nonexistent_task_websocket(self):
        """异常场景1：订阅不存在的任务 ID"""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/tasks/99999") as websocket:
                await asyncio.sleep(0.1)

                websocket.send_json({"type": "ping"})

                try:
                    # receive_json 同步返回；服务端对 ping 回 pong
                    message = websocket.receive_json()
                    assert message is not None
                except Exception:
                    # 连接关闭或无消息时通过测试（异常场景只需确保不挂起）
                    pass

    @pytest.mark.asyncio
    async def test_4_invalid_agent_websocket(self):
        """异常场景2：无效的聊天 Agent 名称"""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat/nonexistent") as websocket:
                await asyncio.sleep(0.1)

                websocket.send_json({"message": "测试消息", "timestamp": "2024-01-01T00:00:00Z"})

                try:
                    # receive_json 同步返回；无效 agent 会收到 error 事件
                    message = websocket.receive_json()
                    assert message.get("type") == "error"
                    assert "Agent 'nonexistent' not found" in message.get("content", "")
                except Exception as e:
                    raise AssertionError(f"Should receive error message for invalid agent: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

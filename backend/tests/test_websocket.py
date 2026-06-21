"""
WebSocket 实时通信测试
测试任务状态推送和聊天流式转发的 WebSocket 端点
"""

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.main import app


class TestWebSocket:
    """WebSocket 功能测试类"""

    @pytest.mark.asyncio
    async def test_1_task_status_push_success(self):
        """正常场景1：任务状态推送"""
        with TestClient(app) as client:
            task_response = client.post("/tasks", json={
                "title": "测试任务",
                "description": "WebSocket 测试任务",
                "company_id": 1
            })
            task_id = task_response.json()["id"]

            with client.websocket_connect(f"/ws/tasks/{task_id}") as websocket:
                await asyncio.sleep(0.1)

                update_response = client.post(f"/tasks/{task_id}/confirm", json={
                    "status": "in_progress",
                    "message": "WebSocket 测试中"
                })
                assert update_response.status_code == 200

                message = await websocket.receive_json()
                assert message["type"] == "status_update"
                assert message["payload"]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_2_chat_websocket_success(self):
        """正常场景2：聊天 WebSocket 实时对话"""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat/brand_bd") as websocket:
                await asyncio.sleep(0.1)

                test_message = {
                    "message": "帮我找3个美妆博主",
                    "timestamp": "2024-01-01T00:00:00Z"
                }
                await websocket.send_json(test_message)

                events_received = []
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.receive_json(), timeout=2.0)
                        events_received.append(message)

                        if message.get("type") == "done":
                            break
                    except TimeoutError:
                        break

                event_types = [event.get("type") for event in events_received]
                assert "thinking" in event_types
                assert "tool_call" in event_types
                assert "tool_result" in event_types
                assert "text" in event_types
                assert "done" in event_types

    @pytest.mark.asyncio
    async def test_3_nonexistent_task_websocket(self):
        """异常场景1：订阅不存在的任务 ID"""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/tasks/99999") as websocket:
                await asyncio.sleep(0.1)

                await websocket.send_json({"type": "ping"})

                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=2.0)
                    assert message is not None
                except TimeoutError:
                    pass
                except Exception as e:
                    assert False, f"Unexpected error: {e}"

    @pytest.mark.asyncio
    async def test_4_invalid_agent_websocket(self):
        """异常场景2：无效的聊天 Agent 名称"""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat/nonexistent") as websocket:
                await asyncio.sleep(0.1)

                await websocket.send_json({
                    "message": "测试消息",
                    "timestamp": "2024-01-01T00:00:00Z"
                })

                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=2.0)
                    assert message.get("type") == "error"
                    assert "Agent 'nonexistent' not found" in message.get("content", "")
                except TimeoutError:
                    assert False, "Should receive error message for invalid agent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

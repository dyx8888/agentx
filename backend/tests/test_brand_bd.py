import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _parse_sse_events(events: list[str]) -> list[dict]:
    """解析 SSE 事件流为 dict 列表"""
    parsed = []
    for event in events:
        if event.startswith("data: "):
            try:
                parsed.append(json.loads(event[6:]))
            except json.JSONDecodeError:
                parsed.append({"raw": event})
        elif event.startswith("event: "):
            parsed.append({"event_type": event[7:]})
    return parsed


def test_brand_bd_search_kols():
    """正常场景1：请求 agent_name="brand_bd"，发送"帮我找3个美妆博主"，预期响应 200 且流中出现 tool_call 事件。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "帮我找3个美妆博主",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        tool_calls = [e for e in events if 'tool_call' in e]
        assert len(tool_calls) > 0

        parsed = _parse_sse_events(events)
        assert len(parsed) > 0, "Should have at least one parseable SSE event"


def test_brand_bd_generate_outreach():
    """正常场景2：发送"为 LisaBeauty 生成一份邀约话术"，预期出现 generate_outreach 调用。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "为 LisaBeauty 生成一份邀约话术",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        outreach_calls = [e for e in events if 'generate_outreach' in e]
        assert len(outreach_calls) > 0

        parsed = _parse_sse_events(events)
        non_raw = [p for p in parsed if 'raw' not in p]
        assert len(non_raw) > 0, "Should have structured events in SSE stream"


def test_brand_bd_check_delivery():
    """正常场景3：发送"查询订单 ORD001 的物流状态"，预期出现 check_delivery_status 调用。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "查询订单 ORD001 的物流状态",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        delivery_calls = [e for e in events if 'check_delivery_status' in e]
        assert len(delivery_calls) > 0


def test_brand_bd_generate_script():
    """正常场景4：发送"为 BeautyQueen 生成直播间脚本"，预期出现 generate_script 调用。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "为 BeautyQueen 生成直播间脚本",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        script_calls = [e for e in events if 'generate_script' in e]
        assert len(script_calls) > 0


def test_brand_bd_performance_report():
    """正常场景5：发送"生成本月达人带货表现报告"，预期出现 performance_report 调用。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "生成本月达人带货表现报告",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        report_calls = [e for e in events if 'performance_report' in e or 'generate_performance_report' in e]
        assert len(report_calls) > 0


def test_brand_bd_invalid_agent_name():
    """异常场景1：传入不存在的 agent_name，预期返回错误信息。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "帮我找一些KOL",
        "agent_name": "nonexistent_agent"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        error_events = [e for e in events if 'error' in e]
        assert len(error_events) > 0


def test_brand_bd_missing_message():
    """异常场景2：请求体缺少 message 字段，预期返回 422 校验错误。"""
    response = client.post("/chat/chat/", json={
        "agent_name": "brand_bd"
    })
    assert response.status_code == 422


def test_brand_bd_missing_agent_name():
    """异常场景3：请求体缺少 agent_name 字段，预期返回 422 校验错误。"""
    response = client.post("/chat/chat/", json={
        "message": "帮我找一些KOL"
    })
    assert response.status_code == 422


def test_brand_bd_empty_message():
    """异常场景4：发送空消息，预期仍正常响应 200。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        assert len(events) > 0


def test_content_operation_generate_script():
    """正常场景6：内容运营 agent 生成短视频脚本。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "为美妆产品生成一个15秒短视频脚本",
        "agent_name": "content_operation"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        assert len(events) > 0


def test_customer_service_reply():
    """正常场景7：客服 agent 回复客户咨询。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "客户问：这个口红是什么色号？",
        "agent_name": "customer_service"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        assert len(events) > 0


def test_data_analysis_query():
    """正常场景8：数据分析 agent 执行数据查询。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "分析本月销售额趋势",
        "agent_name": "data_analysis"
    }) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]
        assert len(events) > 0


def test_conversation_stateless_behavior():
    """正常场景9：连续两次请求，验证无状态会话行为。"""
    with client.stream("POST", "/chat/chat/", json={
        "message": "帮我找3个美妆博主",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events_1 = [line for line in response.iter_lines() if line]

    with client.stream("POST", "/chat/chat/", json={
        "message": "再帮我找3个穿搭博主",
        "agent_name": "brand_bd"
    }) as response:
        assert response.status_code == 200
        events_2 = [line for line in response.iter_lines() if line]

    assert len(events_1) > 0
    assert len(events_2) > 0

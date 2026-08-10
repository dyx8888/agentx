import json

import requests

url = "http://localhost:8000/chat/chat/"
payload = {
    "message": "帮我找3个美妆博主",
    "agent_name": "brand_bd"
}

print("正在测试品牌商务 Agent...\n")

try:
    # 流式发送请求
    with requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        stream=True,
        timeout=60
    ) as response:
        print(f"状态码: {response.status_code}\n")

        # 分块读取响应内容
        buffer = ""
        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                buffer += chunk
                # 处理完整的行
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()

                    if not line:
                        continue

                    # 兼容带或不带 "data: " 前缀的 SSE 格式
                    if line.startswith('data: '):
                        line = line[6:]

                    try:
                        data = json.loads(line)
                        event_type = data.get('type', 'unknown')

                        if event_type == "tool_call":
                            print(f"🔧 调用工具: {data.get('tool', '')}")
                        elif event_type == "tool_result":
                            tool_name = data.get('tool', '')
                            result = str(data.get('result', ''))
                            preview = result[:150] + "..." if len(result) > 150 else result
                            print(f"📋 工具结果 [{tool_name}]: {preview}")
                        elif event_type == "text":
                            print(f"💬 {data.get('content', '')}")
                        elif event_type == "done":
                            print("✅ 任务完成")
                        elif event_type == "error":
                            print(f"❌ 错误: {data.get('content', '')}")
                        else:
                            print(f"📌 {data}")
                    except (json.JSONDecodeError, KeyError):
                        print(f"📝 原始数据: {line[:100]}")

except requests.exceptions.ConnectionError:
    print("❌ 连接失败，请确认后端服务已启动（python -m app.main）")
except requests.exceptions.Timeout:
    print("❌ 请求超时，Agent 可能处理时间过长")
except Exception as e:
    print(f"❌ 发生异常: {type(e).__name__}: {e}")

print("\n测试结束")

"""
Test script for FastAPI streaming chat interface
"""

import json

import requests


def test_streaming_chat():
    """Test the streaming chat API"""
    try:
        response = requests.post(
            "http://localhost:8000/chat/",
            json={"message": "帮我找3个美妆护肤博主"},
            headers={"Content-Type": "application/json"},
            stream=True
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            print("Streaming Response:")
            print("-" * 50)

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        try:
                            data = json.loads(decoded_line[6:])
                            event_type = data.get('type', 'unknown')

                            if event_type == 'thinking':
                                print(f"🤔 Thinking: {data.get('content', '')}")
                            elif event_type == 'tool_call':
                                print(f"🔧 Tool Call: {data.get('tool', '')} with args: {data.get('args', {})}")
                            elif event_type == 'tool_result':
                                print(f"📋 Tool Result: {data.get('tool', '')} - {len(str(data.get('result', '')))} chars")
                            elif event_type == 'text':
                                print(f"💬 Text: {data.get('content', '')}")
                            elif event_type == 'done':
                                print("✅ Done!")
                                break
                            elif event_type == 'error':
                                print(f"❌ Error: {data.get('content', '')}")
                                break
                            else:
                                print(f"❓ Unknown: {data}")

                        except json.JSONDecodeError:
                            print(f"Raw line: {decoded_line}")

            print("-" * 50)
            return True
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"Test failed: {e}")
        return False

def test_health_check():
    """Test health check endpoint"""
    try:
        response = requests.get("http://localhost:8000/health")
        print(f"Health Check: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

if __name__ == "__main__":
    print("=== Testing AgentX FastAPI Streaming Chat ===\n")

    print("1. Testing Health Check...")
    health_ok = test_health_check()
    print()

    print("2. Testing Streaming Chat...")
    chat_ok = test_streaming_chat()
    print()

    print("=== Results ===")
    print(f"Health Check: {'PASS' if health_ok else 'FAIL'}")
    print(f"Streaming Chat: {'PASS' if chat_ok else 'FAIL'}")

    if health_ok and chat_ok:
        print("\n✅ All tests PASSED! The FastAPI streaming chat interface is working correctly.")
    else:
        print("\n❌ Some tests FAILED. Please check the backend server.")

"""
Test script for the complete web application
"""

import json

import requests


def test_backend_health():
    """Test backend health check"""
    try:
        response = requests.get("http://localhost:8000/health")
        print(f"Health check: {response.status_code} - {response.json()}")
        return True
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

def test_chat_api():
    """Test the chat streaming API"""
    try:
        response = requests.post(
            "http://localhost:8000/chat/",
            json={"message": "Hello, can you help me find some beauty influencers?"},
            headers={"Content-Type": "application/json"},
            stream=True
        )

        print(f"Chat API status: {response.status_code}")

        if response.status_code == 200:
            print("Streaming response:")
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        try:
                            data = json.loads(decoded_line[6:])
                            print(f"  Event: {data['type']} - {data.get('content', '')}")
                        except json.JSONDecodeError:
                            print(f"  Raw: {decoded_line}")
            return True
        else:
            print(f"Error response: {response.text}")
            return False

    except Exception as e:
        print(f"Chat API test failed: {e}")
        return False

def test_feedback_api():
    """Test the feedback API"""
    try:
        response = requests.post(
            "http://localhost:8000/feedback/",
            json={
                "session_id": "test_session_001",
                "tool_name": "outreach_composer",
                "original_output": "Hello Emma Liu! I'm BeautyPro from GlowUp Cosmetics.",
                "human_edited_output": "Hello Emma Liu! I'm BeautyPro from GlowUp Cosmetics. I've been following your amazing content.",
                "kol_name": "Emma Liu",
                "product_name": "Vitamin C Serum"
            },
            headers={"Content-Type": "application/json"}
        )

        print(f"Feedback API status: {response.status_code} - {response.json()}")
        return response.status_code == 200

    except Exception as e:
        print(f"Feedback API test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=== Testing AgentX Web Application ===\n")

    print("1. Testing Backend Health...")
    health_ok = test_backend_health()
    print()

    print("2. Testing Chat API...")
    chat_ok = test_chat_api()
    print()

    print("3. Testing Feedback API...")
    feedback_ok = test_feedback_api()
    print()

    print("=== Test Results ===")
    print(f"Health Check: {'PASS' if health_ok else 'FAIL'}")
    print(f"Chat API: {'PASS' if chat_ok else 'FAIL'}")
    print(f"Feedback API: {'PASS' if feedback_ok else 'FAIL'}")

    if health_ok and chat_ok and feedback_ok:
        print("\nAll tests PASSED! The web application is ready to use.")
    else:
        print("\nSome tests FAILED. Please check the backend server.")

if __name__ == "__main__":
    main()

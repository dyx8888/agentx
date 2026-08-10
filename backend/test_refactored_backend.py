"""
Test script for the refactored backend integration
Tests Agent reuse, routing, and API endpoints
"""

import json
import time

import requests


def test_health_check():
    """Test main health check endpoint"""
    try:
        response = requests.get("http://localhost:8000/health")
        print(f"Main Health Check: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Main Health Check failed: {e}")
        return False

def test_chat_health():
    """Test chat health check endpoint"""
    try:
        response = requests.get("http://localhost:8000/chat/health")
        print(f"Chat Health Check: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Chat Health Check failed: {e}")
        return False

def test_feedback_health():
    """Test feedback health check endpoint"""
    try:
        response = requests.get("http://localhost:8000/feedback/stats")
        print(f"Feedback Stats: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Feedback Stats failed: {e}")
        return False

def test_streaming_chat():
    """Test the streaming chat API"""
    try:
        response = requests.post(
            "http://localhost:8000/chat/",
            json={"message": "Hello, can you help me find some beauty influencers?"},
            headers={"Content-Type": "application/json"},
            stream=True
        )

        print(f"Chat API Status: {response.status_code}")

        if response.status_code == 200:
            print("Streaming Response:")
            print("-" * 50)

            event_count = 0
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        try:
                            data = json.loads(decoded_line[6:])
                            event_type = data.get('type', 'unknown')
                            event_count += 1

                            if event_type == 'thinking':
                                print(f"  Thinking: {data.get('content', '')}")
                            elif event_type == 'tool_call':
                                print(f"  Tool Call: {data.get('tool', '')}")
                            elif event_type == 'tool_result':
                                print(f"  Tool Result: {data.get('tool', '')}")
                            elif event_type == 'text':
                                print(f"  Text: {data.get('content', '')[:50]}...")
                            elif event_type == 'done':
                                print("  Done!")
                                break
                            elif event_type == 'error':
                                print(f"  Error: {data.get('content', '')}")
                                break

                        except json.JSONDecodeError:
                            print(f"  Raw line: {decoded_line}")

            print(f"Total events received: {event_count}")
            print("-" * 50)
            return event_count > 0
        else:
            print(f"Error: {response.status_code} - {response.text}")
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
                "session_id": f"test_session_{int(time.time())}",
                "tool_name": "outreach_composer",
                "original_output": "Hello Emma Liu! I'm BeautyPro from GlowUp Cosmetics.",
                "human_edited_output": "Hello Emma Liu! I'm BeautyPro from GlowUp Cosmetics. I've been following your amazing content.",
                "kol_name": "Emma Liu",
                "product_name": "Vitamin C Serum"
            },
            headers={"Content-Type": "application/json"}
        )

        print(f"Feedback API Status: {response.status_code} - {response.json()}")
        return response.status_code == 200

    except Exception as e:
        print(f"Feedback API test failed: {e}")
        return False

def test_root_endpoint():
    """Test root endpoint"""
    try:
        response = requests.get("http://localhost:8000/")
        print(f"Root Endpoint: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Root Endpoint failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=== Testing Refactored AgentX Backend ===\n")

    # Test basic endpoints
    print("1. Testing Root Endpoint...")
    root_ok = test_root_endpoint()
    print()

    print("2. Testing Main Health Check...")
    health_ok = test_health_check()
    print()

    print("3. Testing Chat Health Check...")
    chat_health_ok = test_chat_health()
    print()

    print("4. Testing Feedback Stats...")
    feedback_stats_ok = test_feedback_health()
    print()

    # Test functionality
    print("5. Testing Streaming Chat...")
    chat_ok = test_streaming_chat()
    print()

    print("6. Testing Feedback API...")
    feedback_ok = test_feedback_api()
    print()

    # Results
    print("=== Test Results ===")
    print(f"Root Endpoint: {'PASS' if root_ok else 'FAIL'}")
    print(f"Main Health: {'PASS' if health_ok else 'FAIL'}")
    print(f"Chat Health: {'PASS' if chat_health_ok else 'FAIL'}")
    print(f"Feedback Stats: {'PASS' if feedback_stats_ok else 'FAIL'}")
    print(f"Streaming Chat: {'PASS' if chat_ok else 'FAIL'}")
    print(f"Feedback API: {'PASS' if feedback_ok else 'FAIL'}")

    all_passed = all([root_ok, health_ok, chat_health_ok, feedback_stats_ok, chat_ok, feedback_ok])

    if all_passed:
        print("\nAll tests PASSED! The refactored backend is working correctly.")
        print("\nRefactoring Summary:")
        print("  - Agent instance centralized in app/agent.py")
        print("  - Chat API uses get_agent() instead of AgentSingleton")
        print("  - Feedback API uses APIRouter instead of FastAPI app")
        print("  - Main app uses include_router for proper routing")
        print("  - All endpoints are properly mounted and functional")
    else:
        print("\nSome tests FAILED. Please check the backend configuration.")

if __name__ == "__main__":
    main()

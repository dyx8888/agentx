#!/usr/bin/env python3
"""Simple chat test to isolate the issue"""


import requests

url = "http://localhost:8000/chat/chat/"
payload = {
    "message": "你好",
    "agent_name": "brand_bd"
}

print("Testing simple chat request...")

try:
    # Make a simple request without streaming
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )

    print(f"Status code: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")

    if response.status_code == 200:
        print("✅ Request successful")
        print(f"Response content type: {type(response.text)}")
        print(f"Response content preview: {response.text[:500]}...")
    else:
        print(f"❌ Request failed with status: {response.status_code}")
        print(f"Response: {response.text}")

except requests.exceptions.ConnectionError:
    print("❌ Connection failed, server may not be running")
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")

print("Test completed")

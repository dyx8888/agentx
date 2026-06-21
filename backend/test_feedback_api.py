"""
Test script for feedback API
"""


import requests


def test_feedback_api():
    """Test the feedback API endpoint"""

    # Test data
    test_data = {
        "session_id": "test_session_001",
        "tool_name": "outreach_composer",
        "original_output": "Hi Emma Liu! I'm BeautyPro from GlowUp Cosmetics. We've been following your amazing content on Douyin and love your expertise in skincare. Our new Vitamin C Serum would be perfect for your audience. Would you be interested in a collaboration?",
        "human_edited_output": "Hi Emma Liu! I'm BeautyPro from GlowUp Cosmetics. I've been following your amazing skincare content on Douyin and I'm really impressed with your expertise! Our new Vitamin C Serum would be perfect for your audience - it delivers brightening and anti-aging benefits. Would you be interested in exploring a collaboration partnership?",
        "kol_name": "Emma Liu",
        "product_name": "Vitamin C Serum"
    }

    try:
        # Send POST request to feedback API
        response = requests.post(
            "http://localhost:8000/feedback/",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")

        if response.status_code == 200:
            print("SUCCESS: Feedback API test passed!")
        else:
            print(f"ERROR: Feedback API test failed with status {response.status_code}")

    except Exception as e:
        print(f"ERROR: Could not connect to feedback API: {e}")
        print("Make sure the API server is running with: python app/main.py")

if __name__ == "__main__":
    test_feedback_api()

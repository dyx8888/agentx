import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

FRONTEND_URL = "http://localhost:5173"


class TestP0ChatBrandBD:
    @pytest.mark.p0
    def test_navigate_to_brand_bd_chat_page(self, page):
        page.goto(f"{FRONTEND_URL}/agents/brand_bd/chat")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p0
    def test_send_message_and_receive_response(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/agents/brand_bd/chat")
        page.wait_for_timeout(2000)

        textarea = page.locator("textarea").first
        assert textarea.is_visible(), "Chat input textarea should be visible"

        textarea.fill("你好")
        send_button = page.locator("button").filter(has_text="发送").first
        assert send_button.is_enabled(), "Send button should be enabled after typing"

        send_button.click()

        page.wait_for_timeout(5000)

        messages = page.locator('[class*="ant-card"]').first
        assert messages.is_visible() or page.locator("text=思考中").is_visible(), \
            "Should see chat messages or thinking indicator"

    @pytest.mark.p0
    def test_empty_message_send_button_disabled(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/agents/brand_bd/chat")
        page.wait_for_timeout(2000)

        send_button = page.locator("button").filter(has_text="发送").first
        assert send_button.is_disabled(), "Send button should be disabled when input is empty"

        textarea = page.locator("textarea").first
        textarea.fill("你好")
        assert send_button.is_enabled(), "Send button should be enabled after typing"

        textarea.clear()
        assert send_button.is_disabled(), "Send button should be disabled after clearing input"
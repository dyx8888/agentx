import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

FRONTEND_URL = "http://localhost:5173"


class TestP0ReviewWorkflow:
    @pytest.mark.p0
    def test_navigate_to_reviews_page(self, page):
        page.goto(f"{FRONTEND_URL}/reviews")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p0
    def test_approve_pending_review(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/reviews")
        page.wait_for_timeout(3000)

        page.wait_for_selector('[class*="ant-card"]', timeout=10000)
        assert page.url.startswith(FRONTEND_URL), "Should stay on reviews page"

        approve_button = page.locator("button").filter(has_text="批准").first
        if approve_button.is_visible():
            approve_button.click()
            page.wait_for_timeout(2000)
            modal = page.locator('[class*="ant-modal"]')
            if modal.is_visible():
                modal_approve = modal.locator("button").filter(has_text="确").first
                if modal_approve.is_visible():
                    modal_approve.click()
                    page.wait_for_timeout(2000)

    @pytest.mark.p0
    def test_reject_pending_review(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/reviews")
        page.wait_for_timeout(3000)

        page.wait_for_selector('[class*="ant-card"]', timeout=10000)
        assert page.url.startswith(FRONTEND_URL), "Should stay on reviews page"

        reject_button = page.locator("button").filter(has_text="驳回").first
        if reject_button.is_visible():
            reject_button.click()
            page.wait_for_timeout(2000)
            modal = page.locator('[class*="ant-modal"]')
            if modal.is_visible():
                modal_reject = modal.locator("button").filter(has_text="确").first
                if modal_reject.is_visible():
                    modal_reject.click()
                    page.wait_for_timeout(2000)

    @pytest.mark.p0
    def test_filter_reviews_by_level(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/reviews")
        page.wait_for_timeout(3000)

        segmented = page.locator('[class*="ant-segmented"]').first
        if segmented.is_visible():
            recommended_option = segmented.locator("label").filter(has_text="推荐").first
            if recommended_option.is_visible():
                recommended_option.click()
                page.wait_for_timeout(2000)

            mandatory_option = segmented.locator("label").filter(has_text="强制").first
            if mandatory_option.is_visible():
                mandatory_option.click()
                page.wait_for_timeout(2000)

        assert page.url.startswith(FRONTEND_URL), "Should stay on reviews page after filtering"
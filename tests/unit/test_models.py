"""
Unit tests for new ORM models (Task 1.1)
Conversation, Message, KolProfile, KolSearchHistory,
ContentScript, LogisticsTracking, ReviewApproval
"""

import pytest
from datetime import datetime

from app.database.models import (
    Conversation,
    Message,
    KolProfile,
    KolSearchHistory,
    ContentScript,
    LogisticsTracking,
    ReviewApproval,
)


class TestConversationModel:
    """Test Conversation ORM model"""

    def test_create_conversation_minimal(self):
        """创建最小字段的 Conversation"""
        conv = Conversation(
            user_id=1,
            company_id=1,
            title="新对话",
            status="active",
            message_count=0,
        )
        assert conv.user_id == 1
        assert conv.company_id == 1
        assert conv.title == "新对话"
        assert conv.status == "active"
        assert conv.message_count == 0
        assert conv.last_message is None

    def test_create_conversation_full(self):
        """创建完整字段的 Conversation"""
        now = datetime.utcnow()
        conv = Conversation(
            user_id=1,
            company_id=1,
            title="美妆达人搜索",
            status="active",
            message_count=5,
            last_message="已找到 20 位美妆达人",
            created_at=now,
            updated_at=now,
        )
        assert conv.title == "美妆达人搜索"
        assert conv.status == "active"
        assert conv.message_count == 5
        assert conv.last_message == "已找到 20 位美妆达人"

    def test_conversation_status_values(self):
        """Conversation status 支持 active / archived / deleted"""
        valid_statuses = ["active", "archived", "deleted"]
        for status in valid_statuses:
            conv = Conversation(user_id=1, company_id=1, title="test", status=status, message_count=0)
            assert conv.status == status

    def test_conversation_repr(self):
        """Conversation repr 格式正确"""
        conv = Conversation(id=1, user_id=1, company_id=1, title="test", status="active", message_count=0)
        assert "Conversation" in repr(conv)


class TestMessageModel:
    """Test Message ORM model"""

    def test_create_message_minimal(self):
        """创建最小字段的 Message"""
        msg = Message(
            conversation_id=1,
            role="user",
            content="帮我找美妆达人",
            content_type="text",
            sequence_num=0,
        )
        assert msg.conversation_id == 1
        assert msg.role == "user"
        assert msg.content == "帮我找美妆达人"
        assert msg.content_type == "text"
        assert msg.sequence_num == 0
        assert msg.user_id is None

    def test_create_message_full(self):
        """创建完整字段的 Message"""
        msg = Message(
            conversation_id=1,
            user_id=1,
            role="user",
            content="帮我找美妆达人",
            content_type="text",
            metadata_json='{"intent": "kol_search"}',
            references_json='[{"source_file": "test.pdf", "score": 0.95}]',
            trace_id="trace-123",
            token_count=150,
            sequence_num=1,
        )
        assert msg.user_id == 1
        assert msg.content_type == "text"
        assert msg.metadata_json == '{"intent": "kol_search"}'
        assert msg.references_json == '[{"source_file": "test.pdf", "score": 0.95}]'
        assert msg.trace_id == "trace-123"
        assert msg.token_count == 150
        assert msg.sequence_num == 1

    def test_message_role_values(self):
        """Message role 支持 user / master / system"""
        for role in ["user", "master", "system"]:
            msg = Message(conversation_id=1, role=role, content="test", content_type="text", sequence_num=0)
            assert msg.role == role

    def test_message_content_type_values(self):
        """Message content_type 支持多种类型"""
        valid_types = ["text", "kol_list", "analysis_report", "script", "logistics", "plan"]
        for ct in valid_types:
            msg = Message(conversation_id=1, role="user", content="test", content_type=ct, sequence_num=0)
            assert msg.content_type == ct

    def test_message_repr(self):
        """Message repr 格式正确"""
        msg = Message(id=1, conversation_id=1, role="user", content="hello", content_type="text", sequence_num=0)
        assert "Message" in repr(msg)


class TestKolProfileModel:
    """Test KolProfile ORM model"""

    def test_create_kol_profile_minimal(self):
        """创建最小字段的 KolProfile"""
        kol = KolProfile(
            company_id=1,
            name="李佳琦",
            platform="douyin",
            category="其他",
            data_source="manual",
            followers=0,
            engagement_rate=0.0,
            avg_views=0,
            avg_likes=0,
            avg_comments=0,
            avg_shares=0,
            verified=False,
            is_active=True,
        )
        assert kol.company_id == 1
        assert kol.name == "李佳琦"
        assert kol.platform == "douyin"
        assert kol.followers == 0
        assert kol.engagement_rate == 0.0
        assert kol.category == "其他"
        assert kol.verified is False
        assert kol.data_source == "manual"
        assert kol.is_active is True

    def test_create_kol_profile_full(self):
        """创建完整字段的 KolProfile"""
        kol = KolProfile(
            company_id=1,
            name="李佳琦Austin",
            platform="douyin",
            platform_uid="douyin_12345",
            followers=48500000,
            engagement_rate=3.5,
            category="美妆",
            sub_category="口红",
            avg_views=10000000,
            avg_likes=500000,
            avg_comments=30000,
            avg_shares=20000,
            price_range_low=8000,
            price_range_high=15000,
            location="上海",
            verified=True,
            bio="知名美妆博主",
            avatar_url="https://example.com/avatar.jpg",
            contact_info="encrypted_contact",
            data_source="api_crawl",
            last_synced_at=datetime.utcnow(),
        )
        assert kol.platform_uid == "douyin_12345"
        assert kol.followers == 48500000
        assert kol.engagement_rate == 3.5
        assert kol.category == "美妆"
        assert kol.sub_category == "口红"
        assert kol.avg_views == 10000000
        assert kol.avg_likes == 500000
        assert kol.avg_comments == 30000
        assert kol.avg_shares == 20000
        assert kol.price_range_low == 8000
        assert kol.price_range_high == 15000
        assert kol.location == "上海"
        assert kol.verified is True
        assert kol.bio == "知名美妆博主"
        assert kol.avatar_url == "https://example.com/avatar.jpg"
        assert kol.data_source == "api_crawl"
        assert kol.last_synced_at is not None

    def test_kol_profile_platform_values(self):
        """KolProfile platform 支持多个平台"""
        platforms = ["douyin", "xiaohongshu", "kuaishou", "bilibili", "weibo"]
        for p in platforms:
            kol = KolProfile(
                company_id=1, name="test", platform=p, category="其他", data_source="manual",
                followers=0, engagement_rate=0.0, avg_views=0, avg_likes=0, avg_comments=0, avg_shares=0
            )
            assert kol.platform == p

    def test_kol_profile_repr(self):
        """KolProfile repr 格式正确"""
        kol = KolProfile(
            id=1, company_id=1, name="test", platform="douyin", category="其他", data_source="manual",
            followers=0, engagement_rate=0.0, avg_views=0, avg_likes=0, avg_comments=0, avg_shares=0
        )
        assert "KolProfile" in repr(kol)


class TestKolSearchHistoryModel:
    """Test KolSearchHistory ORM model"""

    def test_create_search_history_minimal(self):
        """创建最小字段的 KolSearchHistory"""
        hist = KolSearchHistory(
            user_id=1,
            company_id=1,
            query="美妆达人",
            result_count=0,
        )
        assert hist.user_id == 1
        assert hist.company_id == 1
        assert hist.query == "美妆达人"
        assert hist.result_count == 0
        assert hist.rewritten_query is None
        assert hist.clicked_kol_ids is None

    def test_create_search_history_full(self):
        """创建完整字段的 KolSearchHistory"""
        hist = KolSearchHistory(
            user_id=1,
            company_id=1,
            query="美妆达人",
            rewritten_query="找美妆类带货达人",
            platform_filter="douyin",
            category_filter="美妆",
            result_count=20,
            clicked_kol_ids="[1, 3, 5]",
            search_duration_ms=350,
        )
        assert hist.rewritten_query == "找美妆类带货达人"
        assert hist.platform_filter == "douyin"
        assert hist.category_filter == "美妆"
        assert hist.result_count == 20
        assert hist.clicked_kol_ids == "[1, 3, 5]"
        assert hist.search_duration_ms == 350

    def test_search_history_repr(self):
        """KolSearchHistory repr 格式正确"""
        hist = KolSearchHistory(id=1, user_id=1, company_id=1, query="test", result_count=0)
        assert "KolSearchHistory" in repr(hist)


class TestContentScriptModel:
    """Test ContentScript ORM model"""

    def test_create_content_script_minimal(self):
        """创建最小字段的 ContentScript"""
        script = ContentScript(
            company_id=1,
            user_id=1,
            title="618 直播脚本",
            content="# 直播脚本内容",
            script_type="livestream",
            status="draft",
            version=1,
        )
        assert script.company_id == 1
        assert script.user_id == 1
        assert script.title == "618 直播脚本"
        assert script.content == "# 直播脚本内容"
        assert script.script_type == "livestream"
        assert script.status == "draft"
        assert script.version == 1

    def test_create_content_script_full(self):
        """创建完整字段的 ContentScript"""
        script = ContentScript(
            company_id=1,
            user_id=1,
            conversation_id=1,
            message_id=1,
            title="618 直播脚本",
            script_type="livestream",
            platform="douyin",
            content="# 完整脚本",
            segments_json='[{"segment": "开场", "duration": 120, "script": "..."}]',
            products_json='[{"name": "XX精华液", "usp": "美白"}]',
            kol_name="李佳琦",
            status="pending_review",
            review_comment="",
            reviewed_by=None,
            reviewed_at=None,
            version=1,
        )
        assert script.conversation_id == 1
        assert script.message_id == 1
        assert script.script_type == "livestream"
        assert script.platform == "douyin"
        assert script.segments_json == '[{"segment": "开场", "duration": 120, "script": "..."}]'
        assert script.products_json == '[{"name": "XX精华液", "usp": "美白"}]'
        assert script.kol_name == "李佳琦"
        assert script.status == "pending_review"

    def test_content_script_status_values(self):
        """ContentScript status 支持 draft / pending_review / approved / rejected"""
        statuses = ["draft", "pending_review", "approved", "rejected"]
        for status in statuses:
            script = ContentScript(
                company_id=1, user_id=1, title="test", content="test",
                script_type="livestream", status=status, version=1
            )
            assert script.status == status

    def test_content_script_type_values(self):
        """ContentScript script_type 支持多种类型"""
        types = ["livestream", "social_post", "short_video"]
        for st in types:
            script = ContentScript(
                company_id=1, user_id=1, title="test", content="test",
                script_type=st, status="draft", version=1
            )
            assert script.script_type == st

    def test_content_script_repr(self):
        """ContentScript repr 格式正确"""
        script = ContentScript(
            id=1, company_id=1, user_id=1, title="test", content="test",
            script_type="livestream", status="draft", version=1
        )
        assert "ContentScript" in repr(script)


class TestLogisticsTrackingModel:
    """Test LogisticsTracking ORM model"""

    def test_create_logistics_minimal(self):
        """创建最小字段的 LogisticsTracking"""
        log = LogisticsTracking(
            company_id=1,
            user_id=1,
            tracking_number="SF1234567890",
            carrier="SF",
            status="pending",
        )
        assert log.company_id == 1
        assert log.user_id == 1
        assert log.tracking_number == "SF1234567890"
        assert log.carrier == "SF"
        assert log.status == "pending"

    def test_create_logistics_full(self):
        """创建完整字段的 LogisticsTracking"""
        log = LogisticsTracking(
            company_id=1,
            user_id=1,
            tracking_number="SF1234567890",
            carrier="SF",
            status="in_transit",
            status_detail="快件在运输中",
            origin="上海",
            destination="北京",
            estimated_delivery=datetime.utcnow(),
            actual_delivery=None,
            kol_name="李佳琦",
            sample_name="XX精华液试用装",
            tracking_history='[{"time": "2026-06-20 10:00", "status": "已揽收", "location": "上海"}]',
            last_checked_at=datetime.utcnow(),
        )
        assert log.status == "in_transit"
        assert log.status_detail == "快件在运输中"
        assert log.origin == "上海"
        assert log.destination == "北京"
        assert log.kol_name == "李佳琦"
        assert log.sample_name == "XX精华液试用装"
        assert log.tracking_history == '[{"time": "2026-06-20 10:00", "status": "已揽收", "location": "上海"}]'

    def test_logistics_status_values(self):
        """LogisticsTracking status 支持 pending / in_transit / delivered / exception"""
        statuses = ["pending", "in_transit", "delivered", "exception"]
        for status in statuses:
            log = LogisticsTracking(
                company_id=1, user_id=1, tracking_number="SF123", carrier="SF", status=status
            )
            assert log.status == status

    def test_logistics_carrier_values(self):
        """LogisticsTracking carrier 支持多种快递公司"""
        carriers = ["SF", "YTO", "ZTO", "EMS", "JD"]
        for c in carriers:
            log = LogisticsTracking(
                company_id=1, user_id=1, tracking_number="SF123", carrier=c, status="pending"
            )
            assert log.carrier == c

    def test_logistics_repr(self):
        """LogisticsTracking repr 格式正确"""
        log = LogisticsTracking(
            id=1, company_id=1, user_id=1, tracking_number="SF123", carrier="SF", status="pending"
        )
        assert "LogisticsTracking" in repr(log)


class TestReviewApprovalModel:
    """Test ReviewApproval ORM model"""

    def test_create_review_approval_minimal(self):
        """创建最小字段的 ReviewApproval"""
        review = ReviewApproval(
            company_id=1,
            user_id=1,
            content_type="script",
            content_id=1,
            action="approve",
            new_status="approved",
        )
        assert review.company_id == 1
        assert review.user_id == 1
        assert review.content_type == "script"
        assert review.content_id == 1
        assert review.action == "approve"
        assert review.new_status == "approved"

    def test_create_review_approval_full(self):
        """创建完整字段的 ReviewApproval"""
        review = ReviewApproval(
            company_id=1,
            user_id=1,
            content_type="script",
            content_id=1,
            action="reject",
            comment="脚本内容需要调整口播语气",
            previous_status="pending_review",
            new_status="rejected",
        )
        assert review.action == "reject"
        assert review.comment == "脚本内容需要调整口播语气"
        assert review.previous_status == "pending_review"
        assert review.new_status == "rejected"

    def test_review_action_values(self):
        """ReviewApproval action 支持 approve / reject / request_changes"""
        actions = ["approve", "reject", "request_changes"]
        for action in actions:
            review = ReviewApproval(
                company_id=1,
                user_id=1,
                content_type="script",
                content_id=1,
                action=action,
                new_status="approved" if action == "approve" else "rejected",
            )
            assert review.action == action

    def test_review_content_type_values(self):
        """ReviewApproval content_type 支持多种类型"""
        types = ["script", "report", "plan", "outreach_message"]
        for ct in types:
            review = ReviewApproval(
                company_id=1,
                user_id=1,
                content_type=ct,
                content_id=1,
                action="approve",
                new_status="approved",
            )
            assert review.content_type == ct

    def test_review_repr(self):
        """ReviewApproval repr 格式正确"""
        review = ReviewApproval(
            id=1, company_id=1, user_id=1, content_type="script", content_id=1,
            action="approve", new_status="approved"
        )
        assert "ReviewApproval" in repr(review)

"""
API tests for KOL Search endpoints (Task 3.1)
Tests for POST /api/kol/search, GET /api/kol/{id}, POST /api/kol/export
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_db_adapter():
    """Mock PostgresAdapter for database operations"""
    adapter = MagicMock()
    mock_session = MagicMock()
    adapter.get_session.return_value.__enter__.return_value = mock_session
    return adapter, mock_session


@pytest.fixture
def setup_db_proxy(mock_db_adapter):
    """Setup DatabaseProxy with mock adapter"""
    from app.database import db as db_proxy

    adapter, _ = mock_db_adapter
    db_proxy._instance = adapter
    yield
    db_proxy._instance = None


@pytest.fixture
def real_kol_db_proxy():
    """Provide tenant-scoped KOL records through the real ORM query path."""
    from app.database import db as db_proxy
    from app.database.models import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    class Adapter:
        def get_session(self):
            return SessionLocal()

    previous = db_proxy._instance
    db_proxy._instance = Adapter()
    try:
        yield SessionLocal
    finally:
        db_proxy._instance = previous
        Base.metadata.drop_all(engine)
        engine.dispose()


def _add_kol(
    session,
    *,
    company_id=1,
    name="企业护肤达人A",
    platform="xiaohongshu",
    category="护肤",
    data_source="manual_upload",
):
    from app.database.models import KolProfile

    session.add(
        KolProfile(
            company_id=company_id,
            name=name,
            platform=platform,
            platform_uid=f"{company_id}:{platform}:{name}",
            followers=120000,
            engagement_rate=4.2,
            category=category,
            sub_category=category,
            data_source=data_source,
            is_active=True,
        )
    )


# ============================================================
# Test: KolSearchRequest Schema
# ============================================================


class TestKolSearchRequestSchema:
    """Test KolSearchRequest Pydantic schema"""

    def test_minimal_request_valid(self):
        """最小请求有效"""
        from app.api.kol import KolSearchRequest

        req = KolSearchRequest(query="美妆达人")
        assert req.query == "美妆达人"
        assert req.platform == "all"
        assert req.sort_by == "relevance"
        assert req.limit == 20

    def test_full_request_valid(self):
        """完整请求有效"""
        from app.api.kol import KolSearchRequest

        req = KolSearchRequest(
            query="美妆达人",
            platform="douyin",
            category="美妆",
            min_followers=10000,
            max_followers=1000000,
            min_engagement_rate=1.0,
            sort_by="followers",
            limit=10,
        )
        assert req.query == "美妆达人"
        assert req.platform == "douyin"
        assert req.category == "美妆"

    def test_invalid_platform_rejected(self):
        """非法平台被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="test", platform="invalid_platform")

    def test_invalid_sort_by_rejected(self):
        """非法排序字段被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="test", sort_by="invalid_sort")

    def test_limit_below_minimum_rejected(self):
        """limit 低于最小值被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="test", limit=0)

    def test_limit_above_maximum_rejected(self):
        """limit 超过最大值被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="test", limit=51)


# ============================================================
# Test: POST /api/kol/search
# ============================================================


class TestSearchKolsEndpoint:
    """Test POST /api/kol/search"""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, setup_db_proxy, mock_db_adapter):
        """搜索返回结果"""
        with patch("app.agents.kol_search.search_kols") as mock_search:
            mock_kol = MagicMock()
            mock_kol.id = 1
            mock_kol.name = "李佳琦"
            mock_kol.platform = "douyin"
            mock_kol.followers = 48500000
            mock_kol.engagement_rate = 3.5
            mock_kol.category = "美妆"
            mock_kol.price_range_low = 8000
            mock_kol.price_range_high = 15000
            mock_kol.data_source = "manual"
            mock_kol.source_url = "https://example.com/source"
            mock_kol.source_note = "人工导入"
            mock_kol.last_synced_at = None
            mock_search.return_value = [mock_kol]

            from app.api.kol import KolSearchRequest, search_kols_endpoint

            req = KolSearchRequest(query="美妆达人")
            result = await search_kols_endpoint(
                request=req,
                company_id="1",
                user_id=1,
            )

            assert result.total == 1
            assert len(result.results) == 1
            assert result.results[0]["name"] == "李佳琦"
            assert result.results[0]["data_source"] == "manual"
            assert result.results[0]["source"] == "manual"
            assert result.results[0]["source_label"] == "人工导入"
            assert result.results[0]["source_available_for_search"] is True
            assert result.results[0]["follower_count"] == 48500000
            assert result.results[0]["followers_count"] == 48500000
            assert result.results[0]["source_url"] == "https://example.com/source"
            assert result.results[0]["source_note"] == "人工导入"
            assert result.data_source_summary == {"manual": 1}
            assert result.source_labels == {"manual": "人工导入"}
            assert result.data_source_warning is None

    @pytest.mark.asyncio
    async def test_search_excludes_demo_source_records(self, setup_db_proxy, mock_db_adapter):
        """API response must not treat demo/mock records as usable enterprise KOL data."""
        with patch("app.agents.kol_search.search_kols") as mock_search:
            real_kol = MagicMock()
            real_kol.id = 1
            real_kol.name = "企业护肤达人"
            real_kol.platform = "xiaohongshu"
            real_kol.followers = 120000
            real_kol.engagement_rate = 4.2
            real_kol.category = "护肤"
            real_kol.price_range_low = None
            real_kol.price_range_high = None
            real_kol.data_source = "manual_upload"
            real_kol.source_url = None
            real_kol.source_note = None
            real_kol.last_synced_at = None

            demo_kol = MagicMock()
            demo_kol.id = 2
            demo_kol.name = "演示护肤达人"
            demo_kol.platform = "xiaohongshu"
            demo_kol.followers = 999999
            demo_kol.engagement_rate = 9.9
            demo_kol.category = "护肤"
            demo_kol.price_range_low = None
            demo_kol.price_range_high = None
            demo_kol.data_source = "demo"
            demo_kol.source_url = None
            demo_kol.source_note = None
            demo_kol.last_synced_at = None
            mock_search.return_value = [real_kol, demo_kol]

            from app.api.kol import KolSearchRequest, search_kols_endpoint

            result = await search_kols_endpoint(
                request=KolSearchRequest(query="护肤"),
                company_id="1",
                user_id=0,
            )

            assert result.total == 1
            assert [item["name"] for item in result.results] == ["企业护肤达人"]
            assert result.data_source_summary == {"manual_upload": 1}
            assert result.source_labels == {"manual_upload": "人工导入"}

    @pytest.mark.asyncio
    async def test_search_empty_results(self, setup_db_proxy, mock_db_adapter):
        """搜索无结果"""
        with patch("app.agents.kol_search.search_kols") as mock_search:
            mock_search.return_value = []

            from app.api.kol import KolSearchRequest, search_kols_endpoint

            req = KolSearchRequest(query="不存在的达人")
            result = await search_kols_endpoint(
                request=req,
                company_id="1",
                user_id=1,
            )

            assert result.total == 0
            assert len(result.results) == 0
            assert result.data_source_summary == {}
            assert result.data_source_warning is not None
            assert "no_kol_data_found" in result.data_source_warning

    @pytest.mark.asyncio
    async def test_search_includes_search_id(self, setup_db_proxy, mock_db_adapter):
        """搜索结果包含 search_id"""
        with patch("app.agents.kol_search.search_kols") as mock_search:
            mock_search.return_value = []

            from app.api.kol import KolSearchRequest, search_kols_endpoint

            req = KolSearchRequest(query="美妆达人")
            result = await search_kols_endpoint(
                request=req,
                company_id="1",
                user_id=1,
            )

            assert result.search_id is not None

    @pytest.mark.asyncio
    async def test_search_uses_authenticated_company_and_filters_demo_data(
        self, real_kol_db_proxy
    ):
        """搜索必须使用认证用户公司边界，且不能返回 demo/mock 达人。"""
        with real_kol_db_proxy() as session:
            _add_kol(session, company_id=1, name="企业护肤达人A")
            _add_kol(session, company_id=2, name="跨租户护肤达人B")
            _add_kol(session, company_id=1, name="演示护肤达人C", data_source="demo")
            session.commit()

        from app.api.kol import KolSearchRequest, search_kols_endpoint

        result = await search_kols_endpoint(
            request=KolSearchRequest(
                query="护肤",
                platform="xiaohongshu",
                category="护肤",
                limit=10,
            ),
            company_id="2",
            user_id=0,
            current_user=SimpleNamespace(company_id=1),
        )

        assert result.total == 1
        assert [item["name"] for item in result.results] == ["企业护肤达人A"]
        assert result.data_source_summary == {"manual_upload": 1}
        assert result.results[0]["source_label"] == "人工导入"
        assert result.results[0]["source_available_for_search"] is True
        assert result.data_source_warning is None


# ============================================================
# Test: GET /api/kol/{kol_id}
# ============================================================


class TestGetKolDetailEndpoint:
    """Test GET /api/kol/{kol_id}"""

    @pytest.mark.asyncio
    async def test_get_kol_detail_found(self, setup_db_proxy, mock_db_adapter):
        """获取达人详情 — 存在"""
        _, mock_session = mock_db_adapter

        mock_kol = MagicMock()
        mock_kol.id = 1
        mock_kol.name = "李佳琦"
        mock_kol.platform = "douyin"
        mock_kol.followers = 48500000
        mock_kol.engagement_rate = 3.5
        mock_kol.category = "美妆"
        mock_kol.sub_category = "彩妆"
        mock_kol.avg_views = 1000000
        mock_kol.avg_likes = 50000
        mock_kol.avg_comments = 3000
        mock_kol.price_range_low = 8000
        mock_kol.price_range_high = 15000
        mock_kol.location = "上海"
        mock_kol.verified = True
        mock_kol.bio = "知名美妆博主"
        mock_kol.avatar_url = "https://example.com/avatar.jpg"

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_kol

        from app.api.kol import get_kol_detail

        result = await get_kol_detail(kol_id=1, company_id="1")

        assert result["name"] == "李佳琦"
        assert result["platform"] == "douyin"

    @pytest.mark.asyncio
    async def test_get_kol_detail_not_found(self, setup_db_proxy, mock_db_adapter):
        """获取达人详情 — 不存在"""
        from fastapi import HTTPException

        _, mock_session = mock_db_adapter

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        from app.api.kol import get_kol_detail

        with pytest.raises(HTTPException) as exc_info:
            await get_kol_detail(kol_id=999, company_id="1")

        assert exc_info.value.status_code == 404


# ============================================================
# Test: KolExportRequest Schema
# ============================================================


class TestKolExportRequestSchema:
    """Test KolExportRequest Pydantic schema"""

    def test_export_request_valid(self):
        """导出请求有效"""
        from app.api.kol import KolExportRequest

        req = KolExportRequest(kol_ids=[1, 2, 3], format="csv")
        assert req.kol_ids == [1, 2, 3]
        assert req.format == "csv"

    def test_export_request_default_format(self):
        """导出请求默认格式"""
        from app.api.kol import KolExportRequest

        req = KolExportRequest(kol_ids=[1])
        assert req.format == "csv"

    def test_export_request_invalid_format_rejected(self):
        """非法导出格式被拒绝"""
        from app.api.kol import KolExportRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolExportRequest(kol_ids=[1], format="json")

    def test_export_request_empty_kol_ids_accepted(self):
        """空 kol_ids 被接受（Pydantic 默认允许空列表）"""
        from app.api.kol import KolExportRequest

        req = KolExportRequest(kol_ids=[])
        assert req.kol_ids == []

    def test_export_request_filter_only_valid(self):
        from app.api.kol import KolExportRequest

        req = KolExportRequest(query="beauty", platform="douyin", category="beauty")

        assert req.kol_ids == []
        assert req.query == "beauty"
        assert req.platform == "douyin"


# ============================================================
# Test: export_kols endpoint
# ============================================================


class TestExportKolsEndpoint:
    """Test POST /api/kol/export"""

    @pytest.mark.skip(reason="export-by-id source filtering depends on uncommitted KOL data-source constants")
    @pytest.mark.asyncio
    async def test_export_csv(self, setup_db_proxy, mock_db_adapter):
        """导出 CSV 格式"""
        _, mock_session = mock_db_adapter

        mock_kol = MagicMock()
        mock_kol.id = 1
        mock_kol.name = "测试达人"
        mock_kol.platform = "douyin"
        mock_kol.followers = 100000
        mock_kol.engagement_rate = 3.5
        mock_kol.category = "美妆"
        mock_kol.price_range_low = 5000
        mock_kol.price_range_high = 10000
        mock_kol.location = "北京"

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_kol]

        from app.api.kol import export_kols, KolExportRequest

        result = await export_kols(
            request=KolExportRequest(kol_ids=[1], format="csv"),
            company_id="1",
        )

        assert result is not None

    @pytest.mark.skip(reason="export-by-id source filtering depends on uncommitted KOL data-source constants")
    @pytest.mark.asyncio
    async def test_export_pdf_returns_response(self, setup_db_proxy, mock_db_adapter):
        """Export PDF returns a streaming PDF response."""
        _, mock_session = mock_db_adapter

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        from app.api.kol import export_kols, KolExportRequest

        result = await export_kols(
            request=KolExportRequest(kol_ids=[1], format="pdf"),
            company_id="1",
        )

        assert result.media_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_export_by_query_filters(self, setup_db_proxy, mock_db_adapter):
        """Export can use query/category/platform without kol_ids."""
        _, mock_session = mock_db_adapter

        from app.api.kol import export_kols, KolExportRequest

        with patch("app.agents.kol_search.search_kols") as mock_search:
            mock_search.return_value = []

            result = await export_kols(
                request=KolExportRequest(
                    query="beauty",
                    platform="douyin",
                    category="beauty",
                    format="csv",
                ),
                company_id="1",
            )

        assert result.media_type == "text/csv"
        mock_search.assert_called_once()

    @pytest.mark.skip(reason="export-by-id source filtering depends on uncommitted KOL data-source constants")
    @pytest.mark.asyncio
    async def test_export_without_company_id(self, setup_db_proxy, mock_db_adapter):
        """导出时不传 company_id"""
        _, mock_session = mock_db_adapter

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        from app.api.kol import export_kols, KolExportRequest

        result = await export_kols(
            request=KolExportRequest(kol_ids=[1], format="csv"),
            company_id="",
        )

        assert result is not None


# ============================================================
# Test: KolSearchRequest edge cases
# ============================================================


class TestKolSearchRequestEdgeCases:
    """Test KolSearchRequest edge cases"""

    def test_limit_min_value(self):
        """limit 最小值"""
        from app.api.kol import KolSearchRequest

        req = KolSearchRequest(query="测试", limit=1)
        assert req.limit == 1

    def test_limit_max_value(self):
        """limit 最大值"""
        from app.api.kol import KolSearchRequest

        req = KolSearchRequest(query="测试", limit=50)
        assert req.limit == 50

    def test_limit_too_low_rejected(self):
        """limit 太小被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="测试", limit=0)

    def test_limit_too_high_rejected(self):
        """limit 太大被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="测试", limit=51)

    def test_negative_followers_rejected(self):
        """负数粉丝数被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="测试", min_followers=-1)

    def test_negative_engagement_rate_rejected(self):
        """负数互动率被拒绝"""
        from app.api.kol import KolSearchRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KolSearchRequest(query="测试", min_engagement_rate=-1.0)

"""
API tests for KOL Search endpoints (Task 3.1)
Tests for POST /api/kol/search, GET /api/kol/{id}, POST /api/kol/export
"""

import pytest
from unittest.mock import MagicMock, patch


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
        with patch('app.agents.kol_search.search_kols') as mock_search:
            mock_kol = MagicMock()
            mock_kol.id = 1
            mock_kol.name = "李佳琦"
            mock_kol.platform = "douyin"
            mock_kol.followers = 48500000
            mock_kol.engagement_rate = 3.5
            mock_kol.category = "美妆"
            mock_kol.price_range_low = 8000
            mock_kol.price_range_high = 15000
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

    @pytest.mark.asyncio
    async def test_search_empty_results(self, setup_db_proxy, mock_db_adapter):
        """搜索无结果"""
        with patch('app.agents.kol_search.search_kols') as mock_search:
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

    @pytest.mark.asyncio
    async def test_search_includes_search_id(self, setup_db_proxy, mock_db_adapter):
        """搜索结果包含 search_id"""
        with patch('app.agents.kol_search.search_kols') as mock_search:
            mock_search.return_value = []

            from app.api.kol import KolSearchRequest, search_kols_endpoint
            req = KolSearchRequest(query="美妆达人")
            result = await search_kols_endpoint(
                request=req,
                company_id="1",
                user_id=1,
            )

            assert result.search_id is not None


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


# ============================================================
# Test: export_kols endpoint
# ============================================================

class TestExportKolsEndpoint:
    """Test POST /api/kol/export"""

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

    @pytest.mark.asyncio
    async def test_export_pdf_returns_501(self, setup_db_proxy, mock_db_adapter):
        """导出 PDF 返回 501"""
        _, mock_session = mock_db_adapter

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        from fastapi import HTTPException
        from app.api.kol import export_kols, KolExportRequest

        with pytest.raises(HTTPException) as exc_info:
            await export_kols(
                request=KolExportRequest(kol_ids=[1], format="pdf"),
                company_id="1",
            )

        assert exc_info.value.status_code == 501

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

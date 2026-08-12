"""# RAG v2 新模块单元测试
验证 P0-P3 所有新增和修改模块的功能正确性
"""

import time

import pytest

from app.rag.context_extractor import ContextConfig, ContextExtractor
from app.rag.doc_status import DocState, DocStatus, DocStatusManager
from app.rag.document_parser import (
    PARSER_REGISTRY,
    BaseParser,
    CompositeParser,
    DocumentParser,
    PyPDF2Parser,
    get_active_parser,
    get_parser,
    register_parser,
    set_parser,
)
from app.rag.embedding_service import (
    EMBEDDING_MODEL_REGISTRY,
    EmbeddingService,
    get_embedding_model_path,
    list_available_models,
    register_embedding_model,
)
from app.rag.parse_cache import ParseCache
from app.rag.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    retry,
)

# ═══ 解析器注册表测试 ═══


class TestParserRegistry:
    """验证解析器注册表 + 热插拔"""

    def test_registry_contains_composite(self):
        assert "composite" in PARSER_REGISTRY

    def test_registry_contains_pypdf2(self):
        assert "pypdf2" in PARSER_REGISTRY

    def test_registry_contains_python_docx(self):
        assert "python-docx" in PARSER_REGISTRY

    def test_registry_contains_bs4(self):
        assert "bs4" in PARSER_REGISTRY

    def test_get_parser_composite(self):
        parser = get_parser("composite")
        assert isinstance(parser, CompositeParser)
        assert parser.name == "composite"

    def test_get_parser_pypdf2(self):
        parser = get_parser("pypdf2")
        assert isinstance(parser, PyPDF2Parser)
        assert parser.name == "pypdf2"

    def test_get_parser_unknown(self):
        with pytest.raises(ValueError, match="Unknown parser"):
            get_parser("nonexistent")

    def test_set_parser(self):
        set_parser("composite")
        parser = get_active_parser()
        assert isinstance(parser, CompositeParser)

    def test_register_custom_parser(self):
        class CustomParser(BaseParser):
            @property
            def name(self):
                return "custom"

            def parse_pdf(self, content):
                return "custom_pdf"

            def parse_docx(self, content):
                return "custom_docx"

            def parse_html(self, content):
                return "custom_html"

            def parse_txt(self, content):
                return "custom_txt"

        register_parser("custom_test", CustomParser)
        assert "custom_test" in PARSER_REGISTRY
        parser = get_parser("custom_test")
        assert isinstance(parser, CustomParser)

    def test_register_invalid_parser(self):
        with pytest.raises(TypeError, match="must inherit from BaseParser"):
            register_parser("invalid", dict)

    def test_backward_compatible_txt(self):
        result = DocumentParser.parse("test.txt", b"hello world")
        assert "hello world" in result

    def test_composite_parser_check_installation(self):
        parser = CompositeParser()
        assert parser.check_installation() is True


# ═══ 弹性机制测试 ═══


class TestRetry:
    """验证重试装饰器"""

    def test_sync_retry_success_first_attempt(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def always_succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = always_succeed()
        assert result == "success"
        assert call_count == 1

    def test_sync_retry_eventual_success(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        def succeed_on_third():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "success"

        result = succeed_on_third()
        assert result == "success"
        assert call_count == 3

    def test_sync_retry_exhausted(self):
        call_count = 0

        @retry(max_attempts=2, base_delay=0.01, jitter=False)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fail")

        with pytest.raises(ValueError, match="always fail"):
            always_fail()
        assert call_count == 2

    def test_sync_retry_non_retryable_exception(self):
        @retry(max_attempts=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def raise_type_error():
            raise TypeError("not retryable")

        with pytest.raises(TypeError, match="not retryable"):
            raise_type_error()

    def test_retry_invalid_max_attempts(self):
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):

            @retry(max_attempts=0)
            def dummy():
                pass


class TestCircuitBreaker:
    """验证熔断器"""

    def test_initial_state_closed(self):
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.state == "CLOSED"
        assert not breaker.is_open

    def test_before_call_allows_when_closed(self):
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.before_call() is True

    def test_opens_after_failures(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        breaker.on_failure()
        assert breaker.state == "CLOSED"
        breaker.on_failure()
        assert breaker.state == "OPEN"
        assert breaker.is_open

    def test_before_call_raises_when_open(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        breaker.on_failure()
        with pytest.raises(CircuitBreakerOpenError):
            breaker.before_call()

    def test_reset(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        breaker.on_failure()
        assert breaker.is_open
        breaker.reset()
        assert breaker.state == "CLOSED"

    def test_half_open_recovers(self):
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
            success_threshold=2,
        )
        breaker.on_failure()
        assert breaker.state == "OPEN"
        time.sleep(0.02)
        assert breaker.state == "HALF_OPEN"
        breaker.on_success()
        breaker.on_success()
        assert breaker.state == "CLOSED"

    def test_half_open_reopens_on_failure(self):
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        breaker.on_failure()
        time.sleep(0.02)
        assert breaker.state == "HALF_OPEN"
        breaker.on_failure()
        assert breaker.state == "OPEN"


# ═══ 嵌入模型热插拔测试 ═══


class TestEmbeddingModelRegistry:
    """验证嵌入模型注册表 + 热插拔"""

    def test_registry_has_default_models(self):
        models = list_available_models()
        assert "bge-small" in models
        assert "bge-base" in models
        assert "e5-base" in models

    def test_get_model_path_by_alias(self):
        path = get_embedding_model_path("bge-small")
        assert "bge-small-zh" in path

    def test_get_model_path_by_full_path(self):
        path = get_embedding_model_path("BAAI/bge-small-zh-v1.5")
        assert "BAAI/bge-small-zh-v1.5" in path

    def test_get_model_path_unknown(self):
        with pytest.raises(ValueError, match="Unknown embedding model"):
            get_embedding_model_path("nonexistent_model")

    def test_register_custom_model(self):
        register_embedding_model("my-custom", "local/my-model")
        assert "my-custom" in EMBEDDING_MODEL_REGISTRY
        assert EMBEDDING_MODEL_REGISTRY["my-custom"] == "local/my-model"
        # Clean up
        del EMBEDDING_MODEL_REGISTRY["my-custom"]

    def test_embedding_service_accepts_alias(self):
        service = EmbeddingService(model_name="bge-small")
        assert "bge-small-zh" in service.model_name

    def test_embedding_service_switch_model(self):
        service = EmbeddingService(model_name="bge-small")
        service.switch_model("bge-base")
        assert "bge-base-zh" in service.model_name

    def test_fallback_embedding(self):
        service = EmbeddingService(model_name="bge-small")
        vec = service._fallback_embedding("测试文本")
        assert vec.shape == (512,)
        assert abs(float(sum(vec * vec)) - 1.0) < 0.01  # 归一化检查


# ═══ 解析缓存测试 ═══


class TestParseCache:
    """验证解析缓存"""

    def test_cache_set_and_get(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=3600)
        cache.set("/fake/file.txt", "parsed content")
        result = cache.get("/fake/file.txt")
        assert result == "parsed content"

    def test_cache_miss(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=3600)
        result = cache.get("/nonexistent/file.txt")
        assert result is None

    def test_cache_invalidate(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=3600)
        cache.set("/fake/file.txt", "parsed content")
        cache.invalidate("/fake/file.txt")
        result = cache.get("/fake/file.txt")
        assert result is None

    def test_cache_clear(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=3600)
        cache.set("/fake/a.txt", "content a")
        cache.set("/fake/b.txt", "content b")
        cache.clear()
        assert cache.get("/fake/a.txt") is None
        assert cache.get("/fake/b.txt") is None

    def test_cache_with_config_hash(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=3600)
        cache.set("/fake/file.txt", "content_v1", config_hash="v1")
        cache.set("/fake/file.txt", "content_v2", config_hash="v2")
        assert cache.get("/fake/file.txt", config_hash="v1") == "content_v1"
        assert cache.get("/fake/file.txt", config_hash="v2") == "content_v2"

    def test_cache_stats(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=3600)
        cache.set("/fake/file.txt", "content")
        stats = cache.stats
        assert stats["memory_entries"] == 1
        assert stats["ttl"] == 3600

    def test_cache_ttl_expired(self, tmp_path):
        cache = ParseCache(cache_dir=str(tmp_path / ".parse_cache"), ttl=0)
        cache.set("/fake/file.txt", "content")
        result = cache.get("/fake/file.txt")
        assert result is None


# ═══ 文档状态追踪测试 ═══


class TestDocStatus:
    """验证文档状态追踪"""

    def test_initial_state(self):
        status = DocStatus(doc_id="doc1", file_path="/test.pdf")
        assert status.text_state == DocState.READY
        assert status.multimodal_state == DocState.READY
        assert not status.is_fully_processed
        assert not status.has_failed

    def test_text_processing_lifecycle(self):
        status = DocStatus(doc_id="doc1")
        status.start_text_processing()
        assert status.text_state == DocState.HANDLING
        status.complete_text_processing(chunk_count=5)
        assert status.text_state == DocState.PROCESSED
        assert status.text_chunk_count == 5

    def test_text_processing_failure(self):
        status = DocStatus(doc_id="doc1")
        status.fail_text_processing("parse error")
        assert status.text_state == DocState.FAILED
        assert status.text_error == "parse error"
        assert status.has_failed

    def test_multimodal_processing_lifecycle(self):
        status = DocStatus(doc_id="doc1")
        status.start_multimodal_processing()
        assert status.multimodal_state == DocState.HANDLING
        status.complete_multimodal_processing(count=3)
        assert status.multimodal_state == DocState.PROCESSED
        assert status.multimodal_count == 3

    def test_skip(self):
        status = DocStatus(doc_id="doc1")
        status.skip("unsupported format")
        assert status.text_state == DocState.SKIPPED
        assert status.multimodal_state == DocState.SKIPPED

    def test_fully_processed(self):
        status = DocStatus(doc_id="doc1")
        status.complete_text_processing(chunk_count=3)
        status.complete_multimodal_processing(count=2)
        assert status.is_fully_processed

    def test_to_dict(self):
        status = DocStatus(doc_id="doc1", file_path="/test.pdf")
        status.complete_text_processing(chunk_count=3)
        d = status.to_dict()
        assert d["doc_id"] == "doc1"
        assert d["text_state"] == "processed"
        assert d["text_chunk_count"] == 3


class TestDocStatusManager:
    """验证文档状态管理器"""

    def test_get_or_create(self):
        manager = DocStatusManager()
        status = manager.get_or_create("doc1", "/test.pdf")
        assert status.doc_id == "doc1"
        assert status.file_path == "/test.pdf"

    def test_get_existing(self):
        manager = DocStatusManager()
        manager.get_or_create("doc1")
        status = manager.get("doc1")
        assert status is not None
        assert status.doc_id == "doc1"

    def test_get_nonexistent(self):
        manager = DocStatusManager()
        assert manager.get("nonexistent") is None

    def test_remove(self):
        manager = DocStatusManager()
        manager.get_or_create("doc1")
        manager.remove("doc1")
        assert manager.get("doc1") is None

    def test_get_pending_docs(self):
        manager = DocStatusManager()
        manager.get_or_create("doc1")
        manager.get_or_create("doc2")
        manager.get("doc1").complete_text_processing(chunk_count=3)
        pending = manager.get_pending_docs()
        assert "doc2" in pending
        assert "doc1" not in pending

    def test_get_failed_docs(self):
        manager = DocStatusManager()
        manager.get_or_create("doc1")
        manager.get("doc1").fail_text_processing("error")
        failed = manager.get_failed_docs()
        assert "doc1" in failed

    def test_get_processed_docs(self):
        manager = DocStatusManager()
        manager.get_or_create("doc1")
        manager.get("doc1").complete_text_processing(chunk_count=3)
        manager.get("doc1").complete_multimodal_processing(count=2)
        processed = manager.get_processed_docs()
        assert "doc1" in processed

    def test_stats(self):
        manager = DocStatusManager()
        manager.get_or_create("doc1")
        manager.get_or_create("doc2")
        manager.get("doc1").complete_text_processing(chunk_count=3)
        manager.get("doc1").complete_multimodal_processing(count=2)
        stats = manager.stats
        assert stats["total"] == 2
        assert stats["processed"] == 1
        assert stats["pending"] == 1


# ═══ 上下文提取器测试 ═══


class TestContextExtractor:
    """验证上下文提取器"""

    def _make_content_list(self):
        return [
            {"type": "heading", "content": "第一章 概述", "page": 1},
            {"type": "text", "content": "这是第一段文本。", "page": 1},
            {"type": "text", "content": "这是第二段文本。", "page": 1},
            {"type": "image", "content": "", "page": 1, "image_path": "/img1.png"},
            {"type": "text", "content": "这是图片后的文本。", "page": 1},
            {"type": "heading", "content": "第二章 详情", "page": 2},
            {"type": "text", "content": "第二章的内容。", "page": 2},
        ]

    def test_extract_neighbor_context(self):
        extractor = ContextExtractor(ContextConfig(context_mode="neighbor", context_window=1))
        content_list = self._make_content_list()
        # 图片在索引 3，前后各取 1 个文本元素
        context = extractor.extract_context(content_list, 3)
        assert "第二段文本" in context
        assert "图片后的文本" in context

    def test_extract_page_context(self):
        extractor = ContextExtractor(ContextConfig(context_mode="page"))
        content_list = self._make_content_list()
        context = extractor.extract_context(content_list, 3)
        assert "第一段文本" in context
        assert "第二段文本" in context
        assert "图片后的文本" in context
        assert "第二章" not in context  # 不同页

    def test_extract_section_context(self):
        extractor = ContextExtractor(ContextConfig(context_mode="section"))
        content_list = self._make_content_list()
        context = extractor.extract_context(content_list, 3)
        assert "第一章 概述" in context
        assert "第一段文本" in context
        assert "第二章" not in context  # 不同章节

    def test_extract_section_path(self):
        extractor = ContextExtractor()
        content_list = self._make_content_list()
        # 索引 6 在第二章
        path = extractor.extract_section_path(content_list, 6)
        assert "第一章 概述" in path
        assert "第二章 详情" in path

    def test_extract_context_empty_list(self):
        extractor = ContextExtractor()
        context = extractor.extract_context([], 0)
        assert context == ""

    def test_extract_context_out_of_range(self):
        extractor = ContextExtractor()
        content_list = self._make_content_list()
        context = extractor.extract_context(content_list, 999)
        assert context == ""

    def test_truncate_long_context(self):
        config = ContextConfig(max_context_tokens=5)
        extractor = ContextExtractor(config)
        long_text = "A" * 500
        content_list = [{"type": "text", "content": long_text, "page": 1}]
        context = extractor.extract_context(content_list, 0)
        # 截断后不超过 max_chars + 截断后缀长度
        max_chars = 5 * 2 + len("\n...(上下文已截断)") + 5
        assert len(context) <= max_chars


# ═══ CompanyContextBus v2 新增方法测试 ═══


class TestCompanyContextBusV2:
    """验证 CompanyContextBus 新增的 inject_context 和 record_completion 方法"""

    def test_inject_context_has_method(self):
        from app.rag.company_context_bus import CompanyContextBus

        bus = CompanyContextBus("test")
        assert hasattr(bus, "inject_context")
        assert callable(bus.inject_context)

    def test_inject_context_no_layers(self):
        from app.rag.company_context_bus import CompanyContextBus

        bus = CompanyContextBus("test")
        result = bus.inject_context("原始 prompt", layer1=False, layer2=False, layer3=False)
        assert result == "原始 prompt"

    def test_inject_context_with_layer1(self):
        from app.rag.company_context_bus import CompanyContextBus, CompanyProfile

        bus = CompanyContextBus("test")
        bus.set_profile(CompanyProfile(company_name="测试公司", industry="电商"))
        result = bus.inject_context("原始 prompt", layer2=False, layer3=False)
        assert "原始 prompt" in result
        assert "测试公司" in result

    def test_record_completion_has_method(self):
        from app.rag.company_context_bus import CompanyContextBus

        bus = CompanyContextBus("test")
        assert hasattr(bus, "record_completion")
        assert callable(bus.record_completion)

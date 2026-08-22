"""
CompanyContextBus 回归测试
验证「模式识别三问法」发现的问题及修复：
1. get_company_context_bus 单例竞态已修复（双检锁）
2. get_layer2_context 接受 results 参数，避免 retrieve_structured 重复检索
3. get_layer3_context 接受 results 参数，避免 retrieve_structured 重复检索
4. Layer1 CompanyProfile 数据类行为正确
"""

import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.rag.company_context_bus as ccb_module
from app.rag.company_context_bus import (
    CompanyContextBus,
    CompanyProfile,
    get_company_context_bus,
)


@pytest.fixture(autouse=True)
def _reset_bus_cache():
    """每个测试前后清空 bus 缓存，避免测试间污染"""
    ccb_module._bus_cache.clear()
    yield
    ccb_module._bus_cache.clear()


# ═══════════════════════════════════════════════════════════
# get_company_context_bus 单例：双检锁线程安全
# ═══════════════════════════════════════════════════════════
class TestGetBusSingleton:
    """get_company_context_bus 单例：同公司同实例，不同公司不同实例"""

    def test_same_company_returns_same_instance(self):
        a = get_company_context_bus("co_1")
        b = get_company_context_bus("co_1")
        assert a is b

    def test_different_companies_different_instances(self):
        a = get_company_context_bus("co_1")
        b = get_company_context_bus("co_2")
        assert a is not b

    def test_default_company_id(self):
        """不传 company_id 时使用 default"""
        bus = get_company_context_bus()
        assert bus.company_id == "default"

    def test_concurrent_creation_thread_safe(self):
        """10 线程并发请求同一 company_id，应只产生一个实例（双检锁验证）"""
        instances = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            instances.append(get_company_context_bus("concurrent_co"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(i is instances[0] for i in instances), (
            "并发创建不应产生多个 CompanyContextBus 实例"
        )


# ═══════════════════════════════════════════════════════════
# get_layer2_context results 参数：避免重复检索
# ═══════════════════════════════════════════════════════════
class TestGetLayer2ContextResults:
    """get_layer2_context 接受 results 参数，传入时跳过内部 search_knowledge"""

    def test_without_results_calls_search_knowledge(self):
        """不传 results 时，应调用 self.search_knowledge 检索"""
        bus = CompanyContextBus("test")
        called = {"count": 0}

        def mock_search(query, top_k=5):
            called["count"] += 1
            return [
                {
                    "content": "知识内容",
                    "metadata": {},
                    "score": 0.9,
                    "source": "hybrid",
                    "source_file": "",
                    "chunk_index": 0,
                    "source_page": 0,
                }
            ]

        bus.search_knowledge = mock_search
        result = bus.get_layer2_context("查询")
        assert called["count"] == 1
        assert "知识内容" in result

    def test_with_results_skips_search_knowledge(self):
        """传入 results 时，不应调用 self.search_knowledge（避免重复检索）"""
        bus = CompanyContextBus("test")
        called = {"count": 0}

        def mock_search(query, top_k=5):
            called["count"] += 1
            return []

        bus.search_knowledge = mock_search
        pre = [
            {
                "content": "预检索知识",
                "metadata": {},
                "score": 0.9,
                "source": "hybrid",
                "source_file": "",
                "chunk_index": 0,
                "source_page": 0,
            }
        ]
        result = bus.get_layer2_context("查询", results=pre)
        assert called["count"] == 0, "传入 results 后不应再调 search_knowledge"
        assert "预检索知识" in result

    def test_empty_results_returns_empty_string(self):
        """results 为空列表时返回空字符串"""
        bus = CompanyContextBus("test")
        result = bus.get_layer2_context("查询", results=[])
        assert result == ""


# ═══════════════════════════════════════════════════════════
# get_layer3_context results 参数：避免重复检索
# ═══════════════════════════════════════════════════════════
class TestGetLayer3ContextResults:
    """get_layer3_context 接受 results 参数，传入时跳过内部 search_experiences"""

    def test_without_results_calls_search_experiences(self):
        """不传 results 时，应调用 self.search_experiences 检索"""
        bus = CompanyContextBus("test")
        called = {"count": 0}

        def mock_search(query, agent_name=None, top_k=3):
            called["count"] += 1
            return [
                {
                    "content": "经验内容",
                    "agent_name": "客服专员",
                    "task_type": "test",
                    "outcome": "成功",
                    "score": 0.8,
                }
            ]

        bus.search_experiences = mock_search
        result = bus.get_layer3_context("查询")
        assert called["count"] == 1
        assert "经验内容" in result

    def test_with_results_skips_search_experiences(self):
        """传入 results 时，不应调用 self.search_experiences（避免重复检索）"""
        bus = CompanyContextBus("test")
        called = {"count": 0}

        def mock_search(query, agent_name=None, top_k=3):
            called["count"] += 1
            return []

        bus.search_experiences = mock_search
        pre = [
            {
                "content": "预检索经验",
                "agent_name": "客服专员",
                "task_type": "test",
                "outcome": "成功",
                "score": 0.8,
            }
        ]
        result = bus.get_layer3_context("查询", results=pre)
        assert called["count"] == 0, "传入 results 后不应再调 search_experiences"
        assert "预检索经验" in result

    def test_empty_results_returns_empty_string(self):
        """results 为空列表时返回空字符串"""
        bus = CompanyContextBus("test")
        result = bus.get_layer3_context("查询", results=[])
        assert result == ""


# ═══════════════════════════════════════════════════════════
# Layer 1: CompanyProfile 数据类
# ═══════════════════════════════════════════════════════════
class TestCompanyProfile:
    """CompanyProfile 数据类行为"""

    def test_to_context_string_with_data(self):
        profile = CompanyProfile(
            company_name="测试公司",
            industry="电商",
            brand_description="品牌描述",
        )
        ctx = profile.to_context_string()
        assert "测试公司" in ctx
        assert "电商" in ctx

    def test_to_context_string_empty_has_labels(self):
        """空 Profile 仍输出标签（便于 LLM 识别字段结构）"""
        profile = CompanyProfile()
        ctx = profile.to_context_string()
        assert "公司名称:" in ctx

    def test_default_lists_not_shared(self):
        """dataclass field(default_factory=list) 保证实例间不共享可变默认值"""
        p1 = CompanyProfile()
        p2 = CompanyProfile()
        p1.product_categories.append("A")
        assert p2.product_categories == [], "实例间列表不应共享"

    def test_set_and_get_profile(self):
        """set_profile 后 get_profile 返回同一实例"""
        bus = CompanyContextBus("test")
        profile = CompanyProfile(company_name="我的公司")
        bus.set_profile(profile)
        assert bus.get_profile() is profile
        assert "我的公司" in bus.get_layer1_context()

    def test_get_layer1_context_empty_when_no_profile(self):
        """未设置 Profile 时 get_layer1_context 返回空字符串"""
        bus = CompanyContextBus("test")
        bus._profile = None
        # get_profile 会尝试从 db 加载，测试环境 db 无数据返回 None
        # 直接验证未加载时 layer1 为空
        bus._profile = None
        bus.get_profile = lambda: None
        assert bus.get_layer1_context() == ""


class TestGraphEntityExtractionMode:
    """GraphRAG dynamic extraction should not block uploads by default."""

    def _patch_retriever(self, monkeypatch):
        fake_retriever = MagicMock()
        fake_retriever.index_documents.return_value = None
        monkeypatch.setattr(
            "app.rag.hybrid_retriever.get_hybrid_retriever",
            lambda _company_id: fake_retriever,
        )
        return fake_retriever

    def test_dynamic_extraction_disabled(self, monkeypatch):
        self._patch_retriever(monkeypatch)
        fake_graph = MagicMock()
        monkeypatch.setenv("GRAPH_RAG_DYNAMIC_EXTRACTION_MODE", "off")
        monkeypatch.setattr("app.rag.graph_rag.get_graph_rag", lambda: fake_graph)

        doc_id = CompanyContextBus("co_1").add_knowledge("知识内容")

        assert doc_id
        fake_graph.add_dynamic_entities.assert_not_called()

    def test_dynamic_extraction_sync_mode(self, monkeypatch):
        self._patch_retriever(monkeypatch)
        fake_graph = MagicMock()
        monkeypatch.setenv("GRAPH_RAG_DYNAMIC_EXTRACTION_MODE", "sync")
        monkeypatch.setattr("app.rag.graph_rag.get_graph_rag", lambda: fake_graph)

        CompanyContextBus("co_1").add_knowledge("知识内容")

        fake_graph.add_dynamic_entities.assert_called_once_with("知识内容")

    def test_dynamic_extraction_defaults_to_background_thread(self, monkeypatch):
        self._patch_retriever(monkeypatch)
        monkeypatch.delenv("GRAPH_RAG_DYNAMIC_EXTRACTION_MODE", raising=False)
        created_threads = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                self.target = target
                self.name = name
                self.daemon = daemon
                self.started = False
                created_threads.append(self)

            def start(self):
                self.started = True

        monkeypatch.setattr(ccb_module.threading, "Thread", FakeThread)

        CompanyContextBus("co_1").add_knowledge("知识内容")

        assert len(created_threads) == 1
        assert created_threads[0].started is True
        assert created_threads[0].daemon is True
        assert "graph-rag-extract-co_1" == created_threads[0].name


class TestKnowledgeResultRelevance:
    def _result(
        self,
        *,
        source: str,
        chunk_type: str | None = None,
        fact_ids: list[str] | None = None,
        markers: list[str] | None = None,
        source_file: str = "",
        bm25_score: float = 0.0,
        vector_score: float = 0.0,
        metadata: dict | None = None,
    ) -> SimpleNamespace:
        result_metadata = metadata or {}
        if chunk_type is not None:
            result_metadata["chunk_type"] = chunk_type
        if fact_ids is not None:
            result_metadata["fact_ids"] = fact_ids
        if markers is not None:
            result_metadata["markers"] = markers
        if source_file:
            result_metadata["source_file"] = source_file
        return SimpleNamespace(
            bm25_score=bm25_score,
            vector_score=vector_score,
            source=source,
            source_file=source_file,
            metadata=result_metadata,
        )

    def test_filters_low_vector_only_match(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = SimpleNamespace(
            vector_score=0.48,
            bm25_score=0.0,
            source="vector",
            metadata={"company_id": "co_1"},
        )

        assert not CompanyContextBus._is_relevant_knowledge_result(result)

    def test_keeps_strong_vector_match(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        result = SimpleNamespace(
            vector_score=0.77,
            bm25_score=0.0,
            source="vector",
            metadata={"company_id": "co_1"},
        )

        assert CompanyContextBus._is_relevant_knowledge_result(result)

    def test_allows_structured_content_metadata_supplement(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = self._result(
            source="metadata_supplement",
            chunk_type="fact_line",
            fact_ids=["F_CONTENT_META"],
            markers=["QPACK_CONTENT_META"],
        )

        assert CompanyContextBus._is_relevant_knowledge_result(result)

    def test_allows_structured_service_metadata_supplement(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = self._result(
            source="metadata_supplement",
            chunk_type="fact_line",
            fact_ids=["F_SERVICE_META"],
            markers=["QPACK_SERVICE_META"],
        )

        assert CompanyContextBus._is_relevant_knowledge_result(result)

    def test_metadata_supplement_rule_fact_does_not_bypass_score_gate(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = self._result(
            source="metadata_supplement",
            chunk_type="fact_line",
            fact_ids=["F_RULE_META"],
            markers=["QPACK_RULE_META"],
            source_file="qpack_06_platform_rules.txt",
        )

        assert not CompanyContextBus._is_relevant_knowledge_result(result)

    def test_metadata_supplement_inventory_fact_does_not_bypass_score_gate(
        self, monkeypatch
    ):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = self._result(
            source="metadata_supplement",
            chunk_type="fact_line",
            fact_ids=["F_INV_META"],
            markers=["QPACK_INV_META"],
            source_file="qpack_02_inventory_fulfillment.txt",
        )

        assert not CompanyContextBus._is_relevant_knowledge_result(result)

    def test_metadata_supplement_product_fact_does_not_bypass_score_gate(
        self, monkeypatch
    ):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = self._result(
            source="metadata_supplement",
            chunk_type="fact_line",
            fact_ids=["F_PRODUCT_META"],
            markers=["QPACK_PRODUCT_META"],
            source_file="qpack_01_product_manual.txt",
        )

        assert not CompanyContextBus._is_relevant_knowledge_result(result)

    def test_low_score_non_supplement_still_filters(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = self._result(
            source="vector",
            chunk_type="fact_line",
            fact_ids=["F_CONTENT_META"],
            markers=["QPACK_CONTENT_META"],
        )

        assert not CompanyContextBus._is_relevant_knowledge_result(result)

    def test_metadata_supplement_missing_metadata_falls_back_to_score_gate(
        self, monkeypatch
    ):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = SimpleNamespace(
            bm25_score=0.0,
            vector_score=0.0,
            source="metadata_supplement",
            source_file="",
            metadata=None,
        )

        assert not CompanyContextBus._is_relevant_knowledge_result(result)

    def test_keeps_keyword_match(self, monkeypatch):
        monkeypatch.setenv("RAG_MIN_VECTOR_SCORE", "0.55")
        monkeypatch.setenv("RAG_MIN_BM25_SCORE", "0.05")
        result = SimpleNamespace(
            vector_score=0.2,
            bm25_score=0.2,
            source="bm25",
            metadata={"company_id": "co_1"},
        )

        assert CompanyContextBus._is_relevant_knowledge_result(result)

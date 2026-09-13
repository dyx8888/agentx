"""Regression tests for the current company-scoped knowledge backend.

The old tests targeted the removed ``KnowledgeRetrieval`` Chroma/Milvus class.
The production path is now ``CompanyContextBus`` backed by ``HybridRetriever``.
These tests keep the coverage deterministic by replacing the external vector
service with a small in-memory stub while exercising the current contracts.
"""

import json

import pytest

import app.mcp_servers.knowledge_retrieval_server as knowledge_server
import app.rag.hybrid_retriever as hybrid_module
from app.rag.company_context_bus import CompanyContextBus
from app.rag.hybrid_retriever import HybridRetriever


class _FakeEmbeddingService:
    """Deterministic embeddings for tests that intentionally avoid Milvus."""

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def encode_single(self, text):
        return [1.0, 0.0]


def _offline_retriever(company_id: str) -> HybridRetriever:
    retriever = HybridRetriever(company_id=company_id)
    retriever._get_embedding_service = lambda: _FakeEmbeddingService()
    retriever.vector.insert_documents = lambda rows, embeddings: True
    retriever.vector.search = lambda query_vector, top_k=20: []
    retriever.reranker.rerank = lambda query, documents, top_k=10: [
        (index, 0.0) for index in range(min(top_k, len(documents)))
    ]
    return retriever


@pytest.fixture(autouse=True)
def clear_retriever_cache():
    hybrid_module._retriever_cache.clear()
    yield
    hybrid_module._retriever_cache.clear()


def test_current_backend_is_company_scoped_hybrid_retriever():
    retriever = HybridRetriever(company_id="company_A")

    assert retriever.company_id == "company_A"
    assert retriever.vector.company_id == "company_A"
    assert not hasattr(knowledge_server, "KnowledgeRetrieval")


def test_company_context_bus_adds_forced_tenant_metadata(monkeypatch):
    captured = {}

    class StubRetriever:
        def index_documents(self, documents):
            captured["documents"] = documents

    def get_stub(company_id):
        captured["company_id"] = company_id
        return StubRetriever()

    monkeypatch.setattr(hybrid_module, "get_hybrid_retriever", get_stub)
    monkeypatch.setattr(
        CompanyContextBus,
        "_schedule_graph_entity_extraction",
        lambda self, content: None,
    )

    doc_id = CompanyContextBus("company_A").add_knowledge(
        "A-only knowledge", {"company_id": "spoofed", "category": "test"}, doc_id="doc_A"
    )

    assert doc_id == "doc_A"
    assert captured["company_id"] == "company_A"
    document = captured["documents"][0]
    assert document["id"] == "doc_A"
    assert document["content"] == "A-only knowledge"
    assert document["metadata"]["company_id"] == "company_A"
    assert document["metadata"]["layer"] == "knowledge"


def test_company_context_bus_search_uses_current_hybrid_contract(monkeypatch):
    retrievers = {
        "company_A": _offline_retriever("company_A"),
        "company_B": _offline_retriever("company_B"),
    }
    monkeypatch.setattr(hybrid_module, "get_hybrid_retriever", retrievers.__getitem__)

    for company_id, content in (
        ("company_A", "Company A secret knowledge"),
        ("company_B", "Company B secret knowledge"),
    ):
        retrievers[company_id].index_documents(
            [{"id": f"{company_id}-doc", "content": content, "metadata": {}}]
        )

    results_a = CompanyContextBus("company_A").search_knowledge("secret knowledge", top_k=5)
    results_b = CompanyContextBus("company_B").search_knowledge("secret knowledge", top_k=5)

    assert [item["content"] for item in results_a] == ["Company A secret knowledge"]
    assert [item["content"] for item in results_b] == ["Company B secret knowledge"]
    assert all(item["metadata"]["company_id"] == "company_A" for item in results_a)
    assert all(item["metadata"]["company_id"] == "company_B" for item in results_b)


def test_mcp_wrapper_returns_tool_result_json_and_company_scope(monkeypatch):
    calls = []

    class StubBus:
        def search_knowledge(self, query, top_k=5):
            calls.append(("search", query, top_k))
            return []

        def add_knowledge(self, content, metadata=None):
            calls.append(("add", content, metadata))
            return "doc_A"

    monkeypatch.setattr(knowledge_server, "_get_bus_for_company", lambda company_id: StubBus())

    search_result = json.loads(
        knowledge_server.search_knowledge("query", n_results=2, company_id="company_A")
    )
    add_result = json.loads(
        knowledge_server.add_knowledge("content", {"category": "test"}, company_id="company_A")
    )

    assert search_result == {"status": "ok", "data": []}
    assert add_result["status"] == "ok"
    assert add_result["data"] == {"doc_id": "doc_A"}
    assert calls == [("search", "query", 2), ("add", "content", {"category": "test"})]

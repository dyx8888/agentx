"""Current multi-tenant knowledge isolation contracts."""

from app.rag import hybrid_retriever as hybrid_module
from app.rag.company_context_bus import CompanyContextBus
from app.rag.hybrid_retriever import HybridRetriever


class _Embedding:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def encode_single(self, text):
        return [1.0, 0.0]


def _retriever(company_id):
    retriever = HybridRetriever(company_id)
    retriever._get_embedding_service = lambda: _Embedding()
    retriever.vector.insert_documents = lambda rows, embeddings: True
    retriever.vector.search = lambda query_vector, top_k=20: []
    retriever.reranker.rerank = lambda query, documents, top_k=10: [
        (index, 0.0) for index in range(min(top_k, len(documents)))
    ]
    return retriever


def test_company_context_bus_forces_company_id_on_write(monkeypatch):
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

    CompanyContextBus("company_A").add_knowledge(
        "A-only knowledge", {"company_id": "company_B"}, doc_id="doc_A"
    )

    assert captured["company_id"] == "company_A"
    assert captured["documents"][0]["metadata"]["company_id"] == "company_A"


def test_company_context_bus_search_cannot_cross_contaminate(monkeypatch):
    retrievers = {"company_A": _retriever("company_A"), "company_B": _retriever("company_B")}
    monkeypatch.setattr(hybrid_module, "get_hybrid_retriever", retrievers.__getitem__)

    retrievers["company_A"].index_documents(
        [{"id": "doc_A", "content": "Company A marketing plan", "metadata": {}}]
    )
    retrievers["company_B"].index_documents(
        [{"id": "doc_B", "content": "Company B launch plan", "metadata": {}}]
    )

    results_a = CompanyContextBus("company_A").search_knowledge("plan", top_k=5)
    results_b = CompanyContextBus("company_B").search_knowledge("plan", top_k=5)

    assert [item["content"] for item in results_a] == ["Company A marketing plan"]
    assert [item["content"] for item in results_b] == ["Company B launch plan"]
    assert all(item["metadata"]["company_id"] == "company_A" for item in results_a)
    assert all(item["metadata"]["company_id"] == "company_B" for item in results_b)


def test_company_context_bus_instances_are_scoped_by_id(monkeypatch):
    retrievers = {"company_A": _retriever("company_A"), "company_B": _retriever("company_B")}
    monkeypatch.setattr(hybrid_module, "get_hybrid_retriever", retrievers.__getitem__)

    bus_a = CompanyContextBus("company_A")
    bus_b = CompanyContextBus("company_B")

    assert bus_a.company_id != bus_b.company_id
    assert retrievers[bus_a.company_id].company_id == "company_A"
    assert retrievers[bus_b.company_id].company_id == "company_B"

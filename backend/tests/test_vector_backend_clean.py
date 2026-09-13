"""Offline retrieval tests for the lightweight/local part of HybridRetriever."""

from app.rag.hybrid_retriever import BM25Retriever, HybridRetriever


def test_bm25_supports_chinese_without_external_vector_service():
    retriever = BM25Retriever()
    retriever.index(["本品牌主推轻薄防晒衣，核心卖点是冰感透气。"], ["doc_A"])

    results = retriever.search("防晒衣 冰感", top_k=3)

    assert results
    assert results[0][0] == 0
    assert results[0][1] > 0


def test_hybrid_index_keeps_document_id_and_tenant_metadata(monkeypatch):
    retriever = HybridRetriever(company_id="company_A")
    retriever._get_embedding_service = lambda: type(
        "Embedding", (), {"encode": lambda self, texts: [[1.0, 0.0] for _ in texts]}
    )()
    inserted = []
    monkeypatch.setattr(
        retriever.vector,
        "insert_documents",
        lambda rows, embeddings: inserted.extend(rows) or True,
    )

    retriever.index_documents(
        [{"id": "doc_A", "content": "A-only content", "metadata": {"category": "test"}}]
    )

    assert retriever._documents["doc_A"]["metadata"]["company_id"] == "company_A"
    assert inserted[0]["id"] == "doc_A"
    assert inserted[0]["metadata"]["company_id"] == "company_A"

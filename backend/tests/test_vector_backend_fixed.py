"""Regression tests for tenant-safe vector operations."""

from app.rag.hybrid_retriever import HybridRetriever, VectorRetriever


def test_vector_retriever_is_scoped_to_company_id():
    retriever_a = VectorRetriever(company_id="company_A")
    retriever_b = VectorRetriever(company_id="company_B")

    assert retriever_a.company_id == "company_A"
    assert retriever_b.company_id == "company_B"
    assert retriever_a.company_id != retriever_b.company_id


def test_milvus_expression_escapes_tenant_and_document_values():
    payload = 'company_A" or "1"=="1'
    escaped = HybridRetriever._escape_milvus_expr(payload)
    expression = f'company_id == "{escaped}"'

    assert escaped.count('\\"') == payload.count('"')
    assert '\\" or \\"' in expression


def test_rrf_fusion_merges_same_document_by_document_id():
    retriever = HybridRetriever(company_id="company_A")
    retriever.bm25.index(["A-only content"], ["doc_A"])
    retriever._documents["doc_A"] = {
        "id": "doc_A",
        "content": "A-only content",
        "metadata": {"company_id": "company_A"},
    }

    fused = retriever._rrf_fuse(
        [(0, 2.0)],
        [("doc_A", "A-only content", 0.9, '{"company_id": "company_A"}')],
        0.3,
        0.7,
    )

    assert list(fused) == ["doc_A"]
    assert fused["doc_A"].source == "hybrid"
    assert fused["doc_A"].metadata["company_id"] == "company_A"

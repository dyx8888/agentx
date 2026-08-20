from app.core import config
from app.rag import company_context_bus, doc_status, document_parser, hybrid_retriever


class FakeRetriever:
    def __init__(self):
        self.indexed_docs = []

    def index_documents(self, docs):
        self.indexed_docs.extend(docs)


def _ingest_with_mode(monkeypatch, mode):
    status_mgr = doc_status.get_doc_status_manager()
    status_mgr.clear()
    retriever = FakeRetriever()
    text = """售后政策：
适用条件：未拆封且不影响二次销售，支持7天无理由退货。
例外：质量问题由商家承担运费，平台规则优先。
"""

    if mode is None:
        monkeypatch.setattr(config, "RAG_CHUNKER_MODE", "recursive", raising=False)
    else:
        monkeypatch.setattr(config, "RAG_CHUNKER_MODE", mode, raising=False)

    monkeypatch.setattr(
        document_parser.DocumentParser,
        "parse",
        staticmethod(lambda filename, content: text),
    )
    monkeypatch.setattr(hybrid_retriever, "get_hybrid_retriever", lambda company_id: retriever)

    result = company_context_bus.CompanyContextBus("7").ingest_document(
        filename="policy.txt",
        content=b"ignored",
        metadata={"category": "policy", "source": "file_upload"},
    )
    return result, retriever


def test_default_chunker_mode_uses_recursive(monkeypatch):
    result, retriever = _ingest_with_mode(monkeypatch, None)

    assert result["chunks"] == len(retriever.indexed_docs)
    metadata = retriever.indexed_docs[0]["metadata"]
    assert metadata["document_id"] == result["doc_id"]
    assert metadata["source_file"] == "policy.txt"
    assert metadata["company_id"] == "7"
    assert metadata["layer"] == "knowledge"
    assert "chunk_type" not in metadata


def test_explicit_recursive_mode_uses_recursive(monkeypatch):
    _, retriever = _ingest_with_mode(monkeypatch, "recursive")

    metadata = retriever.indexed_docs[0]["metadata"]
    assert "chunk_type" not in metadata
    assert metadata["chunk_index"] == 0
    assert metadata["total_chunks"] == len(retriever.indexed_docs)


def test_smart_mode_indexes_smart_chunk_metadata(monkeypatch):
    result, retriever = _ingest_with_mode(monkeypatch, "smart")

    assert result["chunks"] == len(retriever.indexed_docs)
    smart_doc = next(
        doc for doc in retriever.indexed_docs if doc["metadata"].get("chunk_type") == "numbered_rule"
    )
    metadata = smart_doc["metadata"]
    assert "适用条件" in smart_doc["content"]
    assert "例外" in smart_doc["content"]
    assert metadata["section_title"] == "售后政策："
    assert metadata["line_start"] == 2
    assert metadata["line_end"] == 3
    assert metadata["has_policy_keywords"] is True


def test_smart_mode_preserves_existing_document_contract(monkeypatch):
    result, retriever = _ingest_with_mode(monkeypatch, "smart")
    total_chunks = len(retriever.indexed_docs)

    for index, doc in enumerate(retriever.indexed_docs):
        metadata = doc["metadata"]
        assert metadata["document_id"] == result["doc_id"]
        assert metadata["source_file"] == "policy.txt"
        assert metadata["original_filename"] == "policy.txt"
        assert metadata["company_id"] == "7"
        assert metadata["layer"] == "knowledge"
        assert metadata["chunk_index"] == index
        assert metadata["total_chunks"] == total_chunks


def test_invalid_chunker_mode_falls_back_to_recursive(monkeypatch):
    _, retriever = _ingest_with_mode(monkeypatch, "unknown")

    metadata = retriever.indexed_docs[0]["metadata"]
    assert "chunk_type" not in metadata
    assert metadata["source_file"] == "policy.txt"

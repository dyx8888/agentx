from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import knowledge
from app.rag import company_context_bus, doc_status, document_parser, hybrid_retriever


class FakeRetriever:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.indexed_docs = []

    def index_documents(self, docs):
        self.indexed_docs.extend(docs)

    def list_documents(self):
        return list(self.docs)


def test_ingest_document_tracks_returned_document_id(monkeypatch):
    status_mgr = doc_status.get_doc_status_manager()
    status_mgr.clear()
    retriever = FakeRetriever()

    monkeypatch.setattr(
        document_parser.DocumentParser,
        "parse",
        staticmethod(lambda filename, content: "灵鹿小黑瓶合成知识\nstrict_rag_answer_4271"),
    )
    monkeypatch.setattr(hybrid_retriever, "get_hybrid_retriever", lambda company_id: retriever)

    bus = company_context_bus.CompanyContextBus("7")
    result = bus.ingest_document(
        filename="synthetic.txt",
        content=b"ignored",
        metadata={"category": "general", "source": "file_upload"},
    )

    assert result["doc_id"]
    assert result["chunks"] == len(retriever.indexed_docs)
    assert retriever.indexed_docs
    assert all(doc["metadata"]["document_id"] == result["doc_id"] for doc in retriever.indexed_docs)

    status = status_mgr.get(result["doc_id"])
    assert status is not None
    assert status.is_fully_processed
    assert status.text_chunk_count == result["chunks"]


def test_documents_list_and_status_use_parent_document_id(monkeypatch):
    doc_status.get_doc_status_manager().clear()
    calls = []
    retriever = FakeRetriever(
        [
            {
                "id": "chunk_a",
                "filename": "synthetic.txt",
                "category": "general",
                "source": "file_upload",
                "total_chunks": 2,
                "metadata": {"document_id": "parent_doc_123", "company_id": "7"},
            }
        ]
    )

    def fake_get_hybrid_retriever(company_id):
        calls.append(str(company_id))
        return retriever

    monkeypatch.setattr(hybrid_retriever, "get_hybrid_retriever", fake_get_hybrid_retriever)
    current_user = SimpleNamespace(company_id=7)

    listed = knowledge.list_documents(
        company_id="999",
        category=None,
        current_user=current_user,
    )

    assert calls[-1] == "7"
    assert listed.total == 1
    assert listed.documents[0].id == "parent_doc_123"
    assert listed.documents[0].chunks == 2

    status = knowledge.get_document_status("parent_doc_123", current_user=current_user)
    assert status.doc_id == "parent_doc_123"
    assert status.is_fully_processed


def test_documents_list_requires_authenticated_company():
    with pytest.raises(HTTPException) as exc_info:
        knowledge.list_documents(
            company_id="7",
            category=None,
            current_user=SimpleNamespace(company_id=None),
        )

    assert exc_info.value.status_code == 403


def test_documents_list_filters_category_without_cross_company_query(monkeypatch):
    calls = []
    retriever = FakeRetriever(
        [
            {
                "id": "chunk_a",
                "filename": "a.txt",
                "category": "general",
                "source": "file_upload",
                "total_chunks": 1,
                "metadata": {"document_id": "doc_a", "company_id": "7"},
            },
            {
                "id": "chunk_b",
                "filename": "b.txt",
                "category": "policy",
                "source": "file_upload",
                "total_chunks": 1,
                "metadata": {"document_id": "doc_b", "company_id": "7"},
            },
        ]
    )

    def fake_get_hybrid_retriever(company_id):
        calls.append(str(company_id))
        return retriever

    monkeypatch.setattr(hybrid_retriever, "get_hybrid_retriever", fake_get_hybrid_retriever)

    listed = knowledge.list_documents(
        company_id="999",
        category="policy",
        current_user=SimpleNamespace(company_id=7),
    )

    assert calls == ["7"]
    assert listed.total == 1
    assert listed.documents[0].id == "doc_b"
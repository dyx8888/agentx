from types import SimpleNamespace

import app.perception.rag_retriever as rag_retriever_module
import app.rag.agentic_rag as agentic_rag
from app.perception.rag_retriever import RagRetriever


def test_production_default_uses_lightweight_backend_without_milvus_probe(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("VECTOR_DB", raising=False)
    monkeypatch.delenv("MILVUS_HOST", raising=False)
    monkeypatch.setattr(
        rag_retriever_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("lightweight RAG must not probe Milvus")
        ),
    )

    assert RagRetriever._external_backend_available() is True


def test_production_explicit_milvus_uses_lightweight_backend_without_probe(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("VECTOR_DB", "milvus")
    monkeypatch.delenv("RAG_LIGHTWEIGHT_MODE", raising=False)
    monkeypatch.setattr(
        rag_retriever_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("lightweight RAG must not probe Milvus")
        ),
    )

    assert RagRetriever._external_backend_available() is True


def test_retriever_retries_after_a_transient_backend_failure(monkeypatch):
    attempts = []
    now = 100.0
    monkeypatch.setenv("RAG_RETRY_INTERVAL_SECONDS", "5")
    monkeypatch.setattr(rag_retriever_module.time, "monotonic", lambda: now)
    monkeypatch.setattr(
        RagRetriever,
        "_external_backend_available",
        staticmethod(lambda: attempts.append("preflight") or len(attempts) > 1),
    )
    monkeypatch.setattr(
        agentic_rag,
        "get_agentic_rag",
        lambda _company_id: SimpleNamespace(
            retrieve_structured=lambda **_kwargs: {
                "context": "recovered context",
                "knowledge_results": [],
                "experience_results": [],
            }
        ),
    )

    retriever = RagRetriever()
    first = retriever.retrieve("query", "company", "master", "general")
    now = 102.0
    during_cooldown = retriever.retrieve("query", "company", "master", "general")
    now = 106.0
    second = retriever.retrieve("query", "company", "master", "general")

    assert first.context == ""
    assert during_cooldown.context == ""
    assert second.context == "recovered context"
    assert attempts == ["preflight", "preflight"]
    assert retriever._available is True


def test_retriever_uses_structured_context_without_a_second_retrieval(monkeypatch):
    calls = []
    monkeypatch.setattr(RagRetriever, "_external_backend_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        agentic_rag,
        "get_agentic_rag",
        lambda _company_id: SimpleNamespace(
            retrieve=lambda **_kwargs: calls.append("retrieve"),
            retrieve_structured=lambda **_kwargs: (
                calls.append("structured")
                or {
                    "context": "one retrieval context",
                    "knowledge_results": [
                        {"content": "evidence", "source_file": "test.txt"}
                    ],
                    "experience_results": [],
                }
            ),
        ),
    )

    result = RagRetriever().retrieve("query", "company", "master", "general")

    assert result.context == "one retrieval context"
    assert calls == ["structured"]

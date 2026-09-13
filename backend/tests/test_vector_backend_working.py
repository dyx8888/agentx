"""Contract tests for the working knowledge retrieval MCP wrapper."""

import json

import app.mcp_servers.knowledge_retrieval_server as knowledge_server


def test_search_wrapper_maps_structured_hybrid_result(monkeypatch):
    class StubBus:
        def search_knowledge(self, query, top_k=5):
            return [
                {
                    "content": "retrieved content",
                    "metadata": {"company_id": "company_A"},
                    "score": 0.8,
                    "source": "hybrid",
                    "bm25_score": 1.2,
                    "vector_score": 0.9,
                    "rrf_score": 0.02,
                    "rerank_score": 0.8,
                    "source_file": "manual.txt",
                    "chunk_index": 1,
                    "source_page": 2,
                }
            ]

    monkeypatch.setattr(knowledge_server, "_get_bus_for_company", lambda company_id: StubBus())

    result = json.loads(
        knowledge_server.search_knowledge("query", n_results=1, company_id="company_A")
    )

    assert result["status"] == "ok"
    item = result["data"][0]
    assert item["content"] == "retrieved content"
    assert item["metadata"]["company_id"] == "company_A"
    assert item["source"] == "hybrid"
    assert item["source_file"] == "manual.txt"


def test_search_wrapper_returns_error_result_when_backend_fails(monkeypatch):
    def fail(_company_id):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(knowledge_server, "_get_bus_for_company", fail)

    result = json.loads(
        knowledge_server.search_knowledge("query", n_results=1, company_id="company_A")
    )

    assert result["status"] == "error"
    assert result["error_code"] == "CONNECTION_ERROR"

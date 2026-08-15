"""Local regression tests for Knowledge Management API endpoints."""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.knowledge as knowledge_api
from app.main import app


@pytest.fixture()
def knowledge_client(monkeypatch):
    """Use fake auth and in-memory knowledge functions; never touch Milvus."""
    store = {}
    user = SimpleNamespace(
        id=1,
        username="testuser",
        email="test@example.com",
        company_id=1,
        is_admin=False,
    )

    def fake_add_knowledge(text, metadata, company_id):
        doc_id = f"mock_{len(store) + 1}"
        store[doc_id] = {
            "content": text,
            "metadata": metadata,
            "company_id": company_id,
        }
        return json.dumps({"status": "ok", "data": {"doc_id": doc_id}})

    def fake_search_knowledge(query, n_results=3, company_id="default"):
        matched = []
        for item in store.values():
            haystack = json.dumps(item, ensure_ascii=False)
            if query in haystack:
                matched.append({"content": item["content"], "metadata": item["metadata"]})
        if not matched:
            matched = [
                {"content": item["content"], "metadata": item["metadata"]}
                for item in store.values()
            ]
        return json.dumps({"status": "ok", "data": matched[:n_results]})

    monkeypatch.setitem(
        app.dependency_overrides,
        knowledge_api.get_current_active_user,
        lambda: user,
    )
    monkeypatch.setattr(knowledge_api, "add_knowledge", fake_add_knowledge)
    monkeypatch.setattr(knowledge_api, "search_knowledge", fake_search_knowledge)
    monkeypatch.setattr(
        knowledge_api,
        "_invalidate_result_cache_for_company",
        lambda company_id: 0,
    )

    return TestClient(app), store


def test_upload_and_search_knowledge(knowledge_client):
    """上传知识后可以通过当前 /api/knowledge 路由检索。"""
    client, _store = knowledge_client
    upload_response = client.post(
        "/api/knowledge/upload",
        json={
            "content": "我们的产品主打纯天然成分，不含任何化学添加剂，适合敏感肌肤使用。",
            "category": "product",
            "scenario": "product_intro",
            "company_id": "spoofed_company",
        },
    )
    assert upload_response.status_code == 200
    upload_result = upload_response.json()
    assert upload_result["status"] == "success"
    assert upload_result["doc_id"] == "mock_1"

    search_response = client.get(
        "/api/knowledge/search",
        params={"query": "纯天然", "n_results": 5, "company_id": "spoofed_company"},
    )
    assert search_response.status_code == 200
    search_results = search_response.json()
    assert search_results
    assert search_results[0]["metadata"] == {
        "category": "product",
        "scenario": "product_intro",
        "source": "api_upload",
    }


def test_upload_with_category_and_scenario(knowledge_client):
    """上传的 category/scenario 会进入 metadata。"""
    client, _store = knowledge_client
    response = client.post(
        "/api/knowledge/upload",
        json={
            "content": "这款护肤品采用玻尿酸和维生素C配方，深层保湿同时提亮肤色。",
            "category": "beauty",
            "scenario": "product_intro",
            "company_id": "spoofed_company",
        },
    )
    assert response.status_code == 200

    search_response = client.get(
        "/api/knowledge/search",
        params={"query": "玻尿酸", "n_results": 3, "company_id": "spoofed_company"},
    )
    assert search_response.status_code == 200
    result = search_response.json()[0]
    assert result["metadata"]["category"] == "beauty"
    assert result["metadata"]["scenario"] == "product_intro"
    assert result["metadata"]["source"] == "api_upload"


def test_structured_import_preserves_source_metadata(knowledge_client):
    """结构化导入保留来源字段，便于 RAG 质量追溯。"""
    client, _store = knowledge_client
    response = client.post(
        "/api/knowledge/import",
        json={
            "items": [
                {
                    "content": "RAGIMPORT-001：青竹护肤晚 8 点直播间 GMV 增长 18.6%。",
                    "category": "business_metric",
                    "scenario": "live_ops",
                    "title": "直播 GMV 复盘",
                    "external_id": "manual-row-001",
                    "data_source": "manual_upload",
                    "source_url": "https://example.com/report",
                    "source_note": "用户手工整理的业务复盘",
                    "tags": ["GMV", "直播", "GMV"],
                }
            ],
            "dry_run": False,
        },
    )
    assert response.status_code == 200
    import_result = response.json()
    assert import_result["imported"] == 1
    assert import_result["skipped"] == 0
    assert import_result["dry_run"] is False
    assert import_result["data_source_summary"] == {"manual_upload": 1}
    assert import_result["data_source_warning"] is not None
    assert import_result["doc_ids"] == ["mock_1"]

    search_response = client.get(
        "/api/knowledge/search",
        params={"query": "RAGIMPORT-001", "n_results": 5, "company_id": "spoofed_company"},
    )
    assert search_response.status_code == 200
    metadata = search_response.json()[0]["metadata"]
    assert metadata["source"] == "structured_import"
    assert metadata["data_source"] == "manual_upload"
    assert metadata["source_url"] == "https://example.com/report"
    assert metadata["source_note"] == "用户手工整理的业务复盘"
    assert metadata["external_id"] == "manual-row-001"
    assert metadata["tags"] == ["GMV", "直播"]


def test_import_dry_run_does_not_write(knowledge_client):
    """dry_run=True 只校验，不写入 fake knowledge store。"""
    client, store = knowledge_client
    response = client.post(
        "/api/knowledge/import",
        json={
            "dry_run": True,
            "items": [
                {
                    "content": "RAGIMPORT-DRYRUN：仅校验不写入。",
                    "category": "qa",
                    "scenario": "dry_run",
                    "data_source": "public_web",
                }
            ],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["imported"] == 1
    assert result["dry_run"] is True
    assert result["doc_ids"] == []
    assert store == {}


@pytest.mark.parametrize("data_source", ["seed", "mock", "demo", "sample"])
def test_structured_import_rejects_demo_sources(knowledge_client, data_source):
    """正式导入不能静默接受 seed/mock/demo/sample 数据。"""
    client, store = knowledge_client
    response = client.post(
        "/api/knowledge/import",
        json={
            "items": [
                {
                    "content": "这条演示数据不应进入正式知识库。",
                    "category": "qa",
                    "scenario": "unsafe_source",
                    "data_source": data_source,
                }
            ]
        },
    )
    assert response.status_code == 422
    assert store == {}


def test_search_exposes_retrieval_evidence_fields(knowledge_client, monkeypatch):
    """检索响应暴露 RAG 质量追踪需要的证据字段。"""
    client, _store = knowledge_client

    def search_with_evidence(query, n_results, company_id):
        return json.dumps(
            {
                "status": "ok",
                "data": [
                    {
                        "content": "RAGEVIDENCE-001 hybrid retrieval result",
                        "metadata": {"category": "qa"},
                        "distance": 0.12,
                        "score": 0.73,
                        "source": "hybrid",
                        "bm25_score": 4.2,
                        "vector_score": 0.86,
                        "rrf_score": 0.021,
                        "rerank_score": 0.73,
                        "source_file": "manual_import.csv",
                        "chunk_index": 2,
                        "source_page": 0,
                    }
                ],
            }
        )

    monkeypatch.setattr(knowledge_api, "search_knowledge", search_with_evidence)
    response = client.get(
        "/api/knowledge/search",
        params={"query": "RAGEVIDENCE-001", "n_results": 1, "company_id": "spoofed_company"},
    )

    assert response.status_code == 200
    result = response.json()[0]
    assert result["source"] == "hybrid"
    assert result["bm25_score"] == 4.2
    assert result["vector_score"] == 0.86
    assert result["rrf_score"] == 0.021
    assert result["rerank_score"] == 0.73
    assert result["source_file"] == "manual_import.csv"
    assert result["chunk_index"] == 2


def test_search_timeout_returns_504(knowledge_client, monkeypatch):
    """慢检索必须可见失败，不能挂住客户端。"""
    client, _store = knowledge_client

    def slow_search(query, n_results, company_id):
        time.sleep(0.2)
        return json.dumps({"status": "ok", "data": []})

    monkeypatch.setattr(knowledge_api, "KNOWLEDGE_SEARCH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(knowledge_api, "search_knowledge", slow_search)

    response = client.get(
        "/api/knowledge/search",
        params={"query": "timeout smoke", "n_results": 3, "company_id": "spoofed_company"},
    )

    assert response.status_code == 504
    assert "timed out" in json.dumps(response.json())


def test_upload_empty_content(knowledge_client):
    """空内容或空白内容不能写入知识库。"""
    client, store = knowledge_client
    response = client.post(
        "/api/knowledge/upload",
        json={
            "content": "",
            "category": "test",
            "scenario": "test",
            "company_id": "spoofed_company",
        },
    )
    assert response.status_code == 422

    response = client.post(
        "/api/knowledge/upload",
        json={
            "content": "   ",
            "category": "test",
            "scenario": "test",
            "company_id": "spoofed_company",
        },
    )
    assert response.status_code == 400
    assert store == {}


def test_search_missing_company_id(knowledge_client):
    """API 合同仍要求传入 company_id 参数，但实际隔离使用认证用户。"""
    client, _store = knowledge_client
    response = client.get("/api/knowledge/search", params={"query": "test", "n_results": 3})
    assert response.status_code == 422

    response = client.get(
        "/api/knowledge/search",
        params={"query": "test", "n_results": 3, "company_id": ""},
    )
    assert response.status_code in [200, 422]


def test_upload_content_length_limit(knowledge_client):
    """内容长度边界保持稳定。"""
    client, _store = knowledge_client
    response = client.post(
        "/api/knowledge/upload",
        json={
            "content": "a" * 5001,
            "category": "test",
            "scenario": "test",
            "company_id": "spoofed_company",
        },
    )
    assert response.status_code == 422

    response = client.post(
        "/api/knowledge/upload",
        json={
            "content": "a" * 5000,
            "category": "test",
            "scenario": "test",
            "company_id": "spoofed_company",
        },
    )
    assert response.status_code == 200


def test_search_query_validation(knowledge_client):
    """空检索词返回 400。"""
    client, _store = knowledge_client
    response = client.get(
        "/api/knowledge/search",
        params={"query": "", "n_results": 3, "company_id": "spoofed_company"},
    )
    assert response.status_code == 400
    assert "Query cannot be empty" in json.dumps(response.json())

    response = client.get(
        "/api/knowledge/search",
        params={"query": "   ", "n_results": 3, "company_id": "spoofed_company"},
    )
    assert response.status_code == 400


def test_n_results_validation(knowledge_client):
    """检索结果数量限制保持在 1 到 20。"""
    client, _store = knowledge_client
    response = client.get(
        "/api/knowledge/search",
        params={"query": "test", "n_results": 0, "company_id": "spoofed_company"},
    )
    assert response.status_code == 422

    response = client.get(
        "/api/knowledge/search",
        params={"query": "test", "n_results": 21, "company_id": "spoofed_company"},
    )
    assert response.status_code == 422

    response = client.get(
        "/api/knowledge/search",
        params={"query": "test", "n_results": 15, "company_id": "spoofed_company"},
    )
    assert response.status_code == 200


def test_default_values(knowledge_client):
    """未显式传 category/scenario 时使用默认 metadata。"""
    client, _store = knowledge_client
    response = client.post(
        "/api/knowledge/upload",
        json={"content": "测试默认值的内容", "company_id": "spoofed_company"},
    )
    assert response.status_code == 200

    response = client.get(
        "/api/knowledge/search",
        params={"query": "默认值", "company_id": "spoofed_company"},
    )
    assert response.status_code == 200
    result = response.json()[0]
    assert result["metadata"]["category"] == "general"
    assert result["metadata"]["scenario"] == "general"
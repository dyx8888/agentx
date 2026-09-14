from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers, UploadFile

import app.database as database_module
from app.api import knowledge
from app.database.models import Base, CompanyKnowledge
from app.rag.company_context_bus import CompanyContextBus
from app.rag.graph_rag import GraphRAGRetriever
from app.rag.hybrid_retriever import HybridRetriever


def test_lightweight_package_import_keeps_optional_rag_stacks_unloaded():
    backend_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "ENV": "prod",
            "RAG_LIGHTWEIGHT_MODE": "true",
            "PYTHONPATH": str(backend_root),
        }
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.rag; "
                "from app.rag import CompanyContextBus, HybridRetriever; "
                "blocked=('pymilvus', 'app.rag.llamaindex_retriever', "
                "'app.rag.multimodal_retriever', 'app.rag.rag_evaluator'); "
                "loaded=[name for name in blocked if name in sys.modules]; "
                "assert not loaded, loaded; "
                "assert CompanyContextBus and HybridRetriever"
            ),
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr or probe.stdout


def test_lightweight_memory_manager_skips_optional_backend_imports():
    backend_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "ENV": "prod",
            "RAG_LIGHTWEIGHT_MODE": "true",
            "PYTHONPATH": str(backend_root),
        }
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import builtins; "
                "real_import=builtins.__import__; "
                "builtins.__import__=lambda name,*args,**kwargs: "
                "(_ for _ in ()).throw(AssertionError(name)) "
                "if name.split('.')[0] in {'redis','pymilvus'} "
                "else real_import(name,*args,**kwargs); "
                "from app.runtime.memory import memory_manager; "
                "assert memory_manager._redis is None; "
                "assert memory_manager._milvus is None; "
                "assert memory_manager._milvus_connected is False"
            ),
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr or probe.stdout


class _DatabaseFixture:
    def __init__(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def get_session(self):
        return self._session_factory()


def test_lightweight_rag_persists_and_recovers_without_embedding(monkeypatch):
    database = _DatabaseFixture()
    monkeypatch.setattr(database_module, "db", database)
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("RAG_LIGHTWEIGHT_MODE", "true")
    monkeypatch.setenv("VECTOR_DB", "milvus")

    first = HybridRetriever(company_id="1")
    monkeypatch.setattr(
        first,
        "_get_embedding_service",
        lambda: (_ for _ in ()).throw(AssertionError("embedding must remain unloaded")),
    )
    first.index_documents(
        [
            {
                "id": "chunk-low-memory-1",
                "content": "LIGHTWEIGHT-RAG-UNIQUE 低内存检索资料",
                "metadata": {
                    "layer": "knowledge",
                    "company_id": "1",
                    "document_id": "document-low-memory",
                    "category": "smoke",
                    "source": "file_upload",
                    "source_file": "low-memory.txt",
                    "total_chunks": 1,
                },
            }
        ]
    )

    with database.get_session() as session:
        assert session.query(CompanyKnowledge).count() == 1

    recovered = HybridRetriever(company_id="1")
    monkeypatch.setattr(
        recovered,
        "_get_embedding_service",
        lambda: (_ for _ in ()).throw(AssertionError("embedding must remain unloaded")),
    )
    results = recovered.search("LIGHTWEIGHT-RAG-UNIQUE", top_k=3)

    assert recovered.vector.enabled is False
    assert recovered.reranker.enabled is False
    assert results
    assert results[0].content == "LIGHTWEIGHT-RAG-UNIQUE 低内存检索资料"
    assert results[0].metadata["document_id"] == "document-low-memory"

    other_company = HybridRetriever(company_id="2")
    assert other_company.search("LIGHTWEIGHT-RAG-UNIQUE", top_k=3) == []

    assert recovered.delete_document("document-low-memory") is True
    after_delete = HybridRetriever(company_id="1")
    assert after_delete.search("LIGHTWEIGHT-RAG-UNIQUE", top_k=3) == []


@pytest.mark.asyncio
async def test_file_upload_moves_blocking_ingest_to_threadpool(monkeypatch):
    calls: list[str] = []

    class _Bus:
        def ingest_document(self, *, filename, content, metadata):
            calls.append("ingest")
            assert filename == "smoke.txt"
            assert content == b"threadpool smoke"
            assert metadata["source"] == "file_upload"
            return {
                "doc_id": "doc-threadpool",
                "filename": filename,
                "chunks": 1,
                "text_length": len(content),
            }

    async def fake_run_in_threadpool(func, *args, **kwargs):
        calls.append("threadpool")
        return func(*args, **kwargs)

    monkeypatch.setattr(knowledge, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(knowledge, "_invalidate_result_cache_for_company", lambda _company: 0)

    from app.rag import company_context_bus

    monkeypatch.setattr(company_context_bus, "get_company_context_bus", lambda _company: _Bus())
    upload = UploadFile(
        BytesIO(b"threadpool smoke"),
        filename="smoke.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    result = await knowledge.upload_knowledge_file(
        file=upload,
        company_id="spoofed",
        category="general",
        current_user=SimpleNamespace(company_id=1),
    )

    assert result.status == "success"
    assert result.doc_id == "doc-threadpool"
    assert calls == ["threadpool", "ingest"]


def test_lightweight_graph_matching_does_not_load_embedding(monkeypatch):
    monkeypatch.setenv("RAG_LIGHTWEIGHT_MODE", "true")
    graph = GraphRAGRetriever()
    monkeypatch.setattr(graph, "_get_all_entity_names", lambda: ["抖音", "小红书"])

    import app.rag.embedding_service as embedding_module

    monkeypatch.setattr(
        embedding_module,
        "get_embedding_service",
        lambda: (_ for _ in ()).throw(AssertionError("embedding must remain unloaded")),
    )

    assert graph._find_best_match_entity("未知营销平台") is None


def test_lightweight_ingest_rejects_oversized_extracted_text(monkeypatch):
    monkeypatch.setenv("RAG_LIGHTWEIGHT_MODE", "true")
    monkeypatch.setenv("RAG_LIGHTWEIGHT_MAX_TEXT_CHARS", "10")

    from app.rag.document_parser import DocumentParser

    monkeypatch.setattr(DocumentParser, "parse", lambda _filename, _content: "x" * 11)

    with pytest.raises(ValueError, match="lightweight RAG limit"):
        CompanyContextBus("test").ingest_document("oversized.txt", b"small input")

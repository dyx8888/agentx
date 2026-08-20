from types import SimpleNamespace

import pytest

from app.agents.master_router import MasterAgentRouter
from app.api import chat
from app.perception.context_package import ContextPackage
from app.perception.pipeline import PerceptionPipeline
from app.perception.rag_retriever import RagRetriever, RagResult


class _FakeRag:
    def __init__(self, content):
        self.content = content

    def retrieve(self, **_kwargs):
        return "context"

    def retrieve_structured(self, **_kwargs):
        return {
            "knowledge_results": [
                {
                    "content": self.content,
                    "source_file": "qpack.txt",
                    "source_page": 0,
                    "score": 0.91,
                    "source": "hybrid",
                    "chunk_index": 3,
                    "metadata": {"document_id": "doc-1"},
                }
            ],
            "experience_results": [],
        }


def test_rag_retriever_separates_compact_references_and_richer_evidence(monkeypatch):
    late_fact = "F_UPDATE_003 appears after the compact reference window"
    content = "A" * 240 + late_fact

    import app.rag.agentic_rag as agentic_rag

    monkeypatch.setattr(RagRetriever, "_external_backend_available", staticmethod(lambda: True))
    monkeypatch.setattr(agentic_rag, "get_agentic_rag", lambda _company_id: _FakeRag(content))

    result = RagRetriever().retrieve(
        query="inventory question",
        company_id="65",
        agent_name="master",
        intent_type="knowledge",
    )

    assert result.references
    assert result.evidence_chunks
    assert len(result.references[0]["content"]) == 200
    assert late_fact not in result.references[0]["content"]
    assert late_fact in result.evidence_chunks[0]["content"]
    assert len(result.evidence_chunks[0]["content"]) <= 800


class _IntentType:
    value = "knowledge"


class _MemoryResult:
    cache_hit = False
    direct_return = None
    cache_key = "cache-key"
    memory_context = []
    similar_answers = []


@pytest.mark.asyncio
async def test_context_package_carries_references_evidence_and_legacy_chunks(monkeypatch):
    compact = [{"content": "compact source", "source_file": "qpack.txt"}]
    evidence = [{"content": "full evidence with F_UPDATE_003", "source_file": "qpack.txt"}]

    pipeline = PerceptionPipeline(pre_retrieval_layer=object())
    monkeypatch.setattr(
        pipeline,
        "run",
        lambda **_kwargs: SimpleNamespace(
            rewritten_query="question",
            filtered_input="question",
            intent=SimpleNamespace(intent_type=_IntentType(), entities={}),
        ),
    )

    async def fake_memory(**_kwargs):
        return _MemoryResult()

    monkeypatch.setattr(pipeline, "_run_memory_retriever", fake_memory)
    monkeypatch.setattr(
        pipeline._rag_retriever,
        "retrieve",
        lambda **_kwargs: RagResult(
            context="context",
            references=compact,
            evidence_chunks=evidence,
        ),
    )
    monkeypatch.setattr(pipeline, "_run_skill_matcher", lambda **_kwargs: [])
    monkeypatch.setattr(pipeline, "_run_tool_context_builder", lambda **_kwargs: ([], []))
    monkeypatch.setattr(pipeline, "_build_company_context", lambda _company_id: {})

    package = await pipeline.build_context_package(raw_input="question", company_id="65")

    assert package.rag_references == compact
    assert package.rag_evidence_chunks == evidence
    assert package.rag_chunks == compact
    as_dict = package.to_dict()
    assert as_dict["rag_references_count"] == 1
    assert as_dict["rag_evidence_chunks_count"] == 1


class _FakeResponse:
    content = "answer"
    response_metadata = {}


class _CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def ainvoke(self, messages, **_kwargs):
        self.prompt = "\n".join(getattr(message, "content", "") for message in messages)
        return _FakeResponse()


class _FakeGateway:
    def __init__(self):
        self.llm = _CapturingLLM()

    def get_llm(self, *args, **_kwargs):
        return self.llm


@pytest.mark.asyncio
async def test_master_router_prefers_evidence_chunks_over_compact_rag_chunks():
    gateway = _FakeGateway()
    router = MasterAgentRouter(model_gateway=gateway)
    context = ContextPackage(
        rewritten_query="Q013",
        raw_input="Q013",
        company_id="65",
        intent_type="knowledge",
        rag_chunks=[{"content": "compact reference only", "source_file": "compact.txt"}],
        rag_evidence_chunks=[
            {
                "content": "full evidence includes F_UPDATE_003 and 390套 after char 200",
                "source_file": "evidence.txt",
            }
        ],
    )

    result = await router._answer_from_rag("Q013", context)

    assert result["answer"] == "answer"
    assert "F_UPDATE_003" in gateway.llm.prompt
    assert "compact reference only" not in gateway.llm.prompt


class _FakePipeline:
    async def build_context_package(self, **kwargs):
        return ContextPackage(
            rewritten_query=kwargs["raw_input"],
            raw_input=kwargs["raw_input"],
            intent_type="knowledge",
            company_id=kwargs["company_id"],
            rag_chunks=[{"content": "compact source", "source_file": "qpack.txt"}],
            rag_references=[{"content": "compact source", "source_file": "qpack.txt"}],
            rag_evidence_chunks=[
                {"content": "long evidence should stay out of sources", "source_file": "qpack.txt"}
            ],
        )


class _FakeRouter:
    async def execute(self, _context_package):
        yield {"type": "result", "data": "ok"}
        yield {"type": "done"}


class _DummySession:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


class _DummyDB:
    def get_session(self):
        return _DummySession()


@pytest.mark.asyncio
async def test_chat_sources_and_persistence_use_compact_references(monkeypatch):
    import app.database as database_module
    import app.services.message_persistence as persistence_module

    persisted = []
    monkeypatch.delenv("AGENTX_SMOKE_DISABLE_RAG_PRERETRIEVAL", raising=False)
    monkeypatch.setattr(chat, "_get_perception_pipeline", lambda: _FakePipeline())
    monkeypatch.setattr(chat, "_get_master_router", lambda: _FakeRouter())
    monkeypatch.setattr(chat, "_build_company_context_from_db", lambda _company_id: {})
    monkeypatch.setattr(chat, "_persist_assistant_reply", lambda **kwargs: persisted.append(kwargs))
    monkeypatch.setattr(database_module, "db", _DummyDB())
    monkeypatch.setattr(
        persistence_module,
        "get_or_create_conversation",
        lambda **_kwargs: SimpleNamespace(id=123, message_count=0),
    )
    monkeypatch.setattr(persistence_module, "save_user_message", lambda **_kwargs: None)

    response = await chat.chat_stream(
        chat.ChatRequest(message="Q013", company_context={"brand": "x"}),
        req=SimpleNamespace(),
        current_user=SimpleNamespace(id=7, company_id=65),
    )

    body = []
    async for chunk in response.body_iterator:
        body.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    rendered = "".join(body)

    assert "compact source" in rendered
    assert "long evidence should stay out of sources" not in rendered
    assert persisted
    assert persisted[-1]["references"] == [
        {"content": "compact source", "source_file": "qpack.txt"}
    ]
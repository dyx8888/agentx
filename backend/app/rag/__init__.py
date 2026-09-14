"""Public RAG API with lazy imports.

Historically ``import app.rag`` imported every optional RAG backend. That made
the lightweight PostgreSQL/BM25 path pay the startup-memory cost of LlamaIndex,
multimodal retrieval and evaluation modules even when none were used. The
public API remains compatible while each implementation now loads only when
its exported attribute is first accessed.
"""

from importlib import import_module
from typing import Any


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "HybridRetriever": (".hybrid_retriever", "HybridRetriever"),
    "LlamaIndexRetriever": (".llamaindex_retriever", "LlamaIndexRetriever"),
    "get_llamaindex_retriever": (".llamaindex_retriever", "get_llamaindex_retriever"),
    "LLAMAINDEX_AVAILABLE": (".llamaindex_retriever", "LLAMAINDEX_AVAILABLE"),
    "EmbeddingService": (".embedding_service", "EmbeddingService"),
    "EMBEDDING_MODEL_REGISTRY": (".embedding_service", "EMBEDDING_MODEL_REGISTRY"),
    "register_embedding_model": (".embedding_service", "register_embedding_model"),
    "list_available_models": (".embedding_service", "list_available_models"),
    "CompanyContextBus": (".company_context_bus", "CompanyContextBus"),
    "DataInjector": (".data_injector", "DataInjector"),
    "ContextExtractor": (".context_extractor", "ContextExtractor"),
    "ContextConfig": (".context_extractor", "ContextConfig"),
    "get_context_extractor": (".context_extractor", "get_context_extractor"),
    "DocStatus": (".doc_status", "DocStatus"),
    "DocState": (".doc_status", "DocState"),
    "DocStatusManager": (".doc_status", "DocStatusManager"),
    "get_doc_status_manager": (".doc_status", "get_doc_status_manager"),
    "MultiModalRetriever": (".multimodal_retriever", "MultiModalRetriever"),
    "get_multimodal_retriever": (".multimodal_retriever", "get_multimodal_retriever"),
    "GraphRAGRetriever": (".graph_rag", "GraphRAGRetriever"),
    "DocumentParser": (".document_parser", "DocumentParser"),
    "BaseParser": (".document_parser", "BaseParser"),
    "PARSER_REGISTRY": (".document_parser", "PARSER_REGISTRY"),
    "get_parser": (".document_parser", "get_parser"),
    "set_parser": (".document_parser", "set_parser"),
    "register_parser": (".document_parser", "register_parser"),
    "ParseCache": (".parse_cache", "ParseCache"),
    "get_parse_cache": (".parse_cache", "get_parse_cache"),
    "TextChunker": (".text_splitter", "TextChunker"),
    "RAGEvaluator": (".rag_evaluator", "RAGEvaluator"),
    "build_rag_prompt": (".rag_prompt", "build_rag_prompt"),
    "parse_citations": (".rag_prompt", "parse_citations"),
    "async_retry": (".resilience", "async_retry"),
    "retry": (".resilience", "retry"),
    "CircuitBreaker": (".resilience", "CircuitBreaker"),
    "CircuitBreakerOpenError": (".resilience", "CircuitBreakerOpenError"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load a public RAG attribute on first access and cache it."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

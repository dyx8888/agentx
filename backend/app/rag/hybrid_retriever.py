"""Hybrid retrieval for company knowledge.

The retriever combines BM25 keyword recall, Milvus vector recall, weighted RRF
fusion, and an optional CrossEncoder reranker. It is intentionally resilient:
Milvus/reranker failures degrade to the remaining retrieval stages without
crashing the API.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)

METADATA_STRUCTURED_EVIDENCE_BOOST = 0.0008
METADATA_FACT_LINE_BOOST = 0.0012
METADATA_UPDATE_NOTICE_BOOST = 0.0015
METADATA_DOMAIN_MATCH_BOOST = 0.0020
METADATA_ABSENCE_DISCLAIMER_BOOST = 0.0018
METADATA_SYNTHETIC_PARAGRAPH_PENALTY = 0.0010
METADATA_SOURCE_REPEAT_PENALTY = 0.0010
METADATA_EVIDENCE_SNIPPET_CHARS = 320

MEDICAL_RISK_QUERY_HINTS = (
    "诊断",
    "疾病",
    "皮肤疾病",
    "客服诊断",
    "医疗建议",
    "过敏",
    "成分表",
    "局部试用",
    "绝对不过敏",
)
MEDICAL_SOURCE_RECALL_HINTS = (
    "医疗建议",
    "过敏",
    "局部试用",
    "成分表",
    "评论区",
    "不得给医疗建议",
)

ABSENCE_QUERY_HINTS = (
    "真实",
    "真实资料",
    "真实链接",
    "真实账号",
    "真实客户",
    "真实达人",
    "手机号",
    "订单号",
    "账号链接",
    "是否包含真实",
)
SYNTHETIC_DISCLAIMER_HINTS = (
    "synthetic",
    "测试资料",
    "不对应任何真实商家或个人",
    "不对应真实商家",
    "不包含真实",
    "不含真实",
    "虚构",
)
QUERY_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "service": (
        "客服",
        "售后",
        "过敏",
        "诊断",
        "补偿",
        "疾病",
        "敏感肌",
        "补发",
        "退款",
        "承诺",
        "批号",
        "照片",
        "暂停使用",
    ),
    "content": (
        "内容",
        "口播",
        "评论",
        "脚本",
        "屏障",
        "医学级",
        "医疗建议",
        "素材",
        "短视频",
        "敏感肌",
        "过敏",
        "诊断",
        "疾病",
        "绝对不过敏",
        "成分表",
        "局部试用",
    ),
    "update": ("更新", "优先", "调整", "公告"),
    "inventory": ("库存", "发货", "补货", "仓", "履约"),
    "kol": ("达人", "kol", "乔桥", "米默", "林雅", "林芽"),
    "promo": ("活动", "价格", "满赠", "818", "促销", "券后价"),
    "rule": ("规则", "平台", "合规", "禁用", "允许", "医学级", "医疗建议", "虚假"),
}
METADATA_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "service": (
        "service",
        "sop",
        "after_sales",
        "售后",
        "客服",
        "qpack_service",
        "qpack_05",
        "05_",
        "f_service",
        "qpack_service_",
        "批号",
        "照片",
        "暂停使用",
    ),
    "content": (
        "content",
        "script",
        "copy",
        "内容",
        "口播",
        "qpack_content",
        "qpack_07",
        "07_",
        "f_content",
        "qpack_content_",
        "医疗建议",
        "成分表",
        "局部试用",
    ),
    "update": ("update", "notice", "更新", "公告", "qpack_update", "qpack_09", "09_"),
    "inventory": ("inventory", "fulfillment", "库存", "履约", "qpack_inv", "qpack_02", "02_"),
    "kol": ("kol", "达人", "qpack_kol", "qpack_03", "03_"),
    "promo": ("promo", "818", "活动", "促销", "qpack_promo", "qpack_04", "04_"),
    "rule": ("rule", "rules", "platform", "合规", "规则", "qpack_rule", "qpack_06", "06_"),
}
STRUCTURED_CONTENT_DOMAIN_HINTS = (
    "content",
    "script",
    "copy",
    "内容",
    "内容规范",
    "内容素材",
    "口播",
    "脚本",
    "素材",
    "短视频",
    "qpack_content",
    "qpack_07",
    "07_",
)


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value != "" else []


def _metadata_for(result: "SearchResult") -> dict[str, Any]:
    metadata = getattr(result, "metadata", {}) or {}
    return metadata if isinstance(metadata, dict) else {}


def _result_source_file(result: "SearchResult") -> str:
    metadata = _metadata_for(result)
    return str(
        getattr(result, "source_file", "")
        or metadata.get("source_file")
        or metadata.get("original_filename")
        or metadata.get("filename")
        or ""
    )


def _result_dedupe_key(result: "SearchResult") -> tuple[str, str, str, str, str]:
    metadata = _metadata_for(result)
    fact_ids = "|".join(_as_string_list(metadata.get("fact_ids")))
    markers = "|".join(_as_string_list(metadata.get("markers")))
    chunk_index = str(
        getattr(result, "chunk_index", "")
        or metadata.get("chunk_index")
        or metadata.get("source_page")
        or ""
    )
    return (
        _result_source_file(result),
        chunk_index,
        fact_ids,
        markers,
        str(getattr(result, "content", "") or "")[:160],
    )


def _query_domains(query: str) -> set[str]:
    text = str(query or "").casefold()
    return {
        domain
        for domain, hints in QUERY_DOMAIN_HINTS.items()
        if any(hint.casefold() in text for hint in hints)
    }


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    folded = str(text or "").casefold()
    return any(hint.casefold() in folded for hint in hints)


def _is_absence_query(query: str) -> bool:
    return _contains_any(query, ABSENCE_QUERY_HINTS)


def _is_medical_risk_query(query: str) -> bool:
    return _contains_any(query, MEDICAL_RISK_QUERY_HINTS)


def _is_synthetic_disclaimer(result: "SearchResult") -> bool:
    return _contains_any(getattr(result, "content", "") or "", SYNTHETIC_DISCLAIMER_HINTS)


def _metadata_search_text(result: "SearchResult") -> str:
    metadata = _metadata_for(result)
    values: list[str] = [
        _result_source_file(result),
        str(metadata.get("section_title") or ""),
        str(metadata.get("chunk_type") or ""),
        str(metadata.get("category") or ""),
        str(metadata.get("scenario") or ""),
    ]
    values.extend(_as_string_list(metadata.get("fact_ids")))
    values.extend(_as_string_list(metadata.get("markers")))
    return " ".join(values).casefold()


def _evidence_search_text(result: "SearchResult") -> str:
    content = str(getattr(result, "content", "") or "")[:METADATA_EVIDENCE_SNIPPET_CHARS]
    return f"{_metadata_search_text(result)} {content}".casefold()


def _result_chunk_type(result: "SearchResult") -> str:
    metadata = _metadata_for(result)
    return str(metadata.get("chunk_type") or "").strip().lower()


def _is_fact_line_for_domain(result: "SearchResult", domain: str) -> bool:
    if _result_chunk_type(result) != "fact_line":
        return False
    if domain == "content":
        return _has_structured_domain_metadata(result, domain)
    evidence_text = _evidence_search_text(result)
    return any(hint.casefold() in evidence_text for hint in METADATA_DOMAIN_HINTS[domain])


def _has_structured_content_domain_metadata(result: "SearchResult") -> bool:
    metadata = _metadata_for(result)
    fact_ids = [item.casefold() for item in _as_string_list(metadata.get("fact_ids"))]
    markers = [item.casefold() for item in _as_string_list(metadata.get("markers"))]
    if any(fact_id.startswith("f_content") for fact_id in fact_ids):
        return True
    if any(marker.startswith("qpack_content") for marker in markers):
        return True

    structured_values: list[str] = [
        _result_source_file(result),
        str(metadata.get("filename") or ""),
        str(metadata.get("original_filename") or ""),
        str(metadata.get("section_title") or ""),
        str(metadata.get("category") or ""),
        str(metadata.get("scenario") or ""),
    ]
    structured_text = " ".join(structured_values).casefold()
    return any(hint.casefold() in structured_text for hint in STRUCTURED_CONTENT_DOMAIN_HINTS)


def _has_structured_domain_metadata(result: "SearchResult", domain: str) -> bool:
    if _result_chunk_type(result) != "fact_line":
        return False
    if domain == "content":
        return _has_structured_content_domain_metadata(result)
    metadata = _metadata_for(result)
    structured_values: list[str] = [
        _result_source_file(result),
        str(metadata.get("filename") or ""),
        str(metadata.get("original_filename") or ""),
        str(metadata.get("section_title") or ""),
        str(metadata.get("category") or ""),
        str(metadata.get("scenario") or ""),
    ]
    structured_values.extend(_as_string_list(metadata.get("fact_ids")))
    structured_values.extend(_as_string_list(metadata.get("markers")))
    structured_text = " ".join(structured_values).casefold()
    return any(hint.casefold() in structured_text for hint in METADATA_DOMAIN_HINTS[domain])


def _metadata_boost_score(query: str, result: "SearchResult") -> float:
    metadata = _metadata_for(result)
    chunk_type = _result_chunk_type(result)
    fact_ids = _as_string_list(metadata.get("fact_ids"))
    markers = _as_string_list(metadata.get("markers"))
    absence_query = _is_absence_query(query)
    synthetic_disclaimer = _is_synthetic_disclaimer(result)

    boost = 0.0
    if chunk_type == "fact_line":
        boost += METADATA_FACT_LINE_BOOST
    elif chunk_type == "update_notice":
        boost += METADATA_UPDATE_NOTICE_BOOST

    if fact_ids or markers:
        boost += METADATA_STRUCTURED_EVIDENCE_BOOST

    metadata_text = _metadata_search_text(result)
    for domain in _query_domains(query):
        if any(hint.casefold() in metadata_text for hint in METADATA_DOMAIN_HINTS[domain]):
            boost += METADATA_DOMAIN_MATCH_BOOST

    if synthetic_disclaimer and absence_query:
        boost += METADATA_ABSENCE_DISCLAIMER_BOOST
    elif synthetic_disclaimer and chunk_type == "paragraph":
        boost -= METADATA_SYNTHETIC_PARAGRAPH_PENALTY

    return boost


def _base_rank_score(result: "SearchResult") -> float:
    rerank_score = getattr(result, "rerank_score", None)
    if rerank_score is not None:
        return float(rerank_score or 0.0)
    return float(getattr(result, "rrf_score", 0.0) or 0.0)


try:
    from pymilvus.exceptions import PyMilvusDeprecationWarning
except Exception:
    PyMilvusDeprecationWarning = Warning

warnings.filterwarnings(
    "ignore",
    message=r".*ORM-style PyMilvus API.*",
    category=PyMilvusDeprecationWarning,
)


@dataclass
class SearchResult:
    """Unified retrieval result."""

    content: str
    metadata: dict = field(default_factory=dict)
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float | None = None
    source: str = ""
    source_file: str = ""
    chunk_index: int = 0
    source_page: int = 0


class BM25Retriever:
    """Small BM25 implementation with lightweight Chinese tokenization."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._documents: list[str] = []
        self._doc_ids: list[str] = []
        self._doc_lengths: list[int] = []
        self._avgdl: float = 0.0
        self._idf: dict[str, float] = {}
        self._doc_freqs: list[dict[str, int]] = []

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []

        tokens: list[str] = []
        pattern = r"[a-z0-9]+(?:[+#._-][a-z0-9]+)*|[\u4e00-\u9fff]+"
        for piece in re.findall(pattern, str(text).lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", piece):
                chars = list(piece)
                tokens.extend(chars)
                for n in (2, 3):
                    if len(chars) >= n:
                        tokens.extend(
                            "".join(chars[i : i + n]) for i in range(len(chars) - n + 1)
                        )
                tokens.append(piece)
            else:
                tokens.append(piece)
                compact = re.sub(r"[^a-z0-9]+", "", piece)
                if compact and compact != piece:
                    tokens.append(compact)

        return tokens

    def index(self, documents: list[str], doc_ids: list[str] | None = None) -> None:
        self._documents = [str(doc or "") for doc in documents]
        self._doc_ids = doc_ids or [str(i) for i in range(len(self._documents))]
        self._doc_lengths = []
        self._doc_freqs = []

        df: dict[str, int] = {}
        for doc in self._documents:
            tokens = self._tokenize(doc)
            self._doc_lengths.append(len(tokens))
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            for token in set(tokens):
                df[token] = df.get(token, 0) + 1
            self._doc_freqs.append(tf)

        n_docs = len(self._documents)
        self._avgdl = sum(self._doc_lengths) / max(n_docs, 1)
        self._idf = {
            term: float(np.log(1 + (n_docs - freq + 0.5) / (freq + 0.5)))
            for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        query_tokens = self._tokenize(query)
        if not query_tokens or not self._documents or self._avgdl <= 0:
            return []

        scores: list[tuple[int, float]] = []
        for i, (doc_len, tf) in enumerate(
            zip(self._doc_lengths, self._doc_freqs, strict=False)
        ):
            score = 0.0
            for token in query_tokens:
                if token not in self._idf:
                    continue
                token_tf = tf.get(token, 0)
                if token_tf <= 0:
                    continue
                denom = token_tf + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl)
                score += self._idf[token] * token_tf * (self.k1 + 1) / denom
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]


class VectorRetriever:
    """Milvus vector retriever with lazy connection and retry backoff."""

    def __init__(self, company_id: str = "default"):
        self.company_id = str(company_id)
        self._collection = None
        self._client = None
        self._initialized = False
        self._last_init_attempt = 0.0
        self._retry_interval = float(os.getenv("MILVUS_RETRY_INTERVAL", "30"))
        self._collection_name = os.getenv("MILVUS_COLLECTION", "company_knowledge")
        self._operation_timeout = float(os.getenv("MILVUS_OPERATION_TIMEOUT_SECONDS", "5"))
        self._load_timeout = float(os.getenv("MILVUS_LOAD_TIMEOUT_SECONDS", "10"))
        self._flush_after_write = _env_flag("MILVUS_FLUSH_AFTER_WRITE", "false")
        self._delete_before_insert = _env_flag("MILVUS_DELETE_BEFORE_INSERT", "false")

    def _reset_connection_state(self) -> None:
        self._collection = None
        self._client = None
        self._initialized = False

    def _safe_load_collection(self) -> bool:
        if self._collection is None:
            return False
        try:
            self._collection.load(timeout=self._load_timeout)
            return True
        except Exception as exc:
            logger.warning(
                "milvus_collection_load_failed",
                collection=self._collection_name,
                error=str(exc),
            )
            self._reset_connection_state()
            return False

    def _safe_flush(self, operation: str) -> bool:
        if not self._flush_after_write:
            logger.debug("milvus_flush_skipped", operation=operation)
            return True
        if self._collection is None:
            return False
        try:
            self._collection.flush(timeout=self._operation_timeout)
            return True
        except Exception as exc:
            logger.warning(
                "milvus_flush_failed",
                operation=operation,
                timeout_seconds=self._operation_timeout,
                error=str(exc),
            )
            self._reset_connection_state()
            return False

    @staticmethod
    def _should_reload_after_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "collection not loaded" in message
            or "channel not found" in message
            or "not loaded" in message
        )

    def _ensure_initialized(self, dim: int | None = None) -> None:
        if self._initialized:
            return

        now = time.monotonic()
        if self._last_init_attempt and now - self._last_init_attempt < self._retry_interval:
            return
        self._last_init_attempt = now

        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema
            from pymilvus import MilvusClient, connections, utility

            host = os.getenv("MILVUS_HOST", "localhost")
            port = int(os.getenv("MILVUS_PORT", "19530"))
            connections.connect(host=host, port=port, timeout=5)
            try:
                self._client = MilvusClient(uri=f"http://{host}:{port}", timeout=5)
            except Exception as exc:
                self._client = None
                logger.debug("milvus_client_init_failed_keep_orm_fallback", error=str(exc))

            if utility.has_collection(self._collection_name):
                self._collection = Collection(self._collection_name)
            else:
                vector_dim = int(dim or os.getenv("MILVUS_VECTOR_DIM", "512"))
                fields = [
                    FieldSchema(
                        name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128
                    ),
                    FieldSchema(name="company_id", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=8192),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=vector_dim),
                ]
                schema = CollectionSchema(fields, description="AgentX company knowledge")
                self._collection = Collection(self._collection_name, schema=schema)
                self._collection.create_index(
                    field_name="embedding",
                    index_params={
                        "metric_type": "IP",
                        "index_type": "IVF_FLAT",
                        "params": {"nlist": 128},
                    },
                )

            if not self._safe_load_collection():
                return
            self._initialized = True
            logger.info("milvus_vector_ready", collection=self._collection_name)
        except ImportError:
            logger.warning("pymilvus_not_installed_vector_disabled")
        except Exception as exc:
            logger.warning("milvus_connect_failed_vector_disabled", error=str(exc))

    def insert_documents(self, rows: list[dict[str, Any]], embeddings: np.ndarray) -> bool:
        if not rows:
            return True
        if embeddings is None or len(embeddings) != len(rows):
            logger.warning("milvus_insert_skipped_embedding_count_mismatch")
            return False

        dim = int(np.asarray(embeddings[0]).shape[0])
        self._ensure_initialized(dim=dim)
        if self._collection is None:
            return False

        try:
            data = []
            for row, vector in zip(rows, embeddings, strict=False):
                doc_id = str(row["id"])
                metadata = row.get("metadata") or {}
                if not isinstance(metadata, str):
                    metadata = json.dumps(metadata, ensure_ascii=False)
                data.append(
                    {
                        "id": doc_id,
                        "company_id": self.company_id,
                        "content": str(row.get("content") or ""),
                        "metadata": metadata,
                        "embedding": np.asarray(vector, dtype=np.float32).tolist(),
                    }
                )

            # Imported/live-eval documents use unique IDs, so a pre-delete is usually
            # unnecessary. In Milvus standalone, delete+flush can leave the collection
            # channel in a bad state ("channel not found") on external-disk Docker
            # rehearsals. Keep replacement deletes opt-in for maintenance flows.
            if self._delete_before_insert:
                self._delete_expr(f'id in {json.dumps([r["id"] for r in data])}')
                if self._collection is None:
                    self._ensure_initialized(dim=dim)
                if self._collection is None:
                    return False
            self._collection.insert(data)
            return self._safe_flush("insert_documents")
        except Exception as exc:
            logger.warning("milvus_index_warning", error=str(exc))
            if self._should_reload_after_error(exc):
                self._reset_connection_state()
            return False

    def search(
        self, query_vector: np.ndarray, top_k: int = 20
    ) -> list[tuple[str, str, float, str]]:
        if query_vector is None or np.asarray(query_vector).size == 0:
            return []

        self._ensure_initialized(dim=int(np.asarray(query_vector).shape[0]))
        if self._collection is None:
            return []

        try:
            search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
            expr = f'company_id == "{HybridRetriever._escape_milvus_expr(self.company_id)}"'
            if not self._company_has_documents(expr):
                return []
            query_payload = np.asarray(query_vector, dtype=np.float32).tolist()
            if self._client is not None:
                for attempt in range(2):
                    try:
                        results = self._client.search(
                            collection_name=self._collection_name,
                            data=[query_payload],
                            anns_field="embedding",
                            search_params=search_params,
                            limit=top_k,
                            filter=expr,
                            output_fields=["id", "content", "metadata"],
                            timeout=self._operation_timeout,
                        )
                        return self._format_client_search_results(results)
                    except Exception as exc:
                        logger.warning(
                            "milvus_client_search_failed_keep_orm_fallback",
                            attempt=attempt + 1,
                            error=str(exc),
                        )
                        if attempt == 0 and self._should_reload_after_error(exc):
                            self._safe_load_collection()
                            continue
                        break

            results = self._collection.search(
                data=[query_payload],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=["id", "content", "metadata"],
                timeout=self._operation_timeout,
            )

            formatted: list[tuple[str, str, float, str]] = []
            for hits in results:
                for hit in hits:
                    entity = hit.entity
                    formatted.append(
                        (
                            str(entity.get("id", getattr(hit, "id", ""))),
                            str(entity.get("content", "")),
                            float(hit.score),
                            str(entity.get("metadata", "") or ""),
                        )
                    )
            return formatted
        except Exception as exc:
            logger.error("milvus_search_error", error=str(exc))
            if self._should_reload_after_error(exc):
                self._reset_connection_state()
            return []

    def _company_has_documents(self, expr: str) -> bool:
        try:
            rows = self._collection.query(
                expr=expr,
                output_fields=["id"],
                limit=1,
                timeout=self._operation_timeout,
            )
            return bool(rows)
        except Exception as exc:
            logger.debug("milvus_company_probe_failed", error=str(exc), expr=expr)
            if self._should_reload_after_error(exc):
                self._reset_connection_state()
            return True

    @staticmethod
    def _format_client_search_results(results: list[list[dict]]) -> list[tuple[str, str, float, str]]:
        formatted: list[tuple[str, str, float, str]] = []
        for hits in results or []:
            for hit in hits or []:
                entity = hit.get("entity") or {}
                formatted.append(
                    (
                        str(entity.get("id", hit.get("id", ""))),
                        str(entity.get("content", "")),
                        float(hit.get("distance", hit.get("score", 0.0)) or 0.0),
                        str(entity.get("metadata", "") or ""),
                    )
                )
        return formatted

    def list_documents(self) -> list[dict[str, Any]]:
        self._ensure_initialized()
        if self._collection is None:
            return []
        try:
            expr = f'company_id == "{HybridRetriever._escape_milvus_expr(self.company_id)}"'
            rows = self._collection.query(
                expr=expr,
                output_fields=["id", "content", "metadata", "company_id"],
                limit=int(os.getenv("MILVUS_QUERY_LIMIT", "10000")),
                timeout=self._operation_timeout,
            )
            return [self._normalize_query_row(row) for row in rows]
        except Exception as exc:
            logger.warning("milvus_list_documents_failed", error=str(exc))
            if self._should_reload_after_error(exc):
                self._reset_connection_state()
            return []

    def delete_document(self, doc_id: str) -> bool:
        escaped_doc_id = HybridRetriever._escape_milvus_expr(doc_id)
        escaped_company = HybridRetriever._escape_milvus_expr(self.company_id)
        return self._delete_expr(
            f'id == "{escaped_doc_id}" and company_id == "{escaped_company}"'
        )

    def delete_company_documents(self) -> int:
        self._ensure_initialized()
        if self._collection is None:
            return 0
        try:
            escaped_company = HybridRetriever._escape_milvus_expr(self.company_id)
            result = self._collection.delete(f'company_id == "{escaped_company}"')
            self._safe_flush("delete_company_documents")
            return int(getattr(result, "delete_count", 0) or 0)
        except Exception as exc:
            logger.warning("milvus_delete_company_failed", error=str(exc))
            if self._should_reload_after_error(exc):
                self._reset_connection_state()
            return 0

    def _delete_expr(self, expr: str) -> bool:
        self._ensure_initialized()
        if self._collection is None:
            return False
        try:
            self._collection.delete(expr)
            return self._safe_flush("delete_expr")
        except Exception as exc:
            logger.debug("milvus_delete_expr_failed", error=str(exc), expr=expr)
            if self._should_reload_after_error(exc):
                self._reset_connection_state()
            return False

    @staticmethod
    def _normalize_query_row(row: dict[str, Any]) -> dict[str, Any]:
        metadata_raw = row.get("metadata") or ""
        metadata: dict[str, Any] = {}
        if isinstance(metadata_raw, dict):
            metadata = metadata_raw
        elif metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except (TypeError, json.JSONDecodeError):
                metadata = {}

        doc_id = str(row.get("id", ""))
        return {
            "id": doc_id,
            "content": row.get("content", ""),
            "metadata": metadata,
            "company_id": row.get("company_id") or metadata.get("company_id"),
            "filename": metadata.get("filename")
            or metadata.get("original_filename")
            or metadata.get("source_file")
            or doc_id,
            "category": metadata.get("category", ""),
            "source": metadata.get("source", ""),
            "total_chunks": metadata.get("total_chunks", metadata.get("chunks", 1)),
        }


class CrossEncoderReranker:
    """Optional CrossEncoder reranker."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base")
        self._model = None
        self._load_failed = False

    def _load(self) -> None:
        if self._model is not None or self._load_failed:
            return
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
            logger.info("reranker_loaded", model=self.model_name)
        except Exception as exc:
            self._load_failed = True
            logger.warning("reranker_load_failed_disabled", error=str(exc))

    def rerank(self, query: str, documents: list[str], top_k: int = 10) -> list[tuple[int, float]]:
        if os.getenv("RERANKER_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]

        self._load()
        if self._model is None:
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]

        try:
            pairs = [(query, doc) for doc in documents]
            scores = self._model.predict(pairs)
            ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
            return [(idx, float(score)) for idx, score in ranked[:top_k]]
        except Exception as exc:
            logger.warning("reranker_predict_failed_keep_rrf_order", error=str(exc))
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]


class HybridRetriever:
    """Hybrid retrieval engine scoped to one company."""

    def __init__(self, company_id: str = "default"):
        self.company_id = str(company_id)
        self.bm25 = BM25Retriever()
        self.vector = VectorRetriever(company_id=self.company_id)
        self.reranker = CrossEncoderReranker()
        self._embedding_service = None
        self._documents: dict[str, dict[str, Any]] = {}
        self._indexed = False
        self._last_medical_supplement_debug: dict[str, bool | int] | None = None

    @staticmethod
    def _escape_milvus_expr(value: Any) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def _get_embedding_service(self):
        if self._embedding_service is None:
            from .embedding_service import get_embedding_service

            self._embedding_service = get_embedding_service()
        return self._embedding_service

    def index_documents(self, documents: list[dict[str, Any]]) -> None:
        if not documents:
            return

        rows: list[dict[str, Any]] = []
        for i, document in enumerate(documents):
            doc_id = str(document.get("id", i))
            content = str(document.get("content") or "")
            metadata = dict(document.get("metadata") or {})
            metadata.setdefault("company_id", self.company_id)
            row = {"id": doc_id, "content": content, "metadata": metadata}
            rows.append(row)
            self._documents[doc_id] = row

        self._rebuild_bm25()
        self._indexed = True

        try:
            emb_service = self._get_embedding_service()
            embeddings = emb_service.encode([row["content"] for row in rows])
            self.vector.insert_documents(rows, np.asarray(embeddings, dtype=np.float32))
        except Exception as exc:
            logger.warning("vector_index_skipped", error=str(exc))

    def list_documents(self) -> list[dict[str, Any]]:
        vector_docs = self.vector.list_documents()
        by_id = {str(doc["id"]): doc for doc in vector_docs if doc.get("id")}
        for doc_id, doc in self._documents.items():
            metadata = doc.get("metadata") or {}
            by_id.setdefault(
                doc_id,
                {
                    "id": doc_id,
                    "content": doc.get("content", ""),
                    "metadata": metadata,
                    "company_id": metadata.get("company_id", self.company_id),
                    "filename": metadata.get("filename")
                    or metadata.get("original_filename")
                    or metadata.get("source_file")
                    or doc_id,
                    "category": metadata.get("category", ""),
                    "source": metadata.get("source", ""),
                    "total_chunks": metadata.get("total_chunks", metadata.get("chunks", 1)),
                },
            )
        return list(by_id.values())

    def delete_document(self, doc_id: str) -> bool:
        doc_id = str(doc_id)
        local_hit = doc_id in self._documents
        self._documents.pop(doc_id, None)
        self._rebuild_bm25()
        vector_deleted = self.vector.delete_document(doc_id)
        logger.info(
            "document_deleted",
            doc_id=doc_id,
            company_id=self.company_id,
            local_hit=local_hit,
            vector_deleted=vector_deleted,
        )
        return local_hit or vector_deleted

    def delete_company_documents(self) -> int:
        local_count = len(self._documents)
        self._documents.clear()
        self._rebuild_bm25()
        vector_count = self.vector.delete_company_documents()
        count = max(local_count, vector_count)
        logger.info("company_documents_cleared", company_id=self.company_id, count=count)
        return count

    def search(
        self,
        query: str,
        top_k: int = 10,
        use_reranker: bool = True,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> list[SearchResult]:
        emb_service = self._get_embedding_service()
        query_vector = emb_service.encode_single(query)

        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        vector_results = self.vector.search(query_vector, top_k=top_k * 2)

        fused = self._rrf_fuse(bm25_results, vector_results, bm25_weight, vector_weight)
        candidates = self._apply_metadata_boost(
            query,
            list(fused.values()),
            top_k=top_k * 2,
        )
        candidates = self._supplement_medical_source_candidates(
            query,
            candidates,
            top_k=top_k * 2,
        )
        debug_counters = self._last_medical_supplement_debug
        if debug_counters is not None:
            debug_counters["reranker_candidate_has_content"] = any(
                _is_fact_line_for_domain(result, "content") for result in candidates
            )
            debug_counters["reranker_candidate_has_service"] = any(
                _is_fact_line_for_domain(result, "service") for result in candidates
            )
            debug_counters["guard_candidate_has_content"] = debug_counters[
                "reranker_candidate_has_content"
            ]
            debug_counters["guard_candidate_has_service"] = debug_counters[
                "reranker_candidate_has_service"
            ]

        if use_reranker and candidates:
            contents = [result.content for result in candidates]
            reranked = self.reranker.rerank(query, contents, top_k=top_k)
            final: list[SearchResult] = []
            for idx, score in reranked:
                if idx < len(candidates):
                    candidates[idx].rerank_score = float(score)
                    final.append(candidates[idx])
            guarded = self._apply_source_coverage_guard(query, final, candidates, top_k)
            self._finalize_medical_supplement_debug(guarded)
            return guarded

        final = candidates[:top_k]
        self._finalize_medical_supplement_debug(final)
        return final

    def _supplement_medical_source_candidates(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Add bounded local service/content evidence for medical-risk queries."""
        if top_k <= 0 or not candidates or not _is_medical_risk_query(query):
            self._last_medical_supplement_debug = None
            return candidates[:top_k]

        has_domain = {
            domain: any(_is_fact_line_for_domain(result, domain) for result in candidates)
            for domain in ("service", "content")
        }
        local_pool = self._medical_supplement_candidates_from_rows(
            self._documents.values()
        )
        debug_counters: dict[str, bool | int] = {
            "medical_supplement_enabled": True,
            "local_doc_count": len(self._documents),
            "vector_list_documents_called": False,
            "vector_list_documents_error": False,
            "vector_list_documents_missing": False,
            "vector_listed_doc_count": 0,
            "local_content_fact_count": self._domain_fact_count(local_pool, "content"),
            "local_service_fact_count": self._domain_fact_count(local_pool, "service"),
            "vector_content_fact_count": 0,
            "vector_service_fact_count": 0,
            "supplement_seen_content_domain": bool(has_domain["content"])
            or self._domain_fact_count(local_pool, "content") > 0,
            "supplement_seen_service_domain": bool(has_domain["service"])
            or self._domain_fact_count(local_pool, "service") > 0,
            "supplement_added_count": 0,
            "supplement_added_content_count": 0,
            "supplement_added_service_count": 0,
            "post_supplement_candidate_count": min(len(candidates), top_k),
            "reranker_candidate_has_content": False,
            "reranker_candidate_has_service": False,
            "guard_candidate_has_content": False,
            "guard_candidate_has_service": False,
            "final_has_content": False,
            "final_has_service": False,
        }
        self._last_medical_supplement_debug = debug_counters
        missing_domains = [domain for domain, present in has_domain.items() if not present]
        if not missing_domains:
            return candidates[:top_k]

        seen_keys = {_result_dedupe_key(result) for result in candidates}
        supplements: list[SearchResult] = []
        vector_pool: list[SearchResult] | None = None

        def best_candidate(
            domain: str,
            pool: list[SearchResult],
            order_offset: int = 0,
        ) -> tuple[float, int, SearchResult] | None:
            best: tuple[float, int, SearchResult] | None = None
            for order, result in enumerate(pool, start=order_offset):
                if _result_dedupe_key(result) in seen_keys:
                    continue
                if not _is_fact_line_for_domain(result, domain):
                    continue
                if not _has_structured_domain_metadata(result, domain):
                    continue

                evidence_text = _evidence_search_text(result)
                has_medical_hint = _contains_any(evidence_text, MEDICAL_SOURCE_RECALL_HINTS)
                has_structured_content_fallback = (
                    domain == "content" and _has_structured_domain_metadata(result, "content")
                )
                if not has_medical_hint and not has_structured_content_fallback:
                    continue

                score = _metadata_boost_score(query, result)
                score += sum(
                    0.0002
                    for hint in MEDICAL_SOURCE_RECALL_HINTS
                    if hint.casefold() in evidence_text
                )
                if domain == "content":
                    score += 0.0004

                ranked = (score, -order, result)
                if best is None or ranked > best:
                    best = ranked
            return best

        for domain in missing_domains:
            best = best_candidate(domain, local_pool)
            if best is None:
                if vector_pool is None:
                    vector_pool = self._vector_medical_supplement_candidates(
                        debug_counters
                    )
                best = best_candidate(domain, vector_pool, order_offset=len(local_pool))

            if best is not None:
                supplement = best[2]
                supplements.append(supplement)
                seen_keys.add(_result_dedupe_key(supplement))
                debug_counters["supplement_added_count"] = len(supplements)
                if _is_fact_line_for_domain(supplement, "content"):
                    debug_counters["supplement_added_content_count"] = (
                        int(debug_counters["supplement_added_content_count"]) + 1
                    )
                    debug_counters["supplement_seen_content_domain"] = True
                if _is_fact_line_for_domain(supplement, "service"):
                    debug_counters["supplement_added_service_count"] = (
                        int(debug_counters["supplement_added_service_count"]) + 1
                    )
                    debug_counters["supplement_seen_service_domain"] = True

        if not supplements:
            return candidates[:top_k]

        supplemented = self._apply_metadata_boost(
            query, candidates + supplements, top_k=top_k
        )
        debug_counters["post_supplement_candidate_count"] = len(supplemented)
        return supplemented

    @staticmethod
    def _domain_fact_count(results: list[SearchResult], domain: str) -> int:
        return sum(1 for result in results if _is_fact_line_for_domain(result, domain))

    @staticmethod
    def _metadata_int(metadata: dict[str, Any], key: str) -> int:
        try:
            return int(metadata.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _medical_supplement_result_from_row(
        cls,
        row: dict[str, Any],
    ) -> SearchResult | None:
        if not isinstance(row, dict):
            return None
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, dict):
            return None
        source_file = str(
            metadata.get("source_file")
            or metadata.get("filename")
            or metadata.get("original_filename")
            or row.get("filename")
            or ""
        )
        return SearchResult(
            content=str(row.get("content") or ""),
            metadata=metadata,
            rrf_score=0.0,
            source="metadata_supplement",
            source_file=source_file,
            chunk_index=cls._metadata_int(metadata, "chunk_index"),
            source_page=cls._metadata_int(metadata, "source_page"),
        )

    @classmethod
    def _medical_supplement_candidates_from_rows(
        cls,
        rows: Any,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen_keys: set[tuple[str, str, str, str, str]] = set()
        for row in rows or []:
            result = cls._medical_supplement_result_from_row(row)
            if result is None:
                continue
            key = _result_dedupe_key(result)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append(result)
        return results

    def _vector_medical_supplement_candidates(
        self,
        debug_counters: dict[str, bool | int] | None = None,
    ) -> list[SearchResult]:
        list_documents = getattr(self.vector, "list_documents", None)
        if not callable(list_documents):
            if debug_counters is not None:
                debug_counters["vector_list_documents_missing"] = True
            return []
        try:
            if debug_counters is not None:
                debug_counters["vector_list_documents_called"] = True
            rows = list_documents()
        except Exception as exc:
            if debug_counters is not None:
                debug_counters["vector_list_documents_error"] = True
            logger.debug("medical_supplement_vector_list_failed", error_type=type(exc).__name__)
            return []
        results = self._medical_supplement_candidates_from_rows(rows)
        if debug_counters is not None:
            debug_counters["vector_listed_doc_count"] = len(rows or [])
            debug_counters["vector_content_fact_count"] = self._domain_fact_count(
                results, "content"
            )
            debug_counters["vector_service_fact_count"] = self._domain_fact_count(
                results, "service"
            )
            debug_counters["supplement_seen_content_domain"] = bool(
                debug_counters["supplement_seen_content_domain"]
            ) or debug_counters["vector_content_fact_count"] > 0
            debug_counters["supplement_seen_service_domain"] = bool(
                debug_counters["supplement_seen_service_domain"]
            ) or debug_counters["vector_service_fact_count"] > 0
        return results

    def _finalize_medical_supplement_debug(self, final: list[SearchResult]) -> None:
        counters = self._last_medical_supplement_debug
        if counters is None:
            return
        counters["final_has_content"] = any(
            _is_fact_line_for_domain(result, "content") for result in final
        )
        counters["final_has_service"] = any(
            _is_fact_line_for_domain(result, "service") for result in final
        )
        logger.info("medical_supplement_debug_counters", **counters)

    @staticmethod
    def _apply_metadata_boost(
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Lightly reorder candidates using existing metadata without changing scores."""
        if top_k <= 0 or not candidates:
            return []

        scored = [
            (
                index,
                result,
                _base_rank_score(result) + _metadata_boost_score(query, result),
            )
            for index, result in enumerate(candidates)
        ]
        remaining = sorted(scored, key=lambda item: (-item[2], item[0]))
        selected: list[tuple[int, SearchResult, float]] = []
        source_counts: dict[str, int] = {}

        while remaining and len(selected) < top_k:
            best_position = 0
            best_key: tuple[float, float, int] | None = None
            for position, (index, result, adjusted_score) in enumerate(remaining):
                source_file = _result_source_file(result)
                repeat_count = source_counts.get(source_file, 0) if source_file else 0
                effective_score = adjusted_score - (
                    repeat_count * METADATA_SOURCE_REPEAT_PENALTY
                )
                key = (effective_score, adjusted_score, -index)
                if best_key is None or key > best_key:
                    best_position = position
                    best_key = key

            chosen = remaining.pop(best_position)
            selected.append(chosen)
            source_file = _result_source_file(chosen[1])
            if source_file:
                source_counts[source_file] = source_counts.get(source_file, 0) + 1

        return HybridRetriever._apply_source_coverage_guard(
            query,
            [result for _, result, _ in selected],
            candidates,
            top_k,
        )

    @staticmethod
    def _apply_source_coverage_guard(
        query: str,
        selected: list[SearchResult],
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        if top_k <= 1 or not selected or not _is_medical_risk_query(query):
            return selected[:top_k]

        guarded = list(selected[:top_k])
        candidate_domains = {
            domain: [
                result
                for result in candidates
                if _is_fact_line_for_domain(result, domain)
            ]
            for domain in ("service", "content")
        }
        if not all(candidate_domains.values()):
            return guarded

        selected_ids = {id(result) for result in guarded}

        def has_domain(domain: str) -> bool:
            return any(_is_fact_line_for_domain(result, domain) for result in guarded)

        def is_guarded_domain(result: SearchResult) -> bool:
            return any(
                _is_fact_line_for_domain(result, domain)
                for domain in ("service", "content")
            )

        def best_candidate(domain: str) -> SearchResult | None:
            available = [
                result
                for result in candidate_domains[domain]
                if id(result) not in selected_ids
            ]
            if not available:
                return None
            return max(
                available,
                key=lambda result: (
                    _base_rank_score(result) + _metadata_boost_score(query, result),
                    -candidates.index(result),
                ),
            )

        for domain in ("service", "content"):
            if has_domain(domain):
                continue
            replacement = best_candidate(domain)
            if replacement is None:
                continue
            replace_at = next(
                (
                    index
                    for index in range(len(guarded) - 1, -1, -1)
                    if not is_guarded_domain(guarded[index])
                ),
                None,
            )
            if replace_at is None:
                continue
            selected_ids.discard(id(guarded[replace_at]))
            guarded[replace_at] = replacement
            selected_ids.add(id(replacement))

        return guarded[:top_k]

    def _rrf_fuse(
        self,
        bm25_results: list[tuple[int, float]],
        vector_results: list[tuple[str, str, float, str]],
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> dict[str, SearchResult]:
        rrf_k = 60
        fused: dict[str, SearchResult] = {}

        for rank, (doc_idx, bm25_score) in enumerate(bm25_results):
            if doc_idx >= len(self.bm25._doc_ids):
                continue
            doc_id = self.bm25._doc_ids[doc_idx]
            content = self.bm25._documents[doc_idx]
            metadata = self._documents.get(doc_id, {}).get("metadata", {})
            rrf_bm25 = 1.0 / (rrf_k + rank + 1)
            fused[doc_id] = SearchResult(
                content=content,
                metadata=metadata,
                bm25_score=float(bm25_score),
                rrf_score=bm25_weight * rrf_bm25,
                source="bm25",
                source_file=metadata.get("source_file") or metadata.get("filename", ""),
                chunk_index=int(metadata.get("chunk_index", 0) or 0),
                source_page=int(metadata.get("source_page", 0) or 0),
            )

        for rank, (doc_id, content, vec_score, raw_metadata) in enumerate(vector_results):
            metadata: dict[str, Any] = {}
            if raw_metadata:
                try:
                    metadata = json.loads(raw_metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}

            rrf_vec = 1.0 / (rrf_k + rank + 1)
            if doc_id in fused:
                fused[doc_id].vector_score = float(vec_score)
                fused[doc_id].rrf_score += vector_weight * rrf_vec
                fused[doc_id].source = "hybrid"
            else:
                fused[doc_id] = SearchResult(
                    content=content,
                    metadata=metadata,
                    vector_score=float(vec_score),
                    rrf_score=vector_weight * rrf_vec,
                    source="vector",
                    source_file=metadata.get("source_file") or metadata.get("filename", ""),
                    chunk_index=int(metadata.get("chunk_index", 0) or 0),
                    source_page=int(metadata.get("source_page", 0) or 0),
                )

        return fused

    def _rebuild_bm25(self) -> None:
        docs = list(self._documents.items())
        self.bm25.index([doc["content"] for _, doc in docs], [doc_id for doc_id, _ in docs])


_retriever_cache: dict[str, HybridRetriever] = {}
_retriever_cache_lock = threading.Lock()


def get_hybrid_retriever(company_id: str = "default") -> HybridRetriever:
    company_id = str(company_id)
    if company_id in _retriever_cache:
        return _retriever_cache[company_id]
    with _retriever_cache_lock:
        if company_id not in _retriever_cache:
            _retriever_cache[company_id] = HybridRetriever(company_id)
        return _retriever_cache[company_id]

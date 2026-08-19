"""Knowledge Management API for brand document upload and retrieval."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.database import User

logger = get_logger(__name__)

router = APIRouter(tags=["knowledge"])

KNOWLEDGE_SEARCH_TIMEOUT_SECONDS = float(os.getenv("KNOWLEDGE_SEARCH_TIMEOUT_SECONDS", "8"))
KNOWLEDGE_SEARCH_MAX_WORKERS = int(os.getenv("KNOWLEDGE_SEARCH_MAX_WORKERS", "4"))
_knowledge_search_executor = ThreadPoolExecutor(max_workers=KNOWLEDGE_SEARCH_MAX_WORKERS)


VALID_KNOWLEDGE_IMPORT_DATA_SOURCES = {
    "manual_upload",
    "public_web",
    "cached_snapshot",
    "official_api",
    "partner_api",
}


def add_knowledge(text: str, metadata: dict, company_id: str = "default") -> str:
    """Lazy wrapper to avoid constructing MCP servers during app import."""
    from app.mcp_servers.knowledge_retrieval_server import add_knowledge as _add_knowledge

    return _add_knowledge(text=text, metadata=metadata, company_id=company_id)


def search_knowledge(query: str, n_results: int = 3, company_id: str = "default") -> str:
    """Lazy wrapper to avoid constructing MCP servers during app import."""
    from app.mcp_servers.knowledge_retrieval_server import search_knowledge as _search_knowledge

    return _search_knowledge(query=query, n_results=n_results, company_id=company_id)


def _effective_company_id(current_user: User) -> str:
    """从认证用户获取 company_id，用于多租户隔离（不信任客户端传入的 company_id）。

    客户端传入的 company_id 可能被伪造以跨租户访问知识库，因此统一以认证用户
    的 company_id 作为唯一可信来源。用户未关联公司时拒绝访问。
    """
    if not current_user.company_id:
        raise HTTPException(status_code=403, detail="User is not associated with any company")
    return str(current_user.company_id)


def _invalidate_result_cache_for_company(company_id: str) -> int:
    """Clear cached chat answers after knowledge-base mutations.

    Result cache keys are based on company + normalized question. If knowledge changes,
    the same question can have a different correct answer, so cached answers must be
    invalidated instead of silently serving stale RAG output.
    """
    try:
        from app.database import db as db_proxy
        from app.database.models import ResultCache

        company_id_int = int(company_id)
        with db_proxy.get_session() as session:
            deleted = (
                session.query(ResultCache)
                .filter(ResultCache.company_id == company_id_int)
                .delete(synchronize_session=False)
            )
            session.commit()
            logger.info(
                "result_cache_invalidated_for_knowledge_change",
                company_id=company_id_int,
                deleted=deleted,
            )
            return int(deleted or 0)
    except Exception as exc:
        logger.warning(
            "result_cache_invalidation_failed",
            company_id=company_id,
            error=str(exc),
        )
        return 0


def _extract_doc_id_from_add_result(result: str) -> str:
    """Parse add_knowledge ToolResult and return the stored document id."""
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        if parsed.get("status") == "ok":
            return str(parsed.get("data", {}).get("doc_id", "unknown"))
        message = parsed.get("message") or parsed.get("error") or str(result)
        raise HTTPException(status_code=500, detail=f"Failed to add knowledge: {message}")

    if "Successfully added" in str(result):
        return str(result).split("ID: ")[1] if "ID: " in str(result) else "unknown"

    raise HTTPException(status_code=500, detail=f"Failed to add knowledge: {result}")


def _knowledge_import_summary(items: list["KnowledgeImportItem"]) -> tuple[dict[str, int], str | None]:
    summary: dict[str, int] = {}
    for item in items:
        summary[item.data_source] = summary.get(item.data_source, 0) + 1

    if summary and "official_api" not in summary:
        return (
            summary,
            "imported_non_official_sources: 当前导入知识不是官方平台 API 直连，"
            "可用于真实业务测试和人工运营，但上线报告需标明来源。",
        )
    return summary, None


def _search_knowledge_with_timeout(
    *,
    query: str,
    n_results: int,
    company_id: str,
) -> str:
    """Run the blocking RAG search with a hard API timeout.

    Milvus, embedding, or reranker calls can occasionally stall in a live Docker
    environment. The API must fail visibly instead of holding the client forever,
    otherwise quality tests cannot distinguish a slow search from a broken one.
    """
    if KNOWLEDGE_SEARCH_TIMEOUT_SECONDS <= 0:
        return search_knowledge(query=query, n_results=n_results, company_id=company_id)

    future = _knowledge_search_executor.submit(
        search_knowledge,
        query=query,
        n_results=n_results,
        company_id=company_id,
    )
    try:
        return future.result(timeout=KNOWLEDGE_SEARCH_TIMEOUT_SECONDS)
    except FuturesTimeoutError as exc:
        future.cancel()
        logger.error(
            "knowledge_search_timeout",
            company_id=company_id,
            query_length=len(query),
            n_results=n_results,
            timeout_seconds=KNOWLEDGE_SEARCH_TIMEOUT_SECONDS,
        )
        raise HTTPException(
            status_code=504,
            detail=(
                "Knowledge search timed out; Milvus/embedding/reranker did not "
                f"finish within {KNOWLEDGE_SEARCH_TIMEOUT_SECONDS:g}s"
            ),
        ) from exc


class KnowledgeUploadRequest(BaseModel):
    """Request model for knowledge upload."""

    content: str = Field(
        ..., min_length=1, max_length=5000, description="Knowledge text content"
    )  # 限制最大 5000 字符，防止超大文本消耗向量化资源
    category: str = Field(
        default="general", description="Knowledge category"
    )  # 默认分类，减少前端必填字段
    scenario: str = Field(default="general", description="Knowledge scenario")
    company_id: str = Field(
        ..., description="Company identifier for multi-tenant storage"
    )  # 租户隔离，必填


class KnowledgeUploadResponse(BaseModel):
    """Response model for knowledge upload."""

    status: str = Field(..., description="Operation status")
    doc_id: str = Field(..., description="Document ID")


class KnowledgeImportItem(BaseModel):
    """Single structured knowledge item for non-enterprise-API workflows."""

    content: str = Field(..., min_length=1, max_length=5000)
    category: str = Field(default="general", min_length=1, max_length=100)
    scenario: str = Field(default="general", min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    external_id: str | None = Field(default=None, max_length=200)
    data_source: str = Field(
        default="manual_upload",
        description="manual_upload/public_web/cached_snapshot/official_api/partner_api",
    )
    source_url: str | None = Field(default=None, max_length=1000)
    source_note: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("data_source")
    @classmethod
    def validate_data_source(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        if normalized not in VALID_KNOWLEDGE_IMPORT_DATA_SOURCES:
            raise ValueError(
                "不支持的数据来源；正式导入只允许 "
                f"{sorted(VALID_KNOWLEDGE_IMPORT_DATA_SOURCES)}，不允许 mock/demo/seed/sample 静默进入生产知识库。"
            )
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in tags or []:
            tag = str(tag).strip()
            if tag and tag not in cleaned:
                cleaned.append(tag[:50])
        return cleaned


class KnowledgeImportRequest(BaseModel):
    """Batch structured knowledge import request."""

    items: list[KnowledgeImportItem] = Field(..., min_length=1, max_length=200)
    dry_run: bool = Field(default=False, description="Validate only; do not write")


class KnowledgeImportResponse(BaseModel):
    """Batch structured knowledge import response."""

    imported: int
    skipped: int
    dry_run: bool
    doc_ids: list[str] = Field(default_factory=list)
    data_source_summary: dict[str, int] = Field(default_factory=dict)
    data_source_warning: str | None = None
    errors: list[str] = Field(default_factory=list)


class KnowledgeSearchResponse(BaseModel):
    """Response model for knowledge search results."""

    content: str = Field(..., description="Knowledge content")
    metadata: dict[str, Any] = Field(..., description="Knowledge metadata")
    distance: float | None = Field(
        None, description="Search distance/similarity"
    )  # 向量距离越小越相似
    score: float | None = Field(None, description="Unified retrieval score")
    source: str | None = Field(None, description="Retrieval source: bm25/vector/hybrid")
    bm25_score: float | None = Field(None, description="Raw BM25 score")
    vector_score: float | None = Field(None, description="Raw vector similarity score")
    rrf_score: float | None = Field(None, description="Reciprocal rank fusion score")
    rerank_score: float | None = Field(None, description="Optional reranker score")
    source_file: str | None = Field(None, description="Source file name")
    chunk_index: int | None = Field(None, description="Source chunk index")
    source_page: int | None = Field(None, description="Source page number")


class DocumentListItem(BaseModel):
    """Document list item."""

    id: str = Field(..., description="Document ID")
    filename: str = Field(default="", description="Original filename")
    category: str = Field(default="", description="Document category")
    chunks: int = Field(default=0, description="Number of chunks")
    source: str = Field(default="", description="Upload source")
    text_status: str = Field(default="ready", description="Text processing status")
    multimodal_status: str = Field(default="ready", description="Multimodal processing status")


class DocumentListResponse(BaseModel):
    """Response model for document listing."""

    documents: list[DocumentListItem] = Field(default_factory=list, description="List of documents")
    total: int = Field(default=0, description="Total number of documents")


class DocumentDeleteResponse(BaseModel):
    """Response model for document deletion."""

    status: str = Field(..., description="Operation status")
    message: str = Field(default="", description="Result message")


class DocumentStatusResponse(BaseModel):
    """Response model for document status."""

    doc_id: str = Field(..., description="Document ID")
    text_state: str = Field(default="ready", description="Text processing state")
    multimodal_state: str = Field(default="ready", description="Multimodal processing state")
    is_fully_processed: bool = Field(default=False, description="Whether fully processed")
    has_failed: bool = Field(default=False, description="Whether processing failed")
    text_error: str = Field(default="", description="Text processing error if any")
    multimodal_error: str = Field(default="", description="Multimodal processing error if any")


class ErrorResponse(BaseModel):
    """Error response model."""

    status: str = Field(default="error", description="Error status")
    message: str = Field(..., description="Error message")


@router.post(
    "/upload",
    response_model=KnowledgeUploadResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def upload_knowledge(
    request: KnowledgeUploadRequest,
    current_user: User = Depends(get_current_active_user),
) -> KnowledgeUploadResponse:
    """
    Upload brand knowledge to the knowledge base.

    - **content**: Knowledge text content (required, max 5000 chars)
    - **category**: Knowledge category (optional, default 'general')
    - **scenario**: Knowledge scenario (optional, default 'general')
    - **company_id**: Company identifier (required) —— 已忽略，改用认证用户的 company_id
    """
    try:
        # 安全修复：company_id 从认证用户获取，忽略请求体中可被伪造的 company_id
        company_id = _effective_company_id(current_user)

        # Validate content is not empty
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="Content cannot be empty")

        # Prepare metadata
        metadata = {
            "category": request.category,
            "scenario": request.scenario,
            "source": "api_upload",  # 标记来源为 API 上传，区别于文件导入和人工反馈
        }

        # Add knowledge using the existing MCP server function
        result = add_knowledge(
            text=request.content,
            metadata=metadata,
            company_id=company_id,  # 按公司 ID 隔离知识库（来源：认证用户）
        )

        # add_knowledge 返回 ToolResult JSON 字符串，需解析后取 data.doc_id
        try:
            _parsed = json.loads(result)
            if isinstance(_parsed, dict) and _parsed.get("status") == "ok":
                doc_id = _parsed.get("data", {}).get("doc_id", "unknown")
                _invalidate_result_cache_for_company(company_id)
                return KnowledgeUploadResponse(status="success", doc_id=doc_id)
            else:
                _msg = (
                    _parsed.get("message", str(result))
                    if isinstance(_parsed, dict)
                    else str(result)
                )
                raise HTTPException(status_code=500, detail=f"Failed to add knowledge: {_msg}")
        except (json.JSONDecodeError, TypeError):
            # 兼容旧格式（纯字符串）
            if "Successfully added" in result:
                doc_id = result.split("ID: ")[1] if "ID: " in result else "unknown"
                _invalidate_result_cache_for_company(company_id)
                return KnowledgeUploadResponse(status="success", doc_id=doc_id)
            raise HTTPException(status_code=500, detail=f"Failed to add knowledge: {result}")

    except HTTPException:
        raise  # 重新抛出 HTTPException，保持原有状态码
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post(
    "/import",
    response_model=KnowledgeImportResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def import_knowledge(
    request: KnowledgeImportRequest,
    current_user: User = Depends(get_current_active_user),
) -> KnowledgeImportResponse:
    """
    批量导入结构化知识。

    这是没有企业 API 权限时的正式替代入口：支持人工整理、公开网页、
    缓存快照、合作方 API 或官方 API 导入，并保留 data_source/source_url/source_note
    作为溯源字段。接口拒绝 mock/demo/seed/sample，避免生产环境静默使用演示数据。
    """
    try:
        company_id = _effective_company_id(current_user)
        data_source_summary, data_source_warning = _knowledge_import_summary(request.items)

        if request.dry_run:
            return KnowledgeImportResponse(
                imported=len(request.items),
                skipped=0,
                dry_run=True,
                doc_ids=[],
                data_source_summary=data_source_summary,
                data_source_warning=data_source_warning,
                errors=[],
            )

        imported = 0
        skipped = 0
        doc_ids: list[str] = []
        errors: list[str] = []

        for idx, item in enumerate(request.items, start=1):
            if not item.content.strip():
                skipped += 1
                errors.append(f"items[{idx}]: Content cannot be empty")
                continue

            metadata = {
                "category": item.category,
                "scenario": item.scenario,
                "source": "structured_import",
                "data_source": item.data_source,
                "source_url": item.source_url or "",
                "source_note": item.source_note or "",
                "title": item.title or "",
                "external_id": item.external_id or "",
                "tags": item.tags,
            }

            try:
                result = add_knowledge(
                    text=item.content,
                    metadata=metadata,
                    company_id=company_id,
                )
                doc_ids.append(_extract_doc_id_from_add_result(result))
                imported += 1
            except HTTPException as exc:
                skipped += 1
                errors.append(f"items[{idx}]: {exc.detail}")
            except Exception as exc:
                skipped += 1
                errors.append(f"items[{idx}]: {exc}")

        if imported:
            _invalidate_result_cache_for_company(company_id)

        logger.info(
            "knowledge_import_api",
            company_id=company_id,
            imported=imported,
            skipped=skipped,
            dry_run=False,
            data_source_summary=data_source_summary,
            data_source_warning=data_source_warning,
        )
        return KnowledgeImportResponse(
            imported=imported,
            skipped=skipped,
            dry_run=False,
            doc_ids=doc_ids,
            data_source_summary=data_source_summary,
            data_source_warning=data_source_warning,
            errors=errors,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("knowledge_import_api_error")
        raise HTTPException(status_code=500, detail="知识导入失败")


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".txt",
}  # 白名单机制：只允许安全的文档格式
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 限制 50MB，防止大文件导致内存溢出
SAFE_UPLOAD_FILENAME_RE = re.compile(r"[^0-9A-Za-z._ \-\u4e00-\u9fff]+")
ALLOWED_UPLOAD_CONTENT_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".html": {"text/html", "application/xhtml+xml", "application/octet-stream"},
    ".htm": {"text/html", "application/xhtml+xml", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
}


def _sanitize_upload_filename(filename: str) -> str:
    name = PurePath(str(filename).replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    name = SAFE_UPLOAD_FILENAME_RE.sub("_", name).strip(" .")
    if not name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if len(name) > 160:
        stem, dot, suffix = name.rpartition(".")
        if dot:
            name = f"{stem[: max(1, 159 - len(suffix))]}.{suffix}"
        else:
            name = name[:160]
    return name


def _upload_suffix(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _validate_upload_content_type(suffix: str, content_type: str | None) -> None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized:
        return
    allowed = ALLOWED_UPLOAD_CONTENT_TYPES.get(suffix, set())
    if normalized not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"File content type {normalized} does not match extension {suffix}",
        )


class FileUploadResponse(BaseModel):
    status: str
    doc_id: str
    filename: str
    chunks: int  # 文档被切分为多少个文本块
    text_length: int  # 提取的文本总长度


@router.post(
    "/upload-file",
    response_model=FileUploadResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
async def upload_knowledge_file(
    file: UploadFile = File(...),  # File(...) 表示必传文件
    company_id: str = Form(
        ...
    ),  # 使用 Form 而非 JSON，因为 multipart 上传；已忽略，改用认证用户的 company_id
    category: str = Form(default="general"),
    current_user: User = Depends(get_current_active_user),
):
    """上传文档文件（PDF/Word/HTML/TXT）自动解析并入库"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    safe_filename = _sanitize_upload_filename(file.filename)
    suffix = _upload_suffix(safe_filename)  # 提取扩展名并转小写，统一格式
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {suffix}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    _validate_upload_content_type(suffix, file.content_type)

    content = await file.read()  # 异步读取文件内容，避免阻塞事件循环
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413, detail=f"File size exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)}MB limit"
        )

    try:
        # 安全修复：company_id 从认证用户获取，忽略 Form 中可被伪造的 company_id
        effective_company_id = _effective_company_id(current_user)
        from app.rag.company_context_bus import get_company_context_bus  # 延迟导入，避免循环依赖

        bus = get_company_context_bus(effective_company_id)
        result = bus.ingest_document(  # 使用公司上下文总线处理文档：解析 → 切分 → 向量化 → 入库
            filename=safe_filename,
            content=content,
            metadata={"category": category, "source": "file_upload"},
        )
        _invalidate_result_cache_for_company(effective_company_id)
        return FileUploadResponse(
            status="success",
            doc_id=result["doc_id"],
            filename=result["filename"],
            chunks=result["chunks"],
            text_length=result["text_length"],
        )
    except ValueError:
        raise HTTPException(
            status_code=400, detail="文件格式不支持或处理失败"
        )  # ValueError 通常是格式不支持，返回 400
    except Exception:
        logger.exception("file_upload_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/documents", response_model=DocumentListResponse, responses={500: {"model": ErrorResponse}}
)
def list_documents(
    company_id: str = Query(
        ..., description="Company identifier for multi-tenant isolation"
    ),  # 已忽略，改用认证用户的 company_id
    category: str = Query(default=None, description="Optional category filter"),
    current_user: User = Depends(get_current_active_user),
) -> DocumentListResponse:
    """
    列出公司知识库中的所有文档。

    - **company_id**: 公司标识（已忽略，改用认证用户的 company_id）
    - **category**: 分类过滤（可选）
    """
    try:
        # 安全修复：company_id 从认证用户获取，忽略 Query 中可被伪造的 company_id
        effective_company_id = _effective_company_id(current_user)
        from app.rag.doc_status import get_doc_status_manager
        from app.rag.hybrid_retriever import get_hybrid_retriever

        retriever = get_hybrid_retriever(effective_company_id)
        raw_docs = retriever.list_documents()
        status_mgr = get_doc_status_manager()

        # 按 filename 去重（同一文件可能有多个 chunk）
        seen = {}
        for doc in raw_docs:
            filename = doc.get("filename", "")
            if not filename:
                continue
            if filename in seen:
                continue
            seen[filename] = True

            metadata = doc.get("metadata") or {}
            doc_id = str(
                metadata.get("document_id")
                or metadata.get("doc_id")
                or doc.get("id", "")
            )
            doc_status = status_mgr.get(doc_id)

            if category and doc.get("category") != category:
                continue

            seen[filename] = DocumentListItem(
                id=doc_id,
                filename=filename,
                category=doc.get("category", ""),
                chunks=int(doc.get("total_chunks", 1) or 1),
                source=doc.get("source", ""),
                text_status=doc_status.text_state.value if doc_status else "ready",
                multimodal_status=doc_status.multimodal_state.value if doc_status else "ready",
            )

        items = [v for v in seen.values() if isinstance(v, DocumentListItem)]
        return DocumentListResponse(documents=items, total=len(items))
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_documents_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete(
    "/documents/{doc_id}",
    response_model=DocumentDeleteResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def delete_document(
    doc_id: str,
    company_id: str = Query(
        ..., description="Company identifier for multi-tenant isolation"
    ),  # 已忽略，改用认证用户的 company_id
    current_user: User = Depends(get_current_active_user),
) -> DocumentDeleteResponse:
    """
    删除知识库中的指定文档。

    - **doc_id**: 文档 ID（路径参数）
    - **company_id**: 公司标识（已忽略，改用认证用户的 company_id）
    """
    try:
        # 安全修复：company_id 从认证用户获取，忽略 Query 中可被伪造的 company_id
        effective_company_id = _effective_company_id(current_user)
        from app.rag.doc_status import get_doc_status_manager
        from app.rag.hybrid_retriever import get_hybrid_retriever

        retriever = get_hybrid_retriever(effective_company_id)
        success = retriever.delete_document(doc_id)

        # 同步清理文档状态追踪
        status_mgr = get_doc_status_manager()
        status_mgr.remove(doc_id)
        _invalidate_result_cache_for_company(effective_company_id)

        if success:
            return DocumentDeleteResponse(status="success", message=f"Document {doc_id} deleted")
        else:
            return DocumentDeleteResponse(
                status="warning", message=f"Document {doc_id} may not exist or already deleted"
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete(
    "/documents", response_model=DocumentDeleteResponse, responses={500: {"model": ErrorResponse}}
)
def delete_all_documents(
    company_id: str = Query(
        ..., description="Company identifier for multi-tenant isolation"
    ),  # 已忽略，改用认证用户的 company_id
    current_user: User = Depends(get_current_active_user),
) -> DocumentDeleteResponse:
    """
    清空公司知识库中的所有文档。

    - **company_id**: 公司标识（已忽略，改用认证用户的 company_id）
    """
    try:
        # 安全修复：company_id 从认证用户获取，忽略 Query 中可被伪造的 company_id
        effective_company_id = _effective_company_id(current_user)
        from app.rag.doc_status import get_doc_status_manager
        from app.rag.hybrid_retriever import get_hybrid_retriever

        retriever = get_hybrid_retriever(effective_company_id)
        count = retriever.delete_company_documents()

        # 清理所有状态追踪
        status_mgr = get_doc_status_manager()
        status_mgr.clear()
        _invalidate_result_cache_for_company(effective_company_id)

        return DocumentDeleteResponse(status="success", message=f"Deleted {count} documents")
    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/documents/{doc_id}/status",
    response_model=DocumentStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_document_status(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> DocumentStatusResponse:
    """
    查询文档处理状态。

    - **doc_id**: 文档 ID（路径参数）
    """
    try:
        from app.rag.doc_status import get_doc_status_manager
        from app.rag.hybrid_retriever import get_hybrid_retriever

        effective_company_id = _effective_company_id(current_user)
        status_mgr = get_doc_status_manager()
        doc_status = status_mgr.get(doc_id)

        if not doc_status:
            retriever = get_hybrid_retriever(effective_company_id)
            doc_exists = any(
                str(doc.get("id", "")) == str(doc_id)
                or str((doc.get("metadata") or {}).get("document_id", "")) == str(doc_id)
                or str((doc.get("metadata") or {}).get("doc_id", "")) == str(doc_id)
                for doc in retriever.list_documents()
            )
            if doc_exists:
                return DocumentStatusResponse(
                    doc_id=doc_id,
                    text_state="ready",
                    multimodal_state="ready",
                    is_fully_processed=True,
                    has_failed=False,
                    text_error="",
                    multimodal_error="",
                )
            raise HTTPException(
                status_code=404, detail=f"Document {doc_id} not found in status tracker"
            )

        return DocumentStatusResponse(
            doc_id=doc_id,
            text_state=doc_status.text_state.value,
            multimodal_state=doc_status.multimodal_state.value,
            is_fully_processed=doc_status.is_fully_processed,
            has_failed=doc_status.has_failed,
            text_error=doc_status.text_error,
            multimodal_error=doc_status.multimodal_error,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_document_status_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/search",
    response_model=list[KnowledgeSearchResponse],
    responses={
        400: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def search_knowledge_api(
    query: str = Query(..., description="Search query for finding relevant knowledge"),
    n_results: int = Query(
        default=3, ge=1, le=20, description="Number of results to return"
    ),  # 限制返回数量，避免向量搜索返回过多结果
    company_id: str = Query(
        ..., description="Company identifier for multi-tenant search"
    ),  # 已忽略，改用认证用户的 company_id
    current_user: User = Depends(get_current_active_user),
) -> list[KnowledgeSearchResponse]:
    """
    Search for knowledge in the company's knowledge base.

    - **query**: Search query (required)
    - **n_results**: Number of results to return (optional, default 3, max 20)
    - **company_id**: Company identifier (已忽略，改用认证用户的 company_id)
    """
    try:
        # 安全修复：company_id 从认证用户获取，忽略 Query 中可被伪造的 company_id
        effective_company_id = _effective_company_id(current_user)

        # Validate query is not empty
        if not query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        # Search knowledge using the existing MCP server function
        _results_raw = _search_knowledge_with_timeout(
            query=query,
            n_results=n_results,
            company_id=effective_company_id,  # 按公司 ID 隔离搜索范围（来源：认证用户）
        )

        # search_knowledge 返回 ToolResult JSON 字符串，需解析后取 data 字段
        try:
            _parsed = json.loads(_results_raw)
            results = (
                _parsed.get("data", [])
                if isinstance(_parsed, dict)
                else (_parsed if isinstance(_parsed, list) else [])
            )
        except (json.JSONDecodeError, TypeError):
            results = []

        # Convert results to response format
        search_results = []
        for result in results:
            search_result = KnowledgeSearchResponse(
                content=result.get("content", ""),
                metadata=result.get("metadata", {}),
                distance=result.get("distance"),  # 向量距离，越小表示越相似
                score=result.get("score"),
                source=result.get("source"),
                bm25_score=result.get("bm25_score"),
                vector_score=result.get("vector_score"),
                rrf_score=result.get("rrf_score"),
                rerank_score=result.get("rerank_score"),
                source_file=result.get("source_file"),
                chunk_index=result.get("chunk_index"),
                source_page=result.get("source_page"),
            )
            search_results.append(search_result)

        return search_results

    except HTTPException:
        raise  # 重新抛出 HTTPException
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")

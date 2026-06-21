"""Knowledge Management API for brand document upload and retrieval."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.mcp_servers.knowledge_retrieval_server import add_knowledge, search_knowledge  # 复用已有的 MCP Server 知识管理函数

logger = get_logger(__name__)

router = APIRouter(tags=["knowledge"])


class KnowledgeUploadRequest(BaseModel):
    """Request model for knowledge upload."""
    content: str = Field(..., min_length=1, max_length=5000, description="Knowledge text content")  # 限制最大 5000 字符，防止超大文本消耗向量化资源
    category: str = Field(default="general", description="Knowledge category")  # 默认分类，减少前端必填字段
    scenario: str = Field(default="general", description="Knowledge scenario")
    company_id: str = Field(..., description="Company identifier for multi-tenant storage")  # 租户隔离，必填


class KnowledgeUploadResponse(BaseModel):
    """Response model for knowledge upload."""
    status: str = Field(..., description="Operation status")
    doc_id: str = Field(..., description="Document ID")


class KnowledgeSearchResponse(BaseModel):
    """Response model for knowledge search results."""
    content: str = Field(..., description="Knowledge content")
    metadata: dict[str, Any] = Field(..., description="Knowledge metadata")
    distance: float | None = Field(None, description="Search distance/similarity")  # 向量距离越小越相似


class ErrorResponse(BaseModel):
    """Error response model."""
    status: str = Field(default="error", description="Error status")
    message: str = Field(..., description="Error message")


@router.post("/upload", response_model=KnowledgeUploadResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def upload_knowledge(request: KnowledgeUploadRequest) -> KnowledgeUploadResponse:
    """
    Upload brand knowledge to the knowledge base.
    
    - **content**: Knowledge text content (required, max 5000 chars)
    - **category**: Knowledge category (optional, default 'general')
    - **scenario**: Knowledge scenario (optional, default 'general') 
    - **company_id**: Company identifier (required)
    """
    try:
        # Validate content is not empty
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="Content cannot be empty")

        # Prepare metadata
        metadata = {
            "category": request.category,
            "scenario": request.scenario,
            "source": "api_upload"  # 标记来源为 API 上传，区别于文件导入和人工反馈
        }

        # Add knowledge using the existing MCP server function
        result = add_knowledge(
            text=request.content,
            metadata=metadata,
            company_id=request.company_id  # 按公司 ID 隔离知识库
        )

        # Extract document ID from result
        if "Successfully added" in result:
            # Extract ID from message like "Successfully added knowledge with ID: manual_xxxx"
            doc_id = result.split("ID: ")[1] if "ID: " in result else "unknown"  # 字符串解析获取文档 ID
            return KnowledgeUploadResponse(status="success", doc_id=doc_id)
        else:
            raise HTTPException(status_code=500, detail=f"Failed to add knowledge: {result}")

    except HTTPException:
        raise  # 重新抛出 HTTPException，保持原有状态码
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".html", ".htm", ".txt"}  # 白名单机制：只允许安全的文档格式
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 限制 50MB，防止大文件导致内存溢出


class FileUploadResponse(BaseModel):
    status: str
    doc_id: str
    filename: str
    chunks: int  # 文档被切分为多少个文本块
    text_length: int  # 提取的文本总长度


@router.post("/upload-file", response_model=FileUploadResponse,
             responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}})
async def upload_knowledge_file(
    file: UploadFile = File(...),  # File(...) 表示必传文件
    company_id: str = Form(...),  # 使用 Form 而非 JSON，因为 multipart 上传
    category: str = Form(default="general"),
):
    """上传文档文件（PDF/Word/HTML/TXT）自动解析并入库"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""  # 提取扩展名并转小写，统一格式
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {suffix}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    content = await file.read()  # 异步读取文件内容，避免阻塞事件循环
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)}MB limit")

    try:
        from app.rag.company_context_bus import get_company_context_bus  # 延迟导入，避免循环依赖
        bus = get_company_context_bus(company_id)
        result = bus.ingest_document(  # 使用公司上下文总线处理文档：解析 → 切分 → 向量化 → 入库
            filename=file.filename,
            content=content,
            metadata={"category": category, "source": "file_upload"},
        )
        return FileUploadResponse(
            status="success",
            doc_id=result["doc_id"],
            filename=result["filename"],
            chunks=result["chunks"],
            text_length=result["text_length"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))  # ValueError 通常是格式不支持，返回 400
    except Exception as e:
        logger.error("file_upload_failed", error=str(e), filename=file.filename)
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")


@router.get("/search", response_model=list[KnowledgeSearchResponse], responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def search_knowledge_api(
    query: str = Query(..., description="Search query for finding relevant knowledge"),
    n_results: int = Query(default=3, ge=1, le=20, description="Number of results to return"),  # 限制返回数量，避免向量搜索返回过多结果
    company_id: str = Query(..., description="Company identifier for multi-tenant search")
) -> list[KnowledgeSearchResponse]:
    """
    Search for knowledge in the company's knowledge base.
    
    - **query**: Search query (required)
    - **n_results**: Number of results to return (optional, default 3, max 20)
    - **company_id**: Company identifier (required)
    """
    try:
        # Validate query is not empty
        if not query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        # Search knowledge using the existing MCP server function
        results = search_knowledge(
            query=query,
            n_results=n_results,
            company_id=company_id  # 按公司 ID 隔离搜索范围
        )

        # Convert results to response format
        search_results = []
        for result in results:
            search_result = KnowledgeSearchResponse(
                content=result.get('content', ''),
                metadata=result.get('metadata', {}),
                distance=result.get('distance')  # 向量距离，越小表示越相似
            )
            search_results.append(search_result)

        return search_results

    except HTTPException:
        raise  # 重新抛出 HTTPException
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

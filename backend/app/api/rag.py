"""RAG 配置管理 API — 嵌入模型、公司资料、检索配置"""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.database import User

logger = get_logger(__name__)

router = APIRouter(tags=["rag"])


# ═══════════════════════════════════════════════════
# 嵌入模型管理
# ═══════════════════════════════════════════════════


class EmbeddingModelItem(BaseModel):
    """嵌入模型项"""

    name: str = Field(..., description="模型别名")
    model_path: str = Field(..., description="模型路径")
    is_active: bool = Field(default=False, description="是否为当前激活模型")


class EmbeddingModelListResponse(BaseModel):
    """嵌入模型列表响应"""

    models: list[EmbeddingModelItem] = Field(default_factory=list)
    active_model: str = Field(default="", description="当前激活的模型名称")


class SwitchModelRequest(BaseModel):
    """切换模型请求"""

    model_name: str = Field(..., description="要切换到的模型名称")


class SwitchModelResponse(BaseModel):
    """切换模型响应"""

    status: str
    previous_model: str = Field(default="")
    current_model: str = Field(default="")


@router.get("/embedding/models", response_model=EmbeddingModelListResponse)
def list_embedding_models(
    current_user: User = Depends(get_current_active_user),
) -> EmbeddingModelListResponse:
    """列出所有可用的嵌入模型"""
    try:
        from app.rag.embedding_service import (
            EMBEDDING_MODEL_REGISTRY,
            get_embedding_service,
        )

        service = get_embedding_service()
        active_model = service.model_name

        models = []
        for name, path in EMBEDDING_MODEL_REGISTRY.items():
            models.append(
                EmbeddingModelItem(
                    name=name,
                    model_path=path,
                    is_active=(path == active_model or name == active_model),
                )
            )

        return EmbeddingModelListResponse(models=models, active_model=active_model)
    except Exception:
        logger.exception("list_models_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.put("/embedding/switch", response_model=SwitchModelResponse)
def switch_embedding_model(
    request: SwitchModelRequest,
    current_user: User = Depends(get_current_active_user),
) -> SwitchModelResponse:
    """切换当前使用的嵌入模型"""
    try:
        from app.rag.embedding_service import (
            get_embedding_model_path,
            get_embedding_service,
        )

        service = get_embedding_service()
        previous = service.model_name

        # 验证模型名称
        model_path = get_embedding_model_path(request.model_name)
        if not model_path:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model: {request.model_name}. Use /api/rag/embedding/models to list available models.",
            )

        service.switch_model(request.model_name)
        logger.info("embedding_model_switched", previous=previous, current=request.model_name)

        return SwitchModelResponse(
            status="success",
            previous_model=previous,
            current_model=request.model_name,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("switch_model_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# ═══════════════════════════════════════════════════
# 嵌入模式配置管理（T1.2：local / api_siliconflow / api_deepseek / api_openai）
# ═══════════════════════════════════════════════════

# 临时内存存储（T1.3 将替换为 embedding_config 数据库表）
# 结构: {company_id: {mode, api_base_url, api_key_encrypted, model_name}}
_embedding_config_store: dict[int, dict] = {}


def _mask_api_key(key: str) -> str:
    """脱敏 API Key：sk-****abcd 格式（前 3 + 后 4）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


class EmbeddingConfigResponse(BaseModel):
    """嵌入配置响应（GET）"""

    mode: str = Field(
        default="local", description="嵌入模式: local/api_siliconflow/api_deepseek/api_openai"
    )
    api_base_url: str = Field(default="", description="API 基址")
    model_name: str = Field(default="", description="模型名称")
    api_key_masked: str = Field(default="", description="脱敏的 API Key，如 sk-****abcd")


class EmbeddingConfigUpdateRequest(BaseModel):
    """嵌入配置更新请求（PUT）"""

    mode: str = Field(..., description="嵌入模式: local/api_siliconflow/api_deepseek/api_openai")
    api_base_url: str = Field(default="", description="API 基址（API 模式必填）")
    api_key: str = Field(default="", description="API Key 明文，后端加密存储；空表示保留原值")
    model_name: str = Field(default="", description="API 模型名（API 模式必填）")


class EmbeddingTestRequest(BaseModel):
    """嵌入连接测试请求（POST，不存档）"""

    mode: str = Field(..., description="嵌入模式")
    api_base_url: str = Field(default="", description="API 基址")
    api_key: str = Field(default="", description="API Key")
    model_name: str = Field(default="", description="模型名称")


class EmbeddingTestResponse(BaseModel):
    """嵌入连接测试响应"""

    ok: bool
    dims: int = Field(default=0, description="返回向量维度")
    latency_ms: int = Field(default=0, description="调用耗时（毫秒）")
    message: str = Field(default="", description="成功或中性提示")
    error: str = Field(default="", description="失败时的错误信息")


@router.get("/embedding/config", response_model=EmbeddingConfigResponse)
def get_embedding_config(
    current_user: User = Depends(get_current_active_user),
) -> EmbeddingConfigResponse:
    """获取当前公司的嵌入配置。

    - api_key 返回脱敏版（如 "sk-****abcd"）
    - 未配置时返回默认值（mode=local）
    """
    from app.rag.embedding_service import get_embedding_service

    # 无公司用户不应默认使用公司 1 的配置，直接使用 current_user.company_id
    company_id = current_user.company_id
    service = get_embedding_service()

    # 从内存存储读取（T1.3 后改为数据库）
    cfg = _embedding_config_store.get(company_id, {})

    mode = cfg.get("mode", service.mode.value)
    api_base_url = cfg.get("api_base_url", "")
    model_name = cfg.get("model_name", "")
    api_key_encrypted = cfg.get("api_key_encrypted", "")

    # 解密 API Key 用于脱敏显示
    api_key_masked = ""
    if api_key_encrypted:
        try:
            from app.utils.encryption import decrypt_data

            api_key_plain = decrypt_data(api_key_encrypted)
            api_key_masked = _mask_api_key(api_key_plain)
        except Exception as e:
            logger.warning("embedding_config_decrypt_failed", error=str(e))
            api_key_masked = "****"

    return EmbeddingConfigResponse(
        mode=mode,
        api_base_url=api_base_url,
        model_name=model_name,
        api_key_masked=api_key_masked,
    )


@router.put("/embedding/config", response_model=EmbeddingConfigResponse)
def update_embedding_config(
    request: EmbeddingConfigUpdateRequest,
    current_user: User = Depends(get_current_active_user),
) -> EmbeddingConfigResponse:
    """更新嵌入配置并热切换（不重启服务）。

    - api_key 加密存入内存（T1.3 后存数据库 embedding_config 表）
    - mode 变更后调用 embedding_service.switch_mode() 热切换
    - api_key 为空时保留原值（便于只改 mode 不改 key）
    """
    from app.rag.embedding_service import EmbeddingMode, get_embedding_service
    from app.utils.encryption import decrypt_data, encrypt_data

    # 无公司用户不应默认使用公司 1 的配置，直接使用 current_user.company_id
    company_id = current_user.company_id

    # 验证 mode
    try:
        mode = EmbeddingMode(request.mode)
    except ValueError:
        valid = [m.value for m in EmbeddingMode]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: '{request.mode}'. Must be one of {valid}",
        )

    # 准备存储
    old_cfg = _embedding_config_store.get(company_id, {})
    cfg: dict = {
        "mode": request.mode,
        "api_base_url": request.api_base_url,
        "model_name": request.model_name,
    }

    # API Key 处理：新值加密存储；空值保留原值
    if request.api_key:
        cfg["api_key_encrypted"] = encrypt_data(request.api_key)
    else:
        cfg["api_key_encrypted"] = old_cfg.get("api_key_encrypted", "")

    # 存储配置
    _embedding_config_store[company_id] = cfg

    # 解密 API Key 用于热切换
    api_key_plain = ""
    if cfg.get("api_key_encrypted"):
        try:
            api_key_plain = decrypt_data(cfg["api_key_encrypted"])
        except Exception as e:
            logger.warning("embedding_config_decrypt_for_switch_failed", error=str(e))

    # 热切换 EmbeddingService
    service = get_embedding_service()
    service.switch_mode(
        mode=mode,
        api_base_url=request.api_base_url or None,
        api_key=api_key_plain or None,
        api_model_name=request.model_name or None,
    )

    # 脱敏返回
    api_key_masked = _mask_api_key(api_key_plain) if api_key_plain else ""

    logger.info(
        "embedding_config_updated",
        company_id=company_id,
        mode=request.mode,
        has_key=bool(api_key_plain),
    )

    return EmbeddingConfigResponse(
        mode=request.mode,
        api_base_url=request.api_base_url,
        model_name=request.model_name,
        api_key_masked=api_key_masked,
    )


@router.post("/embedding/test", response_model=EmbeddingTestResponse)
def test_embedding_connection(
    request: EmbeddingTestRequest,
    current_user: User = Depends(get_current_active_user),
) -> EmbeddingTestResponse:
    """测试嵌入 API 连接（不存档）。

    - 用参数临时创建 EmbeddingAPIBackend，encode "测试连接" 文本
    - 成功返回 {ok: true, dims, latency_ms}
    - 失败返回 {ok: false, error}
    - 本地模式直接返回 ok=True（无需测试）
    """
    import time

    from app.rag.embedding_service import EMBEDDING_API_PRESETS, EmbeddingAPIBackend, EmbeddingMode

    # 本地模式无需测试
    if request.mode == "local":
        return EmbeddingTestResponse(
            ok=True,
            dims=512,
            latency_ms=0,
            message="\u672c\u5730\u6a21\u5f0f\u65e0\u9700\u6d4b\u8bd5",
        )

    # 验证 mode
    try:
        mode = EmbeddingMode(request.mode)
    except ValueError:
        return EmbeddingTestResponse(ok=False, error=f"无效模式: {request.mode}")

    # 解析参数：未传则用预设
    preset = EMBEDDING_API_PRESETS.get(mode, {})
    base_url = request.api_base_url or preset.get("base_url", "")
    api_key = request.api_key
    model_name = request.model_name or preset.get("model_name", "")

    if not base_url:
        return EmbeddingTestResponse(ok=False, error="缺少 api_base_url")
    if not api_key:
        return EmbeddingTestResponse(ok=False, error="缺少 api_key")

    # 创建临时后端测试连接
    try:
        backend = EmbeddingAPIBackend(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            mode=mode,
        )
        start = time.time()
        vectors = backend.encode(["测试连接"])
        latency_ms = int((time.time() - start) * 1000)

        if vectors and len(vectors) > 0 and len(vectors[0]) > 0:
            return EmbeddingTestResponse(
                ok=True,
                dims=len(vectors[0]),
                latency_ms=latency_ms,
            )
        return EmbeddingTestResponse(
            ok=False,
            error="API 返回空向量",
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.warning("embedding_test_failed", mode=request.mode, error=str(e))
        return EmbeddingTestResponse(ok=False, error=str(e))


# ═══════════════════════════════════════════════════
# 公司资料管理
# ═══════════════════════════════════════════════════


class CompanyProfileRequest(BaseModel):
    """公司资料更新请求"""

    company_name: str = Field(default="", description="公司名称")
    industry: str = Field(default="", description="行业分类")
    brand_description: str = Field(default="", description="品牌描述")
    target_audience: str = Field(default="", description="目标受众")
    product_categories: list[str] = Field(default_factory=list, description="产品类目")
    core_products: list[dict] = Field(default_factory=list, description="核心产品列表")
    brand_voice: str = Field(default="", description="品牌调性")
    competitors: list[str] = Field(default_factory=list, description="竞品列表")
    usp: str = Field(default="", description="独特卖点")
    social_media_accounts: dict[str, str] = Field(default_factory=dict, description="社媒账号")


class CompanyProfileResponse(BaseModel):
    """公司资料响应"""

    company_id: str = Field(..., description="公司 ID")
    company_name: str = Field(default="")
    industry: str = Field(default="")
    brand_description: str = Field(default="")
    target_audience: str = Field(default="")
    product_categories: list[str] = Field(default_factory=list)
    core_products: list[dict] = Field(default_factory=list)
    brand_voice: str = Field(default="")
    competitors: list[str] = Field(default_factory=list)
    usp: str = Field(default="")
    social_media_accounts: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    setup_required: bool = Field(default=False)


_COMPANY_PROFILE_REQUIRED_FIELDS = (
    "industry",
    "brand_description",
    "target_audience",
    "product_categories",
    "competitors",
    "usp",
)


def _has_profile_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _company_profile_status(values: dict) -> dict:
    missing_fields = [
        field
        for field in _COMPANY_PROFILE_REQUIRED_FIELDS
        if not _has_profile_value(values.get(field))
    ]
    total = len(_COMPANY_PROFILE_REQUIRED_FIELDS)
    completeness_score = round((total - len(missing_fields)) / total, 2)
    return {
        "missing_fields": missing_fields,
        "completeness_score": completeness_score,
        "setup_required": bool(missing_fields),
    }


@router.get("/company/profile", response_model=CompanyProfileResponse)
def get_company_profile(
    current_user: User = Depends(get_current_active_user),
) -> CompanyProfileResponse:
    """获取公司完整资料（Layer 1 上下文）"""
    try:
        from app.rag.company_context_bus import get_company_context_bus

        # company_id 强制从认证用户获取，防止跨租户伪造
        # company_context_bus 以字符串作为 key，需将 int 转为 str
        company_id = str(current_user.company_id) if current_user.company_id is not None else ""

        bus = get_company_context_bus(company_id)
        profile = bus.get_profile()

        if profile is None:
            return CompanyProfileResponse(
                company_id=company_id,
                **_company_profile_status({}),
            )

        values = {
            "company_name": profile.company_name,
            "industry": profile.industry,
            "brand_description": profile.brand_description,
            "target_audience": profile.target_audience,
            "product_categories": profile.product_categories,
            "core_products": profile.core_products,
            "brand_voice": profile.brand_voice,
            "competitors": profile.competitors,
            "usp": profile.usp,
            "social_media_accounts": profile.social_media_accounts,
        }
        return CompanyProfileResponse(
            company_id=company_id,
            **values,
            **_company_profile_status(values),
        )
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.put("/company/profile", response_model=CompanyProfileResponse)
def update_company_profile(
    request: CompanyProfileRequest,
    current_user: User = Depends(get_current_active_user),
) -> CompanyProfileResponse:
    """更新公司完整资料（Layer 1 上下文）"""
    try:
        from app.rag.company_context_bus import CompanyProfile, get_company_context_bus

        # company_id 强制从认证用户获取，防止跨租户伪造
        # company_context_bus 以字符串作为 key，需将 int 转为 str
        company_id = str(current_user.company_id) if current_user.company_id is not None else ""

        bus = get_company_context_bus(company_id)

        profile = CompanyProfile(
            company_name=request.company_name,
            industry=request.industry,
            brand_description=request.brand_description,
            target_audience=request.target_audience,
            product_categories=request.product_categories,
            core_products=request.core_products,
            brand_voice=request.brand_voice,
            competitors=request.competitors,
            usp=request.usp,
            social_media_accounts=request.social_media_accounts,
        )
        bus.set_profile(profile)
        logger.info("company_profile_updated", company_id=company_id)

        values = {
            "company_name": profile.company_name,
            "industry": profile.industry,
            "brand_description": profile.brand_description,
            "target_audience": profile.target_audience,
            "product_categories": profile.product_categories,
            "core_products": profile.core_products,
            "brand_voice": profile.brand_voice,
            "competitors": profile.competitors,
            "usp": profile.usp,
            "social_media_accounts": profile.social_media_accounts,
        }
        return CompanyProfileResponse(
            company_id=company_id,
            **values,
            **_company_profile_status(values),
        )
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# ═══════════════════════════════════════════════════
# RAG 系统配置总览
# ═══════════════════════════════════════════════════


class RagConfigResponse(BaseModel):
    """RAG 系统配置总览"""

    embedding_model: str = Field(default="", description="当前激活的嵌入模型")
    embedding_model_count: int = Field(default=0, description="可用嵌入模型数量")
    retrieval_strategy: str = Field(default="hybrid", description="检索策略")
    reranker_enabled: bool = Field(default=True, description="精排是否启用")
    graph_rag_enabled: bool = Field(default=True, description="知识图谱检索是否启用")
    multimodal_enabled: bool = Field(default=False, description="多模态检索是否启用")
    document_count: int = Field(default=0, description="已索引文档数")
    indexing_status: str = Field(default="idle", description="索引状态")
    evaluator_available: bool = Field(default=False, description="评估器是否可用")


@router.get("/config", response_model=RagConfigResponse)
def get_rag_config(
    current_user: User = Depends(get_current_active_user),
) -> RagConfigResponse:
    """获取 RAG 系统配置总览"""
    try:
        from app.rag.embedding_service import EMBEDDING_MODEL_REGISTRY, get_embedding_service
        from app.rag.hybrid_retriever import get_hybrid_retriever

        # company_id 强制从认证用户获取，防止跨租户伪造
        # hybrid_retriever 以字符串作为 key，需将 int 转为 str
        company_id = str(current_user.company_id) if current_user.company_id is not None else ""

        emb_service = get_embedding_service()
        retriever = get_hybrid_retriever(company_id)

        # 文档数量
        docs = retriever.list_documents()
        doc_count = len(docs)

        # 评估器可用性
        evaluator_available = False
        try:
            from app.rag.rag_evaluator import get_rag_evaluator

            get_rag_evaluator()
            evaluator_available = True
        except Exception as e:
            logger.warning("rag_evaluator_init_failed", error=str(e))

        reranker_env_enabled = os.getenv("RERANKER_ENABLED", "true").lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        reranker = getattr(retriever, "reranker", None)
        reranker_enabled = bool(
            reranker_env_enabled
            and reranker
            and getattr(reranker, "enabled", True)
            and not getattr(reranker, "_load_failed", False)
        )

        return RagConfigResponse(
            embedding_model=emb_service.model_name,
            embedding_model_count=len(EMBEDDING_MODEL_REGISTRY),
            retrieval_strategy="hybrid",  # BM25 + 向量 + RRF + Reranker
            reranker_enabled=reranker_enabled,
            graph_rag_enabled=True,
            multimodal_enabled=False,
            document_count=doc_count,
            indexing_status="ready" if doc_count > 0 else "empty",
            evaluator_available=evaluator_available,
        )
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# ═══════════════════════════════════════════════════
# 知识图谱管理
# ═══════════════════════════════════════════════════


class GraphEntityItem(BaseModel):
    """知识图谱实体"""

    name: str = Field(..., description="实体名称")
    entity_type: str = Field(default="", description="实体类型")
    relations: list[dict] = Field(default_factory=list, description="关联关系列表")


class GraphEntitesResponse(BaseModel):
    """知识图谱实体列表响应"""

    entities: list[GraphEntityItem] = Field(default_factory=list)
    entity_count: int = Field(default=0)
    relation_count: int = Field(default=0)


@router.get("/graph/entities", response_model=GraphEntitesResponse)
def list_graph_entities(
    current_user: User = Depends(get_current_active_user),
) -> GraphEntitesResponse:
    """列出知识图谱中的实体和关系"""
    try:
        from app.rag.graph_rag import get_graph_rag

        # GraphRAG currently stores the built-in ecommerce graph globally.
        # It does not accept a company_id; tenant-specific knowledge stays in
        # the Milvus-backed hybrid retriever.
        graph_rag = get_graph_rag()
        kg = graph_rag.kg

        if kg.graph is None:
            return GraphEntitesResponse()

        entities = []
        relation_count = 0

        for node_id, node_data in kg.graph.nodes(data=True):
            relations = []
            for _, neighbor, edge_data in kg.graph.edges(node_id, data=True):
                neighbor_name = kg.graph.nodes[neighbor].get("name", "")
                relations.append(
                    {
                        "target": neighbor_name,
                        "relation": edge_data.get("type", ""),
                        "weight": edge_data.get("weight", 1.0),
                    }
                )
                relation_count += 1

            entities.append(
                GraphEntityItem(
                    name=node_data.get("name", node_id),
                    entity_type=node_data.get("type", ""),
                    relations=relations,
                )
            )

        return GraphEntitesResponse(
            entities=entities,
            entity_count=len(entities),
            relation_count=relation_count,
        )
    except Exception:
        logger.exception("list_graph_entities_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")

"""应用配置集中入口

将散落在各模块的 os.getenv 调用集中管理，提供统一的配置读取入口。
本模块仅声明配置项，不在导入时执行副作用，避免循环依赖。

文档依据：变更③ 生产级安全与韧性 — T3.1 / T3.5
"""

import os


def _env(key: str, default: str | None = None) -> str | None:
    """统一环境变量读取入口（预留扩展点：后续可接入密钥管理服务）"""
    return os.getenv(key, default)


# 限流相关配置 — T3.1
# 限流专用 Redis URL，默认与全局 REDIS_URL 相同，多实例部署时共享计数
RATE_LIMIT_REDIS_URL: str = _env("RATE_LIMIT_REDIS_URL") or _env(
    "REDIS_URL", "redis://localhost:6379/0"
)


# ── 密钥相关配置 — T3.5 ──────────────────────────────────────────
# 禁用值清单：这些值出现在代码仓库/示例文档中，攻击者可直接据此伪造 JWT 或解密数据
SECRET_KEY_DISABLED_VALUES = frozenset(
    {
        "changeme",
        "default",
        "your_jwt_secret",
        "your-secret-key-change-in-production",
        "your-secret-key",
        "change-me",
        "insecure-default",
    }
)

# JWT 签名密钥：用于签发/校验 access_token
# 生成方式：python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY: str | None = _env("JWT_SECRET_KEY")

# 字段加密密钥：用于加密数据库中的敏感字段（API Key 等）
# 必须是合法的 Fernet key
# 生成方式：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY: str | None = _env("ENCRYPTION_KEY")


# ── 嵌入服务配置 — 变更① T1.4 ──────────────────────────────────
# 嵌入模式：local / api_siliconflow / api_deepseek / api_openai
# 启动时读取，main.py lifespan 据此初始化 EmbeddingService；
# 运行时由公司级配置（embedding_config 表）覆盖，热切换不重启服务
EMBEDDING_MODE: str = _env("EMBEDDING_MODE", "local") or "local"

# 嵌入 API Key（全局兜底值）：当公司级 embedding_config 未配置 api_key 时使用
# 留空表示不设全局兜底，各公司必须自行配置 API Key
EMBEDDING_API_KEY: str | None = _env("EMBEDDING_API_KEY")


# ── RAG 检索后端切换配置 ──────────────────────────────────────
# 检索框架选择：
#   hybrid     —— 自研 HybridRetriever（BM25 + 向量 + RRF + Reranker 四阶段，默认）
#   llamaindex —— LlamaIndex 标准框架（VectorStoreIndex + MilvusVectorStore，对照实现）
# 用途：运行时切换检索后端，证明同时掌握"自研"与"标准框架"两条路线
# 读取点：上层通过 get_retriever_by_framework() 工厂按此值选择后端
RAG_FRAMEWORK: str = _env("RAG_FRAMEWORK", "hybrid") or "hybrid"


# ── 向量数据库配置 ─────────────────────────────────────────────
# VECTOR_DB: 向量后端类型，生产默认 milvus
# 业务代码（hybrid_retriever / multimodal_retriever / runtime/memory / main）均使用 pymilvus 连接 Milvus；
# chromadb 仅作为可选备选后端（需 pip install chromadb），生产不推荐
VECTOR_DB: str = _env("VECTOR_DB", "milvus") or "milvus"

# Milvus 连接参数（与 app/rag/hybrid_retriever.py、app/main.py 读取的环境变量一致）
MILVUS_HOST: str = _env("MILVUS_HOST", "localhost") or "localhost"
MILVUS_PORT: str = _env("MILVUS_PORT", "19530") or "19530"
# 文本向量 Collection（hybrid_retriever 默认 company_knowledge，.env.example 推荐 agentx_vectors）
MILVUS_COLLECTION: str = _env("MILVUS_COLLECTION", "company_knowledge") or "company_knowledge"
# 图像向量 Collection（multimodal_retriever 使用，与文本向量库分离）
MILVUS_IMAGE_COLLECTION: str = _env("MILVUS_IMAGE_COLLECTION", "company_images") or "company_images"


def is_secret_key_valid(value: str | None) -> bool:
    """校验密钥是否为非默认的安全值

    Args:
        value: 待校验的密钥字符串

    Returns:
        True 表示密钥有效（非空且不在禁用值清单中）
    """
    if not value:
        return False
    return value.strip().lower() not in SECRET_KEY_DISABLED_VALUES


def validate_secrets_on_startup() -> None:
    """启动时校验关键密钥，不通过则抛 RuntimeError 阻止启动

    文档依据：03-安全与韧性.md 2.4 节
    在 main.py lifespan startup 阶段调用，确保生产环境不会用默认密钥启动。
    开发环境（ENV=dev）若密钥缺失则仅 warn，便于本地快速启动；
    生产环境（ENV=prod）强制要求密钥存在且非默认值。
    """
    env = _env("ENV", "dev")
    errors: list[str] = []

    if not is_secret_key_valid(JWT_SECRET_KEY):
        if env == "prod":
            errors.append(
                "JWT_SECRET_KEY 未配置或为默认值。"
                '生成方式: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        else:
            # 开发环境仅 warn，不阻塞启动（auth.py 内部已有 dev 降级）
            pass

    if not is_secret_key_valid(ENCRYPTION_KEY):
        if env == "prod":
            errors.append(
                "ENCRYPTION_KEY 未配置或为默认值。"
                '生成方式: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        else:
            pass

    if errors:
        raise RuntimeError(
            "启动密钥校验失败（生产环境必须配置安全密钥）:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

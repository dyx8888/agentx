"""文本 Embedding 服务

将文本转为稠密向量，是 RAG 检索的核心基础设施。
支持：
- 本地 SentenceTransformer（保留原逻辑，模型注册表热插拔）
- 远程嵌入 API（OpenAI 兼容：硅基流动 / DeepSeek / OpenAI）
- 双重缓存：进程级 LRU（functools.lru_cache maxsize=10000）+ Redis（24h TTL）
- 自动降级：API 失败 → 本地（如已加载）→ 空向量（不抛异常）
- 运行时热切换模式（switch_mode，不重启服务）
"""

import asyncio  # 同步上下文调用异步 API
import functools  # lru_cache 进程级缓存
import hashlib  # MD5 生成缓存 key
import os  # 读取环境变量
import re  # lightweight tokenization for hashing embeddings
import threading  # 单例锁,保护 get_embedding_service 的 check-then-act
from enum import StrEnum  # EmbeddingMode 枚举基类

import numpy as np  # 向量存储和运算

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


# ═══════════════════════════════════════════════════════════
# 本地模型注册表（保留原逻辑，热插拔）
# ═══════════════════════════════════════════════════════════
MODEL_CACHE: dict = {}  # 进程级模型缓存，避免多次加载同一模型浪费显存/内存
DEFAULT_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")  # 环境变量 > 默认值

# 嵌入模型注册表：借鉴 RAG-Anything 的 embedding_func 热插拔设计
EMBEDDING_MODEL_REGISTRY: dict[str, str] = {
    "bge-small": "BAAI/bge-small-zh-v1.5",  # 轻量中文嵌入，512维，速度快
    "bge-base": "BAAI/bge-base-zh-v1.5",  # 标准中文嵌入，768维
    "bge-large": "BAAI/bge-large-zh-v1.5",  # 大型中文嵌入，1024维
    "bge-m3": "BAAI/bge-m3",  # 多语言嵌入
    "m3e-base": "moka-ai/m3e-base",  # M3E 中文嵌入，768维
    "m3e-large": "moka-ai/m3e-large",  # M3E 大型中文嵌入
    "text2vec-base": "shibing624/text2vec-base-chinese",  # Text2Vec 中文嵌入
    "e5-small": "intfloat/multilingual-e5-small",  # E5 多语言嵌入，384维
    "e5-base": "intfloat/multilingual-e5-base",  # E5 多语言嵌入，768维
    "e5-large": "intfloat/multilingual-e5-large",  # E5 多语言嵌入，1024维
}


def register_embedding_model(name: str, model_path: str):  # 注册嵌入模型到注册表
    """注册嵌入模型，支持运行时热插拔扩展。

    Args:
        name: 模型简称
        model_path: 模型 HuggingFace 路径或本地路径
    """
    EMBEDDING_MODEL_REGISTRY[name] = model_path
    logger.info("embedding_model_registered", name=name, path=model_path)


def get_embedding_model_path(name: str) -> str:  # 从注册表获取模型路径
    """从注册表获取嵌入模型路径。

    Args:
        name: 模型简称

    Returns:
        模型 HuggingFace 路径

    Raises:
        ValueError: 当模型名称不在注册表中时
    """
    if name in EMBEDDING_MODEL_REGISTRY:
        return EMBEDDING_MODEL_REGISTRY[name]
    # 如果 name 本身就是完整路径（如 "BAAI/bge-small-zh-v1.5"），直接返回
    if "/" in name:
        return name
    available = ", ".join(EMBEDDING_MODEL_REGISTRY.keys())
    raise ValueError(f"Unknown embedding model: '{name}'. Available: {available}")


# ═══════════════════════════════════════════════════════════
# 嵌入模式枚举（新增）
# ═══════════════════════════════════════════════════════════
class EmbeddingMode(StrEnum):
    """嵌入模式枚举：本地 / 远程 API（硅基流动 / DeepSeek / OpenAI）。

    继承 str 便于 JSON 序列化和直接比较（mode == "local" 也成立）。
    """

    LOCAL = "local"
    HASH = "hash"
    API_SILICONFLOW = "api_siliconflow"
    API_DEEPSEEK = "api_deepseek"
    API_OPENAI = "api_openai"


# 供应商默认配置（base_url + 默认模型）
EMBEDDING_API_PRESETS: dict[EmbeddingMode, dict[str, str]] = {
    EmbeddingMode.API_SILICONFLOW: {
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "BAAI/bge-large-zh-v1.5",  # 国内访问快，免费额度
    },
    EmbeddingMode.API_DEEPSEEK: {
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-embedding",
    },
    EmbeddingMode.API_OPENAI: {
        "base_url": "https://api.openai.com/v1",
        "model_name": "text-embedding-3-small",  # 国际用户
    },
}


# ═══════════════════════════════════════════════════════════
# 远程嵌入 API 后端 + 双重缓存
# ═══════════════════════════════════════════════════════════
# 后端注册表：供 LRU 缓存函数按 namespace 解析后端实例
_EMB_BACKEND_REGISTRY: dict[str, "EmbeddingAPIBackend"] = {}


@functools.lru_cache(maxsize=10000)
def _lru_encode_single(cache_namespace: str, text: str) -> tuple[float, ...]:
    """进程级 LRU 缓存（maxsize=10000）—— 单文本嵌入。

    缓存层级：LRU（本函数）→ Redis（24h TTL）→ API 调用。
    - LRU 命中：直接返回（最快，无 IO）
    - LRU 未命中：函数体执行 → 查 Redis → 命中则返回 → 否则调 API → 写 Redis → 返回
    结果由 lru_cache 自动缓存（key = (cache_namespace, text)）。

    仅在同步上下文中调用。异步批量编码请用 EmbeddingAPIBackend.encode_async()。

    Args:
        cache_namespace: 缓存命名空间，格式 "{mode}:{model_name}"，不同后端隔离
        text: 待编码文本

    Returns:
        向量元组；空元组表示失败
    """
    backend = _EMB_BACKEND_REGISTRY.get(cache_namespace)
    if backend is None:
        return ()

    text_md5 = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()

    # 1) Redis 缓存层
    cached = backend._redis_get(text_md5)
    if cached is not None:
        return tuple(cached)

    # 2) API 调用（同步包装异步）
    vec = backend._encode_one_sync(text)
    if vec is None:
        return ()

    # 3) 写 Redis（LRU 由 lru_cache 装饰器自动写入）
    backend._redis_set(text_md5, list(vec))

    return tuple(vec)


def _run_async(coro):
    """在同步上下文中运行协程，处理嵌套事件循环。

    若当前线程已有运行中的事件循环（如被 sync 调用方嵌入 async 上下文），
    则借用线程池在新线程跑 asyncio.run，避免 RuntimeError。

    修复点:
    - 用 asyncio.get_running_loop() 替代已弃用的 get_event_loop()。
      get_event_loop() 在 3.12+ 行为变化且会偷偷创建新循环；
      get_running_loop() 严格只返回当前运行的循环，无则抛 RuntimeError。
    - except RuntimeError 只包裹检测语句，精确捕获"无运行循环"，
      不再吞掉协程执行阶段抛出的 RuntimeError。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 当前线程无运行中的事件循环 —— 直接 asyncio.run
        return asyncio.run(coro)

    # 有运行中的循环:不能在当前线程再跑 asyncio.run，借线程池在新线程执行
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class EmbeddingAPIBackend:
    """远程嵌入 API 后端（OpenAI 兼容的 /v1/embeddings 接口）。

    支持：硅基流动 / DeepSeek / OpenAI 等任何 OpenAI 兼容接口。
    双重缓存：进程级 LRU（functools.lru_cache maxsize=10000）+ Redis（24h TTL）。
    Redis 不可用时仅用 LRU，不报错。

    用法：
        backend = EmbeddingAPIBackend(
            base_url="https://api.siliconflow.cn/v1",
            api_key="sk-xxx",
            model_name="BAAI/bge-large-zh-v1.5",
            mode=EmbeddingMode.API_SILICONFLOW,
        )
        vectors = backend.encode(["文本1", "文本2"])  # 同步
        vectors = await backend.encode_async(["文本1", "文本2"])  # 异步批量
    """

    REDIS_TTL = 24 * 3600  # Redis 缓存 24 小时

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        mode: EmbeddingMode = EmbeddingMode.API_SILICONFLOW,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.mode = mode
        # 缓存命名空间：不同 mode + model 隔离，避免向量维度混用
        self._cache_namespace = f"{mode.value}:{model_name}"
        # 注册到全局表，供 _lru_encode_single 解析后端实例
        _EMB_BACKEND_REGISTRY[self._cache_namespace] = self
        # Redis 懒连接（首次 _redis_get 时才初始化）
        self._redis_client = None
        self._redis_checked = False
        # T3.3: 嵌入 API 熔断器（全局单例）
        from app.core.circuit_breaker import get_circuit_breaker

        self._breaker = get_circuit_breaker("embedding_api", 5, 30)

    # ───────── Redis 缓存层 ─────────
    def _init_redis(self) -> None:
        """懒初始化 Redis 连接。失败时仅 warning，不抛异常（降级为仅 LRU）。"""
        if self._redis_checked:
            return
        self._redis_checked = True
        try:
            import redis as rds  # 延迟导入，未安装 redis 包时不阻塞模块加载

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = rds.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            self._redis_client = client
            logger.info("embedding_redis_connected", namespace=self._cache_namespace)
        except ImportError:
            logger.info("embedding_redis_not_installed_lru_only", namespace=self._cache_namespace)
        except Exception as e:
            logger.warning(
                "embedding_redis_unavailable_lru_only",
                error=str(e),
                namespace=self._cache_namespace,
            )

    def _redis_key(self, text_md5: str) -> str:
        """构造 Redis 缓存 key —— 必须包含 model_name,避免切换模型后命中旧向量。

        旧实现 key = "emb:{mode}:{md5}" 漏了 model_name,导致同一 mode 下切换
        不同模型(如 bge-large → bge-m3)时,Redis 返回旧模型的向量。
        虽然维度可能相同,但不同模型的向量空间完全不同,会导致检索结果错乱。
        与 LRU 层的 _cache_namespace = "{mode}:{model_name}" 保持一致。
        """
        return f"emb:{self.mode.value}:{self.model_name}:{text_md5}"

    def _redis_get(self, text_md5: str) -> list[float] | None:
        """从 Redis 读取。Redis 不可用时返回 None。"""
        if not self._redis_checked:
            self._init_redis()
        if self._redis_client is None:
            return None
        try:
            import json

            key = self._redis_key(text_md5)
            val = self._redis_client.get(key)
            if val:
                return json.loads(val)
        except Exception as e:
            logger.warning("embedding_redis_get_failed", error=str(e))
            self._redis_client = None  # 标记不可用，后续跳过
        return None

    def _redis_set(self, text_md5: str, vector: list[float]) -> None:
        """写入 Redis，带 24h TTL。失败仅 warning，不影响主流程。"""
        if self._redis_client is None:
            return
        try:
            import json

            key = self._redis_key(text_md5)
            self._redis_client.setex(key, self.REDIS_TTL, json.dumps(vector))
        except Exception as e:
            logger.warning("embedding_redis_set_failed", error=str(e))

    # ───────── API 调用 ─────────
    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """调用远程 /v1/embeddings 接口（批量）。

        用 httpx.AsyncClient 调 POST {base_url}/embeddings，
        body 为 {"model": model_name, "input": texts}。
        支持 OpenAI 兼容响应格式 {"data": [{"embedding": [...]}, ...]}。
        """
        import httpx  # 延迟导入

        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {"model": self.model_name, "input": texts}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # 变更① T1.5：记录嵌入 API 调用成本（失败不影响主流程，仅 warn）
        self._record_cost(len(texts))

        # OpenAI 标准响应：{"data": [{"embedding": [...]}, ...]}
        return [item["embedding"] for item in data.get("data", [])]

    def _record_cost(self, text_count: int) -> None:
        """记录本次 API 调用的成本到 CostTracker —— 变更① T1.5

        延迟导入 CostTracker 避免循环依赖（cost_tracker 依赖 db，db 可能反向引用 rag）。
        任何异常都吞掉只 warn，确保成本统计失败不阻塞嵌入主流程。
        """
        try:
            from app.tracking.cost_tracker import CostTracker

            CostTracker.record_embedding_usage(
                mode=self.mode.value,
                model_name=self.model_name,
                text_count=text_count,
            )
        except Exception as e:
            logger.warning("embedding_cost_record_failed", error=str(e), mode=self.mode.value)

    async def encode_async(self, texts: list[str]) -> list[list[float]]:
        """异步批量编码：Redis 缓存查表 + 批量 API 调用。

        LRU 缓存不在此路径使用（lru_cache 不支持批量注入）。
        单文本同步查表请用 encode()，会经 LRU 缓存。
        后续单条查表时会经 Redis 命中并通过 _lru_encode_single 函数体返回，那时被 LRU 缓存。

        Returns:
            List[List[float]]，与输入文本列表一一对应；失败的位置返回空列表
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        texts_to_call: list[tuple[int, str]] = []

        # Step 1: Redis 缓存查表
        for i, text in enumerate(texts):
            text_md5 = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()
            cached = self._redis_get(text_md5)
            if cached is not None:
                results[i] = cached
                continue
            texts_to_call.append((i, text))

        # Step 2: 批量 API 调用（T3.3: 熔断保护）
        if texts_to_call:
            try:
                new_vectors = await self._breaker.call(
                    self._call_api, [t for _, t in texts_to_call]
                )
                for (idx, text), vec in zip(texts_to_call, new_vectors, strict=False):
                    vec_list = list(vec) if vec else []
                    results[idx] = vec_list
                    # 写 Redis
                    text_md5 = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()
                    self._redis_set(text_md5, vec_list)
            except Exception as e:
                logger.error("embedding_api_batch_failed", error=str(e), count=len(texts_to_call))
                raise

        return [r if r is not None else [] for r in results]

    def _encode_one_sync(self, text: str) -> list[float] | None:
        """同步编码单文本（供 _lru_encode_single 回调）。"""
        try:
            vectors = _run_async(self._breaker.call(self._call_api, [text]))
            if vectors and len(vectors) > 0:
                return list(vectors[0])
        except Exception as e:
            logger.warning("embedding_api_single_failed", error=str(e))
        return None

    def encode(self, texts: list[str]) -> list[list[float]]:
        """同步批量编码：通过 LRU 缓存（含 Redis 回退 + 单文本 API 调用）。

        每个文本独立走 LRU 缓存，未命中时单条 API 调用。
        如需批量 API 调用效率，请用 encode_async()。

        Returns:
            List[List[float]]，与输入文本列表一一对应
        """
        if not texts:
            return []
        return [list(_lru_encode_single(self._cache_namespace, t)) for t in texts]

    def clear_cache(self) -> None:
        """清除 LRU 缓存。

        注：lru_cache 不支持按 key 部分清除，只能全清。
        通常在 switch_mode / 配置变更后调用。
        """
        _lru_encode_single.cache_clear()
        logger.info("embedding_lru_cache_cleared", namespace=self._cache_namespace)


# ═══════════════════════════════════════════════════════════
# EmbeddingService（统一入口，保留原 LOCAL 逻辑 + 新增 API 模式 + 降级）
# ═══════════════════════════════════════════════════════════
class EmbeddingService:
    """文本 Embedding 服务，封装模型加载、向量化、缓存、fallback 全套逻辑。

    支持：
    - mode=LOCAL：本地 SentenceTransformer（保留原有逻辑）
    - mode=API_*：远程嵌入 API（OpenAI 兼容）
    - 自动降级：API 失败 → 本地（如已加载）→ 空向量（不抛异常）
    - 运行时热切换模式（switch_mode，不重启服务）
    - 保留 EMBEDDING_MODEL_REGISTRY 热插拔本地模型

    用法：
        # 本地模式（默认）
        service = EmbeddingService()
        # API 模式
        service = EmbeddingService(
            mode=EmbeddingMode.API_SILICONFLOW,
            api_key="sk-xxx",
            api_model_name="BAAI/bge-large-zh-v1.5",
        )
        # 热切换
        service.switch_mode(EmbeddingMode.LOCAL)
    """

    def __init__(
        self,
        model_name: str = None,
        mode: EmbeddingMode = EmbeddingMode.LOCAL,
        api_base_url: str = None,
        api_key: str = None,
        api_model_name: str = None,
    ):
        self.mode = mode
        # 本地模型相关（保留原逻辑）
        self._raw_model_name = model_name or DEFAULT_MODEL_NAME
        self.model_name = get_embedding_model_path(self._raw_model_name)
        self._model = None  # 懒加载
        self._cache: dict = {}  # 文本 → 向量本地缓存
        self._cache_hits = 0
        self._cache_misses = 0
        # API 后端相关
        self._api_backend: EmbeddingAPIBackend | None = None
        self._api_base_url = api_base_url
        self._api_key = api_key
        self._api_model_name = api_model_name
        # 降级状态
        self._degraded_to_local = False
        self._api_failure_count = 0
        # 初始化 API 后端（若 mode != LOCAL）
        if mode not in {EmbeddingMode.LOCAL, EmbeddingMode.HASH}:
            self._init_api_backend()

    def _init_api_backend(self) -> None:
        """根据当前 mode 和参数初始化 API 后端。"""
        if self.mode in {EmbeddingMode.LOCAL, EmbeddingMode.HASH}:
            self._api_backend = None
            return
        preset = EMBEDDING_API_PRESETS.get(self.mode, {})
        base_url = self._api_base_url or preset.get("base_url", "")
        api_key = self._api_key or os.getenv("EMBEDDING_API_KEY", "")
        model_name = self._api_model_name or preset.get("model_name", "")
        if not base_url or not api_key:
            logger.warning("embedding_api_config_incomplete_fallback_local", mode=self.mode.value)
            self._api_backend = None
            return
        self._api_backend = EmbeddingAPIBackend(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            mode=self.mode,
        )
        logger.info("embedding_api_backend_initialized", mode=self.mode.value, model=model_name)

    def switch_model(self, model_name: str):  # 运行时切换本地嵌入模型（保留原 API）
        """运行时切换本地嵌入模型，清除缓存和已加载模型。

        Args:
            model_name: 模型简称或完整路径
        """
        self._raw_model_name = model_name
        self.model_name = get_embedding_model_path(model_name)
        self._model = None  # 清除模型引用，下次 encode 时重新加载
        self._cache.clear()  # 不同模型的向量不可混用
        self._cache_hits = 0
        self._cache_misses = 0
        logger.info("embedding_model_switched", model=self.model_name)

    def switch_mode(
        self,
        mode: EmbeddingMode,
        api_base_url: str = None,
        api_key: str = None,
        api_model_name: str = None,
    ) -> None:
        """运行时热切换嵌入模式（不重启服务）。

        Args:
            mode: 目标模式
            api_base_url: 可选，API 基址（None 表示沿用原值或预设）
            api_key: 可选，API 密钥
            api_model_name: 可选，API 模型名
        """
        self.mode = mode
        if api_base_url is not None:
            self._api_base_url = api_base_url
        if api_key is not None:
            self._api_key = api_key
        if api_model_name is not None:
            self._api_model_name = api_model_name
        # 重置降级状态
        self._degraded_to_local = False
        self._api_failure_count = 0
        # 重建 API 后端
        self._init_api_backend()
        # 清 LRU 缓存（避免旧后端的结果残留）
        if self._api_backend:
            self._api_backend.clear_cache()
        logger.info("embedding_mode_switched", mode=mode.value)

    def _load_model(self):  # 加载本地 SentenceTransformer 模型，支持进程级缓存
        if self._model is not None:
            return self._model

        if self.model_name in MODEL_CACHE:
            self._model = MODEL_CACHE[self.model_name]
            return self._model

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            MODEL_CACHE[self.model_name] = self._model
            logger.info("embedding_model_loaded", model=self.model_name)
        except ImportError:
            logger.warning("sentence_transformers_not_installed_using_hashing_embedding")
            self._model = None
        except Exception as e:
            logger.error("embedding_model_load_error", error=str(e))
            self._model = None

        return self._model

    def _cache_key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()

    @property
    def dimension(self) -> int:
        if self.mode == EmbeddingMode.HASH:
            return 512
        # API 模式且未降级：根据模型名推断维度
        if self.mode != EmbeddingMode.LOCAL and self._api_backend and not self._degraded_to_local:
            preset = EMBEDDING_API_PRESETS.get(self.mode, {})
            mn = self._api_model_name or preset.get("model_name", "")
            if "bge-large" in mn or "e5-large" in mn:
                return 1024
            if "bge-base" in mn or "e5-base" in mn or "m3e-base" in mn:
                return 768
            if "text-embedding-3-small" in mn:
                return 1536
            if "deepseek-embedding" in mn:
                return 1024
        # 本地模式 / 降级本地
        model = self._load_model()
        if model:
            return model.get_sentence_embedding_dimension()
        return 512

    def encode(self, texts: list[str]) -> np.ndarray:
        """编码文本为向量。

        - LOCAL 模式：调本地 SentenceTransformer
        - API 模式：调 EmbeddingAPIBackend（带双重缓存）
        - 降级策略：API 失败 → 本地（如已加载）→ 空向量（不抛异常）

        Args:
            texts: 待编码文本列表

        Returns:
            np.ndarray，shape=(len(texts), dim)
        """
        if not texts:
            return np.array([])

        if self.mode == EmbeddingMode.HASH:
            return self._encode_hash(texts)

        # LOCAL 模式 或 已降级到本地：走原逻辑
        if self.mode == EmbeddingMode.LOCAL or self._degraded_to_local:
            return self._encode_local(texts)

        # API 模式
        if self._api_backend is None:
            logger.warning("embedding_api_not_ready_fallback_local")
            return self._encode_local_with_fallback(texts)

        try:
            vectors = self._api_backend.encode(texts)  # List[List[float]]
            if vectors and any(v for v in vectors):
                return np.array(vectors, dtype=np.float32)
            logger.warning("embedding_api_empty_response_degrade_local")
            return self._degrade_and_encode(texts)
        except Exception as e:
            logger.warning("embedding_api_failed_degrade_local", error=str(e))
            return self._degrade_and_encode(texts)

    async def encode_async(self, texts: list[str]) -> np.ndarray:
        """异步编码（API 模式批量效率更高，单次 API 调用编码多文本）。

        LOCAL 模式退化为同步本地调用。
        """
        if not texts:
            return np.array([])

        if self.mode == EmbeddingMode.HASH:
            return self._encode_hash(texts)

        if self.mode == EmbeddingMode.LOCAL or self._degraded_to_local:
            return self._encode_local(texts)

        if self._api_backend is None:
            return self._encode_local_with_fallback(texts)

        try:
            vectors = await self._api_backend.encode_async(texts)
            if vectors and any(v for v in vectors):
                return np.array(vectors, dtype=np.float32)
            return self._degrade_and_encode(texts)
        except Exception as e:
            logger.warning("embedding_api_async_failed_degrade_local", error=str(e))
            return self._degrade_and_encode(texts)

    def _encode_local(self, texts: list[str]) -> np.ndarray:
        """本地编码（保留原逻辑，含本地缓存）。"""
        cached = []
        indices_to_encode = []
        texts_to_encode = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                cached.append((i, self._cache[key]))
                self._cache_hits += 1
            else:
                indices_to_encode.append(i)
                texts_to_encode.append(text)
                self._cache_misses += 1

        if texts_to_encode:
            model = self._load_model()
            if model:
                encoded = model.encode(texts_to_encode, normalize_embeddings=True)
            else:
                encoded = np.array([self._fallback_embedding(t) for t in texts_to_encode])

            for idx, emb in zip(indices_to_encode, encoded, strict=False):
                key = self._cache_key(texts[idx])
                self._cache[key] = emb
                cached.append((idx, emb))

        cached.sort(key=lambda x: x[0])
        result = np.array([emb for _, emb in cached])
        return result

    def _encode_hash(self, texts: list[str]) -> np.ndarray:
        """Deterministic smoke/test embedding path that never loads ML models."""
        encoded = [self._fallback_embedding(t) for t in texts]
        return np.array(encoded, dtype=np.float32)

    def _degrade_and_encode(self, texts: list[str]) -> np.ndarray:
        """降级到本地编码。若本地模型也未加载，返回空向量（不抛异常）。"""
        self._api_failure_count += 1
        if self._api_failure_count >= 3:
            self._degraded_to_local = True
            logger.warning(
                "embedding_api_degraded_to_local_after_repeated_failures",
                count=self._api_failure_count,
            )
        model = self._load_model()
        if model:
            return self._encode_local(texts)
        logger.warning("embedding_final_fallback_hashing_vectors")
        return np.array([self._fallback_embedding(t) for t in texts], dtype=np.float32)

    def _encode_local_with_fallback(self, texts: list[str]) -> np.ndarray:
        """尝试本地，失败则返回确定性哈希向量。"""
        model = self._load_model()
        if model:
            return self._encode_local(texts)
        return np.array([self._fallback_embedding(t) for t in texts], dtype=np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        return self.encode([text])[0]

    def _fallback_embedding(self, text: str, dim: int = 512) -> np.ndarray:
        """Deterministic lightweight hashing vectorizer used when ML/API embeddings are unavailable."""
        normalized = (text or "").lower()
        vec = np.zeros(dim, dtype=np.float32)

        features: list[str] = []
        for token in re.findall(r"[a-z0-9]+(?:[+#._-][a-z0-9]+)*|[\u4e00-\u9fff]+", normalized):
            features.append("tok:" + token)
            if re.fullmatch(r"[\u4e00-\u9fff]+", token):
                chars = list(token)
                features.extend("c:" + ch for ch in chars)
                for n in (2, 3):
                    features.extend(
                        f"zh{n}:" + "".join(chars[i : i + n])
                        for i in range(max(len(chars) - n + 1, 0))
                    )
            else:
                compact = re.sub(r"[^a-z0-9]+", "", token)
                if compact and compact != token:
                    features.append("compact:" + compact)

        if not features:
            features = ["empty"]

        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    @property
    def cache_stats(self) -> dict:
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": round(hit_rate, 3),
            "cache_size": len(self._cache),
            "mode": self.mode.value,
            "degraded_to_local": self._degraded_to_local,
            "api_failure_count": self._api_failure_count,
        }


_embedding_service: EmbeddingService | None = None  # 模块级单例
_embedding_service_lock = threading.Lock()  # 保护 get_embedding_service 的 check-then-act


def _embedding_mode_from_env() -> EmbeddingMode:
    smoke_mode = os.getenv("AGENTX_SMOKE_EMBEDDING_MODE", "").strip().lower()
    if smoke_mode:
        if smoke_mode == EmbeddingMode.HASH.value:
            return EmbeddingMode.HASH
        logger.warning("smoke_embedding_mode_invalid_ignored", invalid_mode=smoke_mode)

    mode_str = os.getenv("EMBEDDING_MODE", "local").strip().lower()
    try:
        return EmbeddingMode(mode_str)
    except ValueError:
        logger.warning("embedding_mode_invalid_fallback_local", invalid_mode=mode_str)
        return EmbeddingMode.LOCAL


def _create_embedding_service_from_env(model_name: str | None = None) -> EmbeddingService:
    return EmbeddingService(
        model_name=model_name,
        mode=_embedding_mode_from_env(),
        api_base_url=os.getenv("EMBEDDING_API_BASE_URL") or None,
        api_key=os.getenv("EMBEDDING_API_KEY") or None,
        api_model_name=os.getenv("EMBEDDING_API_MODEL") or None,
    )


def set_embedding_service(service: EmbeddingService | None) -> None:
    global _embedding_service
    with _embedding_service_lock:
        _embedding_service = service


def get_embedding_service(model_name: str = None) -> EmbeddingService:  # 工厂函数
    """获取全局 EmbeddingService 单例。
    支持指定模型名称，切换模型时重新创建实例。
    向后兼容：仅接受 model_name 参数（mode 默认 LOCAL）。

    Args:
        model_name: 可选模型名称，支持注册表简称或完整路径

    Returns:
        EmbeddingService 实例
    """
    global _embedding_service
    # 双重检查锁:快速路径(实例已存在且模型匹配)无需加锁,避免热路径性能损失
    if model_name is None:
        if _embedding_service is not None:
            return _embedding_service
    else:
        if _embedding_service is not None and _embedding_service._raw_model_name == model_name:
            return _embedding_service

    with _embedding_service_lock:
        # 二次检查:等待锁期间可能已被其他线程创建/切换
        if model_name is None:
            if _embedding_service is None:
                _embedding_service = _create_embedding_service_from_env()
        else:
            if _embedding_service is None:
                _embedding_service = _create_embedding_service_from_env(model_name)
            elif _embedding_service._raw_model_name != model_name:
                _embedding_service.switch_model(model_name)
        return _embedding_service


def list_available_models() -> dict[str, str]:  # 列出所有可用嵌入模型
    """列出注册表中所有可用的嵌入模型。

    Returns:
        模型名称 → 模型路径 的字典
    """
    return dict(EMBEDDING_MODEL_REGISTRY)

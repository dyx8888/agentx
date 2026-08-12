"""
Rate Limiter Middleware
Provides per-user and per-company rate limiting for API requests and LLM calls
Multi-layer: IP → Login → User → LLM

文档依据: 2.docx - 大模型API调用工程实践
  - 限流分层策略: 用户级 → 租户级 → 模型级 → 供应商级
  - 4级限流: 用户级(User), 租户级(Tenant), 模型级(Model), 供应商级(Supplier)

变更③ T3.1 — 升级为分布式限流：
  - 新增 DistributedRateLimiter：基于 Redis ZSET 滑动窗口，多实例共享计数
  - Redis 不可用时自动降级到内存限流（单实例容灾），日志 warn
  - 旧 RateLimiter 保留作为降级后端

P0 优化：所有阈值改为环境变量可配，部署时无需改代码即可调整
  - RATE_LIMIT_USER (默认 120): 每用户每分钟最大请求数
  - RATE_LIMIT_LLM (默认 10): 每公司每分钟最大 LLM 调用数
  - RATE_LIMIT_LOGIN (默认 20): 每 IP 每 5 分钟最大登录尝试数
  - RATE_LIMIT_IP (默认 200): 每 IP 每分钟最大请求数
  - RATE_LIMIT_WINDOW (默认 60): 限流窗口（秒）
"""

import os
import threading
import time
import uuid
from collections import defaultdict
from enum import StrEnum

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)


class LazyRedisClient:
    """Redis proxy that defers importing and creating the real client until first use."""

    def __init__(self, factory):
        self._factory = factory
        self._client = None
        self._failed = False
        self._lock = threading.Lock()

    def _get_client(self):
        if self._failed:
            raise RuntimeError("lazy redis client previously failed to initialize")
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            client = self._factory()
            if client is None:
                self._failed = True
                raise RuntimeError("lazy redis client factory returned None")
            self._client = client
            return client

    def pipeline(self):
        return self._get_client().pipeline()

    def ping(self):
        return self._get_client().ping()


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数，非法值降级到默认值并告警"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "rate_limit_env_invalid_fallback_to_default", name=name, raw=raw, default=default
        )
        return default


class RateLimitLevel(StrEnum):
    """限流级别 - 文档依据: 2.docx"""

    USER = "user"  # 用户级: 按user_id限流
    TENANT = "tenant"  # 租户级: 按company_id限流
    MODEL = "model"  # 模型级: 按model_name限流
    SUPPLIER = "supplier"  # 供应商级: 按provider限流


class RateLimiter:
    """Sliding-window rate limiter (in-memory, single-instance fallback)"""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, list] = defaultdict(list)

    def _clean_window(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

    def is_allowed(self, key: str) -> tuple[bool, int]:
        self._clean_window(key)
        count = len(self._windows[key])
        if count >= self.max_requests:
            return False, count
        self._windows[key].append(time.monotonic())
        return True, count + 1

    def remaining(self, key: str) -> int:
        self._clean_window(key)
        return max(0, self.max_requests - len(self._windows[key]))


class DistributedRateLimiter:
    """基于 Redis ZSET 的分布式滑动窗口限流器

    文档依据：变更③ 03-安全与韧性.md 2.1 节
    每个请求:
        ZADD key {member: now_ms, score: now_ms}    # 记录本次请求
        ZREMRANGEBYSCORE key 0 now_ms - window*1000 # 清理过期
        ZCARD key                                     # 计数 → 比较阈值
    key 格式: rate:{level}:{identifier}:{window}s

    降级策略：Redis 不可用时回退到内存 RateLimiter（单实例容灾），日志 warn
    """

    def __init__(
        self,
        redis_client,
        key_prefix: str,
        max_requests: int,
        window_seconds: int = 60,
    ):
        self._redis = redis_client
        self._key_prefix = key_prefix
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # 内存降级后端 —— Redis 不可用时使用
        self._fallback = RateLimiter(max_requests, window_seconds)
        self._redis_available = redis_client is not None

    def _build_key(self, identifier: str) -> str:
        # key 格式：rate:{level}:{identifier}:{window}s
        return f"{self._key_prefix}:{identifier}:{self.window_seconds}s"

    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """检查标识符是否允许通过

        Args:
            identifier: 限流标识符 (ip / user_id / company_id 等)

        Returns:
            (is_allowed, current_count) — current_count 含本次请求
        """
        # Redis 未注入或之前已标记不可用 → 走内存降级
        if not self._redis_available:
            return self._fallback.is_allowed(identifier)

        try:
            key = self._build_key(identifier)
            now_ms = int(time.time() * 1000)
            window_start = now_ms - self.window_seconds * 1000

            # pipeline 保证"清理 + 计数"原子性，避免并发竞态
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)  # 清理过期成员
            pipe.zcard(key)  # 当前窗口计数
            results = pipe.execute()
            current_count = results[1]

            if current_count >= self.max_requests:
                # 达到阈值：拒绝，不再写入新成员
                return False, current_count

            # 通过：写入本次请求（member 需唯一，防止并发同毫秒覆盖）
            member = f"{now_ms}:{uuid.uuid4().hex}"
            pipe = self._redis.pipeline()
            pipe.zadd(key, {member: now_ms})
            pipe.expire(key, self.window_seconds)  # 自动过期，避免脏 key 堆积
            pipe.execute()

            return True, current_count + 1
        except Exception as e:
            # Redis 异常（连接断开 / 超时）→ 降级到内存，避免限流层拖垮主流程
            logger.warning(
                "rate_limiter_redis_error_fallback_to_memory",
                key_prefix=self._key_prefix,
                error=str(e),
            )
            self._redis_available = False
            return self._fallback.is_allowed(identifier)

    def remaining(self, identifier: str) -> int:
        """返回剩余可用请求数（用于响应头 X-RateLimit-Remaining）"""
        if not self._redis_available:
            return self._fallback.remaining(identifier)
        try:
            key = self._build_key(identifier)
            now_ms = int(time.time() * 1000)
            window_start = now_ms - self.window_seconds * 1000
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            results = pipe.execute()
            count = results[1]
            return max(0, self.max_requests - count)
        except Exception:
            return self._fallback.remaining(identifier)


class MultiLevelRateLimiter:
    """多级限流器 - 文档依据: 2.docx

    4级限流策略:
    1. 用户级 (User): 按 user_id 限流，默认 RATE_LIMIT_USER=120 req/min
    2. 租户级 (Tenant): 按 company_id 限流，默认 RATE_LIMIT_TENANT=100 req/min
    3. 模型级 (Model): 按 model_name 限流，默认 RATE_LIMIT_MODEL=50 req/min
    4. 供应商级 (Supplier): 按 provider 限流，默认 RATE_LIMIT_SUPPLIER=200 req/min

    变更③ T3.1：内部 limiter 改为 DistributedRateLimiter，
    构造时接收 redis_client，多实例共享 Redis 计数；
    redis_client 为 None 时自动降级为内存限流。
    """

    # 默认限流配置（P0 优化：阈值从环境变量读取，启动时计算一次）
    # 各级阈值可用环境变量覆盖：RATE_LIMIT_USER / RATE_LIMIT_TENANT / RATE_LIMIT_MODEL / RATE_LIMIT_SUPPLIER
    # LLM 调用阈值：RATE_LIMIT_LLM_USER / RATE_LIMIT_LLM_TENANT / RATE_LIMIT_LLM_MODEL / RATE_LIMIT_LLM_SUPPLIER
    # 窗口：RATE_LIMIT_WINDOW（默认 60s）
    _WINDOW = _env_int("RATE_LIMIT_WINDOW", 60)
    DEFAULT_LIMITS = {
        RateLimitLevel.USER: {"max_requests": _env_int("RATE_LIMIT_USER", 120), "window": _WINDOW},
        RateLimitLevel.TENANT: {
            "max_requests": _env_int("RATE_LIMIT_TENANT", 100),
            "window": _WINDOW,
        },
        RateLimitLevel.MODEL: {"max_requests": _env_int("RATE_LIMIT_MODEL", 50), "window": _WINDOW},
        RateLimitLevel.SUPPLIER: {
            "max_requests": _env_int("RATE_LIMIT_SUPPLIER", 200),
            "window": _WINDOW,
        },
    }
    # LLM调用额外限制（更严格）
    LLM_LIMITS = {
        RateLimitLevel.USER: {
            "max_requests": _env_int("RATE_LIMIT_LLM_USER", 10),
            "window": _WINDOW,
        },
        RateLimitLevel.TENANT: {
            "max_requests": _env_int("RATE_LIMIT_LLM_TENANT", 50),
            "window": _WINDOW,
        },
        RateLimitLevel.MODEL: {
            "max_requests": _env_int("RATE_LIMIT_LLM_MODEL", 20),
            "window": _WINDOW,
        },
        RateLimitLevel.SUPPLIER: {
            "max_requests": _env_int("RATE_LIMIT_LLM_SUPPLIER", 100),
            "window": _WINDOW,
        },
    }

    def __init__(self, redis_client=None):
        """多级限流器

        Args:
            redis_client: Redis 客户端实例；为 None 时降级为内存限流
        """
        self._redis_client = redis_client
        # DistributedRateLimiter 实例缓存：同一 level+阈值+窗口只创建一次
        self._limiters: dict[str, DistributedRateLimiter] = {}

    def _get_limiter(
        self, level_name: str, max_requests: int, window_seconds: int
    ) -> DistributedRateLimiter:
        # 同一级别复用同一个 limiter 实例（limiter 本身无状态，仅靠 key_prefix+identifier 区分）
        limiter_key = f"{level_name}:{max_requests}:{window_seconds}"
        if limiter_key not in self._limiters:
            self._limiters[limiter_key] = DistributedRateLimiter(
                redis_client=self._redis_client,
                key_prefix=f"rate:{level_name}",
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        return self._limiters[limiter_key]

    def check_level(
        self, level: RateLimitLevel, identifier: str, is_llm_call: bool = False
    ) -> tuple[bool, str, int]:
        """检查特定级别的限流

        Args:
            level: 限流级别
            identifier: 标识符 (user_id, company_id, model_name, provider)
            is_llm_call: 是否LLM调用（使用更严格的限制）

        Returns:
            (is_allowed, message, retry_after_seconds)
        """
        limits = self.LLM_LIMITS if is_llm_call else self.DEFAULT_LIMITS
        limit_config = limits.get(level, {"max_requests": 30, "window": 60})
        max_req = limit_config["max_requests"]
        window = limit_config["window"]

        limiter = self._get_limiter(level.value, max_req, window)
        allowed, current = limiter.is_allowed(identifier)

        if not allowed:
            msg = f"[{level.value}] 限流触发: {max_req}次/{window}秒 (当前: {current})"
            return False, msg, window

        return True, "", 0

    def check_all_levels(
        self,
        user_id: str = "",
        company_id: str = "",
        model_name: str = "",
        provider: str = "",
        is_llm_call: bool = False,
    ) -> tuple[bool, str, int]:
        """逐级检查所有限流级别

        文档依据: 2.docx - 限流分层: 用户→租户→模型→供应商
        按优先级顺序检查，任一级别触发限流则拒绝

        Returns:
            (is_allowed, block_message, retry_after_seconds)
        """
        # 1. 用户级限流
        if user_id:
            allowed, msg, retry = self.check_level(RateLimitLevel.USER, user_id, is_llm_call)
            if not allowed:
                return False, msg, retry

        # 2. 租户级限流
        if company_id:
            allowed, msg, retry = self.check_level(RateLimitLevel.TENANT, company_id, is_llm_call)
            if not allowed:
                return False, msg, retry

        # 3. 模型级限流
        if model_name:
            allowed, msg, retry = self.check_level(RateLimitLevel.MODEL, model_name, is_llm_call)
            if not allowed:
                return False, msg, retry

        # 4. 供应商级限流
        if provider:
            allowed, msg, retry = self.check_level(RateLimitLevel.SUPPLIER, provider, is_llm_call)
            if not allowed:
                return False, msg, retry

        return True, "", 0


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Multi-layer rate limiter middleware

    变更③ T3.1：所有 limiter 改为 DistributedRateLimiter，多实例共享 Redis 计数。
    redis_client 为 None 时自动降级为内存限流（单实例容灾）。
    """

    # 阈值改为类属性 + 环境变量（P0 优化：部署时无需改代码即可调整）
    USER_LIMIT = _env_int("RATE_LIMIT_USER", 120)
    LLM_LIMIT = _env_int("RATE_LIMIT_LLM", 10)
    LOGIN_LIMIT = _env_int("RATE_LIMIT_LOGIN", 20)
    IP_LIMIT = _env_int("RATE_LIMIT_IP", 200)
    WINDOW_SECONDS = _env_int("RATE_LIMIT_WINDOW", 60)

    LLM_ENDPOINTS = {"/api/chat/stream", "/api/chat/", "/api/tasks/"}
    LOGIN_ENDPOINTS = {"/api/auth/token", "/api/auth/login"}
    SKIP_ENDPOINTS = {
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
        "/api/chat/health",
    }

    def __init__(self, app, redis_client=None):
        super().__init__(app)
        # 各级限流器改为分布式实现；redis_client 为 None 时内部自动降级为内存
        self._user_limiter = DistributedRateLimiter(
            redis_client, "rate:user", self.USER_LIMIT, self.WINDOW_SECONDS
        )
        self._llm_limiter = DistributedRateLimiter(
            redis_client, "rate:llm:company", self.LLM_LIMIT, self.WINDOW_SECONDS
        )
        self._login_limiter = DistributedRateLimiter(
            redis_client, "rate:login", self.LOGIN_LIMIT, 300
        )
        self._ip_limiter = DistributedRateLimiter(
            redis_client, "rate:ip", self.IP_LIMIT, self.WINDOW_SECONDS
        )
        # 多级限流器 - 文档依据: 2.docx
        self._multi_level_limiter = MultiLevelRateLimiter(redis_client)

        if redis_client is not None:
            logger.info("rate_limiter_distributed_enabled")
        else:
            logger.warning("rate_limiter_redis_not_injected_fallback_to_memory")

    @staticmethod
    def _extract_access_token(request: Request) -> str | None:
        """Extract JWT from Bearer header or httpOnly access_token cookie."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token:
                return token
        return request.cookies.get("access_token")

    @staticmethod
    def _decode_access_payload(token: str | None) -> dict | None:
        """Decode JWT for rate-limit identity without raising into middleware flow."""
        if not token:
            return None
        try:
            from app.auth import decode_access_token

            return decode_access_token(token)
        except Exception:
            return None

    async def dispatch(self, request: Request, call_next):
        if os.getenv("TEST_MODE") == "true":
            return await call_next(request)

        path = request.url.path

        if path in self.SKIP_ENDPOINTS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        allowed, current = self._ip_limiter.is_allowed(client_ip)
        if not allowed:
            logger.warning("rate_limit_ip_blocked", ip=client_ip, path=path)
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(self.WINDOW_SECONDS)},
            )

        if path in self.LOGIN_ENDPOINTS:
            allowed, _ = self._login_limiter.is_allowed(client_ip)
            if not allowed:
                logger.warning("rate_limit_login_blocked", ip=client_ip)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "登录尝试过于频繁，请5分钟后再试"},
                    headers={"Retry-After": "300"},
                )

        token = self._extract_access_token(request)
        payload = self._decode_access_payload(token)

        if path in self.LLM_ENDPOINTS:
            if payload:
                company_id = payload.get("company_id", 0)
                allowed, _ = self._llm_limiter.is_allowed(str(company_id))
                if not allowed:
                    logger.warning("rate_limit_llm_blocked", company_id=company_id)
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "LLM调用过于频繁，请稍后再试"},
                        headers={"Retry-After": str(self.WINDOW_SECONDS)},
                    )

        user_id = None
        if payload:
            user_id = payload.get("sub") or payload.get("user_id")

        if user_id is not None:
            allowed, current_count = self._user_limiter.is_allowed(str(user_id))
            if not allowed:
                logger.warning("rate_limit_exceeded", user_id=user_id)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded. Maximum {self.USER_LIMIT} requests per {self.WINDOW_SECONDS}s."
                    },
                    headers={
                        "X-RateLimit-Limit": str(self.USER_LIMIT),
                        "X-RateLimit-Remaining": "0",
                        "Retry-After": str(self.WINDOW_SECONDS),
                    },
                )

        response = await call_next(request)
        if user_id is not None:
            response.headers["X-RateLimit-Limit"] = str(self.USER_LIMIT)
            response.headers["X-RateLimit-Remaining"] = str(
                self._user_limiter.remaining(str(user_id))
            )
        return response

    def check_llm_multi_level(
        self, user_id: str, company_id: str, model_name: str = "", provider: str = ""
    ) -> tuple[bool, str, int]:
        """LLM调用多级限流检查 - 文档依据: 2.docx

        按用户→租户→模型→供应商顺序逐级检查
        """
        return self._multi_level_limiter.check_all_levels(
            user_id=user_id,
            company_id=company_id,
            model_name=model_name,
            provider=provider,
            is_llm_call=True,
        )


def _build_redis_client():
    """构建限流专用 Redis 客户端

    读 RATE_LIMIT_REDIS_URL（默认与 REDIS_URL 相同），连接失败返回 None。
    返回 None 时上层自动降级为内存限流，不阻塞应用启动。
    """
    try:
        import redis as _redis  # 延迟导入，未安装 redis 包时不阻塞
    except ImportError:
        logger.warning("rate_limiter_redis_not_installed_fallback_to_memory")
        return None

    from app.core.config import RATE_LIMIT_REDIS_URL

    try:
        client = _redis.from_url(
            RATE_LIMIT_REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        logger.info("rate_limiter_redis_client_configured", url=RATE_LIMIT_REDIS_URL)
        return client
    except Exception as e:
        logger.warning("rate_limiter_redis_unavailable_fallback_to_memory", error=str(e))
        return None


def setup_rate_limiter(app, redis_client=None):
    """Setup rate limiter middleware for FastAPI app

    Args:
        app: FastAPI 应用实例
        redis_client: 可选的 Redis 客户端；为 None 时使用 LazyRedisClient 延迟创建，
                      首个限流请求连接失败则降级为内存限流
    """
    if redis_client is None:
        redis_client = LazyRedisClient(_build_redis_client)
    app.add_middleware(RateLimiterMiddleware, redis_client=redis_client)
    logger.info(
        "rate_limiter_middleware_configured",
        user_limit=RateLimiterMiddleware.USER_LIMIT,
        llm_limit=RateLimiterMiddleware.LLM_LIMIT,
        login_limit=RateLimiterMiddleware.LOGIN_LIMIT,
        distributed=True,
        redis_lazy=isinstance(redis_client, LazyRedisClient),
    )

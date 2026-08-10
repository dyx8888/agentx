"""
Rate Limiter Middleware
Provides per-user and per-company rate limiting for API requests and LLM calls
Multi-layer: IP → Login → User → LLM

文档依据: 2.docx - 大模型API调用工程实践
  - 限流分层策略: 用户级 → 租户级 → 模型级 → 供应商级
  - 4级限流: 用户级(User), 租户级(Tenant), 模型级(Model), 供应商级(Supplier)
"""

import time
from collections import defaultdict
from enum import StrEnum

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimitLevel(StrEnum):
    """限流级别 - 文档依据: 2.docx"""
    USER = "user"        # 用户级: 按user_id限流
    TENANT = "tenant"    # 租户级: 按company_id限流
    MODEL = "model"      # 模型级: 按model_name限流
    SUPPLIER = "supplier"  # 供应商级: 按provider限流


class RateLimiter:
    """Sliding-window rate limiter"""

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


class MultiLevelRateLimiter:
    """多级限流器 - 文档依据: 2.docx

    4级限流策略:
    1. 用户级 (User): 按 user_id 限流, 30 req/min
    2. 租户级 (Tenant): 按 company_id 限流, 100 req/min
    3. 模型级 (Model): 按 model_name 限流, 50 req/min
    4. 供应商级 (Supplier): 按 provider 限流, 200 req/min
    """

    # 默认限流配置
    DEFAULT_LIMITS = {
        RateLimitLevel.USER: {"max_requests": 30, "window": 60},
        RateLimitLevel.TENANT: {"max_requests": 100, "window": 60},
        RateLimitLevel.MODEL: {"max_requests": 50, "window": 60},
        RateLimitLevel.SUPPLIER: {"max_requests": 200, "window": 60},
    }
    # LLM调用额外限制（更严格）
    LLM_LIMITS = {
        RateLimitLevel.USER: {"max_requests": 10, "window": 60},
        RateLimitLevel.TENANT: {"max_requests": 50, "window": 60},
        RateLimitLevel.MODEL: {"max_requests": 20, "window": 60},
        RateLimitLevel.SUPPLIER: {"max_requests": 100, "window": 60},
    }

    def __init__(self):
        self._limiters: dict[str, RateLimiter] = {}

    def _get_limiter(self, key: str, max_requests: int,
                     window_seconds: int) -> RateLimiter:
        limiter_key = f"{key}:{max_requests}:{window_seconds}"
        if limiter_key not in self._limiters:
            self._limiters[limiter_key] = RateLimiter(
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        return self._limiters[limiter_key]

    def check_level(self, level: RateLimitLevel, identifier: str,
                    is_llm_call: bool = False) -> tuple[bool, str, int]:
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

        limiter = self._get_limiter(f"{level.value}:{identifier}", max_req, window)
        allowed, current = limiter.is_allowed(f"{level.value}:{identifier}")

        if not allowed:
            msg = (f"[{level.value}] 限流触发: "
                   f"{max_req}次/{window}秒 (当前: {current})")
            return False, msg, window

        return True, "", 0

    def check_all_levels(self, user_id: str = "",
                          company_id: str = "",
                          model_name: str = "",
                          provider: str = "",
                          is_llm_call: bool = False) -> tuple[bool, str, int]:
        """逐级检查所有限流级别

        文档依据: 2.docx - 限流分层: 用户→租户→模型→供应商
        按优先级顺序检查，任一级别触发限流则拒绝

        Returns:
            (is_allowed, block_message, retry_after_seconds)
        """
        # 1. 用户级限流
        if user_id:
            allowed, msg, retry = self.check_level(
                RateLimitLevel.USER, user_id, is_llm_call
            )
            if not allowed:
                return False, msg, retry

        # 2. 租户级限流
        if company_id:
            allowed, msg, retry = self.check_level(
                RateLimitLevel.TENANT, company_id, is_llm_call
            )
            if not allowed:
                return False, msg, retry

        # 3. 模型级限流
        if model_name:
            allowed, msg, retry = self.check_level(
                RateLimitLevel.MODEL, model_name, is_llm_call
            )
            if not allowed:
                return False, msg, retry

        # 4. 供应商级限流
        if provider:
            allowed, msg, retry = self.check_level(
                RateLimitLevel.SUPPLIER, provider, is_llm_call
            )
            if not allowed:
                return False, msg, retry

        return True, "", 0


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Multi-layer rate limiter middleware"""

    USER_LIMIT = 30
    LLM_LIMIT = 10
    LOGIN_LIMIT = 20
    IP_LIMIT = 200
    WINDOW_SECONDS = 60

    LLM_ENDPOINTS = {"/api/chat/stream", "/api/chat/", "/api/tasks/"}
    LOGIN_ENDPOINTS = {"/api/auth/token", "/api/auth/login"}
    SKIP_ENDPOINTS = {"/health", "/metrics", "/docs", "/openapi.json", "/favicon.ico"}

    def __init__(self, app):
        super().__init__(app)
        self._user_limiter = RateLimiter(max_requests=self.USER_LIMIT, window_seconds=self.WINDOW_SECONDS)
        self._llm_limiter = RateLimiter(max_requests=self.LLM_LIMIT, window_seconds=self.WINDOW_SECONDS)
        self._login_limiter = RateLimiter(max_requests=self.LOGIN_LIMIT, window_seconds=300)
        self._ip_limiter = RateLimiter(max_requests=self.IP_LIMIT, window_seconds=self.WINDOW_SECONDS)
        # 多级限流器 - 文档依据: 2.docx
        self._multi_level_limiter = MultiLevelRateLimiter()

    async def dispatch(self, request: Request, call_next):
        import os

        if os.getenv("TEST_MODE") == "true":
            return await call_next(request)

        path = request.url.path

        if path in self.SKIP_ENDPOINTS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        allowed, current = self._ip_limiter.is_allowed(f"ip:{client_ip}")
        if not allowed:
            logger.warning("rate_limit_ip_blocked", ip=client_ip, path=path)
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(self.WINDOW_SECONDS)},
            )

        if path in self.LOGIN_ENDPOINTS:
            allowed, _ = self._login_limiter.is_allowed(f"login:{client_ip}")
            if not allowed:
                logger.warning("rate_limit_login_blocked", ip=client_ip)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "登录尝试过于频繁，请5分钟后再试"},
                    headers={"Retry-After": "300"},
                )

        if path in self.LLM_ENDPOINTS:
            try:
                token = request.headers.get("Authorization", "").replace("Bearer ", "")
                if token:
                    from app.auth import decode_access_token
                    payload = decode_access_token(token)
                    if payload:
                        company_id = payload.get("company_id", 0)
                        allowed, _ = self._llm_limiter.is_allowed(f"llm:company:{company_id}")
                        if not allowed:
                            logger.warning("rate_limit_llm_blocked", company_id=company_id)
                            return JSONResponse(
                                status_code=429,
                                content={"detail": "LLM调用过于频繁，请稍后再试"},
                                headers={"Retry-After": str(self.WINDOW_SECONDS)},
                            )
            except Exception:
                pass

        user_id = None
        try:
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if token:
                from app.auth import decode_access_token
                payload = decode_access_token(token)
                if payload:
                    user_id = payload.get("sub", str(client_ip))
        except Exception:
            pass

        if user_id is None:
            user_id = client_ip

        allowed, current_count = self._user_limiter.is_allowed(f"user:{user_id}")
        if not allowed:
            logger.warning("rate_limit_exceeded", user_id=user_id)
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Maximum {self.USER_LIMIT} requests per {self.WINDOW_SECONDS}s."},
                headers={
                    "X-RateLimit-Limit": str(self.USER_LIMIT),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(self.WINDOW_SECONDS),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.USER_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(self._user_limiter.remaining(f"user:{user_id}"))
        return response

    def check_llm_multi_level(self, user_id: str, company_id: str,
                               model_name: str = "", provider: str = ""
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


def setup_rate_limiter(app):
    """Setup rate limiter middleware for FastAPI app"""
    app.add_middleware(RateLimiterMiddleware)
    logger.info("rate_limiter_middleware_configured",
                user_limit=RateLimiterMiddleware.USER_LIMIT,
                llm_limit=RateLimiterMiddleware.LLM_LIMIT,
                login_limit=RateLimiterMiddleware.LOGIN_LIMIT)

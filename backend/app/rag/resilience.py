"""# Resilience 模块，弹性机制（重试 + 熔断），借鉴 RAG-Anything 的 resilience.py 设计
弹性机制模块  # 为网络依赖操作（LLM 调用、Milvus 连接、嵌入编码）提供重试和熔断保护
借鉴 RAG-Anything 的 async_retry 装饰器和 CircuitBreaker 类设计
"""

import asyncio  # asyncio.sleep 用于异步重试等待
import random  # random.uniform 用于重试抖动
import time  # time.time 用于熔断器时间窗口计算
from functools import wraps  # wraps 用于保留被装饰函数的元数据

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


def async_retry(  # 异步重试装饰器，借鉴 RAG-Anything 的 async_retry 设计
    max_attempts: int = 3,  # 最大重试次数（含首次调用）
    base_delay: float = 1.0,  # 基础等待时间（秒）
    max_delay: float = 60.0,  # 最大等待时间（秒），防止指数退避爆炸
    exponential_base: float = 2.0,  # 指数退避基数，每次重试延迟 = base_delay * base^(attempt-1)
    jitter: bool = True,  # 是否添加随机抖动，避免惊群效应
    retryable_exceptions: tuple = (Exception,),  # 可重试的异常类型，默认所有异常
):
    """异步重试装饰器，支持指数退避和随机抖动。

    借鉴 RAG-Anything 的 async_retry 设计，适用于：
    - LLM API 调用（网络超时、速率限制）
    - Milvus 连接和检索（连接超时、服务不可用）
    - 嵌入模型编码（GPU 显存不足、模型加载失败）

    Args:
        max_attempts: 最大尝试次数（含首次调用）
        base_delay: 基础等待时间（秒）
        max_delay: 最大等待时间（秒）
        exponential_base: 指数退避基数
        jitter: 是否添加随机抖动
        retryable_exceptions: 可重试的异常类型元组

    Example:
        @async_retry(max_attempts=3, base_delay=1.0)
        async def call_llm(prompt):
            return await some_llm_api(prompt)
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt >= max_attempts:
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            attempts=attempt,
                            error=str(e),
                        )
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.uniform(0, 0.5))  # 50%~100% 的随机抖动

                    logger.warning(
                        "retry_attempt",
                        function=func.__name__,
                        attempt=attempt,
                        next_delay=round(delay, 2),
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
            raise last_exception  # 理论上不会到此，但确保类型安全

        return wrapper

    return decorator


def retry(  # 同步重试装饰器
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (Exception,),
):
    """同步重试装饰器，支持指数退避和随机抖动。

    适用于同步调用场景（如文档解析、文本切片等）。

    Example:
        @retry(max_attempts=3, retryable_exceptions=(ConnectionError, TimeoutError))
        def connect_milvus():
            return milvus_client.connect()
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt >= max_attempts:
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            attempts=attempt,
                            error=str(e),
                        )
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.uniform(0, 0.5))

                    logger.warning(
                        "retry_attempt",
                        function=func.__name__,
                        attempt=attempt,
                        next_delay=round(delay, 2),
                        error=str(e),
                    )
                    time.sleep(delay)
            raise last_exception

        return wrapper

    return decorator


class CircuitBreaker:  # 熔断器，借鉴 RAG-Anything 的 CircuitBreaker 设计
    """熔断器，用于隔离故障服务，防止级联失败。

    借鉴 RAG-Anything 的 CircuitBreaker 设计，支持三种状态：
    - CLOSED: 正常状态，请求正常通过
    - OPEN: 熔断状态，快速失败拒绝请求
    - HALF_OPEN: 半开状态，允许少量请求尝试恢复

    Example:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

        @breaker
        async def call_external_service():
            return await external_api()
    """

    def __init__(  # 初始化熔断器参数
        self,
        failure_threshold: int = 5,  # 连续失败次数阈值，达到后进入 OPEN 状态
        recovery_timeout: float = 30.0,  # 恢复超时（秒），OPEN 状态持续此时间后进入 HALF_OPEN
        half_open_max_requests: int = 3,  # HALF_OPEN 状态下允许的最大试探请求数
        success_threshold: int = 2,  # HALF_OPEN 状态下连续成功次数阈值，达到后回到 CLOSED
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests
        self.success_threshold = success_threshold

        self._failure_count = 0  # 连续失败计数
        self._success_count = 0  # 连续成功计数（仅 HALF_OPEN 状态）
        self._state = "CLOSED"  # 当前状态：CLOSED / OPEN / HALF_OPEN
        self._last_failure_time: float = 0.0  # 最后一次失败时间
        self._half_open_requests = 0  # HALF_OPEN 状态下的请求计数

    @property
    def state(self) -> str:
        """当前熔断器状态"""
        self._transition_if_needed()
        return self._state

    @property
    def is_open(self) -> bool:
        """熔断器是否处于 OPEN 状态"""
        return self.state == "OPEN"

    def _transition_if_needed(self):  # 状态转换逻辑
        if self._state == "OPEN" and time.time() - self._last_failure_time >= self.recovery_timeout:
            self._state = "HALF_OPEN"
            self._half_open_requests = 0
            self._success_count = 0
            logger.info("circuit_breaker_half_open", recovery_timeout=self.recovery_timeout)

    def on_success(self):  # 记录成功，用于状态恢复
        self._transition_if_needed()
        if self._state == "HALF_OPEN":
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = "CLOSED"
                self._failure_count = 0
                logger.info("circuit_breaker_closed")
        elif self._state == "CLOSED":
            self._failure_count = 0  # 重置失败计数

    def on_failure(self):  # 记录失败，用于触发熔断
        self._last_failure_time = time.time()
        if self._state == "HALF_OPEN":
            self._state = "OPEN"
            self._failure_count = self.failure_threshold  # 直接触发熔断
            logger.warning("circuit_breaker_reopened")
        elif self._state == "CLOSED":
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = "OPEN"
                logger.warning(
                    "circuit_breaker_opened",
                    failure_count=self._failure_count,
                    threshold=self.failure_threshold,
                )

    def before_call(self):  # 调用前检查是否允许通过
        """在调用前检查熔断器状态。

        Returns:
            bool: True 表示允许调用，False 表示熔断拒绝

        Raises:
            CircuitBreakerOpenError: 当熔断器处于 OPEN 状态时
        """
        self._transition_if_needed()
        if self._state == "OPEN":
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN. "
                f"Failed {self._failure_count} times. "
                f"Will retry after {self.recovery_timeout}s from last failure."
            )
        if self._state == "HALF_OPEN":
            self._half_open_requests += 1
            if self._half_open_requests > self.half_open_max_requests:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is HALF_OPEN and max probe requests "
                    f"({self.half_open_max_requests}) exceeded."
                )
        return True

    def __call__(self, func):  # 作为装饰器使用
        @wraps(func)
        async def wrapper(*args, **kwargs):
            self.before_call()
            try:
                result = await func(*args, **kwargs)
                self.on_success()
                return result
            except Exception:
                self.on_failure()
                raise

        return wrapper

    def reset(self):  # 手动重置熔断器
        """手动重置熔断器到 CLOSED 状态"""
        self._state = "CLOSED"
        self._failure_count = 0
        self._success_count = 0
        self._half_open_requests = 0
        logger.info("circuit_breaker_reset")


class CircuitBreakerOpenError(Exception):  # 熔断器打开时抛出的异常
    """熔断器处于 OPEN 状态时抛出的异常"""

    pass

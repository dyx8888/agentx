"""三态熔断器 — 保护外部依赖

文档依据：变更③ 03-安全与韧性.md 2.2 节

三态机：
  CLOSED  (正常)
    └─ 失败次数达到 failure_threshold → OPEN
  OPEN    (熔断，拒绝所有请求，持续 recovery_timeout 秒)
    └─ 经过 recovery_timeout → HALF_OPEN
  HALF_OPEN (试探，放行 half_open_max_requests 个请求)
    ├─ 成功 → CLOSED
    └─ 失败 → OPEN（重置 recovery_timeout）

熔断触发后：
  - 拒绝新请求 → 抛 CircuitBreakerOpenError（含 retry_after）
  - Prometheus 指标 agentx_circuit_breaker_state{name="..."}
    值：0=CLOSED, 1=OPEN, 2=HALF_OPEN
"""

import asyncio
import functools
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from enum import IntEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class CircuitState(IntEnum):
    """熔断器三态 — 整数值同步 Prometheus 指标"""

    CLOSED = 0  # 正常：放行所有请求
    OPEN = 1  # 熔断：拒绝所有请求
    HALF_OPEN = 2  # 半开：试探性放行有限请求


class CircuitBreakerOpenError(Exception):
    """熔断器处于 OPEN 态时抛出，调用方应捕获并返回标准化错误"""

    def __init__(self, name: str, retry_after: int):
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker '{name}' is OPEN. Retry after {retry_after}s.")


# ── Prometheus 指标（延迟注册，避免 prometheus_client 未安装时导入失败）──────────
_breaker_gauge = None


def _get_breaker_gauge():
    """延迟创建 Prometheus Gauge，避免模块加载期副作用"""
    global _breaker_gauge
    if _breaker_gauge is not None:
        return _breaker_gauge
    try:
        from app.monitoring.metrics import CIRCUIT_BREAKER_STATE

        _breaker_gauge = CIRCUIT_BREAKER_STATE
    except Exception:
        # prometheus_client 未安装或 metrics 模块不可用 → 降级为无指标，不影响熔断功能
        _breaker_gauge = False  # 标记为不可用，避免反复尝试
    return _breaker_gauge


# ── 模块级熔断器注册表：同一 name 只创建一个实例（T3.3 依赖此单例语义）──────────
_breaker_registry: dict[str, "CircuitBreaker"] = {}
_registry_lock = threading.Lock()


class CircuitBreaker:
    """三态熔断器

    线程安全：所有状态变更通过 _lock 串行化。
    既可用于同步函数（call_sync）也可用于异步函数（call / __call__ 装饰器）。
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max_requests: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0  # OPEN 态进入时间（monotonic）
        self._half_open_in_flight = 0  # HALF_OPEN 态已放行的试探请求数

        self._lock = threading.Lock()
        self._update_metrics()

    # ── 状态查询 ──────────────────────────────────────────────
    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def retry_after(self) -> int:
        """距离熔断恢复的剩余秒数（OPEN 态）"""
        with self._lock:
            if self._state != CircuitState.OPEN:
                return 0
            elapsed = time.monotonic() - self._opened_at
            return max(0, int(self.recovery_timeout - elapsed))

    # ── 核心方法 ──────────────────────────────────────────────
    def _before_call(self) -> None:
        """调用前置检查 + 状态流转（调用方持锁）"""
        if self._state == CircuitState.CLOSED:
            return  # 正常态，直接放行

        if self._state == CircuitState.OPEN:
            # 检查是否已过恢复期 → 转 HALF_OPEN
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_in_flight = 0
                logger.info("circuit_breaker_half_open", name=self.name)
                self._update_metrics_locked()
            else:
                # 仍在熔断期，拒绝
                remaining = int(self.recovery_timeout - elapsed)
                raise CircuitBreakerOpenError(self.name, max(0, remaining))

        if self._state == CircuitState.HALF_OPEN:
            # 半开态：只允许有限试探请求
            if self._half_open_in_flight >= self.half_open_max_requests:
                remaining = int(self.recovery_timeout - (time.monotonic() - self._opened_at))
                raise CircuitBreakerOpenError(self.name, max(0, remaining))
            self._half_open_in_flight += 1

    def on_success(self) -> None:
        """调用成功：CLOSED 重置计数；HALF_OPEN → CLOSED"""
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._half_open_in_flight = 0
                logger.info("circuit_breaker_recovered", name=self.name)
                self._update_metrics_locked()

    def on_failure(self) -> None:
        """调用失败：CLOSED 累计→超阈值转 OPEN；HALF_OPEN → OPEN（重置超时）"""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    logger.warning(
                        "circuit_breaker_opened",
                        name=self.name,
                        failure_count=self._failure_count,
                        threshold=self.failure_threshold,
                    )
                    self._update_metrics_locked()
            elif self._state == CircuitState.HALF_OPEN:
                # 试探失败 → 重新熔断，重置恢复计时
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._failure_count = 0
                self._half_open_in_flight = 0
                logger.warning("circuit_breaker_reopened_after_probe", name=self.name)
                self._update_metrics_locked()

    # ── 异步调用入口 ──────────────────────────────────────────
    async def call(self, func: Callable, *args, **kwargs):
        """异步调用受熔断器保护的函数

        Args:
            func: 异步可调用对象
            *args, **kwargs: 透传给 func

        Returns:
            func 的返回值

        Raises:
            CircuitBreakerOpenError: 熔断器开启时
            Exception: func 本身抛出的异常（同时触发 on_failure）
        """
        with self._lock:
            self._before_call()

        try:
            result = await func(*args, **kwargs)
            self.on_success()
            return result
        except CircuitBreakerOpenError:
            raise
        except Exception:
            self.on_failure()
            raise

    # ── 同步调用入口 ──────────────────────────────────────────
    def call_sync(self, func: Callable, *args, **kwargs):
        """同步调用受熔断器保护的函数"""
        with self._lock:
            self._before_call()

        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except CircuitBreakerOpenError:
            raise
        except Exception:
            self.on_failure()
            raise

    # ── 装饰器用法 ────────────────────────────────────────────
    # 用法：
    #   cb = CircuitBreaker("platform_douyin", 5, 30)
    #
    #   @cb
    #   async def call_douyin_api(): ...
    def __call__(self, func):
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await self.call(func, *args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                return self.call_sync(func, *args, **kwargs)

            return sync_wrapper

    # ── Prometheus 指标 ───────────────────────────────────────
    def _update_metrics_locked(self) -> None:
        """更新 Prometheus 指标（调用方持锁）"""
        gauge = _get_breaker_gauge()
        if not gauge:
            return
        with suppress(Exception):
            gauge.labels(name=self.name).set(int(self._state))

    def _update_metrics(self) -> None:
        with self._lock:
            self._update_metrics_locked()


# ── 工厂 + 单例注册表 ─────────────────────────────────────────
def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
    half_open_max_requests: int = 1,
) -> CircuitBreaker:
    """获取或创建具名熔断器单例

    同一 name 全局只创建一次，保证多模块共享同一熔断器实例。
    后续调用可省略 threshold/timeout 参数（已注册则忽略新参数）。
    """
    with _registry_lock:
        if name not in _breaker_registry:
            _breaker_registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max_requests=half_open_max_requests,
            )
        return _breaker_registry[name]


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
    half_open_max_requests: int = 1,
):
    """装饰器工厂：为函数挂载具名熔断器

    用法：
        @circuit_breaker("platform_douyin", 5, 30)
        async def call_douyin_api(): ...
    """
    cb = get_circuit_breaker(name, failure_threshold, recovery_timeout, half_open_max_requests)
    return cb

"""
OpenTelemetry 链路追踪模块

提供 traced 装饰器，自动为函数调用创建 span。
与 app/monitoring/metrics.py 的 Prometheus 指标共存互补。
"""

import functools
import uuid
from contextlib import contextmanager
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── 全局 TracerProvider 初始化 ──────────────────────────

_tracer_provider_initialized = False


def init_tracer(service_name: str = "agentx", exporter_endpoint: Optional[str] = None):
    """
    初始化 OpenTelemetry TracerProvider。

    Args:
        service_name: 服务名称
        exporter_endpoint: OTLP exporter 端点（可选，不设置则仅日志输出）
    """
    global _tracer_provider_initialized
    if _tracer_provider_initialized:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        if exporter_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            otlp_exporter = OTLPSpanExporter(endpoint=exporter_endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        trace.set_tracer_provider(provider)
        _tracer_provider_initialized = True
        logger.info("otel_tracer_initialized", service_name=service_name)

    except ImportError:
        logger.warning("otel_not_installed_skip_tracing")
    except Exception as e:
        logger.error("otel_init_error", error=str(e))


def get_tracer():
    """获取当前 tracer 实例"""
    try:
        from opentelemetry import trace
        return trace.get_tracer("agentx")
    except ImportError:
        return _NoopTracer()


class _NoopTracer:
    """当 OpenTelemetry 未安装时使用的空操作 tracer"""
    def start_as_current_span(self, name, **kwargs):
        return _NoopSpan()


class _NoopSpan:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def set_attribute(self, key, value):
        pass
    def set_status(self, status):
        pass


# ── traced 装饰器 ────────────────────────────────────────

def traced(name: str = None):
    """
    装饰器：自动为函数创建 OpenTelemetry span。

    Usage:
        @traced("executor_step")
        async def executor_node(state, llm, tools):
            ...
    """
    def decorator(func):
        span_name = name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("function", func.__name__)
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("function", func.__name__)
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ── trace_id 生成 ───────────────────────────────────────

def generate_trace_id(company_id: str = "", agent_name: str = "") -> str:
    """生成格式化的 trace_id: <company>-<agent>-<uuid8>"""
    company = company_id or "unknown"
    agent = agent_name or "unknown"
    short_uuid = uuid.uuid4().hex[:8]
    return f"{company}-{agent}-{short_uuid}"


# ── Span 上下文管理器 ────────────────────────────────────

@contextmanager
def trace_span(name: str, attributes: dict = None):
    """创建带属性的 span 上下文管理器"""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        yield span
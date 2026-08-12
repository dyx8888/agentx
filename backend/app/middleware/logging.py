"""
Logging Middleware for HTTP Request Monitoring
Provides request logging, performance metrics, and health monitoring
"""

import re
import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)


def _redact_url(url: str) -> str:
    """脱敏 URL 中的敏感 query 参数（token、password、secret、key、api_key 等）。

    避免日志中明文记录凭据类参数，仅保留参数名，值替换为 ***。
    """
    if not url:
        return url
    # 命中 token/password/secret/key/api_key 等参数，将其值替换为 ***
    return re.sub(r"(token|password|secret|key|api_key)=[^&]+", r"\1=***", url, flags=re.IGNORECASE)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests with performance metrics and distributed tracing"""

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log metrics with request_id and correlation_id tracing"""
        start_time = time.time()

        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get(
            "X-Correlation-ID",
            request.headers.get("X-Request-ID", str(uuid.uuid4())),
        )

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=getattr(request.state, "user_id", None),
            client_ip=request.client.host if request.client else "unknown",
        )

        method = request.method
        url = str(request.url)
        user_agent = request.headers.get("user-agent", "unknown")

        try:
            logger.info(
                "http_request_start",
                method=method,
                url=_redact_url(url),
                user_agent=user_agent,
            )

            response = await call_next(request)

            duration = time.time() - start_time

            logger.info(
                "http_request_complete",
                method=method,
                url=_redact_url(url),
                status_code=response.status_code,
                duration=f"{duration:.3f}",
            )

            response.headers["X-Response-Time"] = f"{duration:.3f}"
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id

            return response

        except Exception as e:
            duration = time.time() - start_time
            logger.exception(
                "http_request_error",
                method=method,
                url=_redact_url(url),
                duration=f"{duration:.3f}",
                error=str(e),
            )

            from fastapi.responses import JSONResponse

            # 不向客户端返回异常详情（可能泄露堆栈/SQL/文件路径），
            # 异常详情已通过上方 logger.exception 记录到服务端日志。
            # 与 app/main.py 的 general_exception_handler 行为保持一致。
            return JSONResponse({"error": "Internal server error"}, status_code=500)
        finally:
            structlog.contextvars.clear_contextvars()


class HealthCheckMiddleware(BaseHTTPMiddleware):
    """Middleware to provide liveness and readiness endpoints."""

    def __init__(self, app, health_paths: list = None):
        super().__init__(app)
        self.liveness_paths = health_paths or ["/health", "/health/", "/health/db", "/health/redis"]
        self.readiness_paths = ["/ready", "/ready/"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle health/readiness check requests."""
        path = str(request.url.path)
        if path in self.readiness_paths:
            return await self._health_check(request, readiness=True)
        if path in self.liveness_paths:
            return await self._health_check(request, readiness=False)

        return await call_next(request)

    async def _health_check(self, request: Request, readiness: bool = False) -> Response:
        """Perform health checks with strict dependency gates for /ready."""
        import os

        from fastapi.responses import JSONResponse

        vector_db = os.getenv("VECTOR_DB", "milvus").strip().lower()
        milvus_host = os.getenv("MILVUS_HOST")
        milvus_port = os.getenv("MILVUS_PORT", "19530")
        milvus_collection = os.getenv("MILVUS_COLLECTION", "company_knowledge")

        health_status = {
            "status": "checking",
            "overall": "checking",
            "probe": "readiness" if readiness else "liveness",
            "service": "agentx-backend",
            "timestamp": time.time(),
            "version": "1.0.0",
        }

        # Check database health
        try:
            from app.database import db

            db_status = db.health_check()
            health_status["database"] = db_status
        except Exception as e:
            health_status["database"] = {"status": "unhealthy", "error": str(e)}

        # Check Redis health (if configured)
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                from app.messaging.redis_queue import get_redis_queue

                redis_queue = get_redis_queue()
                if redis_queue and redis_queue.is_available():
                    # Test Redis operations
                    queue_length = redis_queue.get_queue_length()
                    health_status["redis"] = {
                        "status": "healthy",
                        "queue_length": queue_length,
                        "url": redis_url.split("@")[-1] if "@" in redis_url else redis_url,
                    }
                else:
                    health_status["redis"] = {"status": "unavailable", "url": redis_url}
            except Exception as e:
                health_status["redis"] = {"status": "unhealthy", "error": str(e)}
        else:
            health_status["redis"] = {"status": "not_configured"}

        # Check Milvus health when vector search is configured for Milvus.
        if vector_db == "milvus" and milvus_host:
            try:
                from pymilvus import MilvusClient

                client = MilvusClient(
                    uri=f"http://{milvus_host}:{milvus_port}",
                    timeout=2,
                )
                collections = client.list_collections()
                collection_exists = milvus_collection in collections if milvus_collection else False
                milvus_status = "healthy"
                milvus_error = None
                query_probe = {"status": "skipped", "reason": "liveness_probe"}
                if readiness and milvus_collection and not collection_exists:
                    milvus_status = "unhealthy"
                    milvus_error = "MILVUS_COLLECTION is not present"
                    query_probe = {"status": "skipped", "reason": "collection_missing"}
                elif readiness and milvus_collection and collection_exists:
                    try:
                        # Collection existence alone misses shard/channel failures that only
                        # surface during real query/search operations. A bounded read-only
                        # query gives /ready a stronger signal without requiring embeddings.
                        probe_rows = client.query(
                            collection_name=milvus_collection,
                            filter='id != ""',
                            output_fields=["id"],
                            limit=1,
                            timeout=2,
                        )
                        query_probe = {
                            "status": "healthy",
                            "row_count": len(probe_rows or []),
                        }
                    except Exception as probe_exc:
                        milvus_status = "unhealthy"
                        milvus_error = f"MILVUS_COLLECTION query probe failed: {probe_exc}"
                        query_probe = {"status": "unhealthy", "error": str(probe_exc)}
                client.close()
                health_status["milvus"] = {
                    "status": milvus_status,
                    "host": milvus_host,
                    "port": milvus_port,
                    "collection": milvus_collection,
                    "collection_count": len(collections),
                    "collection_exists": collection_exists,
                    "query_probe": query_probe,
                }
                if milvus_error:
                    health_status["milvus"]["error"] = milvus_error
            except ImportError:
                health_status["milvus"] = {
                    "status": "unhealthy",
                    "error": "pymilvus_not_installed",
                }
            except Exception as e:
                health_status["milvus"] = {"status": "unhealthy", "error": str(e)}
        elif vector_db == "milvus":
            health_status["milvus"] = {
                "status": "not_configured",
                "error": "MILVUS_HOST is not set",
            }
        else:
            health_status["milvus"] = {"status": "not_configured", "backend": vector_db}

        runtime = getattr(request.app.state, "runtime", None)
        runtime_initialized = getattr(runtime, "initialized", None) if runtime is not None else None
        chat_agent_ready = runtime_initialized if isinstance(runtime_initialized, bool) else False
        health_status["chat_agent"] = {
            "status": "ready" if chat_agent_ready else "not_initialized",
            "initialized": chat_agent_ready,
        }

        # Check environment variables
        health_status["environment"] = {
            "tool_load_mode": os.getenv("TOOL_LOAD_MODE", "local"),
            "run_as_http_service": os.getenv("RUN_AS_HTTP_SERVICE", "false"),
            "database_configured": bool(os.getenv("DATABASE_URL")),
            "redis_configured": bool(redis_url),
            "vector_db": vector_db,
            "milvus_configured": bool(milvus_host),
            "milvus_collection_configured": bool(milvus_collection),
        }

        # Determine overall status. Redis can be absent in local/dev because it
        # has in-memory fallbacks. Milvus is different: when VECTOR_DB=milvus,
        # it is the declared RAG vector backend, so "not_configured" must not be
        # reported as production-ready healthy.
        db_healthy = health_status.get("database", {}).get("status") == "healthy"
        redis_healthy = health_status.get("redis", {}).get("status") in [
            "healthy",
            "not_configured",
        ]
        milvus_status = health_status.get("milvus", {}).get("status")
        if vector_db == "milvus":
            milvus_healthy = milvus_status == "healthy"
        else:
            milvus_healthy = milvus_status in ["healthy", "not_configured"]

        dependency_ready = db_healthy and redis_healthy and milvus_healthy
        ready = dependency_ready and chat_agent_ready
        health_status["ready"] = ready
        health_status["readiness"] = "ready" if ready else "not_ready"

        if readiness:
            status_code = 200 if ready else 503
            health_status["status"] = "ready" if ready else "not_ready"
            health_status["overall"] = "healthy" if ready else "degraded"
        elif dependency_ready and chat_agent_ready:
            status_code = 200
            health_status["status"] = "healthy"
            health_status["overall"] = "healthy"
        else:
            status_code = 200
            health_status["status"] = "degraded"
            health_status["overall"] = "degraded"

        return JSONResponse(content=health_status, status_code=status_code)


# Metrics storage for monitoring
class SimpleMetricsCollector:
    """Simple metrics collector for monitoring"""

    def __init__(self):
        self.metrics = {
            "requests_total": 0,
            "requests_errors": 0,
            "response_time_sum": 0.0,
            "response_time_count": 0,
            "active_connections": 0,
        }
        self.start_time = time.time()

    def record_request(self, method: str, status_code: int, duration: float):
        """Record request metrics"""
        self.metrics["requests_total"] += 1

        if status_code >= 400:
            self.metrics["requests_errors"] += 1

        self.metrics["response_time_sum"] += duration
        self.metrics["response_time_count"] += 1

    def get_metrics(self) -> dict:
        """Get current metrics"""
        uptime = time.time() - self.start_time

        avg_response_time = (
            self.metrics["response_time_sum"] / self.metrics["response_time_count"]
            if self.metrics["response_time_count"] > 0
            else 0
        )

        return {
            "uptime_seconds": uptime,
            "requests_total": self.metrics["requests_total"],
            "requests_errors": self.metrics["requests_errors"],
            "error_rate": (
                self.metrics["requests_errors"] / self.metrics["requests_total"]
                if self.metrics["requests_total"] > 0
                else 0
            ),
            "avg_response_time": avg_response_time,
            "active_connections": self.metrics["active_connections"],
        }

    def increment_connections(self):
        """Increment active connections"""
        self.metrics["active_connections"] += 1

    def decrement_connections(self):
        """Decrement active connections"""
        self.metrics["active_connections"] = max(0, self.metrics["active_connections"] - 1)


# Global metrics collector
_metrics_collector = SimpleMetricsCollector()


def get_metrics_collector() -> SimpleMetricsCollector:
    """Get global metrics collector instance"""
    return _metrics_collector


def setup_logging_middleware(app):
    """Setup logging middleware for FastAPI app"""
    # Add request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Add health check middleware
    app.add_middleware(HealthCheckMiddleware)

    logger.info("Logging middleware configured")

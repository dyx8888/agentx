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
    """Redact sensitive query parameter values before URLs are written to logs."""
    if not url:
        return url
    return re.sub(
        r"([?&](?:token|password|secret|key|api_key)=)[^&]+",
        r"\1***",
        url,
        flags=re.IGNORECASE,
    )


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
            return JSONResponse({"error": "Internal server error"}, status_code=500)
        finally:
            structlog.contextvars.clear_contextvars()


class HealthCheckMiddleware(BaseHTTPMiddleware):
    """Middleware to provide enhanced health check endpoints"""

    def __init__(self, app, health_paths: list = None):
        super().__init__(app)
        self.health_paths = health_paths or ["/health", "/health/", "/health/db", "/health/redis"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle health check requests"""
        if str(request.url.path) in self.health_paths:
            return await self._health_check(request)

        return await call_next(request)

    async def _health_check(self, request: Request) -> Response:
        """Perform comprehensive health check"""
        import os

        from fastapi.responses import JSONResponse

        health_status = {
            "status": "healthy",
            "service": "agentx-backend",
            "timestamp": time.time(),
            "version": "1.0.0"
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
                        "url": redis_url.split('@')[-1] if '@' in redis_url else redis_url
                    }
                else:
                    health_status["redis"] = {"status": "unavailable", "url": redis_url}
            except Exception as e:
                health_status["redis"] = {"status": "unhealthy", "error": str(e)}
        else:
            health_status["redis"] = {"status": "not_configured"}

        # Check environment variables
        health_status["environment"] = {
            "tool_load_mode": os.getenv("TOOL_LOAD_MODE", "local"),
            "run_as_http_service": os.getenv("RUN_AS_HTTP_SERVICE", "false"),
            "database_configured": bool(os.getenv("DATABASE_URL")),
            "redis_configured": bool(redis_url)
        }

        # Determine overall status
        db_healthy = health_status.get("database", {}).get("status") == "healthy"
        redis_healthy = health_status.get("redis", {}).get("status") in ["healthy", "not_configured"]

        if db_healthy and redis_healthy:
            status_code = 200
            health_status["overall"] = "healthy"
        else:
            status_code = 503
            health_status["overall"] = "unhealthy"

        return JSONResponse(
            content=health_status,
            status_code=status_code
        )


# Metrics storage for monitoring
class MetricsCollector:
    """Simple metrics collector for monitoring"""

    def __init__(self):
        self.metrics = {
            "requests_total": 0,
            "requests_errors": 0,
            "response_time_sum": 0.0,
            "response_time_count": 0,
            "active_connections": 0
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
            if self.metrics["response_time_count"] > 0 else 0
        )

        return {
            "uptime_seconds": uptime,
            "requests_total": self.metrics["requests_total"],
            "requests_errors": self.metrics["requests_errors"],
            "error_rate": (
                self.metrics["requests_errors"] / self.metrics["requests_total"]
                if self.metrics["requests_total"] > 0 else 0
            ),
            "avg_response_time": avg_response_time,
            "active_connections": self.metrics["active_connections"]
        }

    def increment_connections(self):
        """Increment active connections"""
        self.metrics["active_connections"] += 1

    def decrement_connections(self):
        """Decrement active connections"""
        self.metrics["active_connections"] = max(0, self.metrics["active_connections"] - 1)


# Global metrics collector
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance"""
    return _metrics_collector


def setup_logging_middleware(app):
    """Setup logging middleware for FastAPI app"""
    # Add request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Add health check middleware
    app.add_middleware(HealthCheckMiddleware)

    logger.info("Logging middleware configured")

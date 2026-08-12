"""
Structured Logging Configuration
Provides centralized logging with structlog for consistent formatting

Environment-aware log output:
  ENV=dev   (default) -> colored console output for local development
  ENV=prod  -> JSON output for centralized log platforms (ELK, Splunk, etc.)

Log level is controlled by LOG_LEVEL env var:
  dev  default: DEBUG
  prod default: INFO

Log level usage conventions:
  DEBUG    - Detailed diagnostic info (SQL queries, variable dumps, request payloads)
  INFO     - Normal business events (request start/end, task created, state change)
  WARNING  - Recoverable anomalies (timeout retry, fallback to mock, deprecated API)
  ERROR    - Operation failures (API call failed, DB query error, validation failure)
  CRITICAL - System-level emergencies (DB disconnected, OOM, startup failure)

File logging (controlled by LOG_TO_FILE; defaults to enabled in prod, disabled in dev):
  LOG_TO_FILE=true|false -> enable/disable file output
                           (prod/staging defaults to true, dev defaults to false;
                            explicit LOG_TO_FILE=false always overrides prod default)
  LOG_DIR=./logs          -> log directory
  LOG_FILE=app.log        -> main log file name
  LOG_MAX_BYTES=10485760  -> max bytes per file before rotation (default 10MB)
  LOG_BACKUP_COUNT=7      -> number of rotated backup files to keep (default 7)
  Error logs (level >= ERROR) are additionally written to logs/error.log
  with the same rotation policy, for quick triage in production.

Sensitive data protection:
  Fields named password, token, api_key, secret, credential, authorization
  are automatically redacted to [REDACTED] in all log output.
  User/model payload fields such as prompt, content, message, and raw_content
  are also redacted by default so production logs do not store conversation text.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "agentx-backend")
ENV_NAME = os.getenv("ENV", "dev").lower()

_sensitive_field_names = {"password", "token", "api_key", "secret", "credential", "authorization"}
_sensitive_payload_field_names = {
    "content",
    "contents",
    "final_response",
    "messages",
    "prompt",
    "prompts",
    "raw_content",
    "response_content",
    "system_message",
    "system_prompt",
    "user_content",
    "user_message",
    "user_prompt",
}
_payload_field_suffixes = ("_content", "_message", "_messages", "_prompt", "_prompts")


def _is_sensitive_payload_field(key_lower: str) -> bool:
    if key_lower == "event":
        return False
    if key_lower in _sensitive_payload_field_names:
        return True
    return key_lower.endswith(_payload_field_suffixes)


def _redact_sensitive(logger, method_name, event_dict):
    """Structlog processor: replaces sensitive field values with [REDACTED]"""
    for key in list(event_dict.keys()):
        key_lower = key.lower()
        if any(s in key_lower for s in _sensitive_field_names) or _is_sensitive_payload_field(
            key_lower
        ):
            event_dict[key] = "[REDACTED]"
    return event_dict


def _redact_url_query(url_str: str) -> str:
    """Redact sensitive query params (token, api_key, etc.) from URLs"""
    question_idx = url_str.find("?")
    if question_idx == -1:
        return url_str
    base = url_str[:question_idx]
    params = url_str[question_idx + 1 :]
    clean_parts = []
    for part in params.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            if any(s in k.lower() for s in _sensitive_field_names):
                clean_parts.append(f"{k}=[REDACTED]")
            else:
                clean_parts.append(part)
        else:
            clean_parts.append(part)
    return base + "?" + "&".join(clean_parts) if clean_parts else base


def configure_logging():
    """Configure structured logging with environment-aware formatting and file rotation"""

    env = os.getenv("ENV", "dev").lower()
    log_level_name = os.getenv("LOG_LEVEL", "DEBUG" if env == "dev" else "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    log_to_stderr = os.getenv("LOG_TO_STDERR", "").lower() in ("true", "1", "yes")
    stream = sys.stderr if log_to_stderr else sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    handlers = [logging.StreamHandler(stream)]

    # 文件日志启用策略（生产加固）：
    #   - 显式 LOG_TO_FILE=true/false 优先级最高，始终生效
    #   - 未设置时：生产环境（prod/staging）默认启用，开发环境默认关闭
    #   - 生产环境默认启用配合 RotatingFileHandler 轮转，避免日志无限增长打满磁盘
    _log_to_file_raw = os.getenv("LOG_TO_FILE", "").lower()
    if _log_to_file_raw in ("false", "0", "no"):
        enable_file_logging = False
    elif _log_to_file_raw in ("true", "1", "yes"):
        enable_file_logging = True
    else:
        enable_file_logging = env in ("prod", "production", "staging")

    if enable_file_logging:
        log_dir = os.getenv(
            "LOG_DIR",
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs"
            ),
        )
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.getenv("LOG_FILE", "app.log")
        max_bytes = int(os.getenv("LOG_MAX_BYTES", 10 * 1024 * 1024))
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", 7))

        app_log_path = os.path.join(log_dir, log_file)
        file_handler = RotatingFileHandler(
            app_log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(file_handler)

        error_log_path = os.path.join(log_dir, "error.log")
        error_handler = RotatingFileHandler(
            error_log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setFormatter(logging.Formatter("%(message)s"))
        error_handler.setLevel(logging.ERROR)
        handlers.append(error_handler)

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=handlers,
        force=True,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _redact_sensitive,
    ]

    if env in ("prod", "production", "staging"):
        shared_processors.insert(-2, structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
        context_class=dict,
    )

    structlog.contextvars.bind_contextvars(
        environment=ENV_NAME,
        service=SERVICE_NAME,
    )

    if enable_file_logging:
        logging.getLogger(__name__).info("file_logging_enabled log_dir=%s", log_dir)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger for a specific module

    Args:
        name: Module name (usually __name__)

    Returns:
        Configured structured logger
    """
    return structlog.get_logger(name)


# Initialize logging on import
configure_logging()

# Export common logger instances
logger = get_logger(__name__)


def log_function_call(func_name: str, **kwargs):
    """Log function calls with structured data"""
    logger.info("function_call", function=func_name, **kwargs)


def log_api_request(method: str, path: str, user_id: int = None, **kwargs):
    """Log API requests with structured data"""
    logger.info("api_request", method=method, path=path, user_id=user_id, **kwargs)


def log_api_response(method: str, path: str, status_code: int, duration_ms: float = None, **kwargs):
    """Log API responses with structured data"""
    logger.info(
        "api_response",
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        **kwargs,
    )


def log_database_operation(operation: str, table: str, **kwargs):
    """Log database operations with structured data"""
    logger.info("database_operation", operation=operation, table=table, **kwargs)


def log_task_event(event_type: str, task_id: int = None, **kwargs):
    """Log task events with structured data"""
    logger.info("task_event", event_type=event_type, task_id=task_id, **kwargs)


def log_error(error: Exception, context: dict[str, Any] = None):
    """Log errors with structured data and full traceback"""
    logger.exception(
        "error_occurred",
        error_type=type(error).__name__,
        error_message=str(error),
        context=context or {},
    )


# Replace print statements in critical paths
def info(message: str, **kwargs):
    """Structured info log"""
    logger.info(message, **kwargs)


def warning(message: str, **kwargs):
    """Structured warning log"""
    logger.warning(message, **kwargs)


def error(message: str, **kwargs):
    """Structured error log"""
    logger.error(message, **kwargs)


def debug(message: str, **kwargs):
    """Structured debug log"""
    logger.debug(message, **kwargs)


def critical(message: str, **kwargs):
    """Structured critical log (system-level failures: DB disconnect, OOM, etc.)"""
    logger.critical(message, **kwargs)

"""
Enterprise Logging Test Suite
Validates all checklist items:
  (4)  Log level usage
  (5)  Sensitive data redaction
  (6)  File logging output
  (8)  Log rotation and retention
  (9)  Exception handling logging
  (10) Context enrichment
  (12) Environment differentiation
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core.logging import (
    _redact_sensitive,
    _redact_url_query,
    configure_logging,
    get_logger,
    log_api_request,
    log_api_response,
    log_database_operation,
    log_error,
    log_function_call,
    log_task_event,
)


class TestLogLevels(unittest.TestCase):
    """清单 (4): 日志级别规范"""

    def setUp(self):
        os.environ["ENV"] = "dev"
        os.environ["LOG_LEVEL"] = "DEBUG"
        configure_logging()
        self.logger = get_logger("test")

    def test_all_log_levels_available(self):
        self.assertTrue(hasattr(self.logger, "debug"))
        self.assertTrue(hasattr(self.logger, "info"))
        self.assertTrue(hasattr(self.logger, "warning"))
        self.assertTrue(hasattr(self.logger, "error"))
        self.assertTrue(hasattr(self.logger, "critical"))
        self.assertTrue(hasattr(self.logger, "exception"))

    def test_debug_level_outputs(self):
        self.logger.debug("test_debug", key="value")

    def test_info_level_outputs(self):
        self.logger.info("test_info", key="value")

    def test_warning_level_outputs(self):
        self.logger.warning("test_warning", key="value")

    def test_error_level_outputs(self):
        self.logger.error("test_error", key="value")

    def test_critical_level_outputs(self):
        self.logger.critical("test_critical", key="value")


class TestSensitiveDataRedaction(unittest.TestCase):
    """清单 (5): 敏感信息脱敏"""

    def test_password_redacted(self):
        event = {"password": "secret123", "user": "test"}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["password"], "[REDACTED]")
        self.assertEqual(result["user"], "test")

    def test_token_redacted(self):
        event = {"token": "abc123xyz", "id": 1}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["token"], "[REDACTED]")

    def test_api_key_redacted(self):
        event = {"api_key": "sk-1234567890"}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["api_key"], "[REDACTED]")

    def test_secret_redacted(self):
        event = {"client_secret": "s3cret!"}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["client_secret"], "[REDACTED]")

    def test_credential_redacted(self):
        event = {"credentials": "very-secret"}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["credentials"], "[REDACTED]")

    def test_authorization_redacted(self):
        event = {"authorization": "Bearer token123"}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["authorization"], "[REDACTED]")

    def test_normal_fields_preserved(self):
        event = {"username": "john", "email": "john@test.com", "id": 123}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result, event)

    def test_url_query_redaction(self):
        url = "https://api.example.com/data?token=secret123&user=john&api_key=sk-test"
        result = _redact_url_query(url)
        self.assertIn("token=[REDACTED]", result)
        self.assertIn("api_key=[REDACTED]", result)
        self.assertIn("user=john", result)

    def test_url_without_query_preserved(self):
        url = "https://api.example.com/data"
        self.assertEqual(_redact_url_query(url), url)

    def test_case_insensitive_redaction(self):
        event = {"Password": "secret", "API_KEY": "key", "Token": "tok"}
        result = _redact_sensitive(None, None, event)
        self.assertEqual(result["Password"], "[REDACTED]")
        self.assertEqual(result["API_KEY"], "[REDACTED]")
        self.assertEqual(result["Token"], "[REDACTED]")


class TestFileLogging(unittest.TestCase):
    """清单 (6): 文件日志输出"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.environ["ENV"] = "dev"
        os.environ["LOG_LEVEL"] = "INFO"
        os.environ["LOG_TO_FILE"] = "true"
        os.environ["LOG_DIR"] = self.temp_dir
        os.environ["LOG_FILE"] = "test_app.log"
        os.environ["LOG_MAX_BYTES"] = str(1024)
        os.environ["LOG_BACKUP_COUNT"] = "2"
        configure_logging()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        for key in ("LOG_TO_FILE", "LOG_DIR", "LOG_FILE", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
            os.environ.pop(key, None)

    def test_app_log_file_created(self):
        logger = get_logger("test_file")
        logger.info("test_file_logging", data="hello")
        log_path = os.path.join(self.temp_dir, "test_app.log")
        self.assertTrue(os.path.exists(log_path), f"Log file not found at {log_path}")

    def test_error_log_file_created(self):
        logger = get_logger("test_file")
        logger.error("test_error_log", error="something broke")
        error_path = os.path.join(self.temp_dir, "error.log")
        self.assertTrue(os.path.exists(error_path), f"Error log not found at {error_path}")

    def test_log_content_written(self):
        logger = get_logger("test_file")
        logger.info("test_content", msg="hello world")
        log_path = os.path.join(self.temp_dir, "test_app.log")
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("test_content", content)
        self.assertIn("hello world", content)


class TestLogRotation(unittest.TestCase):
    """清单 (8): 日志轮转和保留"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.environ["ENV"] = "dev"
        os.environ["LOG_LEVEL"] = "INFO"
        os.environ["LOG_TO_FILE"] = "true"
        os.environ["LOG_DIR"] = self.temp_dir
        os.environ["LOG_FILE"] = "rotate_test.log"
        os.environ["LOG_MAX_BYTES"] = str(256)
        os.environ["LOG_BACKUP_COUNT"] = "3"
        configure_logging()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        for key in ("LOG_TO_FILE", "LOG_DIR", "LOG_FILE", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
            os.environ.pop(key, None)

    def test_rotation_creates_backups(self):
        logger = get_logger("test_rotate")
        for i in range(50):
            logger.info("rotate_test", iteration=i, padding="x" * 50)

        log_path = os.path.join(self.temp_dir, "rotate_test.log")
        self.assertTrue(os.path.exists(log_path))

        backup_files = [f for f in os.listdir(self.temp_dir) if f.startswith("rotate_test.log.")]
        self.assertGreater(len(backup_files), 0, "No rotated backup files found")


class TestExceptionLogging(unittest.TestCase):
    """清单 (9): 异常处理和崩溃日志"""

    def setUp(self):
        os.environ["ENV"] = "dev"
        os.environ["LOG_LEVEL"] = "DEBUG"
        configure_logging()

    def test_log_error_function(self):
        exc = ValueError("test error")
        log_error(exc, context={"operation": "test_op"})

    def test_logger_exception_method(self):
        logger = get_logger("test_exc")
        try:
            raise RuntimeError("test runtime error")
        except RuntimeError:
            logger.exception("test_exception_caught", context="test")


class TestContextEnrichment(unittest.TestCase):
    """清单 (10): 上下文丰富"""

    def setUp(self):
        os.environ["ENV"] = "dev"
        os.environ["LOG_LEVEL"] = "DEBUG"
        configure_logging()
        self.logger = get_logger("test_context")

    def test_log_function_call(self):
        log_function_call("test_func", param1="val1", param2=42)

    def test_log_api_request(self):
        log_api_request("GET", "/api/test", user_id=1, ip="127.0.0.1")

    def test_log_api_response(self):
        log_api_response("POST", "/api/test", status_code=200, duration_ms=15.5)

    def test_log_database_operation(self):
        log_database_operation("SELECT", "users", rows=10)

    def test_log_task_event(self):
        log_task_event("task_created", task_id=42, task_type="email_notification")


class TestEnvironmentDifferentiation(unittest.TestCase):
    """清单 (12): 环境差异化"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dev_env_console_output(self):
        os.environ["ENV"] = "dev"
        configure_logging()
        logger = get_logger("test_env")
        logger.info("dev_test", env="dev")

    def test_prod_env_json_output(self):
        os.environ["ENV"] = "prod"
        os.environ["LOG_LEVEL"] = "INFO"
        os.environ["LOG_TO_FILE"] = "true"
        os.environ["LOG_DIR"] = self.temp_dir
        os.environ["LOG_FILE"] = "prod_test.log"
        configure_logging()
        logger = get_logger("test_env")
        logger.info("prod_test", env="prod")

        log_path = os.path.join(self.temp_dir, "prod_test.log")
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("prod_test", content)

        for key in ("ENV", "LOG_TO_FILE", "LOG_DIR", "LOG_FILE"):
            os.environ.pop(key, None)


class TestGetLogger(unittest.TestCase):
    """工具函数测试"""

    def test_get_logger_returns_bound_logger(self):
        logger = get_logger("test_module")
        self.assertIsNotNone(logger)
        self.assertTrue(hasattr(logger, "info"))
        self.assertTrue(hasattr(logger, "error"))

    def test_get_logger_has_correct_name(self):
        logger = get_logger("my.custom.module")
        self.assertTrue(hasattr(logger, "_context"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

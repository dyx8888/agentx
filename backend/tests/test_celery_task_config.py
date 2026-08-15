"""Local tests for optional Celery configuration.

These tests inspect configuration only. They must not connect to Redis, start a
worker, enqueue tasks, or import platform integrations.
"""

from __future__ import annotations

import importlib
import sys
import types


CELERY_MODULES = [
    "app.tasks.celery_app",
    "app.celery_worker",
    "app.celery_app",
]


def _fresh_import(module_name: str):
    for name in CELERY_MODULES:
        sys.modules.pop(name, None)
    return importlib.import_module(module_name)


def test_celery_app_imports_without_redis_connection(monkeypatch):
    calls = []

    fake_redis = types.SimpleNamespace(
        from_url=lambda *args, **kwargs: calls.append((args, kwargs)),
        Redis=types.SimpleNamespace(
            from_url=lambda *args, **kwargs: calls.append((args, kwargs))
        ),
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    celery_module = _fresh_import("app.celery_app")

    assert celery_module.app.main == "agentx"
    assert calls == []


def test_celery_routes_and_beat_schedule_are_declared():
    celery_module = _fresh_import("app.celery_app")
    app = celery_module.app

    routes = app.conf.task_routes
    assert routes["app.tasks.document_tasks.*"]["queue"] == "document_tasks"
    assert routes["app.tasks.memory_tasks.*"]["queue"] == "memory_tasks"
    assert routes["app.tasks.periodic_tasks.*"]["queue"] == "periodic_tasks"
    assert routes["app.celery_app.worker_heartbeat"]["queue"] == "periodic_tasks"

    schedule = app.conf.beat_schedule
    assert "optional-worker-heartbeat" in schedule
    assert schedule["optional-worker-heartbeat"]["task"] == "app.celery_app.worker_heartbeat"
    schedule_text = str(schedule)
    assert "token_refresh" not in schedule_text
    assert "refresh_expiring_tokens" not in schedule_text


def test_celery_reliability_settings_are_present():
    celery_module = _fresh_import("app.celery_app")
    app = celery_module.app

    assert app.conf.broker_transport_options["visibility_timeout"] == 3600
    assert app.conf.result_backend_transport_options["visibility_timeout"] == 3600
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1


def test_tasks_celery_app_reuses_single_app_instance():
    celery_module = _fresh_import("app.celery_app")
    tasks_celery_module = importlib.import_module("app.tasks.celery_app")

    assert tasks_celery_module.app is celery_module.app
    assert tasks_celery_module.app.conf.worker_prefetch_multiplier == 1


def test_worker_entrypoint_only_exposes_configured_app():
    celery_module = _fresh_import("app.celery_app")
    worker_module = importlib.import_module("app.celery_worker")

    assert worker_module.app is celery_module.app

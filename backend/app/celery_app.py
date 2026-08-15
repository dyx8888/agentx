"""Import-safe optional Celery application configuration.

This module declares queue and reliability settings only. Importing it must not
connect to Redis, start a worker, enqueue tasks, or touch external services.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
CELERY_BROKER_URL = (
    os.getenv("CELERY_BROKER_URL")
    or os.getenv("REDIS_URL")
    or DEFAULT_REDIS_URL
)
CELERY_RESULT_BACKEND = (
    os.getenv("CELERY_RESULT_BACKEND")
    or CELERY_BROKER_URL
)
VISIBILITY_TIMEOUT_SECONDS = 3600


app = Celery(
    "agentx",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    result_expires=3600,
    task_create_missing_queues=True,
    task_default_queue="default",
    task_routes={
        "app.celery_app.worker_heartbeat": {"queue": "periodic_tasks"},
        "app.tasks.document_tasks.*": {"queue": "document_tasks"},
        "app.tasks.memory_tasks.*": {"queue": "memory_tasks"},
        "app.tasks.periodic_tasks.*": {"queue": "periodic_tasks"},
    },
    beat_schedule={
        "optional-worker-heartbeat": {
            "task": "app.celery_app.worker_heartbeat",
            "schedule": crontab(minute="*/30"),
        },
    },
    broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
    result_backend_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


@app.task(name="app.celery_app.worker_heartbeat")
def worker_heartbeat() -> dict[str, str]:
    """No-op task used only as a safe beat schedule placeholder."""
    return {"status": "ok"}


__all__ = [
    "app",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "VISIBILITY_TIMEOUT_SECONDS",
    "worker_heartbeat",
]

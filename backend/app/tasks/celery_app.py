"""Optional Celery reliability overlay.

This module reuses ``app.celery_app.app`` and reinforces worker reliability
settings without creating a second Celery application or connecting to Redis.
"""

from __future__ import annotations

from app.celery_app import VISIBILITY_TIMEOUT_SECONDS, app


app.conf.update(
    broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
    result_backend_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


__all__ = ["app"]

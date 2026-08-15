"""Optional Celery worker entry point.

This file intentionally only exposes the configured Celery app. Workers must be
started explicitly with a Celery command; importing FastAPI does not import or
start this module.
"""

from __future__ import annotations

from app.celery_app import app


__all__ = ["app"]

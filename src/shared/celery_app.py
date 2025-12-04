from __future__ import annotations

from celery import Celery
from api.settings import settings

celery_app = Celery(
    "ai_art_studio",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["worker.tasks"],
)

# Keep config explicit for reproducibility.
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

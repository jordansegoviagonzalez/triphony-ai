from __future__ import annotations

from celery import Celery
from celery.signals import task_postrun, task_prerun
from api.settings import settings
from triphony_lib.observability import clear_correlation_id, metric_inc, set_correlation_id

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
    broker_connection_retry_on_startup=True,
    worker_concurrency=settings.celery_concurrency,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
)


@task_prerun.connect
def _set_task_correlation_id(task_id: str | None = None, task: object | None = None, **_: object) -> None:
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", {}) or {}
    set_correlation_id(headers.get("correlation_id"))
    metric_inc("triphony.queue.tasks", task=getattr(task, "name", "unknown"))


@task_postrun.connect
def _clear_task_correlation_id(**_: object) -> None:
    clear_correlation_id()

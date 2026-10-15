"""Durable outbox dispatcher and dead-letter recovery helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from api.governance import record_audit
from api.models import DeadLetterRecord, OutboxEvent, OutboxEventStatus, Scene, WorkflowStateRecord
from shared.celery_app import celery_app
from workflow.orchestrator import SessionLocal
from triphony_lib.observability import json_log, metric_inc, span


def dispatch_outbox(*, publish: Any | None = None, limit: int = 100) -> dict[str, int]:
    publish = publish or (lambda event: celery_app.send_task(
        "worker.tasks.start_scene_workflow",
        args=[event.payload["scene_id"]],
        task_id=event.event_key,
        headers={"correlation_id": event.correlation_id},
    ))
    db = SessionLocal()
    published = failed = 0
    try:
        events = db.query(OutboxEvent).filter(
            OutboxEvent.status == OutboxEventStatus.pending,
            OutboxEvent.available_at <= datetime.now(timezone.utc).replace(tzinfo=None),
        ).order_by(OutboxEvent.created_at).limit(limit).with_for_update(skip_locked=True).all()
        for event in events:
            event.attempts += 1
            try:
                with span("queue.outbox.publish", event_type=event.event_type, event_key=event.event_key):
                    publish(event)
                event.status = OutboxEventStatus.published
                event.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
                published += 1
            except Exception:
                event.status = OutboxEventStatus.failed if event.attempts >= 5 else OutboxEventStatus.pending
                event.last_error = "outbox publication failed"
                metric_inc("triphony.outbox.publication_failures", event_type=event.event_type)
                json_log(__import__("logging").getLogger("triphony.worker"), __import__("logging").ERROR, "outbox_publication_failed", event_type=event.event_type, event_key=event.event_key, attempts=event.attempts)
                if event.attempts >= 5:
                    create_dead_letter(
                        scene_id=event.payload.get("scene_id"), provider_job_id=None,
                        task_type=event.event_type, failure_code="outbox_publish_failed",
                        attempt_count=event.attempts, correlation_id=event.correlation_id,
                        replay_eligible=True, details={"source": "outbox_dispatch"},
                    )
                    metric_inc("triphony.dead_letters.created", task_type=event.event_type)
                failed += 1
        db.commit()
        return {"published": published, "failed": failed}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reconcile_workflows(*, limit: int = 100) -> dict[str, int]:
    """Re-enqueue non-terminal scenes so an interrupted worker can resume them."""
    db = SessionLocal()
    dispatched = 0
    try:
        scenes = db.query(Scene).filter(
            Scene.workflow_state.notin_([
                WorkflowStateRecord.completed,
                WorkflowStateRecord.failed,
                WorkflowStateRecord.cancelled,
            ])
        ).order_by(Scene.created_at).limit(limit).all()
        for scene in scenes:
            celery_app.send_task(
                "worker.tasks.start_scene_workflow",
                args=[scene.id],
                task_id=f"reconcile:{scene.id}",
                headers={"correlation_id": scene.id},
            )
            dispatched += 1
        metric_inc("triphony.workflow.reconciliations", count=dispatched)
        return {"dispatched": dispatched}
    except Exception as error:
        json_log(__import__("logging").getLogger("triphony.worker"), __import__("logging").ERROR, "workflow_reconciliation_failed", error_type=type(error).__name__)
        db.rollback()
        raise
    finally:
        db.close()


def create_dead_letter(*, scene_id: str | None, provider_job_id: str | None, task_type: str, failure_code: str, attempt_count: int, correlation_id: str, replay_eligible: bool, details: dict[str, Any] | None = None) -> str:
    db = SessionLocal()
    try:
        record = DeadLetterRecord(
            id=f"dlq-{uuid.uuid4().hex}", scene_id=scene_id, provider_job_id=provider_job_id,
            task_type=task_type, failure_code=failure_code[:128], attempt_count=attempt_count,
            correlation_id=correlation_id, replay_eligible=replay_eligible, safe_details=details or {},
            first_failed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            last_failed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(record)
        record_audit(db, actor_user_id=None, event_type="dead_letter_creation", resource_type="dead_letter", resource_id=record.id, correlation=correlation_id, outcome="created", metadata={"task_type": task_type, "failure_code": failure_code[:128], "replay_eligible": replay_eligible})
        db.commit()
        return record.id
    finally:
        db.close()


def replay_dead_letter(dead_letter_id: str, *, publish: Any | None = None) -> bool:
    publish = publish or (lambda record: celery_app.send_task(record.task_type, args=[record.scene_id], task_id=f"replay:{record.id}"))
    db = SessionLocal()
    try:
        record = db.get(DeadLetterRecord, dead_letter_id)
        if not record or record.resolved or not record.replay_eligible:
            return False
        publish(record)
        record.resolved = True
        record_audit(db, actor_user_id=None, event_type="dead_letter_replay", resource_type="dead_letter", resource_id=record.id, correlation=record.correlation_id, outcome="replayed", metadata={"task_type": record.task_type})
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()

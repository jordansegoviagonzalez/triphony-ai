"""Safety, audit, and Redis-backed usage governance helpers."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import redis
from sqlalchemy.orm import Session

from api.models import AuditEvent, OutboxEvent, OutboxEventStatus
from api.settings import settings


def correlation_id(value: str | None = None) -> str:
    return value if value and re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value) else str(uuid.uuid4())


def safe_prompt_fingerprint(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def safety_gate(prompt: str) -> tuple[bool, str]:
    normalized = prompt.casefold()
    if any(term in normalized for term in ("<script", "javascript:", "data:text/html", "ignore previous system")):
        return False, "unsafe_content"
    return True, "allowed"


def record_audit(db: Session, *, actor_user_id: str | None, event_type: str, resource_type: str, resource_id: str, correlation: str, outcome: str, metadata: dict[str, Any] | None = None) -> AuditEvent:
    event = AuditEvent(
        id=f"audit-{uuid.uuid4().hex}", actor_user_id=actor_user_id, event_type=event_type,
        resource_type=resource_type, resource_id=resource_id, correlation_id=correlation,
        outcome=outcome, safe_metadata=metadata or {},
    )
    db.add(event)
    return event


def add_outbox_event(db: Session, *, event_key: str, event_type: str, payload: dict[str, Any], correlation: str) -> OutboxEvent:
    existing = db.query(OutboxEvent).filter(OutboxEvent.event_key == event_key).first()
    if existing:
        return existing
    event = OutboxEvent(
        id=f"outbox-{uuid.uuid4().hex}", event_key=event_key, event_type=event_type,
        payload=payload, correlation_id=correlation, status=OutboxEventStatus.pending,
        available_at=datetime.now(timezone.utc).replace(tzinfo=None),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(event)
    db.flush()
    return event


class RedisGovernance:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client or redis.Redis.from_url(os.getenv("REDIS_URL") or settings.redis_url, decode_responses=True)

    def _now(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    def check_submission(self, user_id: str, *, prompt: str, requested_duration_seconds: int = 3, shot_count: int = 1) -> tuple[bool, str, int | None]:
        if len(prompt) > settings.max_prompt_length:
            return False, "prompt_too_long", None
        if requested_duration_seconds > settings.max_requested_duration_seconds:
            return False, "duration_limit_exceeded", None
        if shot_count > settings.max_shots:
            return False, "shot_limit_exceeded", None
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rate_key = f"triphony:rate:submission:{user_id}"
        concurrent_key = f"triphony:quota:concurrent:{user_id}"
        daily_key = f"triphony:quota:daily:{user_id}:{day}"
        try:
            if not self.client.set(rate_key, "1", nx=True, ex=settings.submission_rate_limit_seconds):
                return False, "submission_rate_limit", settings.submission_rate_limit_seconds
            pipe = self.client.pipeline(transaction=True)
            pipe.get(concurrent_key)
            pipe.get(daily_key)
            concurrent, daily = pipe.execute()
        except Exception as error:
            if settings.provider_mode in {"fake", "mock"}:
                return True, "allowed", None
            raise RuntimeError("usage governance datastore unavailable") from error
        if int(concurrent or 0) >= settings.max_concurrent_workflows:
            return False, "concurrent_workflow_limit", 5
        if int(daily or 0) >= settings.daily_generation_quota:
            return False, "daily_generation_quota", 60
        pipe = self.client.pipeline(transaction=True)
        pipe.incr(concurrent_key)
        pipe.expire(concurrent_key, 60 * 60)
        pipe.incr(daily_key)
        pipe.expire(daily_key, 60 * 60 * 24)
        try:
            pipe.execute()
        except Exception as error:
            if settings.provider_mode in {"fake", "mock"}:
                return True, "allowed", None
            raise RuntimeError("usage governance datastore unavailable") from error
        return True, "allowed", None

    def release_concurrent(self, user_id: str) -> None:
        try:
            key = f"triphony:quota:concurrent:{user_id}"
            remaining = self.client.decrby(key, 1)
            if int(remaining) <= 0:
                self.client.delete(key)
        except Exception:
            pass

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
from triphony_lib.observability import safe_fields


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
        outcome=outcome, safe_metadata=safe_fields(metadata or {}),
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
            if hasattr(self.client, "eval"):
                result = self.client.eval(
                    """
                    local rate = redis.call('SET', KEYS[1], '1', 'NX', 'EX', ARGV[1])
                    if not rate then return {0, 'submission_rate_limit', ARGV[1]} end
                    local concurrent = tonumber(redis.call('GET', KEYS[2]) or '0')
                    local daily = tonumber(redis.call('GET', KEYS[3]) or '0')
                    if concurrent >= tonumber(ARGV[2]) then
                        redis.call('DEL', KEYS[1])
                        return {0, 'concurrent_workflow_limit', '5'}
                    end
                    if daily >= tonumber(ARGV[3]) then
                        redis.call('DEL', KEYS[1])
                        return {0, 'daily_generation_quota', '60'}
                    end
                    redis.call('INCR', KEYS[2])
                    redis.call('EXPIRE', KEYS[2], 3600)
                    redis.call('INCR', KEYS[3])
                    redis.call('EXPIRE', KEYS[3], 86400)
                    return {1, 'allowed', '0'}
                    """,
                    3,
                    rate_key,
                    concurrent_key,
                    daily_key,
                    settings.submission_rate_limit_seconds,
                    settings.max_concurrent_workflows,
                    settings.daily_generation_quota,
                )
                allowed_flag, reason_value, retry_value = result
                reason_text = reason_value.decode() if isinstance(reason_value, bytes) else str(reason_value)
                return bool(int(allowed_flag)), reason_text, int(retry_value) or None

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
            if hasattr(self.client, "delete"):
                self.client.delete(rate_key)
            return False, "concurrent_workflow_limit", 5
        if int(daily or 0) >= settings.daily_generation_quota:
            if hasattr(self.client, "delete"):
                self.client.delete(rate_key)
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

    def bind_reservation(self, user_id: str, scene_id: str) -> None:
        key = f"triphony:quota:reservation:{scene_id}"
        try:
            self.client.set(key, user_id, nx=True, ex=60 * 60 * 24 * 7)
        except Exception as error:
            if settings.provider_mode not in {"fake", "mock"}:
                raise RuntimeError("usage governance datastore unavailable") from error

    def release_concurrent(self, user_id: str, reservation_id: str | None = None) -> None:
        try:
            if reservation_id:
                reservation_key = f"triphony:quota:reservation:{reservation_id}"
                owner = self.client.get(reservation_key)
                if isinstance(owner, bytes):
                    owner = owner.decode()
                if owner != user_id:
                    return
                if hasattr(self.client, "eval"):
                    self.client.eval(
                        """
                        if redis.call('GET', KEYS[1]) == ARGV[1] then
                            redis.call('DEL', KEYS[1])
                            local remaining = redis.call('DECRBY', KEYS[2], 1)
                            if remaining <= 0 then redis.call('DEL', KEYS[2]) end
                        end
                        return 1
                        """,
                        2,
                        reservation_key,
                        f"triphony:quota:concurrent:{user_id}",
                        user_id,
                    )
                    return
                if hasattr(self.client, "delete"):
                    self.client.delete(reservation_key)
                else:
                    return
            key = f"triphony:quota:concurrent:{user_id}"
            remaining = self.client.decrby(key, 1)
            if int(remaining) <= 0:
                self.client.delete(key)
        except Exception:
            pass

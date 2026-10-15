"""Small provider-boundary helpers; no SDK types cross this module."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from triphony_lib.domain import (
    AgentType,
    IdempotencyInfo,
    MediaType,
    ProviderJob,
    ProviderJobStatus,
    ProvenanceMetadata,
)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def fixed_safe_now() -> datetime:
    return datetime.now(timezone.utc)


def provider_job(
    *,
    job_id: str,
    scene_id: str,
    agent_type: AgentType,
    media_type: MediaType,
    idempotency: IdempotencyInfo,
    provider: str,
    model: str,
    status: ProviderJobStatus,
    provider_job_id: str | None = None,
    failure: Any = None,
) -> ProviderJob:
    now = fixed_safe_now()
    return ProviderJob(
        job_id=job_id,
        scene_id=scene_id,
        agent_type=agent_type,
        media_type=media_type,
        status=status,
        idempotency=idempotency,
        provenance=ProvenanceMetadata(source="provider", provider=provider, model=model),
        provider_job_id=provider_job_id,
        failure=failure,
        created_at=now,
        updated_at=now,
    )


def response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(response, dict):
        value = response.get("text")
        if isinstance(value, str):
            return value
    raise ValueError("provider response did not contain structured text")


def nested_value(value: Any, *names: str) -> Any:
    current = value
    for name in names:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(name)
        else:
            current = getattr(current, name, None)
    return current


"""Lazy official Runway SDK adapter.

Only provider-neutral domain objects leave this module. The SDK is imported
inside the client factory so fake mode and automated tests never construct a
live client.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from providers.common import digest, provider_job
from providers.config import ProviderConfig
from providers.errors import ProviderError, ProviderErrorKind, translate_provider_exception
from triphony_lib.agents import VisualAgent
from triphony_lib.observability import span
from triphony_lib.domain import (
    AgentCapabilities, AgentType, AssetVersion, AssetVersionStatus, MediaType,
    ProviderJob, ProviderJobStatus, ProvenanceMetadata, VisualAgentRequest,
    VisualAgentResult,
)


def create_runway_client(config: ProviderConfig) -> Any:
    if config.mode != "real" or not config.runway_api_secret:
        raise ProviderError(ProviderErrorKind.configuration, "Runway configuration is incomplete")
    try:
        from runwayml import RunwayML

        return RunwayML(api_key=config.runway_api_secret, timeout=config.runway_request_timeout_seconds)
    except ProviderError:
        raise
    except Exception as error:
        raise ProviderError(ProviderErrorKind.configuration, "Runway SDK client could not be created") from error


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


@dataclass(frozen=True)
class RunwayPollResult:
    job: ProviderJob
    asset: AssetVersion | None = None


class RunwayVisualAgent(VisualAgent):
    capabilities = AgentCapabilities(
        agent_type=AgentType.visual,
        provider_name="runway",
        supported_media_types=[MediaType.video],
        asynchronous_jobs=True,
        cancellation_supported=True,
        deterministic=False,
    )

    def __init__(
        self,
        config: ProviderConfig,
        client_factory: Callable[[], Any] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._client_factory = client_factory or (lambda: create_runway_client(config))
        self._client: Any | None = None
        self._clock = clock
        self._sleep = sleep_fn
        self._submissions: dict[str, tuple[str, ProviderJob]] = {}

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def submit(self, request: VisualAgentRequest) -> ProviderJob:
        fingerprint = digest(request.model_dump(mode="json"))
        cached = self._submissions.get(request.idempotency.key)
        if cached:
            if cached[0] != fingerprint:
                raise ProviderError(ProviderErrorKind.invalid_request, "idempotency key was reused for a different request")
            return cached[1]
        shot = next((item for item in request.plan.shots if item.shot_id == request.shot_id), None)
        if shot is None:
            raise ProviderError(ProviderErrorKind.invalid_request, "requested shot is not in the approved plan")
        duration = min(self.config.runway_max_duration_seconds, max(2, round(shot.timing.duration_ms / 1000)))
        try:
            with span("provider.runway.submit", provider="runway", model=self.config.runway_model):
                task = self._client_or_create().image_to_video.create(
                    model=self.config.runway_model,
                    prompt_text=(
                        f"Cinematic shot: {shot.prompt}. Visual direction: {shot.visual.description}. "
                        f"Camera: {shot.camera.shot_type}, {shot.camera.movement}, {shot.camera.framing}."
                    ),
                    ratio="1280:720",
                    duration=duration,
                )
            external_id = _value(task, "id")
            if not isinstance(external_id, str) or not external_id:
                raise ProviderError(ProviderErrorKind.malformed, "Runway submission did not return a task identifier")
            job = provider_job(
                job_id=f"runway-{digest(request.idempotency.key)[:20]}",
                scene_id=request.plan.scene_id,
                agent_type=AgentType.visual,
                media_type=MediaType.video,
                idempotency=request.idempotency,
                provider="runway",
                model=self.config.runway_model,
                status=ProviderJobStatus.queued,
                provider_job_id=external_id,
            )
            self._submissions[request.idempotency.key] = (fingerprint, job)
            return job
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def poll(self, job: ProviderJob, request: VisualAgentRequest) -> RunwayPollResult:
        if not job.provider_job_id:
            raise ProviderError(ProviderErrorKind.malformed, "Runway job has no external task identifier")
        try:
            with span("provider.runway.poll", provider="runway", model=self.config.runway_model):
                task = self._client_or_create().tasks.retrieve(job.provider_job_id)
            raw_status = str(_value(task, "status") or "").lower()
            running = job if job.status is ProviderJobStatus.running else job.transition(ProviderJobStatus.running)
            if raw_status in {"pending", "running", "processing", "throttled"}:
                return RunwayPollResult(job=running)
            if raw_status in {"canceled", "cancelled"}:
                return RunwayPollResult(job=running.transition(ProviderJobStatus.cancelled))
            if raw_status == "failed":
                error = ProviderError(ProviderErrorKind.terminal, "Runway generation failed")
                return RunwayPollResult(job=running.transition(ProviderJobStatus.failed).model_copy(update={"failure": error.failure_info()}))
            if raw_status != "succeeded":
                raise ProviderError(ProviderErrorKind.malformed, "Runway returned an unknown task status")
            output = _value(task, "output")
            uri = output[0] if isinstance(output, list) and output else None
            if not isinstance(uri, str) or not uri.startswith(("https://", "http://")):
                raise ProviderError(ProviderErrorKind.malformed, "Runway completed without a valid output URL")
            shot_id = request.shot_id or request.plan.shots[0].shot_id
            asset = AssetVersion(
                asset_version_id=f"asset-{digest(job.job_id)[:24]}",
                scene_id=request.plan.scene_id,
                asset_id=f"visual-{shot_id}",
                version=1,
                media_type=MediaType.video,
                status=AssetVersionStatus.draft,
                artifact_uri=uri,
                provenance=ProvenanceMetadata(
                    source="provider", provider="runway", model=self.config.runway_model,
                    metadata={"external_task_id": job.provider_job_id, "mime_type": "video/mp4"},
                ),
            )
            return RunwayPollResult(job=running.transition(ProviderJobStatus.succeeded), asset=asset)
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def generate(self, request: VisualAgentRequest) -> VisualAgentResult:
        job = self.submit(request)
        deadline = self._clock() + self.config.runway_poll_deadline_seconds
        while True:
            result = self.poll(job, request)
            job = result.job
            if result.asset is not None:
                return VisualAgentResult(job=job, asset=result.asset)
            if job.status is ProviderJobStatus.failed:
                raise ProviderError(ProviderErrorKind.terminal, "Runway generation failed")
            if job.status is ProviderJobStatus.cancelled:
                raise ProviderError(ProviderErrorKind.terminal, "Runway generation was cancelled")
            if self._clock() >= deadline:
                raise ProviderError(ProviderErrorKind.timeout, "Runway task polling timed out", retryable=True)
            self._sleep(self.config.runway_poll_interval_seconds)

    def cancel(self, job_id: str) -> None:
        try:
            with span("provider.runway.cancel", provider="runway"):
                self._client_or_create().tasks.cancel(job_id)
        except Exception as error:
            raise translate_provider_exception(error) from error

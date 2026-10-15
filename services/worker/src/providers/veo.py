"""Veo asynchronous submit/poll adapter with resumable provider jobs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from providers.common import digest, nested_value, provider_job
from providers.config import ProviderConfig
from providers.errors import ProviderError, ProviderErrorKind, translate_provider_exception
from providers.vertex import create_vertex_client
from triphony_lib.agents import VisualAgent
from triphony_lib.domain import (
    AgentCapabilities,
    AgentType,
    AssetVersion,
    AssetVersionStatus,
    MediaType,
    ProviderJob,
    ProviderJobStatus,
    ProvenanceMetadata,
    VisualAgentRequest,
    VisualAgentResult,
)


@dataclass(frozen=True)
class VisualPollResult:
    job: ProviderJob
    asset: AssetVersion | None = None


class _OperationReference:
    def __init__(self, name: str) -> None:
        self.name = name


def _operation_reference(name: str) -> Any:
    """Rebuild the official SDK operation shape after a worker restart when possible."""
    try:
        from google.genai.types import GenerateVideosOperation

        return GenerateVideosOperation(name=name)
    except Exception:
        return _OperationReference(name)


def _operation_id(operation: Any) -> str | None:
    value = getattr(operation, "name", None)
    if value is None and isinstance(operation, dict):
        value = operation.get("name") or operation.get("operation_id")
    return value if isinstance(value, str) and value else None


def _operation_done(operation: Any) -> bool:
    value = getattr(operation, "done", None)
    if value is None and isinstance(operation, dict):
        value = operation.get("done")
    return bool(value)


def _operation_cancelled(operation: Any) -> bool:
    value = getattr(operation, "cancelled", None)
    if value is None:
        value = getattr(operation, "canceled", None)
    if value is None and isinstance(operation, dict):
        value = operation.get("cancelled") or operation.get("canceled")
    return bool(value)


def _operation_error(operation: Any) -> bool:
    value = getattr(operation, "error", None)
    if value is None and isinstance(operation, dict):
        value = operation.get("error")
    return value is not None


def _video_uri(operation: Any) -> str | None:
    result = nested_value(operation, "result") or nested_value(operation, "response")
    videos = nested_value(result, "generated_videos")
    if videos is None and isinstance(result, dict):
        videos = result.get("generatedVideos")
    if not videos:
        return None
    first = videos[0]
    uri = nested_value(first, "video", "uri")
    return uri if isinstance(uri, str) else None


class VeoVisualAgent(VisualAgent):
    capabilities = AgentCapabilities(
        agent_type=AgentType.visual,
        provider_name="google-vertex-ai",
        supported_media_types=[MediaType.video],
        asynchronous_jobs=True,
        cancellation_supported=False,
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
        self._client_factory = client_factory or (lambda: create_vertex_client(config))
        self._client: Any | None = None
        self._clock = clock
        self._sleep = sleep_fn
        self._submissions: dict[str, tuple[str, ProviderJob]] = {}
        self._operations: dict[str, Any] = {}

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
            if request.shot_id is not None:
                raise ProviderError(ProviderErrorKind.invalid_request, "requested shot is not in the approved plan")
            shot = request.plan.shots[0]
        if not self.config.veo_output_gcs_uri or not self.config.veo_output_gcs_uri.startswith("gs://"):
            raise ProviderError(ProviderErrorKind.configuration, "VEO_OUTPUT_GCS_URI must be configured as a gs:// URI")
        prompt = (
            f"Cinematic shot: {shot.prompt}. Visual direction: {shot.visual.description}. "
            f"Camera: {shot.camera.shot_type}, {shot.camera.movement}, {shot.camera.framing}. "
            "Generate a short film shot; do not create an interactive 3D or walk-around environment."
        )
        duration = min(
            self.config.max_generation_duration_seconds,
            max(1, round(shot.timing.duration_ms / 1000)),
        )
        try:
            operation = self._client_or_create().models.generate_videos(
                model=self.config.veo_model,
                prompt=prompt,
                config={
                    "aspect_ratio": "16:9",
                    "duration_seconds": duration,
                    "output_gcs_uri": self.config.veo_output_gcs_uri,
                    "generate_audio": False,
                },
            )
            external_id = _operation_id(operation)
            if not external_id:
                raise ProviderError(ProviderErrorKind.malformed, "Veo submission did not return an operation identifier")
            job = provider_job(
                job_id=f"veo-{digest(request.idempotency.key)[:20]}",
                scene_id=request.plan.scene_id,
                agent_type=AgentType.visual,
                media_type=MediaType.video,
                idempotency=request.idempotency,
                provider="google-vertex-ai",
                model=self.config.veo_model,
                status=ProviderJobStatus.queued,
                provider_job_id=external_id,
            )
            self._submissions[request.idempotency.key] = (fingerprint, job)
            self._operations[external_id] = operation
            return job
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def poll(self, job: ProviderJob, request: VisualAgentRequest) -> VisualPollResult:
        if not job.provider_job_id:
            raise ProviderError(ProviderErrorKind.malformed, "provider job has no external operation identifier")
        try:
            operation = self._operations.get(job.provider_job_id, _operation_reference(job.provider_job_id))
            if not _operation_done(operation):
                operation = self._client_or_create().operations.get(operation)
            if not _operation_done(operation):
                next_job = job if job.status is ProviderJobStatus.running else job.transition(ProviderJobStatus.running)
                self._operations[job.provider_job_id] = operation
                return VisualPollResult(job=next_job)
            if _operation_cancelled(operation):
                next_job = job if job.status is ProviderJobStatus.cancelled else (
                    job.transition(ProviderJobStatus.running)
                    if job.status is ProviderJobStatus.queued
                    else job
                ).transition(ProviderJobStatus.cancelled)
                return VisualPollResult(job=next_job)
            if _operation_error(operation):
                running_job = job if job.status is ProviderJobStatus.running else job.transition(ProviderJobStatus.running)
                failure = ProviderError(ProviderErrorKind.terminal, "Veo generation failed")
                return VisualPollResult(job=running_job.transition(ProviderJobStatus.failed).model_copy(update={"failure": failure.failure_info()}))
            uri = _video_uri(operation)
            if not uri or not uri.startswith("gs://"):
                raise ProviderError(ProviderErrorKind.malformed, "Veo completed without a valid output URI")
            running_job = job if job.status is ProviderJobStatus.running else job.transition(ProviderJobStatus.running)
            succeeded_job = running_job.transition(ProviderJobStatus.succeeded)
            asset_id = f"asset-{digest(job.job_id)[:24]}"
            asset = AssetVersion(
                asset_version_id=asset_id,
                scene_id=request.plan.scene_id,
                asset_id=f"visual-{request.shot_id or request.plan.shots[0].shot_id}",
                version=1,
                media_type=MediaType.video,
                status=AssetVersionStatus.draft,
                artifact_uri=uri,
                provenance=ProvenanceMetadata(
                    source="provider",
                    provider="google-vertex-ai",
                    model=self.config.veo_model,
                    metadata={"external_operation_id": job.provider_job_id, "mime_type": "video/mp4"},
                ),
            )
            return VisualPollResult(job=succeeded_job, asset=asset)
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def generate(self, request: VisualAgentRequest) -> VisualAgentResult:
        job = self.submit(request)
        deadline = self._clock() + self.config.operation_timeout_seconds
        while True:
            result = self.poll(job, request)
            job = result.job
            if result.asset is not None:
                return VisualAgentResult(job=job, asset=result.asset)
            if job.status is ProviderJobStatus.failed:
                raise ProviderError(ProviderErrorKind.terminal, "Veo generation failed")
            if job.status is ProviderJobStatus.cancelled:
                raise ProviderError(ProviderErrorKind.terminal, "Veo generation was cancelled")
            if self._clock() >= deadline:
                raise ProviderError(ProviderErrorKind.timeout, "Veo operation polling timed out", retryable=True)
            self._sleep(self.config.poll_interval_seconds)

    def cancel(self, job_id: str) -> None:
        del job_id

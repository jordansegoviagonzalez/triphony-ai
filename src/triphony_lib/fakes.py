"""Deterministic, provider-free implementations of the four agent interfaces."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, TypeVar, cast

from triphony_lib.agents import (
    IdempotencyConflictError,
    NonRetryableAgentError,
    RetryableAgentError,
)
from triphony_lib.domain import (
    AgentCapabilities,
    AgentType,
    AssetVersion,
    AssetVersionStatus,
    AudioAgentRequest,
    AudioAgentResult,
    AudioDirection,
    CameraDirection,
    FailureMode,
    IdempotencyInfo,
    MediaType,
    NarrativeDirectorRequest,
    NarrativeDirectorResult,
    NarrativeDirection,
    ProviderJob,
    ProviderJobStatus,
    ProvenanceMetadata,
    QAAgentRequest,
    QAAgentResult,
    QAEvaluation,
    QAFinding,
    QARecommendation,
    QAStatus,
    ScenePlan,
    Shot,
    ShotTiming,
    VisualAgentRequest,
    VisualAgentResult,
    VisualDirection,
)


_FIXED_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)
T = TypeVar("T")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _FakeAgentBase:
    def __init__(self) -> None:
        self._results: dict[str, tuple[str, object]] = {}
        self._cancelled_jobs: set[str] = set()

    def _prepare(self, request: Any) -> tuple[str, object | None]:
        fingerprint = _digest(request.model_dump(mode="json"))
        previous = self._results.get(request.idempotency.key)
        if previous and previous[0] != fingerprint:
            raise IdempotencyConflictError(
                f"idempotency key {request.idempotency.key!r} was reused for a different request"
            )
        self._raise_controlled_failure(request.failure_mode)
        return fingerprint, previous[1] if previous else None

    def _remember(self, request: Any, fingerprint: str, result: T) -> T:
        self._results[request.idempotency.key] = (fingerprint, result)
        return result

    @staticmethod
    def _raise_controlled_failure(failure_mode: FailureMode) -> None:
        if failure_mode == "retryable":
            raise RetryableAgentError("controlled retryable fake-agent failure")
        if failure_mode == "fatal":
            raise NonRetryableAgentError("controlled non-retryable fake-agent failure")

    @staticmethod
    def _job(
        *,
        job_id: str,
        scene_id: str,
        agent_type: AgentType,
        media_type: MediaType,
        idempotency: IdempotencyInfo,
    ) -> ProviderJob:
        provider_job_id = f"mock-{job_id}"
        provenance = ProvenanceMetadata(
            source="fake",
            provider="deterministic-mock",
            model="phase2-contracts",
            model_version="1",
        )
        return ProviderJob(
            job_id=job_id,
            scene_id=scene_id,
            agent_type=agent_type,
            media_type=media_type,
            status=ProviderJobStatus.succeeded,
            idempotency=idempotency,
            provenance=provenance,
            provider_job_id=provider_job_id,
            created_at=_FIXED_TIME,
            updated_at=_FIXED_TIME,
        )

    @staticmethod
    def _asset_provenance(media_type: MediaType) -> ProvenanceMetadata:
        return ProvenanceMetadata(
            source="fake",
            provider="deterministic-mock",
            model="phase2-contracts",
            model_version="1",
            metadata={"media_type": media_type.value},
        )

    def cancel(self, job_id: str) -> None:
        self._cancelled_jobs.add(job_id)


class FakeNarrativeDirector(_FakeAgentBase):
    capabilities = AgentCapabilities(
        agent_type=AgentType.narrative_director,
        provider_name="deterministic-mock",
        supported_media_types=[MediaType.narrative],
        asynchronous_jobs=False,
        cancellation_supported=True,
        deterministic=True,
    )

    def plan(self, request: NarrativeDirectorRequest) -> NarrativeDirectorResult:
        fingerprint, cached = self._prepare(request)
        if cached is not None:
            return cast(NarrativeDirectorResult, cached)

        plan_digest = _digest({"scene_id": request.scene_id, "prompt": request.user_prompt})
        shot_id = f"shot-{plan_digest[:16]}"
        shot = Shot(
            shot_id=shot_id,
            order=1,
            prompt=request.user_prompt,
            timing=ShotTiming(start_ms=0, duration_ms=3000),
            narration=NarrativeDirection(
                summary=f"A concise cinematic interpretation of {request.user_prompt}",
                tone="cinematic",
                narration_text=request.user_prompt,
            ),
            visual=VisualDirection(
                description=request.user_prompt,
                palette="neon blue and magenta",
                lighting="soft atmospheric light",
            ),
            camera=CameraDirection(
                shot_type="wide",
                movement="slow push-in",
                framing="balanced center composition",
            ),
            audio=AudioDirection(
                music="minimal cinematic pulse",
                ambience="subtle room tone",
                sound_effects=["soft transition", "distant atmosphere"],
            ),
        )
        plan = ScenePlan(
            plan_id=f"plan-{plan_digest[:16]}",
            scene_id=request.scene_id,
            user_prompt=request.user_prompt,
            shots=[shot],
            output_requirements=request.output_requirements,
            constraints=request.constraints,
        )
        job = self._job(
            job_id=f"job-{plan_digest[16:32]}",
            scene_id=request.scene_id,
            agent_type=AgentType.narrative_director,
            media_type=MediaType.narrative,
            idempotency=request.idempotency,
        )
        return self._remember(request, fingerprint, NarrativeDirectorResult(job=job, plan=plan))


class FakeVisualAgent(_FakeAgentBase):
    capabilities = AgentCapabilities(
        agent_type=AgentType.visual,
        provider_name="deterministic-mock",
        supported_media_types=[MediaType.video, MediaType.image],
        asynchronous_jobs=True,
        cancellation_supported=True,
        deterministic=True,
    )

    def generate(self, request: VisualAgentRequest) -> VisualAgentResult:
        fingerprint, cached = self._prepare(request)
        if cached is not None:
            return cast(VisualAgentResult, cached)

        shot = next(
            (item for item in request.plan.shots if item.shot_id == request.shot_id),
            request.plan.shots[0] if request.shot_id is None else None,
        )
        if shot is None:
            raise NonRetryableAgentError(f"shot {request.shot_id!r} is not in the approved plan")
        result_digest = _digest({"plan": request.plan.plan_id, "shot": shot.shot_id})
        job = self._job(
            job_id=f"job-{result_digest[:16]}",
            scene_id=request.plan.scene_id,
            agent_type=AgentType.visual,
            media_type=MediaType.video,
            idempotency=request.idempotency,
        )
        asset = AssetVersion(
            asset_version_id=f"asset-{result_digest[16:32]}",
            scene_id=request.plan.scene_id,
            asset_id=f"visual-{shot.shot_id}",
            version=1,
            media_type=MediaType.video,
            status=AssetVersionStatus.approved,
            artifact_uri=f"mock://video/{result_digest}.mp4",
            provenance=self._asset_provenance(MediaType.video),
            created_at=_FIXED_TIME,
        )
        return self._remember(request, fingerprint, VisualAgentResult(job=job, asset=asset))


class FakeAudioAgent(_FakeAgentBase):
    capabilities = AgentCapabilities(
        agent_type=AgentType.audio,
        provider_name="deterministic-mock",
        supported_media_types=[
            MediaType.narration,
            MediaType.music,
            MediaType.ambience,
            MediaType.sound_effect,
        ],
        asynchronous_jobs=True,
        cancellation_supported=True,
        deterministic=True,
    )

    def generate(self, request: AudioAgentRequest) -> AudioAgentResult:
        fingerprint, cached = self._prepare(request)
        if cached is not None:
            return cast(AudioAgentResult, cached)

        result_digest = _digest({"plan": request.plan.plan_id, "audio": True})
        job = self._job(
            job_id=f"job-{result_digest[:16]}",
            scene_id=request.plan.scene_id,
            agent_type=AgentType.audio,
            media_type=MediaType.audio,
            idempotency=request.idempotency,
        )
        assets: list[AssetVersion] = []
        for index, media_type in enumerate(
            [MediaType.narration, MediaType.music, MediaType.ambience, MediaType.sound_effect],
            start=1,
        ):
            assets.append(
                AssetVersion(
                    asset_version_id=f"asset-{result_digest[index * 8 : index * 8 + 16]}",
                    scene_id=request.plan.scene_id,
                    asset_id=f"audio-{media_type.value}",
                    version=1,
                    media_type=media_type,
                    status=AssetVersionStatus.approved,
                    artifact_uri=f"mock://audio/{result_digest}-{media_type.value}.wav",
                    content_text=(
                        request.plan.shots[0].narration.narration_text
                        if media_type is MediaType.narration
                        else None
                    ),
                    provenance=self._asset_provenance(media_type),
                    created_at=_FIXED_TIME,
                )
            )
        return self._remember(request, fingerprint, AudioAgentResult(job=job, assets=assets))


class FakeQAAgent(_FakeAgentBase):
    capabilities = AgentCapabilities(
        agent_type=AgentType.qa,
        provider_name="deterministic-mock",
        supported_media_types=[MediaType.video, MediaType.audio, MediaType.narrative],
        asynchronous_jobs=False,
        cancellation_supported=True,
        deterministic=True,
    )

    def evaluate(self, request: QAAgentRequest) -> QAAgentResult:
        fingerprint, cached = self._prepare(request)
        if cached is not None:
            return cast(QAAgentResult, cached)

        result_digest = _digest(
            {"plan": request.plan.plan_id, "assets": [asset.asset_version_id for asset in request.assets]}
        )
        findings = [
            QAFinding(
                code="asset_metadata_present",
                message="All supplied asset versions include provider-neutral metadata.",
                severity="info",
            )
        ]
        job = self._job(
            job_id=f"job-{result_digest[:16]}",
            scene_id=request.plan.scene_id,
            agent_type=AgentType.qa,
            media_type=MediaType.narrative,
            idempotency=request.idempotency,
        )
        evaluation = QAEvaluation(
            evaluation_id=f"qa-{result_digest[16:32]}",
            scene_id=request.plan.scene_id,
            status=QAStatus.passed,
            score=1.0,
            recommendation=QARecommendation.approve,
            findings=findings,
            evaluated_asset_version_ids=[asset.asset_version_id for asset in request.assets],
            created_at=_FIXED_TIME,
        )
        return self._remember(request, fingerprint, QAAgentResult(job=job, evaluation=evaluation))

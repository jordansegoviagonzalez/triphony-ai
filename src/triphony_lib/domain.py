"""Provider-neutral domain contracts for the Phase 2 workflow foundation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractError(ValueError):
    """Base error raised when a domain contract cannot be constructed."""


class InvalidTimingError(ContractError):
    """Raised when shot timing is invalid or out of order."""


class InvalidStateTransitionError(ContractError):
    """Raised when a lifecycle state transition is not allowed."""


class UnsupportedMediaSpecificationError(ContractError):
    """Raised when an output format is not supported by the domain contract."""


class AgentType(str, Enum):
    narrative_director = "narrative_director"
    visual = "visual"
    audio = "audio"
    qa = "qa"


class MediaType(str, Enum):
    narrative = "narrative"
    video = "video"
    image = "image"
    narration = "narration"
    music = "music"
    ambience = "ambience"
    sound_effect = "sound_effect"
    audio = "audio"


class ProviderJobStatus(str, Enum):
    created = "created"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ProviderAttemptStatus(str, Enum):
    started = "started"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class AssetVersionStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class QAStatus(str, Enum):
    passed = "passed"
    failed = "failed"


class QARecommendation(str, Enum):
    approve = "approve"
    retry = "retry"
    reject = "reject"


class FinalRenderStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class WorkflowState(str, Enum):
    queued = "queued"
    planning = "planning"
    generating = "generating"
    technical_qa = "technical_qa"
    agent_qa = "agent_qa"
    regenerating = "regenerating"
    assembling = "assembling"
    final_qa = "final_qa"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FailureCategory(str, Enum):
    validation = "validation"
    provider = "provider"
    timeout = "timeout"
    media = "media"
    ownership = "ownership"
    internal = "internal"


FailureMode = Literal["none", "retryable", "fatal"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FailureInfo(DomainModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    category: FailureCategory
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class IdempotencyInfo(DomainModel):
    key: str = Field(min_length=8, max_length=255)
    request_hash: str = Field(min_length=8, max_length=128)


class ProvenanceMetadata(DomainModel):
    source: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    model: str | None = Field(default=None, max_length=255)
    model_version: str | None = Field(default=None, max_length=255)
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NarrativeDirection(DomainModel):
    summary: str = Field(min_length=1, max_length=2000)
    tone: str = Field(min_length=1, max_length=255)
    narration_text: str | None = Field(default=None, max_length=4000)


class VisualDirection(DomainModel):
    description: str = Field(min_length=1, max_length=4000)
    palette: str = Field(min_length=1, max_length=255)
    lighting: str = Field(min_length=1, max_length=255)


class CameraDirection(DomainModel):
    shot_type: str = Field(min_length=1, max_length=128)
    movement: str = Field(min_length=1, max_length=255)
    framing: str = Field(min_length=1, max_length=255)


class AudioDirection(DomainModel):
    music: str = Field(min_length=1, max_length=1000)
    ambience: str = Field(min_length=1, max_length=1000)
    sound_effects: list[str] = Field(min_length=1, max_length=32)


class ShotTiming(DomainModel):
    """All scene timing uses integer milliseconds."""

    start_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0, le=86_400_000)

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms


class OutputFormatRequirements(DomainModel):
    media_type: MediaType
    mime_type: str = Field(min_length=1, max_length=128)
    container: str | None = Field(default=None, max_length=64)
    video_codec: str | None = Field(default=None, max_length=64)
    audio_codec: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_media_specification(self) -> "OutputFormatRequirements":
        supported = {
            MediaType.narrative: {"text/plain", "application/json"},
            MediaType.video: {"video/mp4"},
            MediaType.image: {"image/png", "image/jpeg"},
            MediaType.narration: {"audio/wav", "audio/mpeg"},
            MediaType.music: {"audio/wav", "audio/mpeg"},
            MediaType.ambience: {"audio/wav", "audio/mpeg"},
            MediaType.sound_effect: {"audio/wav", "audio/mpeg"},
            MediaType.audio: {"audio/wav", "audio/mpeg"},
        }
        if self.mime_type not in supported[self.media_type]:
            raise UnsupportedMediaSpecificationError(
                f"{self.media_type.value} does not support {self.mime_type}"
            )
        if self.media_type is MediaType.video and not self.container:
            raise UnsupportedMediaSpecificationError("video output requires a container")
        return self


class Shot(DomainModel):
    shot_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=4000)
    timing: ShotTiming
    narration: NarrativeDirection
    visual: VisualDirection
    camera: CameraDirection
    audio: AudioDirection


class ScenePlan(DomainModel):
    contract_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    plan_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    user_prompt: str = Field(min_length=3, max_length=4000)
    shots: list[Shot] = Field(min_length=1, max_length=256)
    output_requirements: list[OutputFormatRequirements] = Field(min_length=1, max_length=32)
    constraints: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shot_sequence(self) -> "ScenePlan":
        expected_orders = list(range(1, len(self.shots) + 1))
        actual_orders = [shot.order for shot in self.shots]
        if actual_orders != expected_orders:
            raise InvalidTimingError("shots must be ordered consecutively from one")
        for previous, current in zip(self.shots, self.shots[1:]):
            if current.timing.start_ms < previous.timing.start_ms:
                raise InvalidTimingError("shot start times must be ordered")
            if current.timing.start_ms < previous.timing.end_ms:
                raise InvalidTimingError("shots may not overlap")
        return self

    @property
    def total_duration_ms(self) -> int:
        return max(shot.timing.end_ms for shot in self.shots)


class ProviderJob(DomainModel):
    job_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    agent_type: AgentType
    media_type: MediaType
    status: ProviderJobStatus = ProviderJobStatus.created
    idempotency: IdempotencyInfo
    provenance: ProvenanceMetadata
    provider_job_id: str | None = Field(default=None, max_length=255)
    failure: FailureInfo | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    _allowed_transitions = {
        ProviderJobStatus.created: {ProviderJobStatus.queued, ProviderJobStatus.cancelled},
        ProviderJobStatus.queued: {
            ProviderJobStatus.running,
            ProviderJobStatus.failed,
            ProviderJobStatus.cancelled,
        },
        ProviderJobStatus.running: {
            ProviderJobStatus.succeeded,
            ProviderJobStatus.failed,
            ProviderJobStatus.cancelled,
        },
        ProviderJobStatus.succeeded: set(),
        ProviderJobStatus.failed: set(),
        ProviderJobStatus.cancelled: set(),
    }

    def transition(self, next_status: ProviderJobStatus) -> "ProviderJob":
        if next_status not in self._allowed_transitions[self.status]:
            raise InvalidStateTransitionError(
                f"cannot transition provider job from {self.status.value} to {next_status.value}"
            )
        return self.model_copy(update={"status": next_status, "updated_at": utc_now()})


class ProviderJobAttempt(DomainModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    attempt_number: int = Field(ge=1)
    status: ProviderAttemptStatus
    provider_job_id: str | None = Field(default=None, max_length=255)
    failure: FailureInfo | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class AssetVersion(DomainModel):
    """An immutable generated asset version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_version_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    asset_id: str | None = Field(default=None, max_length=128)
    version: int = Field(ge=1)
    media_type: MediaType
    status: AssetVersionStatus
    artifact_uri: str | None = Field(default=None, max_length=1000)
    content_text: str | None = None
    provenance: ProvenanceMetadata
    created_at: datetime = Field(default_factory=utc_now)


class QAFinding(DomainModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    severity: Literal["info", "warning", "error"]
    shot_id: str | None = Field(default=None, max_length=128)


class QAEvaluation(DomainModel):
    evaluation_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    status: QAStatus
    score: float = Field(ge=0.0, le=1.0)
    recommendation: QARecommendation
    findings: list[QAFinding] = Field(default_factory=list, max_length=256)
    evaluated_asset_version_ids: list[str] = Field(min_length=1, max_length=256)
    created_at: datetime = Field(default_factory=utc_now)


class FinalRender(DomainModel):
    render_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    status: FinalRenderStatus
    artifact_uri: str | None = Field(default=None, max_length=1000)
    mime_type: str = Field(default="video/mp4", pattern=r"^video/mp4$")
    duration_ms: int | None = Field(default=None, gt=0)
    source_asset_version_ids: list[str] = Field(min_length=1, max_length=256)
    failure: FailureInfo | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AgentRequest(DomainModel):
    idempotency: IdempotencyInfo
    failure_mode: FailureMode = "none"


class NarrativeDirectorRequest(AgentRequest):
    scene_id: str = Field(min_length=1, max_length=128)
    user_prompt: str = Field(min_length=3, max_length=4000)
    output_requirements: list[OutputFormatRequirements] = Field(
        default_factory=lambda: [
            OutputFormatRequirements(media_type=MediaType.narrative, mime_type="text/plain"),
            OutputFormatRequirements(
                media_type=MediaType.video,
                mime_type="video/mp4",
                container="mp4",
                video_codec="h264",
            ),
            OutputFormatRequirements(media_type=MediaType.audio, mime_type="audio/wav"),
        ]
    )
    constraints: dict[str, Any] = Field(default_factory=dict)


class VisualAgentRequest(AgentRequest):
    plan: ScenePlan
    shot_id: str | None = Field(default=None, max_length=128)


class AudioAgentRequest(AgentRequest):
    plan: ScenePlan


class QAAgentRequest(AgentRequest):
    plan: ScenePlan
    assets: list[AssetVersion] = Field(min_length=1, max_length=256)


class AgentCapabilities(DomainModel):
    agent_type: AgentType
    provider_name: str = Field(min_length=1, max_length=128)
    supported_media_types: list[MediaType] = Field(min_length=1, max_length=16)
    asynchronous_jobs: bool
    cancellation_supported: bool
    deterministic: bool


class NarrativeDirectorResult(DomainModel):
    job: ProviderJob
    plan: ScenePlan


class VisualAgentResult(DomainModel):
    job: ProviderJob
    asset: AssetVersion


class AudioAgentResult(DomainModel):
    job: ProviderJob
    assets: list[AssetVersion] = Field(min_length=1, max_length=32)


class QAAgentResult(DomainModel):
    job: ProviderJob
    evaluation: QAEvaluation

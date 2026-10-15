from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, String, DateTime, Enum, Integer, ForeignKey, Text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    scenes: Mapped[list["Scene"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class SceneStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class WorkflowStateRecord(str, enum.Enum):
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


class AssetType(str, enum.Enum):
    narrative = "narrative"
    visual = "visual"
    soundtrack = "soundtrack"


class AssetStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ScenePlanStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    superseded = "superseded"


class ProviderJobRecordStatus(str, enum.Enum):
    created = "created"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ProviderJobAttemptRecordStatus(str, enum.Enum):
    started = "started"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class AssetVersionRecordStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class QARecordStatus(str, enum.Enum):
    passed = "passed"
    failed = "failed"


class QARecordRecommendation(str, enum.Enum):
    approve = "approve"
    retry = "retry"
    reject = "reject"


class FinalRenderRecordStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True) # Nullable for backward compatibility with existing scenes
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SceneStatus] = mapped_column(Enum(SceneStatus), default=SceneStatus.queued, nullable=False)
    workflow_state: Mapped[WorkflowStateRecord] = mapped_column(
        Enum(WorkflowStateRecord), default=WorkflowStateRecord.queued, nullable=False
    )
    workflow_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    workflow_error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="scenes")
    assets: Mapped[list["Asset"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    scene_plans: Mapped[list["ScenePlanRecord"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    provider_jobs: Mapped[list["ProviderJobRecord"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    asset_versions: Mapped[list["AssetVersionRecord"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    qa_evaluations: Mapped[list["QAEvaluationRecord"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    final_renders: Mapped[list["FinalRenderRecord"]] = relationship(back_populates="scene", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_scenes_created_at", "created_at"),
        Index("ix_scenes_workflow_state", "workflow_state"),
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True, nullable=False)

    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[AssetStatus] = mapped_column(Enum(AssetStatus), default=AssetStatus.pending, nullable=False)

    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    scene: Mapped["Scene"] = relationship(back_populates="assets")

    __table_args__ = (
        Index("ix_assets_scene_type", "scene_id", "asset_type"),
    )


class ScenePlanRecord(Base):
    __tablename__ = "scene_plans"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ScenePlanStatus] = mapped_column(Enum(ScenePlanStatus), nullable=False)
    output_requirements: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    scene: Mapped["Scene"] = relationship(back_populates="scene_plans")
    shots: Mapped[list["ShotRecord"]] = relationship(back_populates="scene_plan", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("scene_id", "version", name="uq_scene_plans_scene_version"),
        Index("ix_scene_plans_scene_status", "scene_id", "status"),
    )


class ShotRecord(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_plan_id: Mapped[str] = mapped_column(ForeignKey("scene_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    shot_order: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_direction: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    visual_direction: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    camera_direction: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    audio_direction: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    scene_plan: Mapped["ScenePlanRecord"] = relationship(back_populates="shots")

    __table_args__ = (
        UniqueConstraint("scene_plan_id", "shot_order", name="uq_shots_plan_order"),
        Index("ix_shots_plan_timing", "scene_plan_id", "start_ms"),
    )


class ProviderJobRecord(Base):
    __tablename__ = "provider_jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ProviderJobRecordStatus] = mapped_column(Enum(ProviderJobRecordStatus), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    scene: Mapped["Scene"] = relationship(back_populates="provider_jobs")
    attempts: Mapped[list["ProviderJobAttemptRecord"]] = relationship(back_populates="provider_job", cascade="all, delete-orphan")


class ProviderJobAttemptRecord(Base):
    __tablename__ = "provider_job_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_job_id: Mapped[str] = mapped_column(ForeignKey("provider_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ProviderJobAttemptRecordStatus] = mapped_column(Enum(ProviderJobAttemptRecordStatus), nullable=False)
    provider_job_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    provider_job: Mapped["ProviderJobRecord"] = relationship(back_populates="attempts")

    __table_args__ = (
        UniqueConstraint("provider_job_id", "attempt_number", name="uq_provider_job_attempt_number"),
    )


class AssetVersionRecord(Base):
    __tablename__ = "asset_versions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AssetVersionRecordStatus] = mapped_column(Enum(AssetVersionRecordStatus), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("asset_versions.id", ondelete="SET NULL"), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # ``metadata`` is reserved by SQLAlchemy's declarative base; keep the
    # database column name while using a safe Python attribute name.
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    scene: Mapped["Scene"] = relationship(back_populates="asset_versions")
    asset: Mapped[Asset | None] = relationship()

    __table_args__ = (
        UniqueConstraint("scene_id", "media_type", "version", name="uq_asset_versions_scene_media_version"),
        Index("ix_asset_versions_scene_status", "scene_id", "status"),
        Index("ix_asset_versions_parent_id", "parent_id"),
    )


class QAEvaluationRecord(Base):
    __tablename__ = "qa_evaluations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[QARecordStatus] = mapped_column(Enum(QARecordStatus), nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)
    recommendation: Mapped[QARecordRecommendation] = mapped_column(Enum(QARecordRecommendation), nullable=False)
    evaluated_asset_version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    scene: Mapped["Scene"] = relationship(back_populates="qa_evaluations")
    findings: Mapped[list["QAFindingRecord"]] = relationship(back_populates="evaluation", cascade="all, delete-orphan")


class QAFindingRecord(Base):
    __tablename__ = "qa_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("qa_evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    shot_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    evaluation: Mapped["QAEvaluationRecord"] = relationship(back_populates="findings")


class FinalRenderRecord(Base):
    __tablename__ = "final_renders"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[FinalRenderRecordStatus] = mapped_column(Enum(FinalRenderRecordStatus), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_asset_version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    failure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    scene: Mapped["Scene"] = relationship(back_populates="final_renders")

    __table_args__ = (
        UniqueConstraint("scene_id", "version", name="uq_final_renders_scene_version"),
    )


class OutboxEventStatus(str, enum.Enum):
    pending = "pending"
    published = "published"
    failed = "failed"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[OutboxEventStatus] = mapped_column(Enum(OutboxEventStatus), default=OutboxEventStatus.pending, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (Index("ix_outbox_events_dispatch", "status", "available_at"),)


class DeadLetterRecord(Base):
    __tablename__ = "dead_letters"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_job_id: Mapped[str | None] = mapped_column(ForeignKey("provider_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(128), nullable=False)
    failure_code: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    replay_eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    safe_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (Index("ix_audit_events_resource", "resource_type", "resource_id"),)

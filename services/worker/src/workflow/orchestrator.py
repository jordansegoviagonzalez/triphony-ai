"""Phase 4 durable orchestration tasks and persistence boundary."""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

from celery import chord, group
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from api.models import (
    Asset, AssetStatus, AssetType, AssetVersionRecord, AssetVersionRecordStatus,
    FinalRenderRecord, FinalRenderRecordStatus, ProviderJobAttemptRecord,
    ProviderJobAttemptRecordStatus, ProviderJobRecord, ProviderJobRecordStatus,
    QAEvaluationRecord, QAFindingRecord, QARecordRecommendation, QARecordStatus,
    Scene, ScenePlanRecord, ScenePlanStatus, SceneStatus, ShotRecord,
    WorkflowStateRecord,
)
from api.governance import record_audit, RedisGovernance
from api.db import engine
from api.settings import settings
from providers.factory import build_provider_bundle
from shared.celery_app import celery_app
from triphony_lib.domain import (
    AgentType, AssetVersion as DomainAssetVersion, AssetVersionStatus, AudioAgentRequest,
    IdempotencyInfo, MediaType, NarrativeDirectorRequest, QAAgentRequest, QARecommendation,
    QAStatus, ScenePlan, Shot, ShotTiming, NarrativeDirection, VisualDirection,
    CameraDirection, AudioDirection, VisualAgentRequest, WorkflowState,
)
from workflow.media import MediaValidationError, assemble_mp4, validate_media, write_fake_audio, write_fake_video
from triphony_lib.storage import ArtifactStoreError, LocalArtifactStore, S3ArtifactStore
from triphony_lib.observability import current_correlation_id, json_log, metric_inc, span


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
ARTIFACT_ROOT = pathlib.Path(settings.artifacts_dir)
MAX_REGENERATIONS = 2


def _artifact_store():
    if settings.artifact_storage_backend == "s3":
        return S3ArtifactStore(
            bucket=settings.s3_bucket or "", region=settings.aws_region, prefix=settings.s3_key_prefix,
            encryption=settings.s3_server_side_encryption, kms_key_id=settings.s3_kms_key_id,
            max_object_size=settings.max_artifact_bytes, multipart_threshold_bytes=settings.s3_multipart_threshold_bytes,
        )
    return LocalArtifactStore(ARTIFACT_ROOT, max_object_size=settings.max_artifact_bytes)


def _with_correlation(signature):
    correlation = current_correlation_id()
    return signature.set(headers={"correlation_id": correlation}) if correlation else signature


_ALLOWED_WORKFLOW_TRANSITIONS: dict[WorkflowStateRecord, set[WorkflowStateRecord]] = {
    WorkflowStateRecord.queued: {WorkflowStateRecord.planning, WorkflowStateRecord.failed, WorkflowStateRecord.cancelled},
    WorkflowStateRecord.planning: {WorkflowStateRecord.generating, WorkflowStateRecord.failed, WorkflowStateRecord.cancelled},
    WorkflowStateRecord.generating: {WorkflowStateRecord.technical_qa, WorkflowStateRecord.regenerating, WorkflowStateRecord.failed, WorkflowStateRecord.cancelled},
    WorkflowStateRecord.technical_qa: {WorkflowStateRecord.agent_qa, WorkflowStateRecord.regenerating, WorkflowStateRecord.failed},
    WorkflowStateRecord.agent_qa: {WorkflowStateRecord.regenerating, WorkflowStateRecord.assembling, WorkflowStateRecord.failed},
    WorkflowStateRecord.regenerating: {WorkflowStateRecord.generating, WorkflowStateRecord.failed},
    WorkflowStateRecord.assembling: {WorkflowStateRecord.final_qa, WorkflowStateRecord.failed},
    WorkflowStateRecord.final_qa: {WorkflowStateRecord.completed, WorkflowStateRecord.failed},
    WorkflowStateRecord.completed: {WorkflowStateRecord.regenerating},
    WorkflowStateRecord.failed: {WorkflowStateRecord.regenerating},
    WorkflowStateRecord.cancelled: set(),
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _transition(scene: Scene, next_state: WorkflowStateRecord) -> None:
    current = scene.workflow_state or WorkflowStateRecord.queued
    if current == next_state:
        return
    if next_state not in _ALLOWED_WORKFLOW_TRANSITIONS[current]:
        raise RuntimeError(f"invalid workflow transition from {current.value} to {next_state.value}")
    scene.workflow_state = next_state
    if next_state is WorkflowStateRecord.completed:
        scene.status = SceneStatus.done
    elif next_state in {WorkflowStateRecord.failed, WorkflowStateRecord.cancelled}:
        scene.status = SceneStatus.failed
    else:
        scene.status = SceneStatus.queued if next_state is WorkflowStateRecord.queued else SceneStatus.running


def _fail(db, scene: Scene, message: str, code: str = "workflow_failed") -> None:
    scene.workflow_error = {"code": code, "message": message[:500]}
    scene.status = SceneStatus.failed
    scene.workflow_state = WorkflowStateRecord.failed
    record_audit(
        db,
        actor_user_id=scene.user_id,
        event_type="workflow_failure",
        resource_type="scene",
        resource_id=scene.id,
        correlation=scene.id,
        outcome="failed",
        metadata={"code": code},
    )
    db.commit()
    RedisGovernance().release_concurrent(scene.user_id)
    metric_inc("triphony.workflow.failures", code=code)


def _create_dead_letter(scene_id: str, task_type: str, code: str, attempt: int = 1) -> None:
    try:
        from workflow.outbox import create_dead_letter

        create_dead_letter(
            scene_id=scene_id,
            provider_job_id=None,
            task_type=task_type,
            failure_code=code,
            attempt_count=attempt,
            correlation_id=scene_id,
            replay_eligible=True,
            details={"source": "worker_task"},
        )
        metric_inc("triphony.dead_letters.created", task_type=task_type)
    except Exception as error:
        json_log(__import__("logging").getLogger("triphony.worker"), __import__("logging").ERROR, "dead_letter_creation_failed", task_type=task_type, error_type=type(error).__name__)


def _plan_from_record(record: ScenePlanRecord) -> ScenePlan:
    shots = [
        Shot(
            shot_id=shot.id,
            order=shot.shot_order,
            prompt=shot.prompt,
            timing=ShotTiming(start_ms=shot.start_ms, duration_ms=shot.duration_ms),
            narration=NarrativeDirection.model_validate(shot.narrative_direction),
            visual=VisualDirection.model_validate(shot.visual_direction),
            camera=CameraDirection.model_validate(shot.camera_direction),
            audio=AudioDirection.model_validate(shot.audio_direction),
        )
        for shot in sorted(record.shots, key=lambda value: value.shot_order)
    ]
    return ScenePlan(
        contract_version=record.contract_version,
        plan_id=record.id,
        scene_id=record.scene_id,
        user_prompt=record.user_prompt,
        shots=shots,
        output_requirements=record.output_requirements,
        constraints=record.constraints,
    )


def _persist_job(db, job, idempotency_key: str) -> ProviderJobRecord:
    record = db.query(ProviderJobRecord).filter(ProviderJobRecord.idempotency_key == idempotency_key).first()
    if record is None:
        record = ProviderJobRecord(
            id=job.job_id,
            scene_id=job.scene_id,
            agent_type=job.agent_type.value,
            media_type=job.media_type.value,
            status=ProviderJobRecordStatus(job.status.value),
            idempotency_key=idempotency_key,
            provider_name=job.provenance.provider,
            model_version=job.provenance.model_version or job.provenance.model,
            provider_job_id=job.provider_job_id,
            provenance=job.provenance.model_dump(mode="json"),
        )
        db.add(record)
        db.flush()
        db.add(ProviderJobAttemptRecord(
            provider_job_id=record.id,
            attempt_number=1,
            status=ProviderJobAttemptRecordStatus.succeeded if job.status.value == "succeeded" else ProviderJobAttemptRecordStatus.started,
            provider_job_identifier=job.provider_job_id,
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None) if job.status.value == "succeeded" else None,
        ))
    else:
        previous_provider_job_id = record.provider_job_id
        record.status = ProviderJobRecordStatus(job.status.value)
        record.provider_job_id = job.provider_job_id or record.provider_job_id
        if job.provider_job_id and job.provider_job_id != previous_provider_job_id:
            latest_attempt = max((attempt.attempt_number for attempt in record.attempts), default=0)
            db.add(ProviderJobAttemptRecord(
                provider_job_id=record.id,
                attempt_number=latest_attempt + 1,
                status=ProviderJobAttemptRecordStatus.succeeded if job.status.value == "succeeded" else ProviderJobAttemptRecordStatus.started,
                provider_job_identifier=job.provider_job_id,
                completed_at=datetime.now(timezone.utc).replace(tzinfo=None) if job.status.value == "succeeded" else None,
            ))
            record.provider_name = job.provenance.provider
            record.model_version = job.provenance.model_version or job.provenance.model
            record.provenance = job.provenance.model_dump(mode="json")
    return record


def _persist_plan(db, scene: Scene, plan: ScenePlan) -> ScenePlanRecord:
    existing = db.query(ScenePlanRecord).filter(ScenePlanRecord.scene_id == scene.id, ScenePlanRecord.version == 1).first()
    if existing:
        return existing
    record = ScenePlanRecord(
        id=plan.plan_id,
        scene_id=scene.id,
        version=1,
        contract_version=plan.contract_version,
        user_prompt=plan.user_prompt,
        status=ScenePlanStatus.approved,
        output_requirements=[item.model_dump(mode="json") for item in plan.output_requirements],
        constraints=plan.constraints,
    )
    db.add(record)
    for shot in plan.shots:
        db.add(ShotRecord(
            id=shot.shot_id,
            scene_plan_id=plan.plan_id,
            shot_order=shot.order,
            start_ms=shot.timing.start_ms,
            duration_ms=shot.timing.duration_ms,
            prompt=shot.prompt,
            narrative_direction=shot.narration.model_dump(mode="json"),
            visual_direction=shot.visual.model_dump(mode="json"),
            camera_direction=shot.camera.model_dump(mode="json"),
            audio_direction=shot.audio.model_dump(mode="json"),
        ))
    return record


def _create_plan_revision(db, scene: Scene, source: ScenePlanRecord) -> ScenePlanRecord:
    """Create an immutable plan revision after a global narrative rejection.

    A new plan owns new shot identifiers so that dependent visual assets cannot
    be mistaken for outputs of the rejected narrative plan. Existing versions
    remain queryable as rejected lineage rather than being deleted.
    """
    version = (db.query(func.max(ScenePlanRecord.version)).filter(ScenePlanRecord.scene_id == scene.id).scalar() or 0) + 1
    plan_id = f"plan-{_digest(f'{scene.id}:{version}:{source.id}')[:28]}"
    source.status = ScenePlanStatus.superseded
    record = ScenePlanRecord(
        id=plan_id,
        scene_id=scene.id,
        version=version,
        contract_version=source.contract_version,
        user_prompt=source.user_prompt,
        status=ScenePlanStatus.approved,
        output_requirements=list(source.output_requirements or []),
        constraints=dict(source.constraints or {}),
    )
    db.add(record)
    db.flush()
    for shot in sorted(source.shots, key=lambda item: item.shot_order):
        db.add(ShotRecord(
            id=f"{shot.id}-v{version}",
            scene_plan_id=record.id,
            shot_order=shot.shot_order,
            start_ms=shot.start_ms,
            duration_ms=shot.duration_ms,
            prompt=shot.prompt,
            narrative_direction=dict(shot.narrative_direction or {}),
            visual_direction=dict(shot.visual_direction or {}),
            camera_direction=dict(shot.camera_direction or {}),
            audio_direction=dict(shot.audio_direction or {}),
        ))
    db.query(AssetVersionRecord).filter(
        AssetVersionRecord.scene_id == scene.id,
        AssetVersionRecord.status.in_([AssetVersionRecordStatus.approved, AssetVersionRecordStatus.draft]),
    ).update({AssetVersionRecord.status: AssetVersionRecordStatus.rejected}, synchronize_session=False)
    return record


def _existing_asset(db, scene_id: str, idempotency_key: str) -> AssetVersionRecord | None:
    records = db.query(AssetVersionRecord).filter(AssetVersionRecord.scene_id == scene_id).all()
    return next((record for record in records if record.extra_metadata.get("idempotency_key") == idempotency_key), None)


def _next_version(db, scene_id: str, media_type: str) -> int:
    value = db.query(func.max(AssetVersionRecord.version)).filter(
        AssetVersionRecord.scene_id == scene_id, AssetVersionRecord.media_type == media_type
    ).scalar()
    return int(value or 0) + 1


def _persist_asset(db, scene: Scene, legacy_asset: Asset, *, media_key: str, media_type: MediaType,
                   relative_path: str, metadata: dict[str, Any], provenance: dict[str, Any],
                   idempotency_key: str, content_text: str | None = None) -> AssetVersionRecord:
    existing = _existing_asset(db, scene.id, idempotency_key)
    if existing:
        return existing
    version = _next_version(db, scene.id, media_key)
    previous = db.query(AssetVersionRecord).filter(
        AssetVersionRecord.scene_id == scene.id, AssetVersionRecord.media_type == media_key,
        AssetVersionRecord.status.in_([AssetVersionRecordStatus.approved, AssetVersionRecordStatus.draft]),
    ).order_by(AssetVersionRecord.version.desc()).first()
    checksum = _sha256(relative_path)
    record = AssetVersionRecord(
        id=f"av-{_digest(idempotency_key)[:28]}",
        scene_id=scene.id,
        asset_id=legacy_asset.id,
        version=version,
        media_type=media_key,
        status=AssetVersionRecordStatus.draft,
        artifact_uri=relative_path,
        content_text=content_text,
        provenance=provenance,
        parent_id=previous.id if previous else None,
        checksum=checksum,
        extra_metadata={**metadata, "idempotency_key": idempotency_key, "media_type": media_type.value},
    )
    db.add(record)
    db.flush()
    if previous and previous.status is AssetVersionRecordStatus.draft:
        previous.status = AssetVersionRecordStatus.superseded
    return record


def _sha256(relative_path: str) -> str:
    path = (ARTIFACT_ROOT / relative_path).resolve()
    if not path.is_relative_to(ARTIFACT_ROOT.resolve()):
        raise MediaValidationError("artifact path escaped the configured root")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _domain_asset(record: AssetVersionRecord) -> DomainAssetVersion:
    media_type = MediaType.video if record.media_type.startswith("video:") else MediaType(record.media_type)
    provenance = dict(record.provenance)
    provenance["metadata"] = {
        **dict(provenance.get("metadata") or {}),
        **{key: value for key, value in provenance.items() if key not in {
            "source", "provider", "model", "model_version", "seed", "metadata"
        }},
    }
    provenance = {
        key: value for key, value in provenance.items()
        if key in {"source", "provider", "model", "model_version", "seed", "metadata"}
    }
    return DomainAssetVersion(
        asset_version_id=record.id,
        scene_id=record.scene_id,
        asset_id=str(record.asset_id) if record.asset_id is not None else None,
        version=record.version,
        media_type=media_type,
        status=AssetVersionStatus(record.status.value),
        content_text=record.content_text,
        provenance=provenance,
        created_at=record.created_at.replace(tzinfo=timezone.utc) if record.created_at.tzinfo is None else record.created_at,
    )


def _current_assets(db, scene_id: str, *, include_drafts: bool = True) -> list[AssetVersionRecord]:
    statuses = [AssetVersionRecordStatus.approved]
    if include_drafts:
        statuses.append(AssetVersionRecordStatus.draft)
    records = db.query(AssetVersionRecord).filter(
        AssetVersionRecord.scene_id == scene_id, AssetVersionRecord.status.in_(statuses)
    ).all()
    latest: dict[str, AssetVersionRecord] = {}
    for record in records:
        if record.media_type not in latest or record.version > latest[record.media_type].version:
            latest[record.media_type] = record
    return list(latest.values())


def _promote_assets(db, scene_id: str) -> None:
    candidates = _current_assets(db, scene_id, include_drafts=True)
    for candidate in candidates:
        if candidate.status is not AssetVersionRecordStatus.draft:
            continue
        previous = db.query(AssetVersionRecord).filter(
            AssetVersionRecord.scene_id == scene_id,
            AssetVersionRecord.media_type == candidate.media_type,
            AssetVersionRecord.status == AssetVersionRecordStatus.approved,
        ).all()
        for record in previous:
            record.status = AssetVersionRecordStatus.superseded
        candidate.status = AssetVersionRecordStatus.approved
    db.flush()


def _persist_qa(db, scene_id: str, evaluation, prefix: str) -> None:
    existing = db.query(QAEvaluationRecord).filter(QAEvaluationRecord.id == evaluation.evaluation_id).first()
    if existing:
        return
    record = QAEvaluationRecord(
        id=evaluation.evaluation_id,
        scene_id=scene_id,
        status=QARecordStatus(evaluation.status.value),
        score=evaluation.score,
        recommendation=QARecordRecommendation(evaluation.recommendation.value),
        evaluated_asset_version_ids=evaluation.evaluated_asset_version_ids,
    )
    db.add(record)
    for finding in evaluation.findings:
        db.add(QAFindingRecord(
            evaluation_id=evaluation.evaluation_id,
            code=f"{prefix}.{finding.code}",
            message=finding.message,
            severity=finding.severity,
            shot_id=finding.shot_id,
        ))


def _technical_qa(db, scene: Scene, plan: ScenePlan) -> bool:
    records = _current_assets(db, scene.id)
    findings: list[dict[str, Any]] = []
    for record in records:
        expected = "video" if record.media_type.startswith("video:") else "audio"
        try:
            validate_media(record.artifact_uri or "", ARTIFACT_ROOT, expected)
        except MediaValidationError as error:
            findings.append({"code": "technical_media_invalid", "message": str(error), "severity": "error"})
    if not any(record.media_type.startswith("video:") for record in records):
        findings.append({"code": "missing_visual_assets", "message": "No approved visual shot assets exist", "severity": "error"})
    evaluation_id = f"qa-technical-{_digest(scene.id + str(plan.plan_id) + str(scene.workflow_attempt))[:24]}"
    if not db.query(QAEvaluationRecord).filter(QAEvaluationRecord.id == evaluation_id).first():
        evaluation = QAEvaluationRecord(
            id=evaluation_id, scene_id=scene.id,
            status=QARecordStatus.failed if findings else QARecordStatus.passed,
            score=0.0 if findings else 1.0,
            recommendation=QARecordRecommendation.retry if findings else QARecordRecommendation.approve,
            evaluated_asset_version_ids=[record.id for record in records],
        )
        db.add(evaluation)
        for finding in findings:
            db.add(QAFindingRecord(evaluation_id=evaluation_id, **finding))
    return not findings


def _mark_legacy_assets(db, scene: Scene, plan: ScenePlan, final_path: str, music_path: str) -> None:
    narrative = next((asset for asset in scene.assets if asset.asset_type is AssetType.narrative), None)
    visual = next((asset for asset in scene.assets if asset.asset_type is AssetType.visual), None)
    soundtrack = next((asset for asset in scene.assets if asset.asset_type is AssetType.soundtrack), None)
    if narrative:
        narrative.status = AssetStatus.succeeded
        narrative.content_text = "\n".join(shot.narration.narration_text or shot.narration.summary for shot in plan.shots)
        narrative.mime_type = "text/plain"
    if visual:
        visual.status = AssetStatus.succeeded
        visual.artifact_path = final_path
        visual.mime_type = "video/mp4"
    if soundtrack:
        soundtrack.status = AssetStatus.succeeded
        soundtrack.artifact_path = music_path
        soundtrack.mime_type = "audio/wav"


def _schedule_media_generation(scene_id: str, plan_record: ScenePlanRecord) -> None:
    """Schedule only missing branches for a persisted plan after worker recovery."""
    db = SessionLocal()
    try:
        current = {record.media_type for record in _current_assets(db, scene_id)}
        visual_signatures = {f"video:{shot.id}" for shot in plan_record.shots}
        header = [
            _with_correlation(generate_visual_asset.si(scene_id, shot.id, plan_record.version))
            for shot in plan_record.shots
            if f"video:{shot.id}" not in current
        ]
        missing_audio = [name for name in ("narration", "music", "ambience", "sound_effect") if name not in current]
        if missing_audio:
            header.append(_with_correlation(generate_audio_assets.si(scene_id, plan_record.version, missing_audio)))
        if not header and visual_signatures.issubset(current) and not missing_audio:
            _with_correlation(join_media.s([], scene_id, plan_record.version)).delay()
            return
        chord(group(header), _with_correlation(join_media.s(scene_id, plan_record.version))).delay()
    finally:
        db.close()


def plan_scene_impl(scene_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).with_for_update().first()
        if not scene or scene.workflow_state is not WorkflowStateRecord.queued:
            return {"scene_id": scene_id, "skipped": True}
        _transition(scene, WorkflowStateRecord.planning)
        db.commit()
        bundle = build_provider_bundle(settings_obj=settings)
        request = NarrativeDirectorRequest(
            scene_id=scene.id,
            user_prompt=scene.prompt,
            idempotency=IdempotencyInfo(key=f"{scene.id}:plan:v1", request_hash=_digest(scene.prompt)),
        )
        result = bundle.narrative.plan(request)
        db.expire_all()
        scene = db.query(Scene).filter(Scene.id == scene_id).with_for_update().first()
        if not scene:
            return {"scene_id": scene_id, "skipped": True}
        _persist_job(db, result.job, request.idempotency.key)
        plan_record = _persist_plan(db, scene, result.plan)
        _transition(scene, WorkflowStateRecord.generating)
        scene.workflow_attempt += 1
        db.commit()
        _schedule_media_generation(scene_id, plan_record)
        return {"scene_id": scene_id, "plan_id": plan_record.id, "version": plan_record.version}
    except Exception as error:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.plan_scene", "planning_failed")
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if scene:
            _fail(db, scene, "Narrative planning failed safely", "planning_failed")
        return {"scene_id": scene_id, "error": "planning_failed"}
    finally:
        db.close()


def generate_visual_impl(scene_id: str, shot_id: str, plan_version: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        plan_record = db.query(ScenePlanRecord).filter(ScenePlanRecord.scene_id == scene_id, ScenePlanRecord.version == plan_version).first()
        if not scene or not plan_record:
            return {"ok": False, "error": "missing_plan"}
        if scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        key = f"{scene_id}:visual:{shot_id}:v{plan_version}:r{scene.workflow_attempt}"
        if _existing_asset(db, scene_id, key):
            return {"ok": True, "skipped": True}
        plan = _plan_from_record(plan_record)
        request = VisualAgentRequest(
            plan=plan, shot_id=shot_id, idempotency=IdempotencyInfo(key=key, request_hash=_digest(key))
        )
        bundle = build_provider_bundle(settings_obj=settings)
        result = bundle.visual.generate(request)
        if bundle.mode != "fake":
            raise RuntimeError("real visual artifact materialization is not enabled in Phase 4")
        relative = f"{scene_id}/inputs/video/{shot_id}/v{_next_version(db, scene_id, 'video:' + shot_id)}.mp4"
        write_fake_video(ARTIFACT_ROOT, relative, next(shot.timing.duration_ms for shot in plan.shots if shot.shot_id == shot_id), _digest(key))
        if settings.artifact_storage_backend == "s3":
            _artifact_store().put(ARTIFACT_ROOT / relative, key=relative, content_type="video/mp4", metadata={"scene-plan-version": str(plan_version), "shot-id": shot_id})
        legacy = next(asset for asset in scene.assets if asset.asset_type is AssetType.visual)
        _persist_job(db, result.job, key)
        if result.job.provenance.metadata.get("fallback_from"):
            record_audit(db, actor_user_id=scene.user_id, event_type="provider_fallback", resource_type="provider_job", resource_id=result.job.job_id, correlation=scene_id, outcome="fallback", metadata={"provider": result.job.provenance.provider, "reason": result.job.provenance.metadata.get("fallback_reason")})
        record = _persist_asset(
            db, scene, legacy, media_key=f"video:{shot_id}", media_type=MediaType.video,
            relative_path=relative, metadata={"duration_ms": next(shot.timing.duration_ms for shot in plan.shots if shot.shot_id == shot_id)},
            provenance={
                **result.asset.provenance.model_dump(mode="json"),
                "metadata": {**result.asset.provenance.metadata, "shot_id": shot_id},
            },
            idempotency_key=key,
        )
        db.commit()
        return {"ok": True, "asset_version_id": record.id}
    except Exception:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.generate_visual_asset", "visual_generation_failed")
        return {"ok": False, "error": "visual_generation_failed"}
    finally:
        db.close()


def generate_audio_impl(scene_id: str, plan_version: int, media_types: list[str] | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        plan_record = db.query(ScenePlanRecord).filter(ScenePlanRecord.scene_id == scene_id, ScenePlanRecord.version == plan_version).first()
        if not scene or not plan_record:
            return {"ok": False, "error": "missing_plan"}
        if scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        key = f"{scene_id}:audio:v{plan_version}:r{scene.workflow_attempt}"
        logical_names = {MediaType.narration.value, MediaType.music.value, MediaType.ambience.value, MediaType.sound_effect.value}
        requested_names = set(media_types or logical_names).intersection(logical_names)
        if requested_names and all(
            _existing_asset(db, scene_id, key + ":" + media_name) for media_name in requested_names
        ):
            return {"ok": True, "skipped": True}
        plan = _plan_from_record(plan_record)
        request = AudioAgentRequest(plan=plan, idempotency=IdempotencyInfo(key=key, request_hash=_digest(key)))
        bundle = build_provider_bundle(settings_obj=settings)
        result = bundle.audio.generate(request)
        if bundle.mode != "fake":
            raise RuntimeError("real audio artifact materialization is not enabled in Phase 4")
        legacy = next(asset for asset in scene.assets if asset.asset_type is AssetType.soundtrack)
        _persist_job(db, result.job, key)
        logical = [(MediaType.narration, 440), (MediaType.music, 520), (MediaType.ambience, 330), (MediaType.sound_effect, 660)]
        requested = set(media_types or [media_type.value for media_type, _ in logical])
        selected = [(media_type, frequency) for media_type, frequency in logical if media_type.value in requested]
        if not selected:
            return {"ok": True, "skipped": True}
        for index, (media_type, frequency) in enumerate(logical):
            if media_type not in {item[0] for item in selected}:
                continue
            asset = next(item for item in result.assets if item.media_type is media_type)
            media_key = media_type.value
            item_key = key + ":" + media_key
            if _existing_asset(db, scene_id, item_key):
                continue
            relative = f"{scene_id}/inputs/audio/{media_key}/v{_next_version(db, scene_id, media_key)}.wav"
            write_fake_audio(ARTIFACT_ROOT, relative, plan.total_duration_ms, frequency)
            if settings.artifact_storage_backend == "s3":
                _artifact_store().put(ARTIFACT_ROOT / relative, key=relative, content_type="audio/wav", metadata={"scene-plan-version": str(plan_version), "media-type": media_key})
            _persist_asset(
                db, scene, legacy, media_key=media_key, media_type=media_type, relative_path=relative,
                metadata={"duration_ms": plan.total_duration_ms, "logical_index": index},
                provenance=asset.provenance.model_dump(mode="json"), idempotency_key=item_key,
                content_text=asset.content_text,
            )
        db.commit()
        return {"ok": True}
    except Exception:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.generate_audio_assets", "audio_generation_failed")
        return {"ok": False, "error": "audio_generation_failed"}
    finally:
        db.close()


def regenerate_rejected_assets_impl(scene_id: str, plan_version: int, targets: list[str]) -> dict[str, Any]:
    """Regenerate only the media identified by agent-QA findings."""
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        plan_record = db.query(ScenePlanRecord).filter(
            ScenePlanRecord.scene_id == scene_id, ScenePlanRecord.version == plan_version
        ).first()
        if not scene or not plan_record:
            return {"ok": False, "error": "missing_plan"}
        if scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        _transition(scene, WorkflowStateRecord.generating)
        scene.workflow_error = None
        db.commit()
        requested = set(targets)
        shot_ids = [value.removeprefix("video:") for value in requested if value.startswith("video:")]
        if not requested:
            shot_ids = [shot.id for shot in plan_record.shots]
        header = [_with_correlation(generate_visual_asset.si(scene_id, shot_id, plan_version)) for shot_id in shot_ids]
        audio_names = {MediaType.narration.value, MediaType.music.value, MediaType.ambience.value, MediaType.sound_effect.value}
        audio_targets = sorted(requested.intersection(audio_names))
        if not requested or audio_targets:
            header.append(_with_correlation(generate_audio_assets.si(scene_id, plan_version, audio_targets or None)))
        if not header:
            return {"ok": False, "error": "no_regeneration_targets"}
        chord(group(header), _with_correlation(join_media.s(scene_id, plan_version))).delay()
        return {"ok": True, "targets": sorted(requested)}
    except Exception:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.regenerate_rejected_assets", "regeneration_failed")
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if scene:
            _fail(db, scene, "Selective regeneration failed safely", "regeneration_failed")
        return {"ok": False, "error": "regeneration_failed"}
    finally:
        db.close()


def join_media_impl(results: list[dict[str, Any]], scene_id: str, plan_version: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        plan_record = db.query(ScenePlanRecord).filter(ScenePlanRecord.scene_id == scene_id, ScenePlanRecord.version == plan_version).first()
        if not scene or not plan_record:
            return {"ok": False, "error": "missing_plan"}
        if scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        if not all(result.get("ok") for result in results):
            _fail(db, scene, "A media branch failed before technical QA", "media_generation_failed")
            return {"ok": False, "error": "media_generation_failed"}
        plan = _plan_from_record(plan_record)
        _transition(scene, WorkflowStateRecord.technical_qa)
        db.commit()
        if not _technical_qa(db, scene, plan):
            _fail(db, scene, "Technical media validation failed", "technical_qa_failed")
            return {"ok": False, "error": "technical_qa_failed"}
        db.commit()
        _transition(scene, WorkflowStateRecord.agent_qa)
        db.commit()
        agent_qa.delay(scene_id, plan_version)
        return {"ok": True}
    except Exception:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.join_media", "workflow_join_failed")
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if scene:
            _fail(db, scene, "Workflow join failed safely", "workflow_join_failed")
        return {"ok": False, "error": "workflow_join_failed"}
    finally:
        db.close()


def agent_qa_impl(scene_id: str, plan_version: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        plan_record = db.query(ScenePlanRecord).filter(ScenePlanRecord.scene_id == scene_id, ScenePlanRecord.version == plan_version).first()
        if not scene or not plan_record:
            return {"ok": False, "error": "missing_plan"}
        if scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        plan = _plan_from_record(plan_record)
        records = _current_assets(db, scene_id)
        request = QAAgentRequest(plan=plan, assets=[_domain_asset(record) for record in records], idempotency=IdempotencyInfo(
            key=f"{scene_id}:qa:v{plan_version}:r{scene.workflow_attempt}", request_hash=_digest([record.id for record in records])
        ))
        result = build_provider_bundle(settings_obj=settings).qa.evaluate(request)
        _persist_job(db, result.job, request.idempotency.key)
        _persist_qa(db, scene_id, result.evaluation, "agent")
        db.commit()
        if result.evaluation.recommendation is not QARecommendation.approve:
            record_audit(db, actor_user_id=scene.user_id, event_type="qa_rejection", resource_type="scene", resource_id=scene_id, correlation=scene_id, outcome="rejected", metadata={"recommendation": result.evaluation.recommendation.value})
            db.commit()
            if scene.workflow_attempt >= MAX_REGENERATIONS:
                _fail(db, scene, "Maximum selective regeneration attempts exhausted", "regeneration_exhausted")
                return {"ok": False, "error": "regeneration_exhausted"}
            targets, global_narrative_rejection = _regeneration_targets(result.evaluation.findings, records)
            if global_narrative_rejection:
                new_plan = _create_plan_revision(db, scene, plan_record)
                _transition(scene, WorkflowStateRecord.regenerating)
                scene.workflow_attempt += 1
                db.commit()
                _with_correlation(regenerate_rejected_assets.s(scene_id, new_plan.version, [])).delay()
                return {"ok": True, "regenerating": True, "plan_version": new_plan.version}
            if not targets:
                targets = {record.media_type for record in records}
            _transition(scene, WorkflowStateRecord.regenerating)
            scene.workflow_attempt += 1
            record_audit(db, actor_user_id=scene.user_id, event_type="selective_regeneration", resource_type="scene", resource_id=scene_id, correlation=scene_id, outcome="accepted", metadata={"targets": sorted(targets)})
            db.commit()
            _with_correlation(regenerate_rejected_assets.s(scene_id, plan_version, sorted(targets))).delay()
            return {"ok": True, "regenerating": True}
        _transition(scene, WorkflowStateRecord.assembling)
        db.commit()
        _with_correlation(assemble_scene.s(scene_id, plan_version)).delay()
        return {"ok": True}
    except Exception:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.agent_qa", "agent_qa_failed")
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if scene:
            _fail(db, scene, "Agent QA failed safely", "agent_qa_failed")
        return {"ok": False, "error": "agent_qa_failed"}
    finally:
        db.close()


def assemble_scene_impl(scene_id: str, plan_version: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        plan_record = db.query(ScenePlanRecord).filter(ScenePlanRecord.scene_id == scene_id, ScenePlanRecord.version == plan_version).first()
        if not scene or not plan_record:
            return {"ok": False, "error": "missing_plan"}
        if scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        plan = _plan_from_record(plan_record)
        records = _current_assets(db, scene_id)
        videos = [record for record in records if record.media_type.startswith("video:")]
        videos.sort(key=lambda record: next(shot.order for shot in plan.shots if f"video:{shot.shot_id}" == record.media_type))
        audio_types = ["narration", "music", "ambience", "sound_effect"]
        audios = [next(record for record in records if record.media_type == media_type) for media_type in audio_types]
        source_ids = [record.id for record in videos + audios]
        version = (db.query(func.max(FinalRenderRecord.version)).filter(FinalRenderRecord.scene_id == scene_id).scalar() or 0) + 1
        existing = next(
            (render for render in db.query(FinalRenderRecord).filter(FinalRenderRecord.scene_id == scene_id).all()
             if render.source_asset_version_ids == source_ids),
            None,
        )
        if existing and existing.status is FinalRenderRecordStatus.succeeded:
            return {"ok": True, "render_id": existing.id, "skipped": True}
        final_path, manifest = assemble_mp4(
            ARTIFACT_ROOT, scene_id=scene_id, version=version,
            video_paths=[record.artifact_uri for record in videos if record.artifact_uri],
            audio_paths=[record.artifact_uri for record in audios if record.artifact_uri],
            expected_duration_ms=plan.total_duration_ms,
        )
        db.expire_all()
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene or scene.workflow_state is WorkflowStateRecord.cancelled:
            return {"ok": False, "error": "workflow_cancelled"}
        if settings.artifact_storage_backend == "s3":
            _artifact_store().put(ARTIFACT_ROOT / final_path, key=final_path, content_type="video/mp4", metadata={"scene-plan-version": str(plan_version)})
        render = FinalRenderRecord(
            id=f"render-{_digest(scene_id + json.dumps(source_ids))[:28]}",
            scene_id=scene_id, version=version, status=FinalRenderRecordStatus.succeeded,
            artifact_uri=final_path, mime_type="video/mp4", duration_ms=manifest["measured_duration_ms"],
            source_asset_version_ids=source_ids, failure=manifest,
        )
        db.add(render)
        _transition(scene, WorkflowStateRecord.final_qa)
        db.commit()
        final_request = QAAgentRequest(
            plan=plan,
            assets=[_domain_asset(record) for record in videos + audios],
            idempotency=IdempotencyInfo(
                key=f"{scene_id}:final-qa:{version}", request_hash=_digest(source_ids + [manifest["output_checksum"]])
            ),
        )
        final_result = build_provider_bundle(settings_obj=settings).qa.evaluate(final_request)
        _persist_job(db, final_result.job, final_request.idempotency.key)
        _persist_qa(db, scene_id, final_result.evaluation, "final")
        if final_result.evaluation.recommendation is not QARecommendation.approve:
            render.status = FinalRenderRecordStatus.failed
            render.failure = {"code": "final_qa_failed", "message": "Final render QA rejected the render"}
            record_audit(db, actor_user_id=scene.user_id, event_type="qa_rejection", resource_type="final_render", resource_id=render.id, correlation=scene_id, outcome="rejected", metadata={"recommendation": final_result.evaluation.recommendation.value})
            _fail(db, scene, "Final render QA rejected the render", "final_qa_failed")
            return {"ok": False, "error": "final_qa_failed"}
        record_audit(db, actor_user_id=scene.user_id, event_type="final_render_acceptance", resource_type="final_render", resource_id=render.id, correlation=scene_id, outcome="accepted", metadata={"checksum": manifest["output_checksum"]})
        _promote_assets(db, scene_id)
        _mark_legacy_assets(db, scene, plan, final_path, next(record.artifact_uri for record in audios if record.media_type == "music"))
        _transition(scene, WorkflowStateRecord.completed)
        db.commit()
        RedisGovernance().release_concurrent(scene.user_id)
        metric_inc("triphony.workflow.successes")
        return {"ok": True, "render_id": render.id}
    except Exception:
        db.rollback()
        _create_dead_letter(scene_id, "worker.tasks.assemble_scene", "assembly_failed")
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if scene:
            _fail(db, scene, "Final assembly or validation failed safely", "assembly_failed")
        return {"ok": False, "error": "assembly_failed"}
    finally:
        db.close()


def _regeneration_targets(findings: list[Any], records: list[AssetVersionRecord]) -> tuple[set[str], bool]:
    """Map QA findings to the smallest safe regeneration set."""
    targets: set[str] = set()
    global_narrative_rejection = False
    for finding in findings:
        if finding.shot_id:
            targets.add(f"video:{finding.shot_id}")
        elif "narrative" in finding.code.lower() or "narrative" in finding.message.lower():
            global_narrative_rejection = True
        for media_name in ("narration", "music", "ambience", "sound_effect"):
            if media_name in finding.code.lower() or media_name in finding.message.lower():
                targets.add(media_name)
    if not targets and not global_narrative_rejection:
        targets = {record.media_type for record in records}
    return targets, global_narrative_rejection


@celery_app.task(name="worker.tasks.start_scene_workflow")
def start_scene_workflow(scene_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene or scene.workflow_state in {WorkflowStateRecord.completed, WorkflowStateRecord.failed, WorkflowStateRecord.cancelled}:
            return {"scene_id": scene_id, "skipped": True}
        if scene.workflow_state is WorkflowStateRecord.regenerating:
            plan = db.query(ScenePlanRecord).filter(
                ScenePlanRecord.scene_id == scene_id
            ).order_by(ScenePlanRecord.version.desc()).first()
            if plan:
                scene.workflow_attempt += 1
                db.commit()
                _with_correlation(regenerate_rejected_assets.s(scene_id, plan.version, [])).delay()
            return {"scene_id": scene_id, "queued": True, "regenerating": True}
        if scene.workflow_state in {WorkflowStateRecord.generating, WorkflowStateRecord.technical_qa}:
            plan = db.query(ScenePlanRecord).filter(
                ScenePlanRecord.scene_id == scene_id
            ).order_by(ScenePlanRecord.version.desc()).first()
            if plan:
                if scene.workflow_state is WorkflowStateRecord.generating:
                    _schedule_media_generation(scene_id, plan)
                else:
                    _with_correlation(join_media.s([{"ok": True}], scene_id, plan.version)).delay()
            return {"scene_id": scene_id, "queued": True, "resumed": True}
        if scene.workflow_state is WorkflowStateRecord.agent_qa:
            plan = db.query(ScenePlanRecord).filter(
                ScenePlanRecord.scene_id == scene_id
            ).order_by(ScenePlanRecord.version.desc()).first()
            if plan:
                _with_correlation(agent_qa.s(scene_id, plan.version)).delay()
            return {"scene_id": scene_id, "queued": True, "resumed": True}
        if scene.workflow_state is WorkflowStateRecord.assembling:
            plan = db.query(ScenePlanRecord).filter(
                ScenePlanRecord.scene_id == scene_id
            ).order_by(ScenePlanRecord.version.desc()).first()
            if plan:
                _with_correlation(assemble_scene.s(scene_id, plan.version)).delay()
            return {"scene_id": scene_id, "queued": True, "resumed": True}
        if scene.workflow_state is not WorkflowStateRecord.queued:
            return {"scene_id": scene_id, "skipped": True}
    finally:
        db.close()
    return _dispatch_plan(scene_id)


@celery_app.task(name="worker.tasks.cancel_scene_workflow")
def cancel_scene_workflow(scene_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            return {"scene_id": scene_id, "skipped": True}
        jobs = [
            (job.agent_type, job.provider_job_id)
            for job in scene.provider_jobs
            if job.provider_job_id and job.status in {ProviderJobRecordStatus.created, ProviderJobRecordStatus.queued, ProviderJobRecordStatus.running}
        ]
        user_id = scene.user_id
    finally:
        db.close()

    cancellation_errors = 0
    if jobs:
        try:
            bundle = build_provider_bundle(settings_obj=settings)
            agents = {
                "narrative": bundle.narrative,
                "visual": bundle.visual,
                "audio": bundle.audio,
                "qa": bundle.qa,
            }
            for agent_type, provider_job_id in jobs:
                try:
                    agents[agent_type].cancel(provider_job_id)
                except Exception:
                    cancellation_errors += 1
        except Exception:
            cancellation_errors = len(jobs)

    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if scene:
            for job in scene.provider_jobs:
                if job.provider_job_id and job.status in {ProviderJobRecordStatus.created, ProviderJobRecordStatus.queued, ProviderJobRecordStatus.running}:
                    job.status = ProviderJobRecordStatus.cancelled
            record_audit(db, actor_user_id=scene.user_id, event_type="workflow_cancellation", resource_type="scene", resource_id=scene_id, correlation=scene_id, outcome="provider_requested", metadata={"provider_errors": cancellation_errors})
            db.commit()
        RedisGovernance().release_concurrent(user_id)
        metric_inc("triphony.workflow.cancellations")
        return {"scene_id": scene_id, "cancelled": True, "provider_errors": cancellation_errors}
    finally:
        db.close()


def _dispatch_plan(scene_id: str) -> dict[str, Any]:
    _with_correlation(plan_scene.s(scene_id)).delay()
    return {"scene_id": scene_id, "queued": True}


@celery_app.task(name="worker.tasks.plan_scene")
def plan_scene(scene_id: str) -> dict[str, Any]:
    with span("orchestration.plan", scene_id=scene_id):
        return plan_scene_impl(scene_id)


@celery_app.task(name="worker.tasks.generate_visual_asset")
def generate_visual_asset(scene_id: str, shot_id: str, plan_version: int) -> dict[str, Any]:
    with span("orchestration.visual", scene_id=scene_id, plan_version=plan_version):
        return generate_visual_impl(scene_id, shot_id, plan_version)


@celery_app.task(name="worker.tasks.generate_audio_assets")
def generate_audio_assets(scene_id: str, plan_version: int, media_types: list[str] | None = None) -> dict[str, Any]:
    with span("orchestration.audio", scene_id=scene_id, plan_version=plan_version):
        return generate_audio_impl(scene_id, plan_version, media_types)


@celery_app.task(name="worker.tasks.regenerate_rejected_assets")
def regenerate_rejected_assets(scene_id: str, plan_version: int, targets: list[str]) -> dict[str, Any]:
    with span("orchestration.regeneration", scene_id=scene_id, plan_version=plan_version):
        return regenerate_rejected_assets_impl(scene_id, plan_version, targets)


@celery_app.task(name="worker.tasks.join_media")
def join_media(results: list[dict[str, Any]], scene_id: str, plan_version: int) -> dict[str, Any]:
    with span("orchestration.join", scene_id=scene_id, plan_version=plan_version):
        return join_media_impl(results, scene_id, plan_version)


@celery_app.task(name="worker.tasks.agent_qa")
def agent_qa(scene_id: str, plan_version: int) -> dict[str, Any]:
    with span("orchestration.agent_qa", scene_id=scene_id, plan_version=plan_version):
        return agent_qa_impl(scene_id, plan_version)


@celery_app.task(name="worker.tasks.assemble_scene")
def assemble_scene(scene_id: str, plan_version: int) -> dict[str, Any]:
    with span("orchestration.assembly", scene_id=scene_id, plan_version=plan_version):
        return assemble_scene_impl(scene_id, plan_version)

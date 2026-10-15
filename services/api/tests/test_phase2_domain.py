import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from api.models import (
    AssetVersionRecord,
    AssetVersionRecordStatus,
    ProviderJobRecord,
    ProviderJobRecordStatus,
    Scene,
    ScenePlanRecord,
    ScenePlanStatus,
    ShotRecord,
    User,
)
from triphony_lib.agents import IdempotencyConflictError, NonRetryableAgentError, RetryableAgentError
from triphony_lib.domain import (
    AgentType,
    AssetVersion,
    AssetVersionStatus,
    AudioAgentRequest,
    CameraDirection,
    IdempotencyInfo,
    InvalidStateTransitionError,
    InvalidTimingError,
    MediaType,
    NarrativeDirectorRequest,
    NarrativeDirection,
    OutputFormatRequirements,
    ProviderJob,
    ProviderJobStatus,
    ProvenanceMetadata,
    QAAgentRequest,
    ScenePlan,
    Shot,
    ShotTiming,
    UnsupportedMediaSpecificationError,
    VisualDirection,
    AudioDirection,
    VisualAgentRequest,
)
from triphony_lib.fakes import FakeAudioAgent, FakeNarrativeDirector, FakeQAAgent, FakeVisualAgent


def _idempotency(key: str) -> IdempotencyInfo:
    return IdempotencyInfo(key=key, request_hash=f"hash-{key}")


def _narrative_request(key: str = "narrative-001", prompt: str = "A moonlit forest") -> NarrativeDirectorRequest:
    return NarrativeDirectorRequest(
        scene_id="scene-1",
        user_prompt=prompt,
        idempotency=_idempotency(key),
    )


def test_scene_plan_round_trip_and_timing_validation():
    plan = FakeNarrativeDirector().plan(_narrative_request()).plan
    assert ScenePlan.model_validate_json(plan.model_dump_json()) == plan
    assert plan.total_duration_ms == 3000

    overlapping = plan.shots[0].model_copy(
        update={"timing": ShotTiming(start_ms=1000, duration_ms=3000)}
    )
    with pytest.raises(ValidationError, match="shots must be ordered consecutively from one"):
        ScenePlan.model_validate({**plan.model_dump(), "shots": [plan.shots[0], overlapping]})


def test_invalid_media_specification_is_rejected():
    with pytest.raises(ValidationError, match="does not support"):
        OutputFormatRequirements(media_type=MediaType.video, mime_type="audio/wav")


def test_provider_job_state_transitions_are_explicit():
    job = ProviderJob(
        job_id="job-1",
        scene_id="scene-1",
        agent_type=AgentType.visual,
        media_type=MediaType.video,
            idempotency=_idempotency("job-0001"),
        provenance=ProvenanceMetadata(source="test", provider="fake"),
    )
    completed = job.transition(ProviderJobStatus.queued).transition(ProviderJobStatus.running).transition(
        ProviderJobStatus.succeeded
    )
    assert completed.status is ProviderJobStatus.succeeded
    with pytest.raises(InvalidStateTransitionError):
        completed.transition(ProviderJobStatus.running)


def test_fake_agents_are_deterministic_and_support_controlled_failures():
    director = FakeNarrativeDirector()
    first = director.plan(_narrative_request())
    second = director.plan(_narrative_request())
    assert first == second

    plan = first.plan
    visual = FakeVisualAgent()
    visual_request = VisualAgentRequest(plan=plan, idempotency=_idempotency("visual-001"))
    visual_result = visual.generate(visual_request)
    assert visual.generate(visual_request) == visual_result
    assert visual_result.asset.provenance.provider == "deterministic-mock"

    audio_result = FakeAudioAgent().generate(
        AudioAgentRequest(plan=plan, idempotency=_idempotency("audio-001"))
    )
    assert len(audio_result.assets) == 4
    qa_result = FakeQAAgent().evaluate(
        QAAgentRequest(
            plan=plan,
            assets=[visual_result.asset, *audio_result.assets],
            idempotency=_idempotency("qa-agent-001"),
        )
    )
    assert qa_result.evaluation.recommendation.value == "approve"
    assert qa_result.evaluation.score == 1.0

    with pytest.raises(RetryableAgentError):
        director.plan(_narrative_request("retry-001").model_copy(update={"failure_mode": "retryable"}))
    with pytest.raises(NonRetryableAgentError):
        director.plan(_narrative_request("fatal-001").model_copy(update={"failure_mode": "fatal"}))


def test_fake_agent_rejects_idempotency_key_reuse_for_different_input():
    director = FakeNarrativeDirector()
    director.plan(_narrative_request())
    with pytest.raises(IdempotencyConflictError):
        director.plan(_narrative_request(prompt="A different forest"))


def test_asset_version_contract_is_immutable():
    asset = AssetVersion(
        asset_version_id="asset-1",
        scene_id="scene-1",
        version=1,
        media_type=MediaType.video,
        status=AssetVersionStatus.approved,
        artifact_uri="mock://video/asset-1.mp4",
        provenance=ProvenanceMetadata(source="test", provider="fake"),
    )
    with pytest.raises(ValidationError):
        asset.status = AssetVersionStatus.rejected


def test_phase2_persistence_relationships_and_constraints(db_session):
    user = User(email="phase2-owner@example.com", name="Phase 2 Owner", hashed_password="hash")
    scene = Scene(id="phase2-scene", user=user, prompt="A persisted plan")
    plan = ScenePlanRecord(
        id="plan-1",
        scene=scene,
        version=1,
        contract_version="1.0",
        user_prompt=scene.prompt,
        status=ScenePlanStatus.approved,
        output_requirements=[{"media_type": "video", "mime_type": "video/mp4"}],
        constraints={},
    )
    plan.shots.append(
        ShotRecord(
            id="shot-1",
            shot_order=1,
            start_ms=0,
            duration_ms=3000,
            prompt=scene.prompt,
            narrative_direction={},
            visual_direction={},
            camera_direction={},
            audio_direction={},
        )
    )
    job = ProviderJobRecord(
        id="job-1",
        scene=scene,
        agent_type="visual",
        media_type="video",
        status=ProviderJobRecordStatus.succeeded,
        idempotency_key="persisted-job-001",
        provider_name="deterministic-mock",
        provenance={},
    )
    db_session.add_all([user, plan, job])
    db_session.commit()
    assert scene.scene_plans[0].shots[0].id == "shot-1"
    assert scene.provider_jobs[0].idempotency_key == "persisted-job-001"

    duplicate_job = ProviderJobRecord(
        id="job-2",
        scene_id=scene.id,
        agent_type="visual",
        media_type="video",
        status=ProviderJobRecordStatus.created,
        idempotency_key="persisted-job-001",
        provider_name="deterministic-mock",
        provenance={},
    )
    db_session.add(duplicate_job)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    version = AssetVersionRecord(
        id="asset-version-1",
        scene_id=scene.id,
        version=1,
        media_type="video",
        status=AssetVersionRecordStatus.approved,
        artifact_uri="mock://video/asset-version-1.mp4",
        provenance={},
    )
    db_session.add(version)
    db_session.commit()
    duplicate_version = AssetVersionRecord(
        id="asset-version-2",
        scene_id=scene.id,
        version=1,
        media_type="video",
        status=AssetVersionRecordStatus.approved,
        artifact_uri="mock://video/asset-version-2.mp4",
        provenance={},
    )
    db_session.add(duplicate_version)
    with pytest.raises(IntegrityError):
        db_session.commit()

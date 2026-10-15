from pathlib import Path
import subprocess

import pytest

import workflow.orchestrator as orchestrator
from api.models import (
    Asset, AssetType, AssetVersionRecord, AssetVersionRecordStatus, Scene, ScenePlanRecord,
    ScenePlanStatus, SceneStatus, ShotRecord, WorkflowStateRecord,
)
from triphony_lib.domain import MediaType
from workflow.media import MediaValidationError, assemble_mp4, validate_media, write_fake_audio, write_fake_video
import workflow.media as media


def test_workflow_state_transitions_are_explicit():
    scene = Scene(id="phase4-state", prompt="A cinematic test", status=SceneStatus.queued)
    orchestrator._transition(scene, WorkflowStateRecord.planning)
    orchestrator._transition(scene, WorkflowStateRecord.generating)
    orchestrator._transition(scene, WorkflowStateRecord.technical_qa)
    orchestrator._transition(scene, WorkflowStateRecord.agent_qa)
    orchestrator._transition(scene, WorkflowStateRecord.assembling)
    orchestrator._transition(scene, WorkflowStateRecord.final_qa)
    orchestrator._transition(scene, WorkflowStateRecord.completed)
    assert scene.status is SceneStatus.done
    with pytest.raises(RuntimeError, match="invalid workflow transition"):
        orchestrator._transition(scene, WorkflowStateRecord.assembling)


def test_media_assembly_is_path_safe_and_verified(tmp_path: Path):
    video = "scene/inputs/video/shot-1.mp4"
    audio = [f"scene/inputs/audio/{name}.wav" for name in ("narration", "music", "ambience", "sound_effect")]
    write_fake_video(tmp_path, video, 1000, "phase4-seed")
    for index, path in enumerate(audio):
        write_fake_audio(tmp_path, path, 1000, 440 + index * 40)

    final_path, manifest = assemble_mp4(
        tmp_path,
        scene_id="scene",
        version=1,
        video_paths=[video],
        audio_paths=audio,
        expected_duration_ms=1000,
    )
    assert "mp4" in validate_media(final_path, tmp_path, "final")["format"]["format_name"]
    assert manifest["output_checksum"]
    with pytest.raises(MediaValidationError, match="escaped"):
        validate_media("../outside.mp4", tmp_path, "video")


def test_asset_versions_preserve_lineage_and_idempotency(db_session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(orchestrator, "ARTIFACT_ROOT", tmp_path)
    user_scene = Scene(id="phase4-lineage", prompt="A cinematic lineage test")
    user_scene.assets = [Asset(asset_type=AssetType.visual, status="pending")]
    db_session.add(user_scene)
    db_session.commit()
    legacy = user_scene.assets[0]

    first_path = "phase4-lineage/first.mp4"
    second_path = "phase4-lineage/second.mp4"
    write_fake_video(tmp_path, first_path, 1000, "first")
    write_fake_video(tmp_path, second_path, 1000, "second")
    first = orchestrator._persist_asset(
        db_session,
        user_scene,
        legacy,
        media_key="video:shot-1",
        media_type=MediaType.video,
        relative_path=first_path,
        metadata={},
        provenance={"source": "fake", "provider": "test"},
        idempotency_key="phase4-lineage-first",
    )
    db_session.commit()
    duplicate = orchestrator._persist_asset(
        db_session,
        user_scene,
        legacy,
        media_key="video:shot-1",
        media_type=MediaType.video,
        relative_path=first_path,
        metadata={},
        provenance={"source": "fake", "provider": "test"},
        idempotency_key="phase4-lineage-first",
    )
    assert duplicate.id == first.id

    second = orchestrator._persist_asset(
        db_session,
        user_scene,
        legacy,
        media_key="video:shot-1",
        media_type=MediaType.video,
        relative_path=second_path,
        metadata={},
        provenance={"source": "fake", "provider": "test"},
        idempotency_key="phase4-lineage-second",
    )
    db_session.commit()
    assert second.parent_id == first.id
    orchestrator._promote_assets(db_session, user_scene.id)
    db_session.commit()
    assert first.status.value == "superseded"
    assert orchestrator._current_assets(db_session, user_scene.id) == [second]


def test_global_narrative_rejection_creates_new_plan_and_rejects_dependents(db_session):
    scene = Scene(id="phase4-plan-revision", prompt="A revised story")
    scene.assets = [Asset(asset_type=AssetType.visual, status="pending")]
    db_session.add(scene)
    db_session.flush()
    source = ScenePlanRecord(
        id="plan-original", scene_id=scene.id, version=1, contract_version="2.0",
        user_prompt=scene.prompt, status=ScenePlanStatus.approved,
        output_requirements=[], constraints={},
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(ShotRecord(
        id="shot-original", scene_plan_id=source.id, shot_order=1, start_ms=0,
        duration_ms=1000, prompt="A shot", narrative_direction={"summary": "old", "tone": "old"},
        visual_direction={"description": "old", "palette": "old", "lighting": "old"},
        camera_direction={"shot_type": "wide", "movement": "static", "framing": "center"},
        audio_direction={"music": "old", "ambience": "old", "sound_effects": ["old"]},
    ))
    db_session.add(AssetVersionRecord(
        id="accepted-old", scene_id=scene.id, asset_id=scene.assets[0].id, version=1,
        media_type="video:shot-original", status=AssetVersionRecordStatus.approved,
        artifact_uri="old.mp4", provenance={}, extra_metadata={},
    ))
    db_session.commit()

    revision = orchestrator._create_plan_revision(db_session, scene, source)
    db_session.commit()

    assert revision.version == 2
    assert revision.status is ScenePlanStatus.approved
    assert source.status is ScenePlanStatus.superseded
    assert revision.shots[0].id == "shot-original-v2"
    assert db_session.get(AssetVersionRecord, "accepted-old").status is AssetVersionRecordStatus.rejected


def test_regeneration_target_mapping_is_selective_and_supports_global_rejection(db_session):
    records = [
        AssetVersionRecord(id="v1", scene_id="s", version=1, media_type="video:shot-1", status=AssetVersionRecordStatus.approved, provenance={}, extra_metadata={}),
        AssetVersionRecord(id="v2", scene_id="s", version=1, media_type="video:shot-2", status=AssetVersionRecordStatus.approved, provenance={}, extra_metadata={}),
        AssetVersionRecord(id="n", scene_id="s", version=1, media_type="narration", status=AssetVersionRecordStatus.approved, provenance={}, extra_metadata={}),
    ]
    finding = type("Finding", (), {"shot_id": "shot-1", "code": "visual_quality", "message": "bad"})()
    targets, global_rejection = orchestrator._regeneration_targets([finding], records)
    assert targets == {"video:shot-1"}
    assert not global_rejection

    for media_name in ("narration", "music", "ambience", "sound_effect"):
        finding = type("Finding", (), {"shot_id": None, "code": f"{media_name}_bad", "message": "bad"})()
        targets, global_rejection = orchestrator._regeneration_targets([finding], records)
        assert targets == {media_name}
        assert not global_rejection

    finding = type("Finding", (), {"shot_id": None, "code": "narrative_coherence", "message": "story rejected"})()
    targets, global_rejection = orchestrator._regeneration_targets([finding], records)
    assert targets == set()
    assert global_rejection


def test_final_assembly_selection_excludes_rejected_versions(db_session):
    for asset_id, media_type, status, version in (
        ("old", "video:shot-1", AssetVersionRecordStatus.rejected, 1),
        ("new", "video:shot-1", AssetVersionRecordStatus.approved, 2),
        ("draft", "music", AssetVersionRecordStatus.draft, 2),
    ):
        db_session.add(AssetVersionRecord(
            id=asset_id, scene_id="phase4-approved-only", version=version,
            media_type=media_type, status=status, provenance={}, extra_metadata={},
        ))
    db_session.commit()
    current = orchestrator._current_assets(db_session, "phase4-approved-only")
    assert {record.id for record in current} == {"new", "draft"}
    assert "old" not in {record.id for record in current}


def test_multiple_visual_shots_are_concatenated_in_order(tmp_path: Path):
    videos = ["scene/video/shot-1.mp4", "scene/video/shot-2.mp4"]
    for index, path in enumerate(videos, start=1):
        write_fake_video(tmp_path, path, 1000, f"shot-{index}")
    audio = [f"scene/audio/{name}.wav" for name in ("narration", "music", "ambience", "sound_effect")]
    for index, path in enumerate(audio):
        write_fake_audio(tmp_path, path, 2000, 440 + index * 40)
    final_path, manifest = assemble_mp4(
        tmp_path, scene_id="scene", version=1, video_paths=videos, audio_paths=audio,
        expected_duration_ms=2000,
    )
    assert manifest["input_asset_paths"] == videos + audio
    assert manifest["measured_duration_ms"] >= 1900
    assert validate_media(final_path, tmp_path, "final")


def test_media_failures_are_safe(tmp_path: Path, monkeypatch):
    with pytest.raises(MediaValidationError, match="missing or empty"):
        validate_media("scene/missing.mp4", tmp_path, "video")
    corrupt = tmp_path / "scene" / "corrupt.mp4"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not media")
    with pytest.raises(MediaValidationError):
        validate_media("scene/corrupt.mp4", tmp_path, "video")
    valid = tmp_path / "scene" / "timeout.mp4"
    valid.write_bytes(b"placeholder")
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 1)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(MediaValidationError, match="timed out"):
        validate_media("scene/timeout.mp4", tmp_path, "video")


def test_repeated_assembly_uses_same_content_addressed_inputs(tmp_path: Path):
    video = "scene/video/shot.mp4"
    audio = [f"scene/audio/{name}.wav" for name in ("narration", "music", "ambience", "sound_effect")]
    write_fake_video(tmp_path, video, 1000, "repeat")
    for index, path in enumerate(audio):
        write_fake_audio(tmp_path, path, 1000, 440 + index * 40)
    first_path, first_manifest = assemble_mp4(tmp_path, scene_id="scene", version=1, video_paths=[video], audio_paths=audio, expected_duration_ms=1000)
    second_path, second_manifest = assemble_mp4(tmp_path, scene_id="scene", version=1, video_paths=[video], audio_paths=audio, expected_duration_ms=1000)
    assert first_path == second_path
    assert first_manifest["input_asset_paths"] == second_manifest["input_asset_paths"]
    assert validate_media(second_path, tmp_path, "final")


def test_orchestrator_has_no_synchronous_celery_waits():
    source = Path(orchestrator.__file__).read_text(encoding="utf-8")
    assert ".get()" not in source

from pathlib import Path

from triphony_lib.contracts import GenerationRequest
from triphony_lib.pipeline import Pipeline


def test_mock_pipeline_generates_valid_video_and_audio(tmp_path: Path):
    pipeline = Pipeline()

    visual = pipeline.run(
        GenerationRequest(
            job_id="test-visual",
            prompt="A deterministic scene",
            asset_type="visual",
            output_dir=str(tmp_path / "visual"),
        )
    )
    assert visual.success is True
    assert visual.mime_type == "video/mp4"
    assert (tmp_path / "visual" / visual.artifact_path).stat().st_size > 0

    audio = pipeline.run(
        GenerationRequest(
            job_id="test-audio",
            prompt="A deterministic scene",
            asset_type="soundtrack",
            output_dir=str(tmp_path / "audio"),
        )
    )
    assert audio.success is True
    assert audio.mime_type == "audio/wav"
    assert (tmp_path / "audio" / audio.artifact_path).stat().st_size > 0


def test_real_mode_fails_without_calling_a_provider(tmp_path: Path):
    result = Pipeline().run(
        GenerationRequest(
            job_id="real-mode",
            prompt="A scene",
            asset_type="visual",
            provider_mode="real",
            api_key="placeholder",
            output_dir=str(tmp_path),
        )
    )
    assert result.success is False
    assert "not connected to the Phase 1 artifact pipeline" in (result.error_message or "")

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from providers.config import ProviderConfig, is_placeholder_secret
from providers.elevenlabs import ElevenLabsAudioAgent
from providers.errors import ProviderError, ProviderErrorKind, translate_provider_exception
from providers.factory import build_provider_bundle
from providers.gemini import GeminiNarrativeDirector, GeminiQAAgent
from providers.readiness import provider_readiness
from providers.veo import VeoVisualAgent
from triphony_lib.domain import (
    AssetVersion,
    AssetVersionStatus,
    AudioAgentRequest,
    IdempotencyInfo,
    MediaType,
    NarrativeDirectorRequest,
    QAAgentRequest,
    QAEvaluation,
    QARecommendation,
    QAStatus,
    ScenePlan,
    VisualAgentRequest,
)
from triphony_lib.fakes import FakeNarrativeDirector


def _idempotency(value: str) -> IdempotencyInfo:
    return IdempotencyInfo(key=value, request_hash=f"hash-{value}")


def _narrative_request(key: str = "narrative-key") -> NarrativeDirectorRequest:
    return NarrativeDirectorRequest(scene_id="scene-1", user_prompt="A cinematic neon city at night", idempotency=_idempotency(key))


def _plan() -> ScenePlan:
    return FakeNarrativeDirector().plan(_narrative_request("plan-key")).plan


class _Models:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response

    def generate_videos(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class _Operations:
    def __init__(self, operations):
        self.operations = list(operations)
        self.calls = 0

    def get(self, operation):
        self.calls += 1
        return self.operations.pop(0) if self.operations else operation


class _VertexClient:
    def __init__(self, *, response=None, error=None, operations=None):
        self.models = _Models(response=response, error=error)
        self.operations = _Operations(operations or [])


@dataclass
class _Video:
    uri: str


@dataclass
class _GeneratedVideo:
    video: _Video


@dataclass
class _VideoResult:
    generated_videos: list[_GeneratedVideo]


@dataclass
class _Operation:
    name: str
    done: bool
    result: object | None = None
    error: object | None = None
    cancelled: bool = False


@dataclass
class _Response:
    text: str | None = None
    prompt_feedback: object | None = None
    parsed: object | None = None


class _SDKError(Exception):
    def __init__(self, status_code, request_id="req-safe"):
        super().__init__("secret xi-api-key should never leak")
        self.status_code = status_code
        self.request_id = request_id


def _real_config(**overrides) -> ProviderConfig:
    values = dict(
        mode="real",
        google_cloud_project="project-1",
        google_cloud_location="global",
        veo_output_gcs_uri="gs://bucket/output/",
        elevenlabs_api_key="real-secret-value",
        elevenlabs_voice_id="voice-1",
    )
    values.update(overrides)
    return ProviderConfig(**values)


def test_gemini_narrative_validates_structured_scene_plan_and_is_lazy():
    plan = _plan()
    client = _VertexClient(response=_Response(text=plan.model_dump_json()))
    created = []
    adapter = GeminiNarrativeDirector(_real_config(), lambda: (created.append(True) or client))
    assert created == []
    result = adapter.plan(_narrative_request())
    assert created == [True]
    assert result.plan.scene_id == "scene-1"
    assert result.job.provenance.provider == "google-vertex-ai"
    assert client.models.calls == 1


@pytest.mark.parametrize(
    "response",
    [
        _Response(text="not-json"),
        _Response(text=json.dumps({"scene_id": "wrong", "plan_id": "p", "user_prompt": "bad", "shots": [], "output_requirements": []})),
    ],
)
def test_gemini_rejects_invalid_json_or_schema(response):
    adapter = GeminiNarrativeDirector(_real_config(), lambda: _VertexClient(response=response))
    with pytest.raises(ProviderError) as exc_info:
        adapter.plan(_narrative_request("invalid-key"))
    assert exc_info.value.kind is ProviderErrorKind.malformed


def test_gemini_maps_safety_auth_quota_and_timeout_without_provider_text():
    safety = _Response(prompt_feedback={"block_reason": "SAFETY"})
    with pytest.raises(ProviderError) as safety_error:
        GeminiNarrativeDirector(_real_config(), lambda: _VertexClient(response=safety)).plan(_narrative_request("safety-key"))
    assert safety_error.value.kind is ProviderErrorKind.safety
    for key, status, expected in [
        ("auth-key", 401, ProviderErrorKind.authentication),
        ("quota-key", 429, ProviderErrorKind.quota),
    ]:
        with pytest.raises(ProviderError) as error:
            GeminiNarrativeDirector(_real_config(), lambda: _VertexClient(error=_SDKError(status))).plan(_narrative_request(key))
        assert error.value.kind is expected
        assert "xi-api-key" not in str(error.value)
    with pytest.raises(ProviderError) as timeout_error:
        GeminiNarrativeDirector(_real_config(), lambda: _VertexClient(error=TimeoutError())).plan(_narrative_request("timeout-key"))
    assert timeout_error.value.kind is ProviderErrorKind.timeout


def test_gemini_qa_returns_cross_modal_findings():
    plan = _plan()
    asset = AssetVersion(
        asset_version_id="asset-1",
        scene_id=plan.scene_id,
        asset_id="visual-shot",
        version=1,
        media_type=MediaType.video,
        status=AssetVersionStatus.draft,
        artifact_uri="gs://bucket/video.mp4",
        provenance={"source": "provider", "provider": "google-vertex-ai"},
    )
    evaluation = QAEvaluation(
        evaluation_id="qa-1",
        scene_id=plan.scene_id,
        status=QAStatus.failed,
        score=0.5,
        recommendation=QARecommendation.retry,
        evaluated_asset_version_ids=[asset.asset_version_id],
        findings=[{"code": "audio_visual_mismatch", "message": "Narration does not match shot timing", "severity": "error", "shot_id": plan.shots[0].shot_id}],
    )
    request = QAAgentRequest(plan=plan, assets=[asset], idempotency=_idempotency("qa-key-1"))
    result = GeminiQAAgent(_real_config(), lambda: _VertexClient(response=_Response(text=evaluation.model_dump_json()))).evaluate(request)
    assert result.evaluation.findings[0].code == "audio_visual_mismatch"
    assert result.evaluation.recommendation is QARecommendation.retry


def _visual_request(key="visual-key") -> VisualAgentRequest:
    return VisualAgentRequest(plan=_plan(), idempotency=_idempotency(key), shot_id=None)


def test_veo_submission_polling_success_and_duplicate_protection():
    completed = _Operation(
        name="operations/video-1",
        done=True,
        result=_VideoResult([_GeneratedVideo(_Video("gs://bucket/video-1.mp4"))]),
    )
    initial = _Operation(name="operations/video-1", done=False)
    client = _VertexClient(response=initial, operations=[completed])
    adapter = VeoVisualAgent(_real_config(), lambda: client, sleep_fn=lambda _: None)
    request = _visual_request()
    job = adapter.submit(request)
    assert job.provider_job_id == "operations/video-1"
    assert adapter.submit(request).job_id == job.job_id
    result = adapter.generate(request)
    assert result.asset.artifact_uri == "gs://bucket/video-1.mp4"
    assert result.job.status.value == "succeeded"
    assert client.models.calls == 1


@pytest.mark.parametrize(
    "operation,expected_status",
    [
        (_Operation("operations/pending", False), "running"),
        (_Operation("operations/failed", True, error={"code": 500}), "failed"),
        (_Operation("operations/cancelled", True, cancelled=True), "cancelled"),
    ],
)
def test_veo_maps_pending_failed_and_cancelled(operation, expected_status):
    client = _VertexClient(response=operation, operations=[operation])
    adapter = VeoVisualAgent(_real_config(), lambda: client, sleep_fn=lambda _: None)
    request = _visual_request(f"{expected_status}-key")
    job = adapter.submit(request)
    result = adapter.poll(job, request)
    assert result.job.status.value == expected_status


def test_veo_timeout_invalid_uri_and_sanitized_failure():
    pending = _Operation("operations/timeout", False)
    client = _VertexClient(response=pending, operations=[pending])
    ticks = iter([0.0, 2.0])
    adapter = VeoVisualAgent(_real_config(operation_timeout_seconds=1), lambda: client, clock=lambda: next(ticks), sleep_fn=lambda _: None)
    with pytest.raises(ProviderError) as timeout:
        adapter.generate(_visual_request("timeout-veo-key"))
    assert timeout.value.kind is ProviderErrorKind.timeout
    invalid = _Operation("operations/invalid", True, result=_VideoResult([]))
    invalid_client = _VertexClient(response=invalid)
    with pytest.raises(ProviderError) as malformed:
        VeoVisualAgent(_real_config(), lambda: invalid_client).generate(_visual_request("invalid-uri-key"))
    assert malformed.value.kind is ProviderErrorKind.malformed
    failure = ProviderError(ProviderErrorKind.quota, "provider quota or rate limit was reached", provider_request_id="req-1", retryable=True).failure_info()
    assert failure.details == {"provider_request_id": "req-1"}


@dataclass
class _AudioPayload:
    data: object
    content_type: str = "audio/mpeg"
    duration_seconds: float | None = None


class _AudioEndpoint:
    def __init__(self, payload=None, error=None):
        self.payload = payload or _AudioPayload(b"audio-bytes")
        self.error = error
        self.calls = 0

    def convert(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload

    def compose(self, **kwargs):
        return self.convert(**kwargs)


class _AudioClient:
    def __init__(self, payload=None, error=None):
        self.text_to_speech = _AudioEndpoint(payload, error)
        self.music = _AudioEndpoint(payload, error)
        self.text_to_sound_effects = _AudioEndpoint(payload, error)


def test_elevenlabs_narration_music_and_effects_validate_binary_outputs():
    client = _AudioClient(_AudioPayload(b"audio-bytes", duration_seconds=2))
    result = ElevenLabsAudioAgent(_real_config(), lambda: client).generate(AudioAgentRequest(plan=_plan(), idempotency=_idempotency("audio-key")))
    assert {asset.media_type for asset in result.assets} == {MediaType.narration, MediaType.music, MediaType.ambience, MediaType.sound_effect}
    assert all(asset.artifact_uri.startswith("provider://elevenlabs/") for asset in result.assets)
    assert client.text_to_sound_effects.calls == 2


@pytest.mark.parametrize(
    "payload,expected",
    [(_AudioPayload(b""), ProviderErrorKind.malformed), (_AudioPayload(b"text", content_type="text/plain"), ProviderErrorKind.malformed)],
)
def test_elevenlabs_rejects_empty_or_invalid_content(payload, expected):
    with pytest.raises(ProviderError) as error:
        ElevenLabsAudioAgent(_real_config(), lambda: _AudioClient(payload)).generate_narration(AudioAgentRequest(plan=_plan(), idempotency=_idempotency("audio-invalid")))
    assert error.value.kind is expected


def test_elevenlabs_maps_auth_quota_timeout_and_limits_without_secret_leak():
    request = AudioAgentRequest(plan=_plan(), idempotency=_idempotency("audio-errors"))
    for status, expected in [(401, ProviderErrorKind.authentication), (429, ProviderErrorKind.quota)]:
        with pytest.raises(ProviderError) as error:
            ElevenLabsAudioAgent(_real_config(), lambda: _AudioClient(error=_SDKError(status))).generate_narration(request)
        assert error.value.kind is expected
        assert "secret xi-api-key" not in str(error.value)
    with pytest.raises(ProviderError) as timeout:
        ElevenLabsAudioAgent(_real_config(), lambda: _AudioClient(error=TimeoutError())).generate_narration(request)
    assert timeout.value.kind is ProviderErrorKind.timeout
    with pytest.raises(ProviderError) as too_large:
        ElevenLabsAudioAgent(_real_config(max_audio_bytes=2), lambda: _AudioClient(_AudioPayload(b"123"))).generate_narration(request)
    assert too_large.value.kind is ProviderErrorKind.invalid_request


def test_factory_fake_real_readiness_and_placeholder_configuration():
    fake = build_provider_bundle(ProviderConfig(mode="fake"))
    assert fake.mode == "fake"
    assert fake.narrative.capabilities.provider_name == "deterministic-mock"
    assert build_provider_bundle(ProviderConfig(mode="fake", elevenlabs_api_key=None)).mode == "fake"
    with pytest.raises(ValueError, match="readiness"):
        build_provider_bundle(ProviderConfig(mode="real"))
    assert is_placeholder_secret("your-api-key")
    report = provider_readiness(ProviderConfig(mode="fake"))
    assert report["ready"] is True
    assert "real-secret-value" not in json.dumps(report)
    real = build_provider_bundle(_real_config(), vertex_client_factory=lambda: None, elevenlabs_client_factory=lambda: None)
    assert isinstance(real.narrative, GeminiNarrativeDirector)
    assert isinstance(real.visual, VeoVisualAgent)
    assert isinstance(real.audio, ElevenLabsAudioAgent)
    assert isinstance(real.qa, GeminiQAAgent)


def test_error_translation_is_provider_neutral_and_safe():
    error = translate_provider_exception(_SDKError(503))
    assert error.kind is ProviderErrorKind.unavailable
    assert error.retryable is True
    assert "secret" not in str(error)

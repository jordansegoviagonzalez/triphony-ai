import hashlib
from pathlib import Path

import pytest

from api.governance import add_outbox_event, safety_gate
from api.models import OutboxEvent, ProviderJobAttemptRecord, ProviderJobRecord, Scene, WorkflowStateRecord
from providers.config import ProviderConfig
from providers.errors import ProviderError, ProviderErrorKind
from providers.fallback import ActivePassiveVisualAgent
from providers.readiness import provider_readiness
from providers.runway import RunwayVisualAgent
from resilience.circuit_breaker import RedisCircuitBreaker
from resilience.retry import RetryPolicy
from triphony_lib.fakes import FakeNarrativeDirector, FakeVisualAgent
from triphony_lib.storage import ArtifactStoreError, LocalArtifactStore, S3ArtifactStore, safe_artifact_key
from triphony_lib.observability import clear_correlation_id, current_correlation_id, metric_inc, safe_fields, set_correlation_id, span
from triphony_lib.domain import IdempotencyInfo, VisualAgentRequest
from triphony_lib.domain import ProvenanceMetadata
from workflow.orchestrator import _create_dead_letter, _persist_job
from shared.celery_app import celery_app


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True


class FakeS3:
    def __init__(self):
        self.calls = []

    def upload_file(self, filename, bucket, key, ExtraArgs, Config=None):
        self.calls.append((filename, bucket, key, ExtraArgs, Config))

    def head_object(self, Bucket, Key):
        return {"ContentLength": 4, "ContentType": "video/mp4", "Metadata": {"checksum-sha256": hashlib.sha256(b"data").hexdigest()}}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://s3.test/{Params['Key']}?expires={ExpiresIn}"


def _visual_request():
    plan = FakeNarrativeDirector().plan(
        __import__("triphony_lib.domain", fromlist=["NarrativeDirectorRequest"]).NarrativeDirectorRequest(
            scene_id="scene", user_prompt="a cinematic scene", idempotency=IdempotencyInfo(key="plan-key-1234", request_hash="hash-1234")
        )
    ).plan
    return VisualAgentRequest(plan=plan, shot_id=plan.shots[0].shot_id, idempotency=IdempotencyInfo(key="visual-key-1234", request_hash="hash-1234"))


def test_runway_adapter_is_lazy_idempotent_and_provider_neutral():
    class Tasks:
        def retrieve(self, _task_id):
            return {"status": "SUCCEEDED", "output": ["https://cdn.runway.example/video.mp4"]}

    class ImageToVideo:
        def create(self, **_kwargs):
            return {"id": "runway-task-1"}

    class Client:
        image_to_video = ImageToVideo()
        tasks = Tasks()

    agent = RunwayVisualAgent(
        ProviderConfig(mode="real", runway_api_secret="real-secret", runway_fallback_enabled=True),
        client_factory=lambda: Client(),
    )
    result = agent.generate(_visual_request())
    duplicate = agent.generate(_visual_request())
    assert result.job.provider_job_id == "runway-task-1"
    assert result.job.provenance.provider == "runway"
    assert result.asset.artifact_uri.startswith("https://")
    assert duplicate.job.job_id == result.job.job_id


def test_fallback_policy_only_uses_runway_for_eligible_provider_failure():
    class Down:
        capabilities = FakeVisualAgent.capabilities
        def generate(self, _request):
            raise ProviderError(ProviderErrorKind.unavailable, "unavailable", retryable=True)
        def cancel(self, _job_id):
            pass
    events = []
    agent = ActivePassiveVisualAgent(Down(), FakeVisualAgent(), True, on_fallback=events.append)
    result = agent.generate(_visual_request())
    assert result.job.provenance.metadata["fallback_from"] == "google-vertex-ai"
    assert events == ["provider_unavailable"]


def test_fallback_is_idempotent_and_terminal_failures_do_not_fallback():
    calls = []

    class Down:
        capabilities = FakeVisualAgent.capabilities
        def generate(self, _request):
            calls.append("primary")
            raise ProviderError(ProviderErrorKind.terminal, "moderation rejection")
        def cancel(self, _job_id):
            pass

    class Fallback(FakeVisualAgent):
        def generate(self, request):
            calls.append("fallback")
            return super().generate(request)

    agent = ActivePassiveVisualAgent(Down(), Fallback(), True)
    with pytest.raises(ProviderError):
        agent.generate(_visual_request())
    assert calls == ["primary"]

    class Retryable(Down):
        def generate(self, _request):
            calls.append("primary-retryable")
            raise ProviderError(ProviderErrorKind.unavailable, "unavailable", retryable=True)

    retryable = ActivePassiveVisualAgent(Retryable(), Fallback(), True)
    request = _visual_request()
    first = retryable.generate(request)
    second = retryable.generate(request)
    assert first.job.job_id == second.job.job_id == request.idempotency.key
    assert calls.count("fallback") == 1


def test_provider_attempt_lineage_preserves_primary_and_fallback(db_session):
    primary = FakeVisualAgent().generate(_visual_request()).job.model_copy(update={"provider_job_id": "veo-operation-1"})
    fallback = primary.model_copy(update={
        "provider_job_id": "runway-task-1",
        "provenance": ProvenanceMetadata(source="provider", provider="runway", model="gen4.5"),
    })
    _persist_job(db_session, primary, primary.idempotency.key)
    db_session.commit()
    _persist_job(db_session, fallback, primary.idempotency.key)
    db_session.commit()
    record = db_session.query(ProviderJobRecord).one()
    attempts = db_session.query(ProviderJobAttemptRecord).filter(ProviderJobAttemptRecord.provider_job_id == record.id).all()
    assert record.provider_name == "runway"
    assert [attempt.provider_job_identifier for attempt in attempts] == ["veo-operation-1", "runway-task-1"]


def test_circuit_breaker_is_shared_through_redis_and_ignores_user_errors():
    redis = FakeRedis()
    now = [100.0]
    changes = []
    breaker = RedisCircuitBreaker(redis, "veo:video", failure_threshold=2, cooldown_seconds=10, clock=lambda: now[0], on_state_change=lambda *event: changes.append(event))
    assert breaker.allow()
    breaker.record_failure(infrastructure=False)
    assert breaker.state().state == "closed"
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state().state == "open"
    assert not breaker.allow()
    now[0] += 11
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state().state == "closed"
    assert changes[-1][1] == "closed"


def test_storage_keys_and_local_store_are_private_and_atomic(tmp_path: Path):
    key = safe_artifact_key("scene-1", "version-1", "render.mp4")
    assert key == "triphony/scene-1/version-1.mp4"
    with pytest.raises(ArtifactStoreError):
        safe_artifact_key("scene@example.com", "version-1", "render.mp4")
    source = tmp_path / "input.mp4"
    source.write_bytes(b"data")
    store = LocalArtifactStore(tmp_path / "private")
    metadata = store.put(source, key=key, content_type="video/mp4")
    assert metadata.content_length == 4
    assert store.signed_get_url(key, expires_in=60) is None


def test_s3_adapter_builds_private_upload_and_signed_get_without_network(tmp_path: Path):
    source = tmp_path / "render.mp4"
    source.write_bytes(b"data")
    client = FakeS3()
    store = S3ArtifactStore(bucket="private-bucket", region="us-west-2", client=client, prefix="media")
    metadata = store.put(source, key="scene-1/version-1.mp4", content_type="video/mp4", metadata={"asset-version": "1"})
    assert metadata.content_length == 4
    _, bucket, key, args, transfer_config = client.calls[0]
    assert bucket == "private-bucket"
    assert key == "media/scene-1/version-1.mp4"
    assert "ACL" not in args
    assert args["ServerSideEncryption"] == "AES256"
    assert transfer_config is not None
    assert store.signed_get_url("scene-1/version-1.mp4", expires_in=30).startswith("https://")


def test_retry_policy_is_bounded_and_honors_retry_after():
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=5, jitter_ratio=0)
    assert policy.delay(1) == 1
    assert policy.delay(3) == 4
    assert policy.delay(1, retry_after=10) == 5


def test_safety_readiness_and_outbox_are_sanitized(db_session):
    assert safety_gate("a cinematic landscape")[0]
    assert not safety_gate("<script>alert(1)</script>")[0]
    report = provider_readiness(ProviderConfig(mode="real", runway_api_secret="secret"))
    assert "secret" not in str(report)
    first = add_outbox_event(db_session, event_key="scene:1:start", event_type="scene.workflow.start", payload={"scene_id": "1"}, correlation="corr-1234")
    duplicate = add_outbox_event(db_session, event_key="scene:1:start", event_type="scene.workflow.start", payload={"scene_id": "1"}, correlation="corr-1234")
    db_session.commit()
    assert first.id == duplicate.id
    assert db_session.query(OutboxEvent).count() == 1


def test_cookie_state_changes_require_csrf_and_allowed_origin(client, monkeypatch):
    registered = client.post("/api/v1/auth/register", json={"name": "CSRF", "email": "csrf@example.com", "password": "securepassword123"})
    assert registered.status_code == 200
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: None)
    rejected = client.post("/api/v1/scenes", json={"prompt": "a scene"})
    assert rejected.status_code == 403
    token = client.cookies.get("triphony_csrf")
    accepted = client.post("/api/v1/scenes", json={"prompt": "a scene"}, headers={"X-CSRF-Token": token, "Origin": "http://localhost:3000"})
    assert accepted.status_code == 200
    blocked = client.post("/api/v1/scenes", json={"prompt": "a scene"}, headers={"X-CSRF-Token": token, "Origin": "https://evil.example"})
    assert blocked.status_code == 403


def test_cancellation_is_owned_idempotent_and_rejects_completed_workflows(client, db_session, monkeypatch):
    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: sent.append((args, kwargs)))
    monkeypatch.setattr(celery_app.control, "revoke", lambda *args, **kwargs: None)
    registered = client.post("/api/v1/auth/register", json={"name": "Cancel", "email": "cancel@example.com", "password": "securepassword123"})
    assert registered.status_code == 200
    token = client.cookies.get("triphony_csrf")
    headers = {"X-CSRF-Token": token, "Origin": "http://localhost:3000"}
    created = client.post("/api/v1/scenes", json={"prompt": "cancel me"}, headers=headers)
    assert created.status_code == 200
    scene_id = created.json()["scene_id"]
    cancelled = client.post(f"/api/v1/scenes/{scene_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert db_session.get(Scene, scene_id).workflow_state is WorkflowStateRecord.cancelled
    assert client.post(f"/api/v1/scenes/{scene_id}/cancel", headers=headers).status_code == 200
    assert any(item[0][0] == "worker.tasks.cancel_scene_workflow" for item in sent)

    scene = db_session.get(Scene, scene_id)
    scene.workflow_state = WorkflowStateRecord.completed
    db_session.commit()
    assert client.post(f"/api/v1/scenes/{scene_id}/cancel", headers=headers).status_code == 409

    other = client.__class__(client.app)
    other_registered = other.post("/api/v1/auth/register", json={"name": "Other", "email": "cancel-other@example.com", "password": "securepassword123"})
    assert other_registered.status_code == 200
    other_token = other.cookies.get("triphony_csrf")
    assert other.post(f"/api/v1/scenes/{scene_id}/cancel", headers={"X-CSRF-Token": other_token, "Origin": "http://localhost:3000"}).status_code == 404


def test_observability_has_correlation_spans_metrics_and_redaction():
    token = set_correlation_id("corr-phase5")
    try:
        assert current_correlation_id() == "corr-phase5"
        assert safe_fields({"authorization": "secret", "scene_id": "scene-1"}) == {"authorization": "[REDACTED]", "scene_id": "scene-1"}
        metric_inc("triphony.test.counter", outcome="ok")
        with span("test.phase5", scene_id="scene-1"):
            pass
    finally:
        clear_correlation_id()
    assert current_correlation_id() is None


def test_terminal_worker_failure_creates_sanitized_dead_letter(monkeypatch):
    captured = {}
    monkeypatch.setattr("workflow.outbox.create_dead_letter", lambda **kwargs: captured.update(kwargs) or "dlq-1")
    _create_dead_letter("scene-1", "worker.tasks.generate_visual_asset", "visual_generation_failed")
    assert captured["scene_id"] == "scene-1"
    assert captured["replay_eligible"] is True
    assert captured["details"] == {"source": "worker_task"}

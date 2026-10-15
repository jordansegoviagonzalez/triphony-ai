from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from api.models import Asset, AssetStatus, AssetType, Scene, SceneStatus
from api.settings import settings
from shared.celery_app import celery_app


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": email.split("@")[0], "email": email, "password": "securepassword123"},
    )
    assert response.status_code == 200


def _csrf_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("triphony_csrf")}


def test_scene_ownership_and_artifact_access_are_isolated(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: None)
    _register(client, "owner@example.com")
    created = client.post("/api/v1/scenes", json={"prompt": "A private scene"}, headers=_csrf_headers(client))
    assert created.status_code == 200
    scene_id = created.json()["scene_id"]

    owner_scene = db_session.query(Scene).filter(Scene.id == scene_id).one()
    owner_asset = next(asset for asset in owner_scene.assets if asset.asset_type == AssetType.visual)
    artifact_root = Path(tmp_path)
    artifact_file = artifact_root / "owner" / "mock.mp4"
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_bytes(b"mock video")
    settings.artifacts_dir = str(artifact_root)
    owner_asset.status = AssetStatus.succeeded
    owner_asset.artifact_path = "owner/mock.mp4"
    owner_asset.mime_type = "video/mp4"
    for asset in owner_scene.assets:
        asset.status = AssetStatus.succeeded
    db_session.commit()

    owner_events = client.get(f"/api/v1/scenes/{scene_id}/events")
    assert owner_events.status_code == 200
    assert "event: scene.update" in owner_events.text
    assert "event: scene.completed" in owner_events.text

    other = TestClient(app)
    _register(other, "other@example.com")
    assert other.get(f"/api/v1/scenes/{scene_id}").status_code == 404
    assert other.get(f"/api/v1/scenes/{scene_id}/events").status_code == 404
    assert other.get(f"/api/v1/artifacts/{owner_asset.id}").status_code == 404

    owned_artifact = client.get(f"/api/v1/artifacts/{owner_asset.id}")
    assert owned_artifact.status_code == 200
    assert owned_artifact.headers["content-type"].startswith("video/mp4")
    ranged_artifact = client.get(
        f"/api/v1/artifacts/{owner_asset.id}", headers={"Range": "bytes=0-3"}
    )
    assert ranged_artifact.status_code == 206
    assert ranged_artifact.headers["content-range"].startswith("bytes 0-3/")


def test_protected_routes_require_authentication(client):
    assert client.get("/api/v1/scenes").status_code == 401
    assert client.get("/api/v1/artifacts/1").status_code == 401

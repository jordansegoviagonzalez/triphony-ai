from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import (
    Scene, Asset, AssetType, AssetStatus, SceneStatus, User, FinalRenderRecord, OutboxEventStatus,
    WorkflowStateRecord,
)
from api.schemas import (
    AssetOut,
    RegenerateRequest,
    SceneCreateRequest,
    SceneCreateResponse,
    SceneOut,
    FinalRenderOut,
    SessionResponse,
    UserCreate,
    UserOut,
)
from api.auth import (
    clear_auth_cookie,
    create_access_token,
    get_current_user,
    get_password_hash,
    require_trusted_origin,
    set_auth_cookie,
    set_csrf_cookie,
    verify_password,
)
from api.governance import RedisGovernance, add_outbox_event, correlation_id, record_audit, safe_prompt_fingerprint, safety_gate
from api.settings import settings
from triphony_lib.storage import ArtifactStoreError, S3ArtifactStore

router = APIRouter(prefix="/api/v1")

# --- Authentication Routes ---

@router.post("/auth/register", response_model=SessionResponse, dependencies=[Depends(require_trusted_origin)])
def register_user(user_in: UserCreate, response: Response, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user_in.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user_in.password)
    new_user = User(email=user_in.email, name=user_in.name, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = create_access_token(
        data={"sub": new_user.id}, expires_delta=timedelta(minutes=60 * 24 * 7)
    )
    set_auth_cookie(response, access_token)
    set_csrf_cookie(response)
    record_audit(db, actor_user_id=new_user.id, event_type="login_success", resource_type="user", resource_id=new_user.id, correlation=correlation_id(), outcome="success")
    db.commit()
    return {"user": new_user}


@router.post("/auth/login", response_model=SessionResponse, dependencies=[Depends(require_trusted_origin)])
def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        record_audit(db, actor_user_id=user.id if user else None, event_type="login_failure", resource_type="user", resource_id=user.id if user else "unknown", correlation=correlation_id(), outcome="rejected")
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=timedelta(minutes=60 * 24 * 7)
    )
    set_auth_cookie(response, access_token)
    set_csrf_cookie(response)
    record_audit(db, actor_user_id=user.id, event_type="login_success", resource_type="user", resource_id=user.id, correlation=correlation_id(), outcome="success")
    db.commit()
    return {"user": user}


@router.post("/auth/logout", dependencies=[Depends(require_trusted_origin)])
def logout(response: Response) -> dict[str, bool]:
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
def current_user(user: User = Depends(get_current_user)) -> User:
    return user

# --- Scene Routes ---

def _scene_to_out(scene: Scene) -> SceneOut:
    final_render = next(
        (render for render in sorted(scene.final_renders, key=lambda item: item.version, reverse=True)
         if render.status.value == "succeeded"),
        None,
    )
    return SceneOut(
        scene_id=scene.id,
        prompt=scene.prompt,
        status=scene.status.value,
        created_at=scene.created_at,
        workflow_state=scene.workflow_state.value,
        assets=[
            AssetOut(
                id=a.id,
                asset_type=a.asset_type.value,
                version=a.version,
                status=a.status.value,
                content_text=a.content_text,
                artifact_url=(f"/api/v1/artifacts/{a.id}" if a.artifact_path else None),
                mime_type=a.mime_type,
                error=a.error,
            )
            for a in sorted(scene.assets, key=lambda x: x.asset_type.value)
        ],
        final_render=(
            FinalRenderOut(
                id=final_render.id,
                version=final_render.version,
                status=final_render.status.value,
                artifact_url=f"/api/v1/final-renders/{final_render.id}",
                mime_type=final_render.mime_type,
                duration_ms=final_render.duration_ms,
            )
            if final_render else None
        ),
    )


def _refresh_scene_status(scene: Scene) -> None:
    statuses = [asset.status for asset in scene.assets]
    if any(asset_status == AssetStatus.failed for asset_status in statuses):
        scene.status = SceneStatus.failed
    elif statuses and all(asset_status == AssetStatus.succeeded for asset_status in statuses):
        scene.status = SceneStatus.done
    elif statuses and all(asset_status == AssetStatus.pending for asset_status in statuses):
        scene.status = SceneStatus.queued
    else:
        scene.status = SceneStatus.running


@router.post("/scenes", response_model=SceneCreateResponse)
def create_scene(
    payload: SceneCreateRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_trusted_origin),
) -> SceneCreateResponse:
    from shared.celery_app import celery_app

    import uuid

    allowed, reason = safety_gate(payload.prompt)
    request_correlation = correlation_id()
    if not allowed:
        record_audit(db, actor_user_id=current_user.id, event_type="scene_submission", resource_type="scene", resource_id="rejected", correlation=request_correlation, outcome="rejected", metadata={"reason": reason, "prompt_sha256": safe_prompt_fingerprint(payload.prompt)})
        db.commit()
        raise HTTPException(status_code=422, detail={"code": "unsafe_content", "message": "Prompt did not pass the content-safety gate"})
    try:
        allowed, reason, retry_after = RedisGovernance().check_submission(current_user.id, prompt=payload.prompt)
    except RuntimeError as error:
        record_audit(db, actor_user_id=current_user.id, event_type="rate_quota_rejection", resource_type="user", resource_id=current_user.id, correlation=request_correlation, outcome="unavailable")
        db.commit()
        raise HTTPException(status_code=503, detail={"code": "governance_unavailable", "message": "Usage controls are temporarily unavailable"}) from error
    if not allowed:
        record_audit(db, actor_user_id=current_user.id, event_type="rate_quota_rejection", resource_type="user", resource_id=current_user.id, correlation=request_correlation, outcome="rejected", metadata={"reason": reason})
        db.commit()
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        raise HTTPException(status_code=429, detail={"code": reason, "message": "Generation limit reached"}, headers=headers)

    scene_id = str(uuid.uuid4())
    # Link the scene to the authenticated user
    scene = Scene(id=scene_id, prompt=payload.prompt, status=SceneStatus.queued, user_id=current_user.id)

    # Assets created upfront so UI can show placeholders instantly.
    scene.assets = [
        Asset(asset_type=AssetType.soundtrack, status=AssetStatus.pending, version=1),
        Asset(asset_type=AssetType.visual, status=AssetStatus.pending, version=1),
        Asset(asset_type=AssetType.narrative, status=AssetStatus.pending, version=1),
    ]

    db.add(scene)
    outbox_event = add_outbox_event(db, event_key=f"scene:{scene_id}:start", event_type="scene.workflow.start", payload={"scene_id": scene_id}, correlation=request_correlation)
    record_audit(db, actor_user_id=current_user.id, event_type="scene_submission", resource_type="scene", resource_id=scene_id, correlation=request_correlation, outcome="accepted")
    db.commit()

    try:
        celery_app.send_task(
            "worker.tasks.start_scene_workflow",
            args=[scene_id],
            task_id=outbox_event.event_key,
            headers={"correlation_id": request_correlation},
        )
        outbox_event.status = OutboxEventStatus.published
        outbox_event.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    except Exception:
        outbox_event.attempts += 1
        outbox_event.last_error = "broker publication failed"
        db.commit()

    return SceneCreateResponse(scene_id=scene_id)


@router.post("/scenes/{scene_id}/cancel")
def cancel_scene(scene_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), _: None = Depends(require_trusted_origin)) -> dict[str, bool]:
    scene = db.query(Scene).filter(Scene.id == scene_id, Scene.user_id == current_user.id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    if scene.workflow_state is WorkflowStateRecord.completed or scene.status is SceneStatus.done:
        raise HTTPException(status_code=409, detail={"code": "workflow_already_completed", "message": "Completed workflows cannot be cancelled"})
    if scene.workflow_state is WorkflowStateRecord.cancelled:
        return {"ok": True}
    scene.workflow_state = WorkflowStateRecord.cancelled
    scene.status = SceneStatus.failed
    scene.workflow_error = {"code": "workflow_cancelled", "message": "Cancelled by the scene owner"}
    record_audit(db, actor_user_id=current_user.id, event_type="workflow_cancellation", resource_type="scene", resource_id=scene_id, correlation=correlation_id(), outcome="success")
    db.commit()
    try:
        from shared.celery_app import celery_app
        celery_app.control.revoke(f"scene:{scene_id}:start", terminate=False)
        celery_app.send_task("worker.tasks.cancel_scene_workflow", args=[scene_id], task_id=f"cancel:{scene_id}", headers={"correlation_id": scene_id})
    except Exception:
        pass
    return {"ok": True}


@router.get("/scenes/{scene_id}", response_model=SceneOut)
def get_scene(scene_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> SceneOut:
    scene = db.query(Scene).filter(Scene.id == scene_id, Scene.user_id == current_user.id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return _scene_to_out(scene)


@router.get("/scenes", response_model=list[SceneOut])
def list_scenes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[SceneOut]:
    scenes = db.query(Scene).filter(Scene.user_id == current_user.id).order_by(Scene.created_at.desc()).limit(50).all()
    return [_scene_to_out(s) for s in scenes]


@router.post("/scenes/{scene_id}/regenerate")
def regenerate(
    scene_id: str,
    payload: RegenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_trusted_origin),
) -> dict[str, bool]:
    from shared.celery_app import celery_app

    scene = db.query(Scene).filter(Scene.id == scene_id, Scene.user_id == current_user.id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    # Mark the legacy presentation slot as pending, then let the durable
    # workflow create new immutable asset versions and a new final render.
    was_regenerating = scene.workflow_state is WorkflowStateRecord.regenerating
    asset = next((a for a in scene.assets if a.asset_type.value == payload.asset_type), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.version += 1
    asset.status = AssetStatus.pending
    asset.artifact_path = None
    asset.mime_type = None
    asset.content_text = None
    asset.error = None
    scene.workflow_state = WorkflowStateRecord.regenerating
    scene.status = SceneStatus.running
    scene.workflow_error = None
    db.commit()

    if not was_regenerating:
        celery_app.send_task("worker.tasks.start_scene_workflow", args=[scene_id], headers={"correlation_id": correlation_id()})
    return {"ok": True}


@router.get("/scenes/{scene_id}/events")
async def scene_events(scene_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> StreamingResponse:
    # Simple SSE: poll DB and emit state changes. Cheap + reliable for a portfolio demo.
    if not db.query(Scene).filter(Scene.id == scene_id, Scene.user_id == current_user.id).first():
        raise HTTPException(status_code=404, detail="Scene not found")

    async def gen() -> AsyncGenerator[bytes, None]:
        last = None
        try:
            while True:
                db.expire_all()
                scene = db.query(Scene).filter(
                    Scene.id == scene_id, Scene.user_id == current_user.id
                ).first()
                if not scene:
                    return

                snapshot = [scene.workflow_state.value] + [
                    (a.asset_type.value, a.status.value, a.version) for a in scene.assets
                ]
                if snapshot != last:
                    last = snapshot
                    yield b"retry: 1500\n\n"
                    yield b"event: scene.update\n"
                    yield (
                        "data: " + _scene_to_out(scene).model_dump_json() + "\n\n"
                    ).encode("utf-8")

                    legacy_complete = (
                        scene.workflow_state.value == "queued"
                        and bool(scene.assets)
                        and all(asset.status is AssetStatus.succeeded for asset in scene.assets)
                    )
                    if scene.workflow_state.value in ("completed", "failed", "cancelled") or scene.status in {
                        SceneStatus.done, SceneStatus.failed
                    } or legacy_complete:
                        yield b"event: scene.completed\ndata: {}\n\n"
                        return

                await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/final-renders/{render_id}")
def get_final_render(render_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    render = (
        db.query(FinalRenderRecord)
        .join(Scene, FinalRenderRecord.scene_id == Scene.id)
        .filter(FinalRenderRecord.id == render_id, Scene.user_id == current_user.id)
        .first()
    )
    if not render or render.status.value != "succeeded" or not render.artifact_uri:
        record_audit(db, actor_user_id=current_user.id, event_type="artifact_access_denied", resource_type="final_render", resource_id=render_id, correlation=correlation_id(), outcome="rejected")
        db.commit()
        raise HTTPException(status_code=404, detail="Final render not found")
    if settings.artifact_storage_backend == "s3":
        try:
            store = S3ArtifactStore(
                bucket=settings.s3_bucket or "", region=settings.aws_region, prefix=settings.s3_key_prefix,
                encryption=settings.s3_server_side_encryption, kms_key_id=settings.s3_kms_key_id,
                max_object_size=settings.max_artifact_bytes, multipart_threshold_bytes=settings.s3_multipart_threshold_bytes,
            )
            return RedirectResponse(store.signed_get_url(render.artifact_uri, expires_in=settings.s3_presigned_url_expiration), status_code=307)
        except ArtifactStoreError as error:
            raise HTTPException(status_code=404, detail="Final render not found") from error
    base = pathlib.Path(settings.artifacts_dir).resolve()
    target = (base / render.artifact_uri).resolve()
    if not target.is_relative_to(base) or not target.is_file() or target.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Final render not found")
    return FileResponse(target, media_type=render.mime_type)


@router.get("/artifacts/{asset_id}")
def get_artifact(asset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    asset = (
        db.query(Asset)
        .join(Scene, Asset.scene_id == Scene.id)
        .filter(Asset.id == asset_id, Scene.user_id == current_user.id)
        .first()
    )
    if not asset or not asset.artifact_path:
        record_audit(db, actor_user_id=current_user.id, event_type="artifact_access_denied", resource_type="asset", resource_id=str(asset_id), correlation=correlation_id(), outcome="rejected")
        db.commit()
        raise HTTPException(status_code=404, detail="Artifact not found")

    if settings.artifact_storage_backend == "s3":
        try:
            store = S3ArtifactStore(
                bucket=settings.s3_bucket or "", region=settings.aws_region, prefix=settings.s3_key_prefix,
                encryption=settings.s3_server_side_encryption, kms_key_id=settings.s3_kms_key_id,
                max_object_size=settings.max_artifact_bytes, multipart_threshold_bytes=settings.s3_multipart_threshold_bytes,
            )
            return RedirectResponse(store.signed_get_url(asset.artifact_path, expires_in=settings.s3_presigned_url_expiration), status_code=307)
        except ArtifactStoreError as error:
            raise HTTPException(status_code=404, detail="Artifact not found") from error

    base = pathlib.Path(settings.artifacts_dir).resolve()
    target = (base / asset.artifact_path).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    if not target.is_file() or target.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(target, media_type=asset.mime_type or "application/octet-stream")

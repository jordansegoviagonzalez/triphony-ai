from __future__ import annotations

import asyncio
import os
import pathlib
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from api.db import get_db, engine, Base
from api.models import Scene, Asset, AssetType, AssetStatus, SceneStatus, User
from api.schemas import SceneCreateRequest, SceneCreateResponse, SceneOut, AssetOut, RegenerateRequest, UserCreate, UserOut, Token
from api.auth import get_current_user, get_password_hash, verify_password, create_access_token
from api.settings import settings

# Create tables automatically for dev/demo.
Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/api/v1")

# --- Authentication Routes ---

@router.post("/auth/register", response_model=Token)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user_in.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user_in.password)
    new_user = User(email=user_in.email, name=user_in.name, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = create_access_token(data={"sub": new_user.id})
    return {"access_token": access_token, "token_type": "bearer", "user": new_user}


@router.post("/auth/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.id})
    return {"access_token": access_token, "token_type": "bearer", "user": user}

# --- Scene Routes ---

def _scene_to_out(scene: Scene) -> SceneOut:
    return SceneOut(
        scene_id=scene.id,
        prompt=scene.prompt,
        status=scene.status.value,
        created_at=scene.created_at,
        assets=[
            AssetOut(
                id=a.id,
                asset_type=a.asset_type.value,
                version=a.version,
                status=a.status.value,
                content_text=a.content_text,
                artifact_path=a.artifact_path,
                error=a.error,
            )
            for a in sorted(scene.assets, key=lambda x: x.asset_type.value)
        ],
    )


@router.post("/scenes", response_model=SceneCreateResponse)
def create_scene(
    payload: SceneCreateRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> SceneCreateResponse:
    from shared.celery_app import celery_app

    import uuid

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
    db.commit()

    # Fan-out tasks (mock by default). This is the “pipeline runner” shape.
    celery_app.send_task("worker.tasks.generate_asset", args=[scene_id, "narrative"])
    celery_app.send_task("worker.tasks.generate_asset", args=[scene_id, "visual"])
    celery_app.send_task("worker.tasks.generate_asset", args=[scene_id, "soundtrack"])

    return SceneCreateResponse(scene_id=scene_id)


@router.get("/scenes/{scene_id}", response_model=SceneOut)
def get_scene(scene_id: str, db: Session = Depends(get_db)) -> SceneOut:
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return _scene_to_out(scene)


@router.get("/scenes", response_model=list[SceneOut])
def list_scenes(db: Session = Depends(get_db)) -> list[SceneOut]:
    scenes = db.query(Scene).order_by(Scene.created_at.desc()).limit(50).all()
    return [_scene_to_out(s) for s in scenes]


@router.post("/scenes/{scene_id}/regenerate")
def regenerate(scene_id: str, payload: RegenerateRequest, db: Session = Depends(get_db)) -> dict:
    from worker.celery_app import celery_app

    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    # Mark asset back to pending and bump version (enterprise-friendly “immutable artifact” pattern).
    asset = next((a for a in scene.assets if a.asset_type.value == payload.asset_type), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.version += 1
    asset.status = AssetStatus.pending
    asset.error = None
    db.commit()

    celery_app.send_task("worker.tasks.generate_asset", args=[scene_id, payload.asset_type])
    return {"ok": True}


@router.get("/scenes/{scene_id}/events")
async def scene_events(scene_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    # Simple SSE: poll DB and emit state changes. Cheap + reliable for a portfolio demo.
    async def gen() -> AsyncGenerator[bytes, None]:
        last = None
        while True:
            db.expire_all()
            scene = db.query(Scene).filter(Scene.id == scene_id).first()
            if not scene:
                yield b'event: error\ndata: {"message":"Scene not found"}\n\n'
                return

            snapshot = [(a.asset_type.value, a.status.value, a.version) for a in scene.assets]
            if snapshot != last:
                last = snapshot
                yield b"event: scene.update\n"
                yield ("data: " + _scene_to_out(scene).model_dump_json() + "\n\n").encode("utf-8")

                if all(s in ("succeeded", "failed") for _, s, _ in snapshot):
                    yield b"event: scene.completed\ndata: {}\n\n"
                    return

            await asyncio.sleep(0.8)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/artifacts")
def get_artifact(path: str) -> Response:
    # Prevent path traversal. Only allow artifacts_dir subtree.
    base = pathlib.Path(settings.artifacts_dir).resolve()
    target = (base / path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(target)

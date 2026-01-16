from __future__ import annotations

import pathlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.settings import settings
from api.models import Scene, Asset, AssetStatus, SceneStatus
from shared.celery_app import celery_app

# Import the new ML Intelligence Layer
from triphony_lib.contracts import GenerationRequest, GenerationResult
from triphony_lib.pipeline import Pipeline

# Worker connects directly to DB (same URL as API).
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _artifact_rel(path: pathlib.Path) -> str:
    # Store relative-to-artifacts dir for portability.
    base = pathlib.Path(settings.artifacts_dir).resolve()
    try:
        return str(path.resolve().relative_to(base))
    except ValueError:
        # Fallback if path is not relative to base (e.g. temp dir)
        return str(path)


def _update_scene_status(db, scene: Scene) -> None:
    statuses = [a.status for a in scene.assets]
    if any(s == AssetStatus.failed for s in statuses):
        scene.status = SceneStatus.failed
    elif all(s == AssetStatus.succeeded for s in statuses):
        scene.status = SceneStatus.done
    else:
        scene.status = SceneStatus.running


def _artifact_path_for(scene_id: str, asset_type: str, version: int) -> pathlib.Path:
    # We construct the *directory* where we want the output.
    # The pipeline decides the filename/extension.
    base = pathlib.Path(settings.artifacts_dir) / scene_id / asset_type
    _ensure_dir(base)
    return base


@celery_app.task(name="worker.tasks.generate_asset")
def generate_asset(scene_id: str, asset_type: str) -> None:
    db = SessionLocal()
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            return

        asset = next((a for a in scene.assets if a.asset_type.value == asset_type), None)
        if not asset:
            return

        # 1. Update Status to Running
        asset.status = AssetStatus.running
        asset.error = None
        _update_scene_status(db, scene)
        db.commit()

        # 2. Prepare Request for the Intelligence Layer
        output_dir = _artifact_path_for(scene_id, asset_type, asset.version)
        
        req = GenerationRequest(
            job_id=f"{scene_id}-{asset_type}-{asset.version}",
            prompt=scene.prompt,
            asset_type=asset_type,
            provider_mode=settings.provider_mode,
            api_key=settings.video_generation_api_key if asset_type == "visual" else None,
            output_dir=str(output_dir)
        )

        # 3. Execute Pipeline (Decoupled from DB)
        pipeline = Pipeline()
        result: GenerationResult = pipeline.run(req)

        # 4. Handle Result & Update DB
        if result.success:
            asset.status = AssetStatus.succeeded
            if result.content_text:
                asset.content_text = result.content_text
            
            if result.artifact_path:
                # The pipeline returns the filename relative to output_dir, 
                # or the full path. We want to store the project-relative path.
                full_path = output_dir / result.artifact_path
                asset.artifact_path = _artifact_rel(full_path)
        else:
            asset.status = AssetStatus.failed
            asset.error = result.error_message

        _update_scene_status(db, scene)
        db.commit()

    except Exception as e:
        try:
            # best-effort update
            scene = db.query(Scene).filter(Scene.id == scene_id).first()
            if scene:
                asset = next((a for a in scene.assets if a.asset_type.value == asset_type), None)
                if asset:
                    asset.status = AssetStatus.failed
                    asset.error = f"System Error: {str(e)}"
                _update_scene_status(db, scene)
                db.commit()
        finally:
            pass
    finally:
        db.close()

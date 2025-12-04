from __future__ import annotations

import os
import pathlib
import random
import uuid
import wave
import struct
import math
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.settings import settings
from api.models import Scene, Asset, AssetType, AssetStatus, SceneStatus

# Worker connects directly to DB (same URL as API).
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _artifact_rel(path: pathlib.Path) -> str:
    # Store relative-to-artifacts dir for portability.
    base = pathlib.Path(settings.artifacts_dir).resolve()
    return str(path.resolve().relative_to(base))


def _render_mock_visual(out_path: pathlib.Path, prompt: str) -> None:
    # Generates high-fidelity placeholder assets to validate UI state handling without incurring API costs.
    W, H = 768, 1024
    img = Image.new("RGB", (W, H), (12, 14, 20))
    d = ImageDraw.Draw(img)

    # Neon gradient bars
    for i in range(0, H, 16):
        r = int(30 + 40 * math.sin(i / 60))
        g = int(20 + 35 * math.sin(i / 80 + 1))
        b = int(40 + 60 * math.sin(i / 90 + 2))
        d.rectangle([0, i, W, i + 16], fill=(r, g, b))

    # Center “frame”
    margin = 90
    d.rounded_rectangle([margin, 140, W - margin, H - 170], radius=28, outline=(255, 255, 255, 60), width=2)

    # Caption
    caption = (prompt[:72] + "…") if len(prompt) > 72 else prompt
    caption = caption or "Neon rain, cinematic mood"
    d.text((margin, H - 140), f"Concept Frame", fill=(230, 230, 230))
    d.text((margin, H - 110), caption, fill=(180, 180, 190))

    img.save(out_path)


def _render_mock_wav(out_path: pathlib.Path, seconds: float = 3.2, sr: int = 44100) -> None:
    n = int(seconds * sr)
    freq = 220.0 + random.random() * 40
    amp = 0.2

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)

        for i in range(n):
            t = i / sr
            sample = amp * math.sin(2 * math.pi * freq * t) + 0.02 * (random.random() * 2 - 1)
            s = int(max(-1, min(1, sample)) * 32767)
            wf.writeframes(struct.pack("<h", s))


def _mock_narrative(prompt: str) -> str:
    # Synthesizes a thematic narrative structure for testing text layout components.
    base = [
        "Rain-soaked streets, aglow in neon light.",
        "Tokyo dreams shimmer in the night.",
        "Umbrella silhouettes passing by,",
        "Reflections dance as raindrops sigh.",
    ]
    if prompt:
        base.insert(0, f"Prompt: {prompt.strip()}")
    return "\n".join(base)


def _update_scene_status(db, scene: Scene) -> None:
    statuses = [a.status for a in scene.assets]
    if any(s == AssetStatus.failed for s in statuses):
        scene.status = SceneStatus.failed
    elif all(s == AssetStatus.succeeded for s in statuses):
        scene.status = SceneStatus.done
    else:
        scene.status = SceneStatus.running


def _artifact_path_for(scene_id: str, asset_type: str, version: int, ext: str) -> pathlib.Path:
    base = pathlib.Path(settings.artifacts_dir) / scene_id / asset_type
    _ensure_dir(base)
    return base / f"v{version}.{ext}"


import requests
from shared.celery_app import celery_app


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

        asset.status = AssetStatus.running
        asset.error = None
        _update_scene_status(db, scene)
        db.commit()

        if asset_type == "narrative":
            asset.content_text = _mock_narrative(scene.prompt)
            asset.artifact_path = None
            asset.status = AssetStatus.succeeded

        elif asset_type == "visual":
            # Real provider generation for cinematic video
            if settings.provider_mode == "real" and settings.video_generation_api_key:
                # Decide on your output format (e.g., mp4 for video)
                out = _artifact_path_for(scene_id, "visual", asset.version, "mp4")

                try:
                    # Offload generation to Hugging Face Inference API.
                    # Model: damo-vilab/text-to-video-ms-1.7b (Optimized for short-form cinematic clips)
                    
                    model_id = "damo-vilab/text-to-video-ms-1.7b"
                    api_endpoint = f"https://api-inference.huggingface.co/models/{model_id}"
                    
                    headers = {
                        "Authorization": f"Bearer {settings.video_generation_api_key}",
                        "Content-Type": "application/json",
                    }
                    # The model expects "inputs" as the key for the prompt
                    payload = {
                        "inputs": scene.prompt,
                    }

                    # Execute external inference request
                    response = requests.post(api_endpoint, headers=headers, json=payload, timeout=120)
                    response.raise_for_status()

                    # Stream binary response directly to artifacts storage
                    with open(out, "wb") as f:
                        f.write(response.content)

                    asset.artifact_path = _artifact_rel(out)
                    asset.status = AssetStatus.succeeded

                except requests.RequestException as e:
                    asset.status = AssetStatus.failed
                    asset.error = f"API Error: {e}"
                    # Log detailed upstream error for debugging
                    if hasattr(e, 'response') and e.response:
                         print(f"API Response Error Content: {e.response.text}")

            else:
                # Mock generation (no keys required).
                out = _artifact_path_for(scene_id, "visual", asset.version, "png")
                _render_mock_visual(out, scene.prompt)
                asset.artifact_path = _artifact_rel(out)
                asset.status = AssetStatus.succeeded

        elif asset_type == "soundtrack":
            out = _artifact_path_for(scene_id, "soundtrack", asset.version, "wav")
            _render_mock_wav(out)
            asset.artifact_path = _artifact_rel(out)
            asset.status = AssetStatus.succeeded

        else:
            asset.status = AssetStatus.failed
            asset.error = f"Unknown asset_type: {asset_type}"

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
                    asset.error = str(e)
                _update_scene_status(db, scene)
                db.commit()
        finally:
            pass
    finally:
        db.close()

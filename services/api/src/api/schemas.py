from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal


AssetType = Literal["narrative", "visual", "soundtrack"]
AssetStatus = Literal["pending", "running", "succeeded", "failed"]
SceneStatus = Literal["queued", "running", "done", "failed"]


class SceneCreateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)


class RegenerateRequest(BaseModel):
    asset_type: AssetType


class AssetOut(BaseModel):
    id: int
    asset_type: AssetType
    version: int
    status: AssetStatus
    content_text: str | None = None
    artifact_path: str | None = None
    error: str | None = None


class SceneOut(BaseModel):
    scene_id: str
    prompt: str
    status: SceneStatus
    created_at: datetime
    assets: list[AssetOut]


class SceneCreateResponse(BaseModel):
    scene_id: str

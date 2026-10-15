from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


AssetType = Literal["narrative", "visual", "soundtrack"]
AssetStatus = Literal["pending", "running", "succeeded", "failed"]
SceneStatus = Literal["queued", "running", "done", "failed"]
WorkflowState = Literal[
    "queued", "planning", "generating", "technical_qa", "agent_qa", "regenerating",
    "assembling", "final_qa", "completed", "failed", "cancelled"
]


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
    artifact_url: str | None = None
    mime_type: str | None = None
    error: str | None = None


class FinalRenderOut(BaseModel):
    id: str
    version: int
    status: Literal["pending", "succeeded", "failed"]
    artifact_url: str | None = None
    mime_type: str
    duration_ms: int | None = None


class SceneOut(BaseModel):
    scene_id: str
    prompt: str
    status: SceneStatus
    created_at: datetime
    workflow_state: WorkflowState
    assets: list[AssetOut]
    final_render: FinalRenderOut | None = None


class SceneCreateResponse(BaseModel):
    scene_id: str


class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    user: UserOut

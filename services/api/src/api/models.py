from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import String, DateTime, Enum, Integer, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


class SceneStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class AssetType(str, enum.Enum):
    narrative = "narrative"
    visual = "visual"
    soundtrack = "soundtrack"


class AssetStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SceneStatus] = mapped_column(Enum(SceneStatus), default=SceneStatus.queued, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    assets: Mapped[list["Asset"]] = relationship(back_populates="scene", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_scenes_created_at", "created_at"),
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True, nullable=False)

    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[AssetStatus] = mapped_column(Enum(AssetStatus), default=AssetStatus.pending, nullable=False)

    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    scene: Mapped["Scene"] = relationship(back_populates="assets")

    __table_args__ = (
        Index("ix_assets_scene_type", "scene_id", "asset_type"),
    )

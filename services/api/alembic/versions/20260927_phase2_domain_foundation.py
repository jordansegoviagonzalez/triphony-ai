"""Add provider-neutral Phase 2 domain foundation.

Revision ID: 20260927phase2
Revises: 20260927mime
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260927phase2"
down_revision: Union[str, Sequence[str], None] = "20260927mime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    scene_plan_status = sa.Enum("draft", "approved", "superseded", name="sceneplanstatus")
    provider_job_status = sa.Enum(
        "created", "queued", "running", "succeeded", "failed", "cancelled", name="providerjobrecordstatus"
    )
    attempt_status = sa.Enum(
        "started", "succeeded", "failed", "cancelled", name="providerjobattemptrecordstatus"
    )
    asset_version_status = sa.Enum(
        "draft", "approved", "rejected", "superseded", name="assetversionrecordstatus"
    )
    qa_status = sa.Enum("passed", "failed", name="qarecordstatus")
    qa_recommendation = sa.Enum("approve", "retry", "reject", name="qarecordrecommendation")
    final_render_status = sa.Enum("pending", "succeeded", "failed", name="finalrenderrecordstatus")

    op.create_table(
        "scene_plans",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("status", scene_plan_status, nullable=False),
        sa.Column("output_requirements", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id", "version", name="uq_scene_plans_scene_version"),
    )
    op.create_index("ix_scene_plans_scene_id", "scene_plans", ["scene_id"], unique=False)
    op.create_index("ix_scene_plans_scene_status", "scene_plans", ["scene_id", "status"], unique=False)

    op.create_table(
        "shots",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scene_plan_id", sa.String(length=128), nullable=False),
        sa.Column("shot_order", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("narrative_direction", sa.JSON(), nullable=False),
        sa.Column("visual_direction", sa.JSON(), nullable=False),
        sa.Column("camera_direction", sa.JSON(), nullable=False),
        sa.Column("audio_direction", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["scene_plan_id"], ["scene_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_plan_id", "shot_order", name="uq_shots_plan_order"),
        sa.CheckConstraint("shot_order > 0", name="ck_shots_order_positive"),
        sa.CheckConstraint("start_ms >= 0", name="ck_shots_start_nonnegative"),
        sa.CheckConstraint("duration_ms > 0", name="ck_shots_duration_positive"),
    )
    op.create_index("ix_shots_scene_plan_id", "shots", ["scene_plan_id"], unique=False)
    op.create_index("ix_shots_plan_timing", "shots", ["scene_plan_id", "start_ms"], unique=False)

    op.create_table(
        "provider_jobs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("status", provider_job_status, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("provider_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_provider_jobs_idempotency_key"),
    )
    op.create_index("ix_provider_jobs_scene_id", "provider_jobs", ["scene_id"], unique=False)

    op.create_table(
        "provider_job_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_job_id", sa.String(length=128), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", attempt_status, nullable=False),
        sa.Column("provider_job_identifier", sa.String(length=255), nullable=True),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_job_id"], ["provider_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_job_id", "attempt_number", name="uq_provider_job_attempt_number"),
        sa.CheckConstraint("attempt_number > 0", name="ck_provider_job_attempt_positive"),
    )
    op.create_index("ix_provider_job_attempts_provider_job_id", "provider_job_attempts", ["provider_job_id"], unique=False)

    op.create_table(
        "asset_versions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("status", asset_version_status, nullable=False),
        sa.Column("artifact_uri", sa.String(length=1000), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id", "media_type", "version", name="uq_asset_versions_scene_media_version"),
        sa.CheckConstraint("version > 0", name="ck_asset_versions_version_positive"),
    )
    op.create_index("ix_asset_versions_scene_id", "asset_versions", ["scene_id"], unique=False)
    op.create_index("ix_asset_versions_asset_id", "asset_versions", ["asset_id"], unique=False)
    op.create_index("ix_asset_versions_scene_status", "asset_versions", ["scene_id", "status"], unique=False)

    op.create_table(
        "qa_evaluations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("status", qa_status, nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("recommendation", qa_recommendation, nullable=False),
        sa.Column("evaluated_asset_version_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_qa_evaluations_score_range"),
    )
    op.create_index("ix_qa_evaluations_scene_id", "qa_evaluations", ["scene_id"], unique=False)

    op.create_table(
        "qa_findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evaluation_id", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("shot_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["evaluation_id"], ["qa_evaluations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_findings_evaluation_id", "qa_findings", ["evaluation_id"], unique=False)

    op.create_table(
        "final_renders",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", final_render_status, nullable=False),
        sa.Column("artifact_uri", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("source_asset_version_ids", sa.JSON(), nullable=False),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id", "version", name="uq_final_renders_scene_version"),
        sa.CheckConstraint("version > 0", name="ck_final_renders_version_positive"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms > 0", name="ck_final_renders_duration_positive"),
    )
    op.create_index("ix_final_renders_scene_id", "final_renders", ["scene_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_final_renders_scene_id", table_name="final_renders")
    op.drop_table("final_renders")
    op.drop_index("ix_qa_findings_evaluation_id", table_name="qa_findings")
    op.drop_table("qa_findings")
    op.drop_index("ix_qa_evaluations_scene_id", table_name="qa_evaluations")
    op.drop_table("qa_evaluations")
    op.drop_index("ix_asset_versions_scene_status", table_name="asset_versions")
    op.drop_index("ix_asset_versions_asset_id", table_name="asset_versions")
    op.drop_index("ix_asset_versions_scene_id", table_name="asset_versions")
    op.drop_table("asset_versions")
    op.drop_index("ix_provider_job_attempts_provider_job_id", table_name="provider_job_attempts")
    op.drop_table("provider_job_attempts")
    op.drop_index("ix_provider_jobs_scene_id", table_name="provider_jobs")
    op.drop_table("provider_jobs")
    op.drop_index("ix_shots_plan_timing", table_name="shots")
    op.drop_index("ix_shots_scene_plan_id", table_name="shots")
    op.drop_table("shots")
    op.drop_index("ix_scene_plans_scene_status", table_name="scene_plans")
    op.drop_index("ix_scene_plans_scene_id", table_name="scene_plans")
    op.drop_table("scene_plans")

    bind = op.get_bind()
    for enum_type in (
        "finalrenderrecordstatus",
        "qarecordrecommendation",
        "qarecordstatus",
        "assetversionrecordstatus",
        "providerjobattemptrecordstatus",
        "providerjobrecordstatus",
        "sceneplanstatus",
    ):
        sa.Enum(name=enum_type).drop(bind, checkfirst=True)

"""Add Phase 5 outbox, dead-letter, and audit records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260927phase5"
down_revision: Union[str, Sequence[str], None] = "20260927phase4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    outbox_status = sa.Enum("pending", "published", "failed", name="outboxeventstatus")
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("event_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", outbox_status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_outbox_events_dispatch", "outbox_events", ["status", "available_at"])
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("scene_id", sa.String(length=36), sa.ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_job_id", sa.String(length=128), sa.ForeignKey("provider_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_type", sa.String(length=128), nullable=False),
        sa.Column("failure_code", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("replay_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_failed_at", sa.DateTime(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(), nullable=False),
        sa.Column("safe_details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_dead_letters_scene_id", "dead_letters", ["scene_id"])
    op.create_index("ix_dead_letters_provider_job_id", "dead_letters", ["provider_job_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_dead_letters_provider_job_id", table_name="dead_letters")
    op.drop_index("ix_dead_letters_scene_id", table_name="dead_letters")
    op.drop_table("dead_letters")
    op.drop_index("ix_outbox_events_dispatch", table_name="outbox_events")
    op.drop_table("outbox_events")
    sa.Enum(name="outboxeventstatus").drop(op.get_bind(), checkfirst=True)

"""Add durable provider-attempt lineage fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261109phase5"
down_revision: Union[str, Sequence[str], None] = "20260927phase5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "provider_job_attempts",
        sa.Column("provider_name", sa.String(length=128), nullable=False, server_default="unknown"),
    )
    op.add_column("provider_job_attempts", sa.Column("failure_classification", sa.String(length=128), nullable=True))
    op.add_column("provider_job_attempts", sa.Column("fallback_reason", sa.String(length=255), nullable=True))
    op.add_column("provider_job_attempts", sa.Column("previous_attempt_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_provider_job_attempts_previous_attempt_id",
        "provider_job_attempts",
        "provider_job_attempts",
        ["previous_attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_provider_job_attempts_previous_attempt_id",
        "provider_job_attempts",
        ["previous_attempt_id"],
    )
    op.alter_column("provider_job_attempts", "provider_name", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_provider_job_attempts_previous_attempt_id", table_name="provider_job_attempts")
    op.drop_constraint(
        "fk_provider_job_attempts_previous_attempt_id",
        "provider_job_attempts",
        type_="foreignkey",
    )
    op.drop_column("provider_job_attempts", "previous_attempt_id")
    op.drop_column("provider_job_attempts", "fallback_reason")
    op.drop_column("provider_job_attempts", "failure_classification")
    op.drop_column("provider_job_attempts", "provider_name")

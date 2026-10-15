"""Add durable Phase 4 workflow and asset lineage fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260927phase4"
down_revision: Union[str, Sequence[str], None] = "20260927phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    workflow_state = sa.Enum(
        "queued", "planning", "generating", "technical_qa", "agent_qa", "regenerating",
        "assembling", "final_qa", "completed", "failed", "cancelled", name="workflowstaterecord",
    )
    workflow_state.create(op.get_bind(), checkfirst=True)
    op.add_column("scenes", sa.Column("workflow_state", workflow_state, nullable=False, server_default="queued"))
    op.add_column("scenes", sa.Column("workflow_attempt", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scenes", sa.Column("workflow_error", sa.JSON(), nullable=True))
    op.create_index("ix_scenes_workflow_state", "scenes", ["workflow_state"], unique=False)
    op.add_column("asset_versions", sa.Column("parent_id", sa.String(length=128), nullable=True))
    op.add_column("asset_versions", sa.Column("checksum", sa.String(length=128), nullable=True))
    op.add_column("asset_versions", sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.create_foreign_key(
        "fk_asset_versions_parent_id", "asset_versions", "asset_versions", ["parent_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_asset_versions_parent_id", "asset_versions", ["parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_asset_versions_parent_id", table_name="asset_versions")
    op.drop_constraint("fk_asset_versions_parent_id", "asset_versions", type_="foreignkey")
    op.drop_column("asset_versions", "metadata")
    op.drop_column("asset_versions", "checksum")
    op.drop_column("asset_versions", "parent_id")
    op.drop_index("ix_scenes_workflow_state", table_name="scenes")
    op.drop_column("scenes", "workflow_error")
    op.drop_column("scenes", "workflow_attempt")
    op.drop_column("scenes", "workflow_state")
    sa.Enum(name="workflowstaterecord").drop(op.get_bind(), checkfirst=True)

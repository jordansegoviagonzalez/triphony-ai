"""Add MIME metadata for protected artifact delivery.

Revision ID: 20260927mime
Revises: 1228e6887efa
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260927mime"
down_revision: Union[str, Sequence[str], None] = "1228e6887efa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("mime_type", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "mime_type")

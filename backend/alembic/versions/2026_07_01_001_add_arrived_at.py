"""add arrived_at to assignments

Revision ID: 2026_07_01_001
Revises:
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa

revision = "2026_07_01_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(
            sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("arrived_at")

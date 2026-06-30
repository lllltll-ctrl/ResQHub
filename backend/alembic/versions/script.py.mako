"""\${message}"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa  # noqa F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
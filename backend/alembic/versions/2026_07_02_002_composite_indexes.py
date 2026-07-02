"""composite indexes for latest-per-object queries

Додає композитні індекси (object_id, ts) на telemetry і scores.
Без них запити "остання телеметрія/score по кожному об'єкту"
(max(ts) group by object_id) роблять full scan — при десятках тисяч
рядків це 2-3с на запит. З індексами — ~30мс.

Revision ID: 2026_07_02_002
Revises: 2026_07_01_001
Create Date: 2026-07-02
"""

from alembic import op

revision = "2026_07_02_002"
down_revision = "2026_07_01_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_telemetry_object_ts", "telemetry", ["object_id", "ts"], if_not_exists=True
    )
    op.create_index(
        "ix_scores_object_ts", "scores", ["object_id", "ts"], if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index("ix_scores_object_ts", table_name="scores", if_exists=True)
    op.drop_index("ix_telemetry_object_ts", table_name="telemetry", if_exists=True)

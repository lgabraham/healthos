"""intake log

Revision ID: 0004_intake_log
Revises: 0003_calendar_events
Create Date: 2026-06-26

Adds intake_log for the free-text food/med/supplement journal (tagged for
correlation against inflammation biomarkers). Append-only: no unique key.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_intake_log"
down_revision: Union[str, None] = "0003_calendar_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intake_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB()),
        sa.Column("source", sa.String(length=50), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_intake_log_date", "intake_log", ["date"])


def downgrade() -> None:
    op.drop_index("ix_intake_log_date", table_name="intake_log")
    op.drop_table("intake_log")

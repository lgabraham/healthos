"""calendar events

Revision ID: 0003_calendar_events
Revises: 0002_oauth_tokens
Create Date: 2026-06-09

Adds calendar_events for behavioral context from secret .ics feeds.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_calendar_events"
down_revision: Union[str, None] = "0002_oauth_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("uid", sa.String(length=512), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("all_day", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_evening", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("keywords", postgresql.JSONB()),
        sa.Column("source", sa.String(length=50), server_default="ics", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "uid", "start_time", name="uq_calendar_uid_start", postgresql_nulls_not_distinct=True
        ),
    )
    op.create_index("ix_calendar_events_date", "calendar_events", ["date"])


def downgrade() -> None:
    op.drop_index("ix_calendar_events_date", table_name="calendar_events")
    op.drop_table("calendar_events")

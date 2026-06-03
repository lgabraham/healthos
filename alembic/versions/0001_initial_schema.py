"""initial HealthOS schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-03

Creates the five core tables: daily_metrics, sleep_sessions, workouts,
daily_events, sync_log.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("is_canonical", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("date", "metric", "source", name="uq_metric_date_source"),
    )
    op.create_index("ix_daily_metrics_date", "daily_metrics", ["date"])
    op.create_index("ix_daily_metrics_metric", "daily_metrics", ["metric"])

    op.create_table(
        "sleep_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("total_minutes", sa.Integer()),
        sa.Column("rem_minutes", sa.Integer()),
        sa.Column("deep_minutes", sa.Integer()),
        sa.Column("light_minutes", sa.Integer()),
        sa.Column("awake_minutes", sa.Integer()),
        sa.Column("sleep_score", sa.Numeric()),
        sa.Column("stages_json", postgresql.JSONB()),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("is_canonical", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sleep_sessions_date", "sleep_sessions", ["date"])

    op.create_table(
        "workouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("sport_type", sa.String(length=100)),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("hr_avg", sa.Integer()),
        sa.Column("hr_max", sa.Integer()),
        sa.Column("calories", sa.Integer()),
        sa.Column("distance_km", sa.Numeric()),
        sa.Column("tss", sa.Numeric()),
        sa.Column("external_id", sa.String(length=128)),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workouts_date", "workouts", ["date"])
    op.create_index("ix_workouts_external_id", "workouts", ["external_id"])

    op.create_table(
        "daily_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Numeric()),
        sa.Column("confidence", sa.String(length=20)),
        sa.Column("notes", sa.Text()),
        sa.Column("source", sa.String(length=50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("date", "event_type", name="uq_event_date_type"),
    )
    op.create_index("ix_daily_events_date", "daily_events", ["date"])

    op.create_table(
        "sync_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("sync_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_written", sa.BigInteger()),
        sa.Column("error_message", sa.Text()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sync_log")
    op.drop_index("ix_daily_events_date", table_name="daily_events")
    op.drop_table("daily_events")
    op.drop_index("ix_workouts_external_id", table_name="workouts")
    op.drop_index("ix_workouts_date", table_name="workouts")
    op.drop_table("workouts")
    op.drop_index("ix_sleep_sessions_date", table_name="sleep_sessions")
    op.drop_table("sleep_sessions")
    op.drop_index("ix_daily_metrics_metric", table_name="daily_metrics")
    op.drop_index("ix_daily_metrics_date", table_name="daily_metrics")
    op.drop_table("daily_metrics")

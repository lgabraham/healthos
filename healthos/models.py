"""SQLAlchemy ORM models mirroring the HealthOS schema.

Timestamps are stored as timezone-aware UTC. Conversion to the user's local
timezone happens only at the edges (frontend / MCP responses).
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _uuid_col() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (UniqueConstraint("date", "metric", "source", name="uq_metric_date_source"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    date: Mapped[_date] = mapped_column(Date, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SleepSession(Base):
    __tablename__ = "sleep_sessions"

    id: Mapped[uuid.UUID] = _uuid_col()
    date: Mapped[_date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_minutes: Mapped[int | None] = mapped_column(Integer)
    rem_minutes: Mapped[int | None] = mapped_column(Integer)
    deep_minutes: Mapped[int | None] = mapped_column(Integer)
    light_minutes: Mapped[int | None] = mapped_column(Integer)
    awake_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_score: Mapped[float | None] = mapped_column(Numeric)
    stages_json: Mapped[dict | None] = mapped_column(JSONB)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[uuid.UUID] = _uuid_col()
    date: Mapped[_date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sport_type: Mapped[str | None] = mapped_column(String(100))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    hr_avg: Mapped[int | None] = mapped_column(Integer)
    hr_max: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Numeric)
    tss: Mapped[float | None] = mapped_column(Numeric)
    # External provider id, used to dedupe activities on re-sync.
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyEvent(Base):
    __tablename__ = "daily_events"
    __table_args__ = (UniqueConstraint("date", "event_type", name="uq_event_date_type"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    date: Mapped[_date] = mapped_column(Date, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric)
    confidence: Mapped[str | None] = mapped_column(String(20))  # inferred|confirmed|manual
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[uuid.UUID] = _uuid_col()
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)  # daily|backfill|manual
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success|error|partial
    records_written: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

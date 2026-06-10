"""Inbound webhooks (iOS Shortcuts).

Two shapes:
  * /webhooks/ios     — behavioral *events* (screen time, manual tags).
  * /webhooks/metric  — numeric *metrics* (e.g. Apple Health steps), which land
                        in daily_metrics and feed the best-available resolver.

Inputs are coerced leniently — Shortcuts can send repeated lines or stray
formatting — and a metric's date defaults to "today" (local tz) when absent or
unparseable, so the Shortcut only has to send the metric + value.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..database import db_session
from ..models import DailyEvent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _first_line(value) -> str:
    """First non-empty line of a value (Shortcuts sometimes repeats lines)."""
    if value is None:
        return ""
    for line in str(value).splitlines():
        if line.strip():
            return line.strip()
    return ""


def _coerce_date(value, *, default_today: bool) -> _date:
    text = _first_line(value)
    if text:
        try:
            return _date.fromisoformat(text)
        except ValueError:
            pass
    if default_today:
        return datetime.now(settings.tz).date()
    raise HTTPException(status_code=400, detail=f"'date' must be YYYY-MM-DD (got {value!r}).")


def _coerce_float(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = _first_line(value).replace(",", "")
    try:
        return float(text)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"'value' must be a number (got {value!r})."
        ) from None


class IOSEvent(BaseModel):
    event_type: str = Field(..., examples=["elevated_screen_time", "screen_time"])
    value: float | None = Field(default=None, examples=[90])
    date: str = Field(..., examples=["2026-06-03"])
    notes: str | None = None


@router.post("/ios")
def ios_shortcut(payload: IOSEvent, db: Session = Depends(db_session)) -> dict:
    """Accept a JSON event from an iOS Shortcut and upsert it as confirmed."""
    day = _coerce_date(payload.date, default_today=False)
    stmt = (
        pg_insert(DailyEvent)
        .values(
            date=day,
            event_type=payload.event_type,
            value=payload.value,
            confidence="confirmed",
            notes=payload.notes,
            source="ios_shortcut",
        )
        .on_conflict_do_update(
            constraint="uq_event_date_type",
            set_={
                "value": payload.value,
                "confidence": "confirmed",
                "notes": payload.notes,
                "source": "ios_shortcut",
            },
        )
    )
    db.execute(stmt)
    db.commit()
    return {"ok": True, "date": day.isoformat(), "event_type": payload.event_type}


class MetricIngest(BaseModel):
    metric: str = Field(..., examples=["steps"])
    value: float | str = Field(..., examples=[8421])
    date: str | None = Field(default=None, examples=["2026-06-09"])
    unit: str | None = Field(default=None, examples=["steps"])
    source: str = Field(default="apple_health", examples=["apple_health"])


@router.post("/metric")
def ingest_metric(payload: MetricIngest, db: Session = Depends(db_session)) -> dict:
    """Accept a numeric metric from an iOS Shortcut (e.g. Apple Health steps).

    ``date`` defaults to today (local tz) when absent/unparseable, so the
    Shortcut only needs to send the metric + value. Canonical flagging follows
    the usual rules (Apple Health owns steps).
    """
    from ..sync.persistence import MetricPoint, upsert_metrics

    day = _coerce_date(payload.date, default_today=True)
    value = _coerce_float(payload.value)
    upsert_metrics(db, [MetricPoint(day, payload.metric, value, payload.unit, payload.source)])
    db.commit()
    return {
        "ok": True,
        "date": day.isoformat(),
        "metric": payload.metric,
        "value": value,
        "source": payload.source,
    }

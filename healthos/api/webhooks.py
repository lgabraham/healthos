"""Inbound webhooks (iOS Shortcuts).

Two shapes:
  * /webhooks/ios     — behavioral *events* (screen time, manual tags).
  * /webhooks/metric  — numeric *metrics* (e.g. Apple Health steps), which land
                        in daily_metrics and feed the best-available resolver.
"""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..database import db_session
from ..models import DailyEvent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class IOSEvent(BaseModel):
    event_type: str = Field(..., examples=["elevated_screen_time", "screen_time"])
    value: float | None = Field(default=None, examples=[90])
    date: str = Field(..., examples=["2026-06-03"])
    notes: str | None = None


@router.post("/ios")
def ios_shortcut(payload: IOSEvent, db: Session = Depends(db_session)) -> dict:
    """Accept a JSON event from an iOS Shortcut and upsert it as confirmed."""
    day = _date.fromisoformat(payload.date)
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
    return {"ok": True, "date": payload.date, "event_type": payload.event_type}


class MetricIngest(BaseModel):
    metric: str = Field(..., examples=["steps"])
    value: float = Field(..., examples=[8421])
    date: str = Field(..., examples=["2026-06-09"])
    unit: str | None = Field(default=None, examples=["steps"])
    source: str = Field(default="apple_health", examples=["apple_health"])


@router.post("/metric")
def ingest_metric(payload: MetricIngest, db: Session = Depends(db_session)) -> dict:
    """Accept a numeric metric from an iOS Shortcut (e.g. Apple Health steps).

    Canonical flagging follows the usual rules, so e.g. Apple steps stay
    non-canonical (Garmin owns steps) and surface only as a labeled fallback.
    """
    from ..sync.persistence import MetricPoint, upsert_metrics

    day = _date.fromisoformat(payload.date)
    upsert_metrics(
        db, [MetricPoint(day, payload.metric, payload.value, payload.unit, payload.source)]
    )
    db.commit()
    return {
        "ok": True,
        "date": payload.date,
        "metric": payload.metric,
        "value": payload.value,
        "source": payload.source,
    }

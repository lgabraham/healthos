"""Event management: manually log, confirm, or dismiss daily_events.

Inference produces low-confidence guesses; this router is how the user curates
them. Confirming upgrades an inferred event to 'confirmed' (the spec's "until
the user confirms a few times" path for sauna); dismissing removes a false
positive; manual create covers events no device can infer (travel, calendar).
"""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..database import db_session
from ..models import DailyEvent

router = APIRouter(prefix="/api/events", tags=["events"])


class EventIn(BaseModel):
    date: str = Field(..., examples=["2026-06-03"])
    event_type: str = Field(..., examples=["travel", "calendar_heavy_day"])
    value: float | None = Field(default=None, examples=[3])
    notes: str | None = None


class ConfirmIn(BaseModel):
    date: str = Field(..., examples=["2026-06-03"])
    value: float | None = None
    notes: str | None = None


def _event_dict(e: DailyEvent) -> dict:
    return {
        "date": e.date.isoformat(),
        "event_type": e.event_type,
        "value": float(e.value) if e.value is not None else None,
        "confidence": e.confidence,
        "notes": e.notes,
        "source": e.source,
    }


@router.post("")
def create_event(payload: EventIn, db: Session = Depends(db_session)) -> dict:
    """Manually log an event (confidence='manual'). Upserts on (date, type)."""
    day = _date.fromisoformat(payload.date)
    stmt = (
        pg_insert(DailyEvent)
        .values(
            date=day,
            event_type=payload.event_type,
            value=payload.value,
            confidence="manual",
            notes=payload.notes,
            source="manual",
        )
        .on_conflict_do_update(
            constraint="uq_event_date_type",
            set_={
                "value": payload.value,
                "confidence": "manual",
                "notes": payload.notes,
                "source": "manual",
            },
        )
        .returning(DailyEvent)
    )
    event = db.scalars(stmt).one()
    db.commit()
    return _event_dict(event)


@router.post("/{event_type}/confirm")
def confirm_event(
    event_type: str, payload: ConfirmIn, db: Session = Depends(db_session)
) -> dict:
    """Upgrade an inferred event to 'confirmed'. Creates one if none exists
    (e.g. confirming a sauna night the inference missed)."""
    day = _date.fromisoformat(payload.date)
    event = db.scalars(
        select(DailyEvent).where(
            DailyEvent.date == day, DailyEvent.event_type == event_type
        )
    ).first()
    if event is None:
        event = DailyEvent(
            date=day,
            event_type=event_type,
            value=payload.value,
            confidence="confirmed",
            notes=payload.notes,
            source="manual",
        )
        db.add(event)
    else:
        event.confidence = "confirmed"
        if payload.value is not None:
            event.value = payload.value
        if payload.notes is not None:
            event.notes = payload.notes
    db.commit()
    return _event_dict(event)


@router.delete("/{event_type}")
def delete_event(
    event_type: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(db_session),
) -> dict:
    """Dismiss/remove an event (e.g. a false-positive inference)."""
    day = _date.fromisoformat(date)
    event = db.scalars(
        select(DailyEvent).where(
            DailyEvent.date == day, DailyEvent.event_type == event_type
        )
    ).first()
    if event is None:
        raise HTTPException(status_code=404, detail="No such event.")
    db.delete(event)
    db.commit()
    return {"ok": True, "deleted": {"date": date, "event_type": event_type}}

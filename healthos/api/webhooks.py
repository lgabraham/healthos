"""Inbound webhooks (currently just iOS Shortcuts).

iOS Shortcuts POSTs behavioral data we can't infer from devices — screen time,
manual tags — and we record them as high-confidence confirmed events.
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

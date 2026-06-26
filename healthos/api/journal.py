"""Food / medication / supplement journal: free text in, tags out.

A plain-text box (e.g. "2 Advil, glass of red wine, 400mg magnesium") is parsed
into coarse exposure tags by ``intake.tag_intake`` and stored append-only in
intake_log — later correlated against inflammation biomarkers (HRV, resting HR,
respiratory rate, skin temp). The parse is re-run on every write, so editing the
tag vocabulary changes future entries (existing rows keep their stored tags).
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date as _date
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import db_session
from ..intake import tag_intake
from ..models import IntakeLog

router = APIRouter(prefix="/api/journal", tags=["journal"])


class JournalIn(BaseModel):
    text: str = Field(..., examples=["2 Advil, glass of red wine, 400mg magnesium"])
    date: str | None = Field(default=None, examples=["2026-06-26"])  # defaults to today (local)


def _intake_dict(e: IntakeLog) -> dict:
    return {
        "id": str(e.id),
        "date": e.date.isoformat(),
        "text": e.raw_text,
        "tags": e.tags or [],
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.post("")
def create_entry(payload: JournalIn, db: Session = Depends(db_session)) -> dict:
    """Log an entry: parse the text into tags and store it (append-only)."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty entry.")
    day = _date.fromisoformat(payload.date) if payload.date else datetime.now(settings.tz).date()
    entry = IntakeLog(date=day, raw_text=text, tags=tag_intake(text), source="manual")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _intake_dict(entry)


@router.get("")
def list_entries(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(db_session),
) -> list[dict]:
    """Recent entries, newest first."""
    since = datetime.now(settings.tz).date() - timedelta(days=days)
    rows = db.scalars(
        select(IntakeLog).where(IntakeLog.date >= since).order_by(IntakeLog.created_at.desc())
    ).all()
    return [_intake_dict(e) for e in rows]


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, db: Session = Depends(db_session)) -> dict:
    """Remove a single entry by id."""
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad id.") from exc
    entry = db.get(IntakeLog, eid)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such entry.")
    db.delete(entry)
    db.commit()
    return {"ok": True, "deleted": entry_id}

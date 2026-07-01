"""Event management: manual create, confirm (upgrade inferred), dismiss."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from healthos.models import DailyEvent


def test_create_manual_event(session, client):
    resp = client.post(
        "/api/events",
        json={"date": "2026-06-03", "event_type": "travel", "value": 1, "notes": "NYC"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["event_type"] == "travel"
    assert body["confidence"] == "manual"
    assert body["source"] == "manual"
    assert body["notes"] == "NYC"


def test_confirm_upgrades_inferred_event(session, client):
    # Seed an inferred sauna guess.
    session.add(
        DailyEvent(
            date=date(2026, 6, 3),
            event_type="sauna",
            confidence="inferred",
            source="inferred_eight_sleep",
            notes="thermal signature",
        )
    )
    session.commit()

    resp = client.post(
        "/api/events/sauna/confirm",
        json={"date": "2026-06-03", "notes": "yep, 20 min sauna"},
    )
    assert resp.status_code == 200
    assert resp.json()["confidence"] == "confirmed"

    ev = session.scalars(
        select(DailyEvent).where(DailyEvent.event_type == "sauna")
    ).first()
    session.refresh(ev)
    assert ev.confidence == "confirmed"
    assert ev.notes == "yep, 20 min sauna"


def test_confirm_creates_when_missing(session, client):
    resp = client.post(
        "/api/events/sauna/confirm", json={"date": "2026-06-03", "value": 1}
    )
    assert resp.status_code == 200
    assert resp.json()["confidence"] == "confirmed"
    assert resp.json()["source"] == "manual"


def test_delete_dismisses_false_positive(session, client):
    """Dismissing an inferred event tombstones it (confidence='dismissed') so
    the next re-inference can't resurrect it, and it drops out of reads."""
    session.add(
        DailyEvent(
            date=date(2026, 6, 3),
            event_type="alcohol_detected",
            confidence="inferred",
            source="inferred_whoop",
        )
    )
    session.commit()

    resp = client.delete("/api/events/alcohol_detected?date=2026-06-03")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    ev = session.scalars(select(DailyEvent)).one()
    session.refresh(ev)
    assert ev.confidence == "dismissed"  # tombstoned, not deleted
    # Hidden from the events read API.
    assert client.get("/api/events").json() == []


def test_dismissed_event_survives_reinference(session, client):
    """The tombstone must block _upsert_event from re-creating the same event."""
    from healthos.inference.behavioral import _upsert_event, InferredEvent

    day = date(2026, 6, 3)
    session.add(
        DailyEvent(date=day, event_type="alcohol_detected",
                   confidence="inferred", source="inferred_behavioral")
    )
    session.commit()
    client.delete("/api/events/alcohol_detected?date=2026-06-03")

    # Inference fires again for the same day, same conditions.
    _upsert_event(session, day, InferredEvent(
        event_type="alcohol_detected", value=None, confidence="inferred",
        notes="re-detected", source="inferred_behavioral"))
    session.commit()

    ev = session.scalars(select(DailyEvent)).one()
    assert ev.confidence == "dismissed"  # still dismissed, not revived


def test_delete_manual_event_hard_deletes(session, client):
    """A user's own manual entry is truly removed (inference never recreates it)."""
    session.add(
        DailyEvent(date=date(2026, 6, 3), event_type="travel",
                   confidence="manual", source="manual")
    )
    session.commit()
    resp = client.delete("/api/events/travel?date=2026-06-03")
    assert resp.status_code == 200
    assert session.scalars(select(DailyEvent)).all() == []


def test_delete_missing_returns_404(session, client):
    resp = client.delete("/api/events/nope?date=2026-06-03")
    assert resp.status_code == 404

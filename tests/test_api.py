"""API endpoint tests via FastAPI TestClient."""

from __future__ import annotations

from datetime import date, timedelta

from healthos.database import SessionLocal
from healthos.sync.persistence import MetricPoint, upsert_metrics


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_status_building_baseline(session, client):
    # session fixture has already truncated the tables.
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["building_baseline"] is True
    assert body["data_days"] == 0


def test_daily_summary_and_trend(session, client):
    base = date(2026, 3, 1)
    points = []
    for i in range(40):
        d = base + timedelta(days=i)
        points.append(MetricPoint(d, "hrv_rmssd", 55.0 + i % 5, "ms", "whoop"))
    upsert_metrics(session, points)
    session.commit()

    target = (base + timedelta(days=39)).isoformat()
    daily = client.get(f"/api/daily?date={target}").json()
    assert daily["metrics"]["hrv_rmssd"]["value"] is not None
    assert daily["metrics"]["hrv_rmssd"]["baseline"] is not None

    trend = client.get("/api/trend/hrv_rmssd?days=60&rolling=7").json()
    assert trend["metric"] == "hrv_rmssd"
    assert len(trend["series"]) == 40


def test_ios_webhook(session, client):
    payload = {"event_type": "elevated_screen_time", "value": 90, "date": "2026-06-03"}
    resp = client.post("/webhooks/ios", json=payload)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Confirm it landed as a confirmed event.
    with SessionLocal() as s:
        from sqlalchemy import select

        from healthos.models import DailyEvent

        ev = s.scalars(
            select(DailyEvent).where(DailyEvent.event_type == "elevated_screen_time")
        ).first()
        assert ev is not None
        assert ev.confidence == "confirmed"
        assert ev.source == "ios_shortcut"


def test_metric_webhook_steps(session, client):
    resp = client.post(
        "/webhooks/metric",
        json={"metric": "steps", "value": 8421, "date": "2026-06-09", "source": "apple_health"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    from sqlalchemy import select

    from healthos.models import DailyMetric

    with SessionLocal() as s:
        row = s.scalars(
            select(DailyMetric).where(
                DailyMetric.metric == "steps", DailyMetric.source == "apple_health"
            )
        ).first()
        assert row is not None
        assert float(row.value) == 8421
        assert row.is_canonical is False  # Garmin is canonical for steps

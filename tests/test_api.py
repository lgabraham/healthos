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
    # Padded to one entry per calendar day, clamped to the first data date —
    # 40 days of data means a 40-entry axis, not 60 days with dead space.
    assert len(trend["series"]) == 40
    assert sum(1 for p in trend["series"] if p["value"] is not None) == 40


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
        assert row.is_canonical is True  # apple_health is canonical for steps


def test_metric_webhook_tolerates_messy_date(session, client):
    # Repeated lines (the Shortcut bug) -> first line used.
    r1 = client.post("/webhooks/metric", json={
        "metric": "steps", "value": "8,421", "date": "2026-06-09\n2026-06-09\n2026-06-09"})
    assert r1.status_code == 200 and r1.json()["value"] == 8421.0
    # Missing date -> defaults to today (no error).
    r2 = client.post("/webhooks/metric", json={"metric": "steps", "value": 5000})
    assert r2.status_code == 200
    assert r2.json()["date"]  # a real date string


def test_estimated_recovery_and_all_source_trend(session, client):
    from datetime import date, timedelta
    from healthos.sync.persistence import MetricPoint, upsert_metrics

    base = date(2026, 3, 1)
    pts = []
    for i in range(30):  # build HRV/RHR baselines (whoop, canonical)
        d = base + timedelta(days=i)
        pts += [MetricPoint(d, "hrv_rmssd", 60.0, "ms", "whoop"),
                MetricPoint(d, "resting_hr", 50.0, "bpm", "whoop")]
    # A later day with only Eight Sleep HRV/RHR (non-canonical), no recovery.
    target = base + timedelta(days=30)
    pts += [MetricPoint(target, "hrv_rmssd", 72.0, "ms", "eight_sleep"),
            MetricPoint(target, "resting_hr", 46.0, "bpm", "eight_sleep")]
    upsert_metrics(session, pts)
    session.commit()

    d = client.get(f"/api/daily?date={target.isoformat()}").json()
    rec = d["metrics"]["recovery_score"]
    assert rec["is_estimated"] is True
    assert rec["value"] > 60  # HRV above baseline -> good recovery
    # HRV fallback (Eight Sleep) shows on the day.
    assert d["metrics"]["hrv_rmssd"]["is_fallback"] is True

    # Trend includes the non-canonical Eight Sleep point (extends past whoop).
    t = client.get("/api/trend/hrv_rmssd?days=90").json()
    assert any(p["value"] == 72.0 for p in t["series"])


def test_coverage_grid(session, client):
    from datetime import date, timedelta
    from healthos.sync.persistence import MetricPoint, upsert_metrics

    d = date.today() - timedelta(days=1)
    upsert_metrics(session, [
        MetricPoint(d, "hrv_rmssd", 60.0, "ms", "whoop"),
        MetricPoint(d, "steps", 8000.0, "steps", "apple_health"),
        MetricPoint(d, "spo2", 96.0, "percent", "whoop"),
    ])
    session.commit()
    cov = client.get("/api/coverage?days=30").json()
    assert "spo2" in cov["metrics"]
    cell = cov["grid"][d.isoformat()]
    assert cell["hrv_rmssd"] == "whoop"
    assert cell["steps"] == "apple_health"
    assert cell["strain_score"] is None


def test_attribution_and_aligned_trend(session, client):
    from datetime import date, timedelta
    from healthos.sync.persistence import MetricPoint, upsert_metrics

    base = date(2026, 3, 1)
    pts = []
    for i in range(30):
        d = base + timedelta(days=i)
        pts += [MetricPoint(d, "hrv_rmssd", 60.0, "ms", "whoop"),
                MetricPoint(d, "resting_hr", 50.0, "bpm", "whoop")]
    target = base + timedelta(days=30)
    pts += [MetricPoint(target, "hrv_rmssd", 45.0, "ms", "whoop"),   # -25% drag
            MetricPoint(target, "resting_hr", 50.0, "bpm", "whoop")]  # neutral
    upsert_metrics(session, pts)
    session.commit()

    a = client.get(f"/api/attribution?date={target.isoformat()}").json()
    by_key = {d["key"]: d for d in a["drivers"]}
    assert by_key["hrv_rmssd"]["pct"] < -20
    assert a["drivers"][0]["key"] == "hrv_rmssd"  # biggest mover first
    assert "HRV" in a["headline"]

    # Trend padding: two different metrics share an identical date axis.
    t1 = client.get("/api/trend/hrv_rmssd?days=40").json()
    t2 = client.get("/api/trend/resting_hr?days=40").json()
    assert [p["date"] for p in t1["series"]] == [p["date"] for p in t2["series"]]
    # One entry per calendar day, clamped to the first data date (31 days of
    # data -> 31 entries, not 41 with dead space before the data starts).
    assert len(t1["series"]) == 31

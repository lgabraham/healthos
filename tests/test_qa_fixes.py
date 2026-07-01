"""Regression tests for the 2026-06-10 QA review fixes (P0 data integrity)."""
from __future__ import annotations

from datetime import date, timedelta

from healthos.models import DailyMetric
from healthos.queries import attribution, best_available, rolling_baseline
from healthos.sync.whoop import normalize_cycles, normalize_recovery

DAY = date(2026, 6, 9)


def test_zero_strain_reads_as_missing(session):
    """A stored 0.0 strain (unsynced strap placeholder) must resolve to None,
    not flow into cards/attribution as a real reading."""
    session.add(DailyMetric(date=DAY, metric="strain_score", value=0, unit="score",
                            source="whoop", is_canonical=True))
    session.commit()
    assert best_available(session, DAY, "strain_score").value is None


def test_zero_excluded_from_baseline(session):
    for i in range(10):
        session.add(DailyMetric(date=DAY - timedelta(days=i + 1), metric="strain_score",
                                value=10.0 if i < 5 else 0, unit="score",
                                source="whoop", is_canonical=True))
    session.commit()
    base = rolling_baseline(session, "strain_score", DAY)
    assert base.n == 5  # the five zeros don't count
    assert base.mean == 10.0


def test_attribution_skips_fake_zero_and_reports_reason(session):
    # Only a zero strain exists -> no drivers, and the reason names the cause.
    session.add(DailyMetric(date=DAY - timedelta(days=1), metric="strain_score", value=0,
                            unit="score", source="whoop", is_canonical=True))
    session.commit()
    a = attribution(session, DAY)
    assert a["drivers"] == []
    assert "No metrics recorded" in a["reason"]


def test_attribution_separates_deviation_and_impact(session):
    # Resting HR 10% BELOW baseline: deviation negative, impact positive.
    for i in range(20):
        session.add(DailyMetric(date=DAY - timedelta(days=i + 1), metric="resting_hr",
                                value=50, unit="bpm", source="whoop", is_canonical=True))
    session.add(DailyMetric(date=DAY, metric="resting_hr", value=45, unit="bpm",
                            source="whoop", is_canonical=True))
    session.commit()
    a = attribution(session, DAY)
    rhr = next(d for d in a["drivers"] if d["key"] == "resting_hr")
    assert rhr["deviation_pct"] == -10.0  # below your normal
    assert rhr["pct"] == 10.0  # which helps recovery
    assert rhr["neutral"] is False


def test_strain_driver_is_neutral_and_not_headlined(session):
    for i in range(20):
        session.add(DailyMetric(date=DAY - timedelta(days=i + 2), metric="strain_score",
                                value=10, unit="score", source="whoop", is_canonical=True))
    # Yesterday's strain way below baseline; no other drivers.
    session.add(DailyMetric(date=DAY - timedelta(days=1), metric="strain_score", value=2,
                            unit="score", source="whoop", is_canonical=True))
    session.commit()
    a = attribution(session, DAY)
    strain = next(d for d in a["drivers"] if d["key"] == "strain_score")
    assert strain["neutral"] is True
    # A rest day must not produce a confident directional headline.
    assert a["headline"] == "Everything is close to baseline today — steady as she goes."


def test_whoop_unscored_records_are_skipped():
    recs = [
        {"created_at": "2026-06-08T08:00:00Z", "score_state": "PENDING_SCORE",
         "score": {"hrv_rmssd_milli": 0, "resting_heart_rate": 0, "recovery_score": 0}},
        {"created_at": "2026-06-07T08:00:00Z", "score_state": "SCORED",
         "score": {"hrv_rmssd_milli": 42, "resting_heart_rate": 50, "recovery_score": 70}},
    ]
    points = normalize_recovery(recs)
    days = {p.date for p in points}
    assert date(2026, 6, 7) in days or len(days) == 1  # tz-shifted but single day
    assert all(p.value > 0 for p in points)

    cycles = [
        {"start": "2026-06-08T07:00:00Z", "score_state": "UNSCORABLE", "score": {"strain": 0}},
        {"start": "2026-06-07T07:00:00Z", "score_state": "SCORED", "score": {"strain": 8.2}},
    ]
    strain = normalize_cycles(cycles)
    assert len(strain) == 1
    assert strain[0].value == 8.2


def test_status_reports_per_source_freshness(session, client):
    session.add(DailyMetric(date=DAY, metric="hrv_rmssd", value=40, unit="ms",
                            source="eight_sleep", is_canonical=False))
    session.add(DailyMetric(date=DAY - timedelta(days=10), metric="hrv_rmssd", value=42,
                            unit="ms", source="whoop", is_canonical=True))
    session.commit()
    body = client.get("/api/status").json()
    assert body["sources"]["whoop"]["days_behind"] == 10
    assert body["sources"]["eight_sleep"]["days_behind"] == 0


def test_degenerate_correlation_flagged(session, client):
    # Metrics exist but zero inferred events -> degenerate, actionable copy.
    for i in range(20):
        session.add(DailyMetric(date=DAY - timedelta(days=i), metric="hrv_rmssd",
                                value=40 + i % 3, unit="ms", source="whoop",
                                is_canonical=True))
    session.commit()
    cards = client.get("/api/correlations?days=30").json()
    sauna = next(c for c in cards if "Sauna" in c["title"])
    assert sauna["degenerate"] is True
    assert "healthos infer" in sauna["interpretation"]


def test_concordance_endpoint(session, client):
    """Whoop vs Eight Sleep on shared nights: offset + correlation."""
    for i in range(10):
        d = DAY - timedelta(days=i)
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=34 + i % 4, unit="ms",
                                source="whoop", is_canonical=True))
        # Pod reads consistently ~10ms higher on the same nights.
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=44 + i % 4, unit="ms",
                                source="eight_sleep", is_canonical=False))
    # One whoop-only travel night.
    session.add(DailyMetric(date=DAY - timedelta(days=11), metric="hrv_rmssd", value=30,
                            unit="ms", source="whoop", is_canonical=True))
    session.commit()
    body = client.get("/api/concordance?metric=hrv_rmssd&days=30").json()
    assert body["n_overlap"] == 10
    assert body["median_offset"] == 10.0
    assert body["r"] == 1.0
    assert body["n_whoop"] == 11

    bad = client.get("/api/concordance?metric=bogus&days=30").json()
    assert "error" in bad


def test_metric_sources_matrix(session, client):
    """Device-by-metric breakdown: per-source day counts, canonical flag,
    freshness; zero-impossible placeholders excluded."""
    for i in range(5):
        d = DAY - timedelta(days=i)
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=40, unit="ms",
                                source="whoop", is_canonical=True))
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=44, unit="ms",
                                source="eight_sleep", is_canonical=False))
    # Garmin HRV on 2 of those days + a placeholder 0 that must NOT count.
    session.add(DailyMetric(date=DAY, metric="hrv_rmssd", value=38, unit="ms",
                            source="garmin", is_canonical=False))
    session.add(DailyMetric(date=DAY - timedelta(days=1), metric="hrv_rmssd", value=39,
                            unit="ms", source="garmin", is_canonical=False))
    session.add(DailyMetric(date=DAY - timedelta(days=2), metric="hrv_rmssd", value=0,
                            unit="ms", source="garmin", is_canonical=False))
    session.commit()
    body = client.get("/api/metric-sources?days=30").json()
    hrv = next(m for m in body["metrics"] if m["metric"] == "hrv_rmssd")
    assert hrv["canonical_source"] == "eight_sleep"
    assert hrv["total_days"] == 5
    by_src = {s["source"]: s for s in hrv["sources"]}
    assert by_src["eight_sleep"]["days"] == 5 and by_src["eight_sleep"]["canonical"] is True
    assert by_src["whoop"]["days"] == 5 and by_src["whoop"]["canonical"] is False
    assert by_src["garmin"]["days"] == 2  # the zero is excluded
    assert hrv["sources"][0]["source"] == "eight_sleep"  # canonical first
    # Resolution logic surfaced for the build phase.
    res = hrv["resolution"]
    assert res["canonical"] == "eight_sleep"
    assert res["zero_is_missing"] is True
    assert res["fallback_order"] == ["whoop", "garmin"]  # away-from-pod priority
    # Eight Sleep is canonical and present on the latest day -> it wins.
    assert res["current_winner"] == "eight_sleep"
    assert res["current_winner_is_fallback"] is False


def test_replace_mode_mirrors_deletion_within_pulled_span(session, monkeypatch):
    """A re-sync in replace mode drops a stale night the provider no longer
    returns *within the span it did return* (the 'kid slept in my bed, I deleted
    that one night' case). Other recent nights still come back, so the pull is
    non-empty and the gap day gets mirrored as a deletion.

    (An entirely empty pull is treated as a transient blank and deletes nothing —
    see test_replace_mode_empty_pull_deletes_nothing; the two cases are
    indistinguishable from an empty response, so we err toward not losing data.)
    """
    from datetime import date as _d

    from healthos.models import DailyMetric, SleepSession
    from healthos.sync.persistence import MetricPoint, SleepRecord
    from healthos.sync import runner

    d1 = _d(2026, 6, 6)
    gap = _d(2026, 6, 7)  # the night the user deleted upstream
    d3 = _d(2026, 6, 8)
    for d in (d1, gap, d3):
        session.add(SleepSession(date=d, source="eight_sleep", total_minutes=300,
                                 is_canonical=True))
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=99, unit="ms",
                                source="eight_sleep", is_canonical=True))
    session.commit()

    # Provider returns d1 and d3 but NOT the deleted gap night.
    def without_gap(s, e):
        return {
            "metrics": [MetricPoint(d1, "hrv_rmssd", 50.0, "ms", "eight_sleep", None),
                        MetricPoint(d3, "hrv_rmssd", 52.0, "ms", "eight_sleep", None)],
            "sleeps": [SleepRecord(date=d1, source="eight_sleep", total_minutes=420),
                       SleepRecord(date=d3, source="eight_sleep", total_minutes=430)],
            "workouts": [],
        }

    monkeypatch.setitem(runner.SOURCES, "eight_sleep", (without_gap, "eight_sleep"))
    runner.sync_source("eight_sleep", d1, d3, sync_type="manual", replace=True)

    from sqlalchemy import select
    metric_dates = {r.date for r in session.scalars(
        select(DailyMetric).where(DailyMetric.source == "eight_sleep")).all()}
    sleep_dates = {r.date for r in session.scalars(
        select(SleepSession).where(SleepSession.source == "eight_sleep")).all()}
    assert metric_dates == {d1, d3}  # gap night mirrored as a deletion
    assert sleep_dates == {d1, d3}
    # And the returned days were rewritten from the pull.
    hrv = {r.date: float(r.value) for r in session.scalars(
        select(DailyMetric).where(DailyMetric.source == "eight_sleep")).all()}
    assert hrv[d1] == 50.0 and hrv[d3] == 52.0


def test_replace_mode_preserves_metrics_when_only_workouts_pulled(session, monkeypatch):
    """The Garmin data-loss case: a replace pull returns workouts (span
    non-empty) but its per-day metric calls were rate-limited to nothing. The
    metrics kind came back empty, so existing steps/body-battery are preserved
    rather than deleted and left un-rewritten."""
    from datetime import date as _d

    from healthos.models import DailyMetric, Workout
    from healthos.sync.persistence import WorkoutRecord
    from healthos.sync import runner

    d = _d(2026, 6, 8)
    session.add(DailyMetric(date=d, metric="steps", value=9000, unit="steps",
                            source="garmin", is_canonical=False))
    session.commit()

    def workouts_only(s, e):
        return {"metrics": [], "sleeps": [],
                "workouts": [WorkoutRecord(date=d, source="garmin", external_id="a1",
                                           sport_type="running", duration_minutes=40)]}

    monkeypatch.setitem(runner.SOURCES, "garmin", (workouts_only, "garmin"))
    runner.sync_source("garmin", d, d, sync_type="manual", replace=True)

    from sqlalchemy import select
    steps = session.scalars(
        select(DailyMetric).where(DailyMetric.source == "garmin", DailyMetric.metric == "steps")
    ).all()
    assert len(steps) == 1 and float(steps[0].value) == 9000  # steps survived
    assert session.scalars(select(Workout).where(Workout.source == "garmin")).all()


def test_garmin_pull_raises_when_throttled_to_empty(monkeypatch):
    """A pull where every call errored (non-404) and nothing came back must
    raise, so the sync logs an error instead of a silent 'success, 0 records'."""
    import healthos.sync.garmin as garmin

    class _ThrottledClient:
        def __init__(self):
            self.api_errors = ["/x: 429 Too Many Requests"]
        def daily_summary(self, d): return None
        def hrv(self, d): return None
        def training_status(self, d): return None
        def vo2max_range(self, s, e): return []
        def activities(self, s, e): return []

    import pytest
    with pytest.raises(RuntimeError, match="Garmin returned no data"):
        garmin.pull(date(2026, 6, 1), date(2026, 6, 1), client=_ThrottledClient())


def test_replace_mode_leaves_other_sources_untouched(session, monkeypatch):
    from datetime import date as _d

    from healthos.models import DailyMetric
    from healthos.sync import runner

    d = _d(2026, 6, 8)
    session.add(DailyMetric(date=d, metric="hrv_rmssd", value=40, unit="ms",
                            source="whoop", is_canonical=True))
    session.commit()
    monkeypatch.setitem(runner.SOURCES, "eight_sleep", (lambda s, e: {}, "eight_sleep"))
    runner.sync_source("eight_sleep", d, d, sync_type="manual", replace=True)
    from sqlalchemy import select
    assert session.scalars(
        select(DailyMetric).where(DailyMetric.source == "whoop")
    ).all()  # whoop survives an eight_sleep replace


def test_sync_trigger_and_status(session, client, monkeypatch):
    import time

    from healthos.sync import runner

    monkeypatch.setattr(runner, "manual_sync", lambda **kw: [])
    r = client.post("/api/sync?days=3").json()
    assert r["started"] is True
    for _ in range(20):
        st = client.get("/api/sync/status").json()
        if not st["running"]:
            break
        time.sleep(0.1)
    assert st["running"] is False
    assert st["error"] is None


def test_canonical_flip_to_eight_sleep():
    """Nightly cardiac/sleep signals are canonical to the pod (worn nightly);
    Whoop-proprietary scores stay Whoop."""
    from healthos.canonical import is_canonical_metric, is_canonical_sleep

    for m in ("hrv_rmssd", "resting_hr", "sleep_duration_minutes"):
        assert is_canonical_metric(m, "eight_sleep") is True
        assert is_canonical_metric(m, "whoop") is False
    assert is_canonical_sleep("eight_sleep") is True
    # Whoop keeps the scores only it produces.
    assert is_canonical_metric("recovery_score", "whoop") is True
    assert is_canonical_metric("strain_score", "whoop") is True


def test_replace_mode_preserves_days_outside_pulled_span(session, monkeypatch):
    """Eight Sleep's /intervals returns only the most-recent sessions, ignoring
    the requested window. A replace-mode sync must clamp its delete to the span
    the pull actually returned, so an OLDER canonical night the pull didn't
    include is preserved rather than blanked."""
    from datetime import date as _d

    from healthos.models import DailyMetric
    from healthos.sync import runner
    from healthos.sync.persistence import MetricPoint

    recent = _d(2026, 6, 8)
    old = recent - timedelta(days=5)
    session.add(DailyMetric(date=old, metric="hrv_rmssd", value=55, unit="ms",
                            source="eight_sleep", is_canonical=True))
    session.add(DailyMetric(date=recent, metric="hrv_rmssd", value=40, unit="ms",
                            source="eight_sleep", is_canonical=True))
    session.commit()

    # Provider returns ONLY the recent night (pulled span = [recent, recent]).
    def only_recent(s, e):
        return {"metrics": [MetricPoint(recent, "hrv_rmssd", 48.0, "ms", "eight_sleep", None)],
                "sleeps": [], "workouts": []}

    monkeypatch.setitem(runner.SOURCES, "eight_sleep", (only_recent, "eight_sleep"))
    runner.sync_source("eight_sleep", old, recent, sync_type="manual", replace=True)

    from sqlalchemy import select
    rows = {r.date: r.value for r in session.scalars(
        select(DailyMetric).where(DailyMetric.source == "eight_sleep")).all()}
    assert rows[old] == 55  # older night the pull didn't include survives
    assert rows[recent] == 48  # recent night rewritten from the pull


def test_replace_mode_empty_pull_deletes_nothing(session, monkeypatch):
    """A transient empty pull must not wipe the window (span is None -> no delete)."""
    from datetime import date as _d

    from healthos.models import DailyMetric
    from healthos.sync import runner

    d = _d(2026, 6, 8)
    session.add(DailyMetric(date=d, metric="hrv_rmssd", value=42, unit="ms",
                            source="eight_sleep", is_canonical=True))
    session.commit()
    monkeypatch.setitem(runner.SOURCES, "eight_sleep",
                        (lambda s, e: {"metrics": [], "sleeps": [], "workouts": []}, "eight_sleep"))
    runner.sync_source("eight_sleep", d, d, sync_type="manual", replace=True)
    from sqlalchemy import select
    assert session.scalars(
        select(DailyMetric).where(DailyMetric.source == "eight_sleep")
    ).all()  # survives an empty replace pull


def test_eight_sleep_skips_in_progress_today_session():
    """An unscored session dated today is still in progress — skip it so a partial
    short/low-HRV night doesn't pollute baselines. Scored-today and unscored-past
    sessions are kept."""
    from datetime import datetime, timedelta as _td

    from healthos.config import settings
    import healthos.sync.eight_sleep as es

    now = datetime.now(settings.tz)
    start = (now - _td(hours=2)).isoformat()

    def sess(ts, score):
        return {"ts": ts, "stages": [{"stage": "light", "duration": 3600}],
                "score": score, "timeseries": {}}

    unscored_today = sess(start, 0)
    scored_today = sess(start, 80)
    unscored_past = sess((now - _td(days=3)).isoformat(), 0)

    assert es.normalize([unscored_today]) == ([], [])  # in-progress -> skipped
    assert len(es.normalize([scored_today])[0]) == 1  # finalized today -> kept
    assert len(es.normalize([unscored_past])[0]) == 1  # past unscored -> kept


def test_estimated_recovery_rewards_sleep(session):
    """A night with more sleep than baseline scores higher than the same
    HRV/RHR night with baseline sleep — sleep now counts."""
    from datetime import date as _date

    from healthos.models import DailyMetric
    from healthos.queries import estimated_recovery

    day = _date(2026, 6, 10)
    # 20 baseline days: HRV 45, RHR 50, sleep 450 min.
    for i in range(1, 21):
        d = day - timedelta(days=i)
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=45, unit="ms",
                                source="eight_sleep", is_canonical=True))
        session.add(DailyMetric(date=d, metric="resting_hr", value=50, unit="bpm",
                                source="eight_sleep", is_canonical=True))
        session.add(DailyMetric(date=d, metric="sleep_duration_minutes", value=450,
                                unit="minutes", source="eight_sleep", is_canonical=True))
    # Today: HRV/RHR exactly at baseline, but a long sleep (540 vs 450).
    session.add(DailyMetric(date=day, metric="hrv_rmssd", value=45, unit="ms",
                            source="eight_sleep", is_canonical=True))
    session.add(DailyMetric(date=day, metric="resting_hr", value=50, unit="bpm",
                            source="eight_sleep", is_canonical=True))
    session.add(DailyMetric(date=day, metric="sleep_duration_minutes", value=540,
                            unit="minutes", source="eight_sleep", is_canonical=True))
    session.commit()
    score = estimated_recovery(session, day)
    # HRV & RHR at baseline -> ~55; long sleep pushes it up.
    assert score > 60

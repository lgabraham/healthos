"""MCP server exposing the HealthOS database to Claude.

Connects to the same Postgres DB (via DATABASE_URL) and surfaces a focused set
of read tools. All timestamps are returned in the user's local timezone, and
trend answers always carry sample size + a baseline-maturity flag so Claude can
caveat appropriately.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select, text

from ..config import settings
from ..correlate import correlate_metrics
from ..database import get_session
from ..models import DailyEvent, SleepSession, Workout
from ..queries import (
    MIN_BASELINE_DAYS,
    canonical_value,
    data_day_count,
    metric_series,
    rolling_baseline,
)

INSTRUCTIONS = (
    "HealthOS contains personal health data. Canonical sources are: Whoop for "
    "HRV/sleep/recovery, Garmin for exercise/training, Eight Sleep for sleep "
    "environment. Behavioral events may be inferred (lower confidence) or "
    "confirmed. Calendar context is available as keywords/flags only — event "
    "titles and locations are intentionally redacted and never exposed here. "
    "When answering trend questions, always note sample size and flag if the "
    "baseline is < 30 days."
)

# Columns whose values are redacted in query_raw output (privacy: calendar
# titles/locations stay on the local dashboard, never reach the model).
REDACTED_COLUMNS = {"title", "location"}

mcp = FastMCP("HealthOS", instructions=INSTRUCTIONS)


def _baseline_flag(n: int) -> str | None:
    if n < MIN_BASELINE_DAYS:
        return f"baseline is only {n} days (< {MIN_BASELINE_DAYS}); treat as provisional"
    return None


@mcp.tool()
def get_daily_summary(date: str) -> dict:
    """All canonical metrics, sleep, and events for a single date (YYYY-MM-DD)."""
    day = _date.fromisoformat(date)
    metrics_of_interest = [
        "recovery_score",
        "hrv_rmssd",
        "resting_hr",
        "strain_score",
        "sleep_duration_minutes",
        "steps",
        "vo2_max",
        "tss",
    ]
    with get_session() as s:
        metrics = {}
        for m in metrics_of_interest:
            val = canonical_value(s, day, m)
            if val is None:
                continue
            base = rolling_baseline(s, m, day)
            metrics[m] = {
                "value": val,
                "baseline": round(base.mean, 1) if base.mean is not None else None,
                "baseline_n": base.n,
                "baseline_note": _baseline_flag(base.n),
            }
        sleep = s.scalars(
            select(SleepSession).where(
                SleepSession.date == day, SleepSession.is_canonical.is_(True)
            )
        ).first()
        events = s.scalars(select(DailyEvent).where(DailyEvent.date == day)).all()
        return {
            "date": date,
            "metrics": metrics,
            "sleep": _sleep_out(sleep),
            "events": [_event_out(e) for e in events],
        }


@mcp.tool()
def get_metric_trend(metric: str, days: int = 30) -> dict:
    """Time series for any metric over the trailing N days, with mean + n.

    Example metrics: hrv_rmssd, resting_hr, recovery_score, strain_score,
    sleep_duration_minutes, steps, vo2_max, tss.
    """
    with get_session() as s:
        series = metric_series(s, metric, days)
        values = [v for _, v in series]
        mean = sum(values) / len(values) if values else None
        return {
            "metric": metric,
            "days": days,
            "n": len(values),
            "mean": round(mean, 2) if mean is not None else None,
            "baseline_note": _baseline_flag(len(values)),
            "series": [{"date": d.isoformat(), "value": v} for d, v in series],
        }


@mcp.tool()
def get_sleep_history(days: int = 30) -> dict:
    """Canonical sleep sessions with staging for the trailing N days."""
    with get_session() as s:
        rows = s.scalars(
            select(SleepSession)
            .where(
                SleepSession.is_canonical.is_(True),
                SleepSession.date >= _date.today() - timedelta(days=days),
            )
            .order_by(SleepSession.date.asc())
        ).all()
        return {"days": days, "n": len(rows), "sessions": [_sleep_out(r) for r in rows]}


@mcp.tool()
def get_workout_history(days: int = 30) -> dict:
    """Workouts with HR and load for the trailing N days."""
    with get_session() as s:
        rows = s.scalars(
            select(Workout)
            .where(Workout.date >= _date.today() - timedelta(days=days))
            .order_by(Workout.date.asc())
        ).all()
        return {
            "days": days,
            "n": len(rows),
            "workouts": [
                {
                    "date": w.date.isoformat(),
                    "sport_type": w.sport_type,
                    "duration_minutes": w.duration_minutes,
                    "hr_avg": w.hr_avg,
                    "hr_max": w.hr_max,
                    "tss": float(w.tss) if w.tss is not None else None,
                    "source": w.source,
                }
                for w in rows
            ],
        }


@mcp.tool()
def get_events(days: int = 30, event_type: str | None = None) -> dict:
    """Behavioral events (inferred or confirmed) for the trailing N days."""
    with get_session() as s:
        stmt = (
            select(DailyEvent)
            .where(DailyEvent.date >= _date.today() - timedelta(days=days))
            .order_by(DailyEvent.date.desc())
        )
        if event_type:
            stmt = stmt.where(DailyEvent.event_type == event_type)
        rows = s.scalars(stmt).all()
        return {"days": days, "n": len(rows), "events": [_event_out(e) for e in rows]}


@mcp.tool()
def correlate(metric_a: str, metric_b: str, days: int = 90, lag_days: int = 0) -> dict:
    """Pearson correlation between two canonical metrics over N days.

    lag_days shifts metric_b forward (lag_days=1 relates metric_a[d] to
    metric_b[d+1]) for next-day-effect questions.
    """
    with get_session() as s:
        return correlate_metrics(s, metric_a, metric_b, days, lag_days=lag_days).to_dict()


@mcp.tool()
def query_raw(sql: str) -> dict:
    """Escape hatch for complex questions: run a read-only SQL SELECT.

    Only a single SELECT/WITH statement is permitted; any write or multi-
    statement input is rejected. Results are capped at 500 rows.
    """
    cleaned = sql.strip().rstrip(";").strip()
    lowered = cleaned.lower()
    if ";" in cleaned:
        return {"error": "Only a single statement is allowed."}
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return {"error": "Only SELECT/WITH queries are allowed."}
    forbidden = ("insert", "update", "delete", "drop", "alter", "truncate", "create", "grant")
    if any(f in lowered.split() for f in forbidden):
        return {"error": "Write keywords are not allowed."}
    with get_session() as s:
        result = s.execute(text(cleaned))
        cols = list(result.keys())
        rows = [dict(zip(cols, r)) for r in result.fetchmany(500)]
        # JSON-safe coercion for dates/decimals; redact sensitive columns.
        for row in rows:
            for k, v in row.items():
                if k in REDACTED_COLUMNS:
                    row[k] = "[redacted]" if v is not None else None
                elif hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
                elif isinstance(v, (bytes, bytearray)):
                    row[k] = v.decode("utf-8", "replace")
                else:
                    try:
                        row[k] = float(v) if v is not None and not isinstance(v, (str, bool, int)) else v
                    except (TypeError, ValueError):
                        row[k] = str(v)
        return {"columns": cols, "row_count": len(rows), "rows": rows}


@mcp.tool()
def get_calendar(days: int = 30) -> dict:
    """Calendar context for the trailing N days — keywords/flags only.

    Event titles and locations are intentionally NOT included (privacy). Use
    this to relate behavior (e.g. evening 'alcohol'-tagged events) to metrics.
    """
    from ..models import CalendarEvent

    with get_session() as s:
        rows = s.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.date >= _date.today() - timedelta(days=days))
            .order_by(CalendarEvent.date.desc())
        ).all()
        return {
            "days": days,
            "n": len(rows),
            "events": [
                {
                    "date": e.date.isoformat(),
                    "is_evening": e.is_evening,
                    "all_day": e.all_day,
                    "keywords": e.keywords or [],
                }
                for e in rows
            ],
        }


@mcp.tool()
def data_overview() -> dict:
    """How much data exists and whether baselines are mature yet."""
    with get_session() as s:
        days = data_day_count(s)
        return {
            "data_days": days,
            "baseline_mature": days >= MIN_BASELINE_DAYS,
            "min_baseline_days": MIN_BASELINE_DAYS,
            "timezone": settings.timezone,
        }


def _sleep_out(s: SleepSession | None) -> dict | None:
    if s is None:
        return None
    start = s.start_time.astimezone(settings.tz).isoformat() if s.start_time else None
    end = s.end_time.astimezone(settings.tz).isoformat() if s.end_time else None
    return {
        "date": s.date.isoformat(),
        "source": s.source,
        "start_time": start,
        "end_time": end,
        "total_minutes": s.total_minutes,
        "rem_minutes": s.rem_minutes,
        "deep_minutes": s.deep_minutes,
        "light_minutes": s.light_minutes,
        "awake_minutes": s.awake_minutes,
        "sleep_score": float(s.sleep_score) if s.sleep_score is not None else None,
    }


def _event_out(e: DailyEvent) -> dict:
    return {
        "date": e.date.isoformat(),
        "event_type": e.event_type,
        "value": float(e.value) if e.value is not None else None,
        "confidence": e.confidence,
        "notes": e.notes,
        "source": e.source,
    }


if __name__ == "__main__":
    mcp.run()

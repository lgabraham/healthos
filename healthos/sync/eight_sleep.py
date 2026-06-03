"""Eight Sleep sync via the unofficial ``pyeight`` community client.

Eight Sleep is canonical for the sleep *environment*: bed/skin temperature and
toss-and-turn counts. The full skin-temp time series is preserved in raw_json
so the sauna-inference rule can mine it later.

The unofficial API token expires aggressively, so the client wrapper builds a
fresh authenticated session per pull and tolerates transient failures.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as _date
from datetime import datetime, timedelta

from ..config import settings
from .persistence import MetricPoint, SleepRecord

log = logging.getLogger(__name__)

SOURCE = "eight_sleep"


class EightSleepClient:
    """Async wrapper around pyeight, exposed with a sync ``pull`` facade."""

    def __init__(self) -> None:
        if not (settings.eight_sleep_email and settings.eight_sleep_password):
            raise RuntimeError(
                "Eight Sleep credentials missing (EIGHT_SLEEP_EMAIL / EIGHT_SLEEP_PASSWORD)."
            )

    async def _fetch(self, start_date: _date, end_date: _date) -> list[dict]:
        from pyeight.eight import EightSleep  # lazy import; optional dependency

        eight = EightSleep(
            settings.eight_sleep_email,
            settings.eight_sleep_password,
            settings.timezone,
        )
        sessions: list[dict] = []
        try:
            await eight.start()
            user = eight.users[next(iter(eight.users))] if eight.users else None
            if user is None:
                return []
            day = start_date
            while day <= end_date:
                try:
                    await user.update_trend_data(day.isoformat(), day.isoformat())
                    intervals = getattr(user, "intervals", None) or []
                    for interval in intervals:
                        interval.setdefault("_query_date", day.isoformat())
                        sessions.append(interval)
                except Exception as exc:  # noqa: BLE001 - skip a bad night, keep going
                    log.warning("Eight Sleep fetch failed for %s: %s", day, exc)
                day += timedelta(days=1)
        finally:
            await eight.stop()
        return sessions

    def fetch(self, start_date: _date, end_date: _date) -> list[dict]:
        return asyncio.run(self._fetch(start_date, end_date))


# -- normalization ----------------------------------------------------------
def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_date(interval: dict) -> _date | None:
    start = _parse_dt(interval.get("ts"))
    if start is not None:
        return start.astimezone(settings.tz).date()
    q = interval.get("_query_date")
    return _date.fromisoformat(q) if q else None


def normalize(sessions: list[dict]) -> tuple[list[SleepRecord], list[MetricPoint]]:
    sleeps: list[SleepRecord] = []
    points: list[MetricPoint] = []
    for interval in sessions:
        d = _local_date(interval)
        if d is None:
            continue
        stages = interval.get("stages") or []
        durations = _stage_durations(stages)
        toss = interval.get("tnt") or interval.get("tossAndTurns")
        bed_temp = _avg(interval.get("tempBedC") or interval.get("bedTemp"))
        skin_temp = _avg(interval.get("tempSkinC") or interval.get("skinTemp"))
        room_temp = _avg(interval.get("tempRoomC") or interval.get("roomTemp"))

        sleeps.append(
            SleepRecord(
                date=d,
                source=SOURCE,
                start_time=_parse_dt(interval.get("ts")),
                total_minutes=durations.get("total"),
                rem_minutes=durations.get("rem"),
                deep_minutes=durations.get("deep"),
                light_minutes=durations.get("light"),
                awake_minutes=durations.get("awake"),
                sleep_score=interval.get("score"),
                stages_json={"stages": stages},
                raw_json=interval,  # preserves skin-temp time series for sauna inference
            )
        )
        for metric, value in [
            ("bed_temp", bed_temp),
            ("skin_temp", skin_temp),
            ("room_temp", room_temp),
            ("toss_turn_count", toss),
        ]:
            if value is not None:
                unit = "count" if metric == "toss_turn_count" else "celsius"
                points.append(MetricPoint(d, metric, float(value), unit, SOURCE, None))
    return sleeps, points


def _stage_durations(stages: list[dict]) -> dict[str, int]:
    buckets = {"rem": 0, "deep": 0, "light": 0, "awake": 0}
    for s in stages:
        stage = (s.get("stage") or "").lower()
        seconds = s.get("duration") or 0
        if stage in ("rem",):
            buckets["rem"] += seconds
        elif stage in ("deep",):
            buckets["deep"] += seconds
        elif stage in ("light",):
            buckets["light"] += seconds
        elif stage in ("awake", "out"):
            buckets["awake"] += seconds
    out = {k: round(v / 60) for k, v in buckets.items()}
    out["total"] = sum(out.get(k, 0) for k in ("rem", "deep", "light"))
    return out


def _avg(series) -> float | None:
    if series is None:
        return None
    if isinstance(series, (int, float)):
        return float(series)
    nums = [float(x) for x in series if isinstance(x, (int, float))]
    return round(sum(nums) / len(nums), 2) if nums else None


# -- orchestration ----------------------------------------------------------
def pull(start_date: _date, end_date: _date, client: EightSleepClient | None = None) -> dict:
    client = client or EightSleepClient()
    sessions = client.fetch(start_date, end_date)
    sleeps, points = normalize(sessions)
    return {"metrics": points, "sleeps": sleeps, "workouts": []}

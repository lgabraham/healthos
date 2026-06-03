"""Garmin sync via the ``garth`` library.

garth wraps Garmin Connect's SSO so we avoid hand-rolling OAuth 1.0a. Garmin is
canonical for exercise HR, VO2 max, training load, steps, and workouts.

Garmin is aggressive about rate limiting, so backfill callers should space day
pulls out (see scripts/backfill.py). We add a small per-call delay here too.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date as _date
from datetime import datetime, timedelta

from ..config import settings
from .persistence import MetricPoint, WorkoutRecord

log = logging.getLogger(__name__)

SOURCE = "garmin"
# Politeness delay between Garmin calls; Garmin blocks aggressive scrapers.
CALL_DELAY_SECONDS = 1.0


class GarminClient:
    """Authenticated garth session.

    Resumes a saved token store when available (GARMIN_TOKENSTORE), otherwise
    logs in with email/password and persists the session for next time.
    """

    def __init__(self) -> None:
        import garth  # imported lazily so the package is optional at import time

        self._garth = garth
        self._authenticated = False

    def login(self) -> None:
        if self._authenticated:
            return
        store = settings.garmin_tokenstore
        if store:
            try:
                self._garth.resume(store)
                self._authenticated = True
                log.info("Resumed Garmin session from token store.")
                return
            except Exception as exc:  # noqa: BLE001 - fall back to fresh login
                log.warning("Garmin token resume failed (%s); logging in fresh.", exc)
        if not (settings.garmin_email and settings.garmin_password):
            raise RuntimeError("Garmin credentials missing (GARMIN_EMAIL / GARMIN_PASSWORD).")
        self._garth.login(settings.garmin_email, settings.garmin_password)
        self._authenticated = True
        if store:
            self._garth.save(store)
        log.info("Logged in to Garmin Connect.")

    def _connectapi(self, path: str, **kwargs) -> dict | list | None:
        self.login()
        _time.sleep(CALL_DELAY_SECONDS)
        try:
            return self._garth.connectapi(path, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning("Garmin call failed for %s: %s", path, exc)
            return None

    # -- endpoints ---------------------------------------------------------
    def daily_summary(self, day: _date) -> dict | None:
        path = f"/usersummary-service/usersummary/daily?calendarDate={day.isoformat()}"
        result = self._connectapi(path)
        return result if isinstance(result, dict) else None

    def hrv(self, day: _date) -> dict | None:
        result = self._connectapi(f"/hrv-service/hrv/{day.isoformat()}")
        return result if isinstance(result, dict) else None

    def vo2max(self, day: _date) -> dict | None:
        # Max metrics include VO2 max for running.
        result = self._connectapi(f"/metrics-service/metrics/maxmet/daily/{day.isoformat()}")
        return result if isinstance(result, dict) else None

    def training_status(self, day: _date) -> dict | None:
        result = self._connectapi(
            f"/metrics-service/metrics/trainingstatus/aggregated/{day.isoformat()}"
        )
        return result if isinstance(result, dict) else None

    def activities(self, start: _date, end: _date) -> list[dict]:
        path = (
            "/activitylist-service/activities/search/activities"
            f"?startDate={start.isoformat()}&endDate={end.isoformat()}&limit=100"
        )
        result = self._connectapi(path)
        return result if isinstance(result, list) else []


# -- normalization ----------------------------------------------------------
def normalize_daily(day: _date, summary: dict | None) -> list[MetricPoint]:
    if not summary:
        return []
    points: list[MetricPoint] = []
    steps = summary.get("totalSteps")
    if steps is not None:
        points.append(MetricPoint(day, "steps", float(steps), "steps", SOURCE, summary))
    return points


def normalize_vo2max(day: _date, data: dict | None) -> list[MetricPoint]:
    if not data:
        return []
    generic = data.get("generic") or {}
    vo2 = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")
    if vo2 is None:
        return []
    return [MetricPoint(day, "vo2_max", float(vo2), "ml/kg/min", SOURCE, data)]


def normalize_training_status(day: _date, data: dict | None) -> list[MetricPoint]:
    if not data:
        return []
    load = None
    # Garmin nests the acute training load under a device-keyed map.
    most_recent = data.get("mostRecentTrainingLoadBalance") or {}
    metrics_map = most_recent.get("metricsTrainingLoadBalanceDTOMap") or {}
    for entry in metrics_map.values():
        load = entry.get("monthlyLoadAerobicLow") or entry.get("trainingLoadAcute")
        if load is not None:
            break
    if load is None:
        return []
    return [MetricPoint(day, "training_load", float(load), "load", SOURCE, data)]


def normalize_activities(activities: list[dict]) -> tuple[list[WorkoutRecord], list[MetricPoint]]:
    workouts: list[WorkoutRecord] = []
    points: list[MetricPoint] = []
    for act in activities:
        start = _parse_local(act.get("startTimeLocal"))
        if start is None:
            continue
        d = start.date()
        duration_s = act.get("duration") or 0
        duration_min = round(duration_s / 60) if duration_s else None
        end = start + timedelta(seconds=duration_s) if duration_s else None
        sport = (act.get("activityType") or {}).get("typeKey")
        hr_avg = _int(act.get("averageHR"))
        workouts.append(
            WorkoutRecord(
                date=d,
                source=SOURCE,
                external_id=str(act.get("activityId")) if act.get("activityId") else None,
                start_time=start,
                end_time=end,
                sport_type=sport,
                duration_minutes=duration_min,
                hr_avg=hr_avg,
                hr_max=_int(act.get("maxHR")),
                calories=_int(act.get("calories")),
                distance_km=round(act["distance"] / 1000, 3) if act.get("distance") else None,
                tss=act.get("trainingStressScore"),
                raw_json=act,
            )
        )
        if hr_avg is not None:
            points.append(MetricPoint(d, "exercise_hr", float(hr_avg), "bpm", SOURCE, None))
        if duration_min:
            points.append(
                MetricPoint(d, "workout_duration_minutes", float(duration_min), "minutes", SOURCE)
            )
        if act.get("trainingStressScore") is not None:
            points.append(
                MetricPoint(d, "tss", float(act["trainingStressScore"]), "tss", SOURCE)
            )
    return workouts, points


def _parse_local(ts: str | None) -> datetime | None:
    if not ts:
        return None
    # Garmin "startTimeLocal" is naive local time; attach the user's tz.
    try:
        return datetime.fromisoformat(ts).replace(tzinfo=settings.tz)
    except ValueError:
        return None


def _int(v) -> int | None:
    return int(v) if v is not None else None


# -- orchestration ----------------------------------------------------------
def pull(start_date: _date, end_date: _date, client: GarminClient | None = None) -> dict:
    """Pull Garmin data day-by-day for the inclusive range."""
    client = client or GarminClient()
    metrics: list[MetricPoint] = []
    day = start_date
    while day <= end_date:
        metrics += normalize_daily(day, client.daily_summary(day))
        metrics += normalize_vo2max(day, client.vo2max(day))
        metrics += normalize_training_status(day, client.training_status(day))
        day += timedelta(days=1)
    workouts, workout_points = normalize_activities(client.activities(start_date, end_date))
    metrics += workout_points
    return {"metrics": metrics, "sleeps": [], "workouts": workouts}

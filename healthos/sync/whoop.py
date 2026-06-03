"""Whoop sync: OAuth 2.0 client + nightly pull.

Endpoints used (Whoop developer API v1):
    GET /recovery        -> HRV, resting HR, recovery score
    GET /activity/sleep  -> sleep stages + score
    GET /activity/workout-> strain workouts
    GET /cycle           -> day strain

Whoop is canonical for HRV, resting HR, sleep, recovery, and strain.
All endpoints are cursor-paginated via ``next_token``.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, time, timedelta, timezone

import httpx

from ..config import settings
from .persistence import MetricPoint, SleepRecord, WorkoutRecord

log = logging.getLogger(__name__)

API_BASE = "https://api.prod.whoop.com/developer"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
SOURCE = "whoop"

# Whoop scopes needed for the endpoints above.
SCOPES = "read:recovery read:sleep read:workout read:cycles read:profile offline"


class WhoopAuthError(RuntimeError):
    pass


class WhoopClient:
    """Thin Whoop API client with automatic access-token refresh.

    Pass ``persist=True`` (the default for ``from_store``) to write refreshed
    tokens back to the DB token store so rotation is transparent and onboarding
    never requires copy-pasting secrets.
    """

    def __init__(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        persist: bool = False,
    ) -> None:
        self.access_token = access_token or settings.whoop_access_token
        self.refresh_token = refresh_token or settings.whoop_refresh_token
        self.client_id = client_id or settings.whoop_client_id
        self.client_secret = client_secret or settings.whoop_client_secret
        self.persist = persist
        self._client = httpx.Client(base_url=API_BASE, timeout=30.0)

    @classmethod
    def from_store(cls) -> WhoopClient:
        """Build a client using DB-stored tokens (env fallback), persisting
        any refreshed tokens back to the store."""
        from ..tokenstore import load

        access, refresh = load("whoop")
        return cls(access_token=access, refresh_token=refresh, persist=True)

    # -- auth --------------------------------------------------------------
    @property
    def tokens(self) -> dict[str, str | None]:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token}

    def _refresh(self) -> None:
        if not (self.refresh_token and self.client_id and self.client_secret):
            raise WhoopAuthError(
                "Cannot refresh Whoop token: missing refresh_token / client credentials."
            )
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": SCOPES,
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            raise WhoopAuthError(f"Whoop token refresh failed: {resp.status_code} {resp.text}")
        payload = resp.json()
        self.access_token = payload["access_token"]
        # Whoop rotates refresh tokens; keep the latest if present.
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        if self.persist:
            from ..tokenstore import save

            save("whoop", self.access_token, self.refresh_token)
        log.info("Refreshed Whoop access token.")

    def _auth_headers(self) -> dict[str, str]:
        if not self.access_token:
            self._refresh()
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._client.get(path, params=params, headers=self._auth_headers())
        if resp.status_code == 401:
            self._refresh()
            resp = self._client.get(path, params=params, headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, start: datetime, end: datetime) -> list[dict]:
        """Follow Whoop's next_token cursor until exhausted."""
        records: list[dict] = []
        params = {
            "start": _iso(start),
            "end": _iso(end),
            "limit": 25,
        }
        while True:
            page = self._get(path, params=params)
            records.extend(page.get("records", []))
            token = page.get("next_token")
            if not token:
                break
            params["nextToken"] = token
        return records

    # -- endpoints ---------------------------------------------------------
    def profile(self) -> dict:
        """Basic user profile — a cheap call used by the auth self-check."""
        return self._get("/v1/user/profile/basic")

    def recovery(self, start: datetime, end: datetime) -> list[dict]:
        return self._paginate("/v1/recovery", start, end)

    def sleep(self, start: datetime, end: datetime) -> list[dict]:
        return self._paginate("/v1/activity/sleep", start, end)

    def workouts(self, start: datetime, end: datetime) -> list[dict]:
        return self._paginate("/v1/activity/workout", start, end)

    def cycles(self, start: datetime, end: datetime) -> list[dict]:
        return self._paginate("/v1/cycle", start, end)

    def close(self) -> None:
        self._client.close()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def authorize_url(state: str = "healthos") -> str:
    """Build the Whoop OAuth consent URL for the initial CLI-driven flow."""
    from urllib.parse import urlencode

    q = urlencode(
        {
            "client_id": settings.whoop_client_id or "",
            "redirect_uri": settings.whoop_redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{q}"


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for tokens (initial OAuth bootstrap)."""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.whoop_client_id,
            "client_secret": settings.whoop_client_secret,
            "redirect_uri": settings.whoop_redirect_uri,
            "scope": SCOPES,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


# -- normalization ----------------------------------------------------------
def _ms_to_min(ms: int | None) -> int | None:
    return round(ms / 60000) if ms else None


def _local_date(iso_ts: str | None) -> _date | None:
    if not iso_ts:
        return None
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return dt.astimezone(settings.tz).date()


def normalize_recovery(records: list[dict]) -> list[MetricPoint]:
    points: list[MetricPoint] = []
    for rec in records:
        d = _local_date(rec.get("created_at"))
        score = rec.get("score") or {}
        if d is None or not score:
            continue
        mapping = {
            "hrv_rmssd": (score.get("hrv_rmssd_milli"), "ms"),
            "resting_hr": (score.get("resting_heart_rate"), "bpm"),
            "recovery_score": (score.get("recovery_score"), "score"),
        }
        for metric, (value, unit) in mapping.items():
            if value is not None:
                points.append(MetricPoint(d, metric, float(value), unit, SOURCE, rec))
    return points


def normalize_sleep(records: list[dict]) -> tuple[list[SleepRecord], list[MetricPoint]]:
    sleeps: list[SleepRecord] = []
    points: list[MetricPoint] = []
    for rec in records:
        if rec.get("nap"):
            continue
        d = _local_date(rec.get("end"))
        score = rec.get("score") or {}
        stage = score.get("stage_summary") or {}
        if d is None:
            continue
        rem = _ms_to_min(stage.get("total_rem_sleep_time_milli"))
        deep = _ms_to_min(stage.get("total_slow_wave_sleep_time_milli"))
        light = _ms_to_min(stage.get("total_light_sleep_time_milli"))
        awake = _ms_to_min(stage.get("total_awake_time_milli"))
        in_bed = _ms_to_min(stage.get("total_in_bed_time_milli"))
        total = sum(v for v in (rem, deep, light) if v is not None) or in_bed
        perf = score.get("sleep_performance_percentage")
        sleeps.append(
            SleepRecord(
                date=d,
                source=SOURCE,
                start_time=_parse_dt(rec.get("start")),
                end_time=_parse_dt(rec.get("end")),
                total_minutes=total,
                rem_minutes=rem,
                deep_minutes=deep,
                light_minutes=light,
                awake_minutes=awake,
                sleep_score=perf,
                stages_json=stage,
                raw_json=rec,
            )
        )
        for metric, value, unit in [
            ("sleep_duration_minutes", total, "minutes"),
            ("rem_sleep_minutes", rem, "minutes"),
            ("deep_sleep_minutes", deep, "minutes"),
            ("light_sleep_minutes", light, "minutes"),
            ("awake_minutes", awake, "minutes"),
        ]:
            if value is not None:
                points.append(MetricPoint(d, metric, float(value), unit, SOURCE, None))
    return sleeps, points


def normalize_workouts(records: list[dict]) -> list[WorkoutRecord]:
    out: list[WorkoutRecord] = []
    for rec in records:
        d = _local_date(rec.get("end"))
        score = rec.get("score") or {}
        if d is None:
            continue
        start, end = _parse_dt(rec.get("start")), _parse_dt(rec.get("end"))
        duration = None
        if start and end:
            duration = round((end - start).total_seconds() / 60)
        out.append(
            WorkoutRecord(
                date=d,
                source=SOURCE,
                external_id=str(rec.get("id")) if rec.get("id") is not None else None,
                start_time=start,
                end_time=end,
                sport_type=str(rec.get("sport_id")) if rec.get("sport_id") is not None else None,
                duration_minutes=duration,
                hr_avg=score.get("average_heart_rate"),
                hr_max=score.get("max_heart_rate"),
                calories=_kj_to_kcal(score.get("kilojoule")),
                distance_km=_m_to_km(score.get("distance_meter")),
                raw_json=rec,
            )
        )
    return out


def normalize_cycles(records: list[dict]) -> list[MetricPoint]:
    points: list[MetricPoint] = []
    for rec in records:
        d = _local_date(rec.get("start"))
        score = rec.get("score") or {}
        strain = score.get("strain")
        if d is not None and strain is not None:
            points.append(MetricPoint(d, "strain_score", float(strain), "score", SOURCE, rec))
    return points


def _parse_dt(iso_ts: str | None) -> datetime | None:
    if not iso_ts:
        return None
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def _kj_to_kcal(kj: float | None) -> int | None:
    return round(kj * 0.239006) if kj else None


def _m_to_km(m: float | None) -> float | None:
    return round(m / 1000, 3) if m else None


# -- orchestration ----------------------------------------------------------
def pull(start_date: _date, end_date: _date, client: WhoopClient | None = None) -> dict:
    """Pull all Whoop data for the inclusive local date range.

    Returns a dict of normalized records ready for persistence. The window is
    padded by a day on each side (in UTC) so timezone-boundary records aren't
    missed, then re-filtered by local date during normalization.
    """
    own = client is None
    client = client or WhoopClient.from_store()
    start = datetime.combine(start_date - timedelta(days=1), time.min, tzinfo=settings.tz)
    end = datetime.combine(end_date + timedelta(days=1), time.max, tzinfo=settings.tz)
    try:
        recovery = normalize_recovery(client.recovery(start, end))
        sleeps, sleep_points = normalize_sleep(client.sleep(start, end))
        workouts = normalize_workouts(client.workouts(start, end))
        cycles = normalize_cycles(client.cycles(start, end))
    finally:
        if own:
            client.close()
    return {
        "metrics": recovery + sleep_points + cycles,
        "sleeps": sleeps,
        "workouts": workouts,
        "tokens": client.tokens,
    }

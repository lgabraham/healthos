"""Eight Sleep sync via the modern OAuth2 API.

Eight Sleep deprecated the legacy ``/v1/login`` endpoint (it now returns 400
for everyone), which broke the old ``pyeight`` library. We authenticate the way
the mobile app does: an OAuth2 password grant against ``auth-api.8slp.net``
using the app's public client credentials (the same values community
integrations ship; overridable via env if Eight Sleep rotates them).

Eight Sleep is canonical for the sleep *environment*: bed/skin temperature and
toss-and-turn counts. Full session payloads are preserved in raw_json so the
sauna-inference rule can mine the temperature curves later.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime

import httpx

from ..config import settings
from .persistence import MetricPoint, SleepRecord

log = logging.getLogger(__name__)

SOURCE = "eight_sleep"
AUTH_URL = "https://auth-api.8slp.net/v1/tokens"
API_BASE = "https://client-api.8slp.net/v1"

# Public OAuth client embedded in the Eight Sleep mobile app — not a user
# secret. Published by community integrations; override via env if rotated.
DEFAULT_CLIENT_ID = "0894c7f33bb94800a03f1f4df13a4f38"
DEFAULT_CLIENT_SECRET = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76"


class EightSleepAuthError(RuntimeError):
    pass


class EightSleepClient:
    """Minimal direct client: OAuth2 token + the trends endpoint."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        if not (settings.eight_sleep_email and settings.eight_sleep_password):
            raise EightSleepAuthError(
                "Eight Sleep credentials missing (EIGHT_SLEEP_EMAIL / EIGHT_SLEEP_PASSWORD)."
            )
        self._client = httpx.Client(timeout=30.0, transport=transport)
        self._token: str | None = None
        self._user_id: str | None = None

    def login(self) -> str:
        """Authenticate and return the user id. Raises with the server's
        response body on failure so misconfig is diagnosable."""
        payload = {
            "client_id": settings.eight_sleep_client_id or DEFAULT_CLIENT_ID,
            "client_secret": settings.eight_sleep_client_secret or DEFAULT_CLIENT_SECRET,
            "grant_type": "password",
            "username": settings.eight_sleep_email,
            "password": settings.eight_sleep_password,
        }
        resp = self._client.post(AUTH_URL, json=payload)
        if resp.status_code != 200:
            raise EightSleepAuthError(
                f"Eight Sleep auth failed: {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        self._token = data["access_token"]
        self._user_id = str(data.get("userId") or data.get("user_id") or "")
        if not self._user_id:
            raise EightSleepAuthError(f"Eight Sleep auth ok but no userId in response: {data}")
        log.info("Authenticated to Eight Sleep.")
        return self._user_id

    def me(self) -> dict:
        """Account/profile, incl. userId, devices, and partner sides."""
        if self._token is None:
            self.login()
        resp = self._client.get(f"{API_BASE}/users/me", headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    def intervals(self, user_id: str | None = None) -> dict:
        """Detailed sleep sessions (stages + timeseries) for a user."""
        if self._token is None:
            self.login()
        uid = user_id or self._user_id
        resp = self._client.get(
            f"{API_BASE}/users/{uid}/intervals", headers=self._auth_headers()
        )
        if resp.status_code == 401:
            self.login()
            resp = self._client.get(
                f"{API_BASE}/users/{uid}/intervals", headers=self._auth_headers()
            )
        resp.raise_for_status()
        return resp.json()

    def device(self, device_id: str) -> dict:
        """Device detail — includes leftUserId / rightUserId / ownerId."""
        if self._token is None:
            self.login()
        resp = self._client.get(
            f"{API_BASE}/devices/{device_id}", headers=self._auth_headers()
        )
        resp.raise_for_status()
        return resp.json()

    def trends_raw(self, start_date: _date, end_date: _date) -> dict:
        """The raw trends response — also exposed via `healthos es-raw` so the
        real payload shape can be inspected when normalization comes up empty."""
        if self._token is None:
            self.login()
        params = {
            "tz": settings.timezone,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "include-main": "false",
            "include-all-sessions": "true",
            "model-version": "v2",
        }
        url = f"{API_BASE}/users/{self._user_id}/trends"
        resp = self._client.get(url, params=params, headers=self._auth_headers())
        if resp.status_code == 401:  # token expired mid-run; re-auth once
            self.login()
            resp = self._client.get(url, params=params, headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    def fetch(self, start_date: _date, end_date: _date) -> list[dict]:
        """Recent sleep sessions via /users/{id}/intervals.

        The intervals endpoint returns the most recent sessions Eight Sleep has
        (each with stages + a per-session timeseries). It doesn't take a date
        range, so we return everything it gives and let the date filter happen
        downstream — important here, since an account may only have older data.
        """
        return self.intervals().get("intervals", [])

    def _auth_headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._token}"}

    def close(self) -> None:
        self._client.close()


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
    q = interval.get("_query_date") or interval.get("day")
    return _date.fromisoformat(q) if q else None


def _series_values(timeseries: dict, key: str) -> list[float]:
    """Pull numeric values from a `[[timestamp, value], ...]` timeseries."""
    series = (timeseries or {}).get(key)
    if not isinstance(series, list):
        return []
    out: list[float] = []
    for pair in series:
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[1], (int, float)):
            out.append(float(pair[1]))
        elif isinstance(pair, (int, float)):
            out.append(float(pair))
    return out


def normalize(sessions: list[dict]) -> tuple[list[SleepRecord], list[MetricPoint]]:
    sleeps: list[SleepRecord] = []
    points: list[MetricPoint] = []
    for interval in sessions:
        d = _local_date(interval)
        if d is None:
            continue
        stages = interval.get("stages") or []
        durations = _stage_durations(stages)
        ts = interval.get("timeseries") or {}
        # Temps + toss/turn live under `timeseries` as [time, value] pairs.
        bed_temp = _avg(_series_values(ts, "tempBedC"))
        skin_temp = _avg(_series_values(ts, "tempSkinC"))
        room_temp = _avg(_series_values(ts, "tempRoomC"))
        tnt_values = _series_values(ts, "tnt")
        toss = sum(tnt_values) if tnt_values else (interval.get("tnt") or None)

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
                raw_json=interval,  # preserves temperature series for sauna inference
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
        if stage == "rem":
            buckets["rem"] += seconds
        elif stage == "deep":
            buckets["deep"] += seconds
        elif stage == "light":
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
    own = client is None
    client = client or EightSleepClient()
    try:
        sessions = client.fetch(start_date, end_date)
    finally:
        if own:
            client.close()
    sleeps, points = normalize(sessions)
    return {"metrics": points, "sleeps": sleeps, "workouts": []}

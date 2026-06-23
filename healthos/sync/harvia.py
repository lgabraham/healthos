"""Harvia sauna sync via the MyHarvia cloud.

The MyHarvia app (Harvia's Xenio/connected saunas) is an AWS Amplify backend:
authentication is AWS Cognito (user pool), and device state/history come from
an AWS AppSync GraphQL API at ``{base}/{service}/graphql`` for services
``users``, ``device``, and ``data``. This module logs in with the user's
MyHarvia credentials, lists their device(s), pulls recent heater activity, and
turns each heating session into a *confirmed* ``sauna`` day-event — the real
device signal that upgrades the low-confidence Eight Sleep thermal inference.

Two layers here have different confidence levels:

* **Auth + transport** (Cognito ``InitiateAuth`` + GraphQL POST) are standard
  AWS and implemented exactly. The Cognito client id is normally discovered
  from the ``users`` service, but can be pinned via ``HARVIA_COGNITO_CLIENT_ID``.
* **The device-history query and its response shape** are the parts most likely
  to drift between accounts/firmware. Both the query string and the field names
  the normalizer looks for are intentionally permissive and overridable, and
  ``fetch_raw`` (exposed as ``healthos harvia-raw``) dumps the real payload so
  the query can be finalized against a live account.

Unset ``HARVIA_EMAIL`` / ``HARVIA_PASSWORD`` and the source is a clean no-op.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timezone

import httpx

from ..config import settings
from .persistence import EventRecord

log = logging.getLogger(__name__)

SOURCE = "harvia"

# Discover the Cognito app client id from the public ``users`` service. The
# MyHarvia web/app fetch this unauthenticated before logging in.
_CLIENT_QUERY = "query { getCognitoConfig { ClientId UserPoolId Region } }"

# Recent heater activity for a device. Field names vary by firmware; the
# normalizer is liberal, and the whole query is overridable via env.
_DATA_QUERY = (
    "query Latest($deviceId: String!) {"
    " getLatestData(deviceId: $deviceId) {"
    " timestamp active heatOn targetTemp temperature remaining } }"
)
_DEVICES_QUERY = "query { getDevices { id name type } }"

# How long a stretch of consecutive "heater on" samples can gap before we treat
# it as a new session (seconds). MyHarvia samples roughly per-minute.
_SESSION_GAP_S = 30 * 60
# Ignore blips shorter than this — opening the app, a brief test (minutes).
_MIN_SESSION_MIN = 5


class HarviaAuthError(RuntimeError):
    pass


class HarviaClient:
    """Cognito-authenticated AppSync GraphQL client for MyHarvia."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        if not (settings.harvia_email and settings.harvia_password):
            raise HarviaAuthError(
                "Harvia credentials missing (HARVIA_EMAIL / HARVIA_PASSWORD)."
            )
        self._client = httpx.Client(timeout=30.0, transport=transport)
        self._id_token: str | None = None

    # -- transport ---------------------------------------------------------
    def _endpoint(self, service: str) -> str:
        return f"{settings.harvia_endpoint_base.rstrip('/')}/{service}/graphql"

    def _graphql(self, service: str, query: str, variables: dict | None = None,
                 auth: bool = True) -> dict:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = self._token()
        resp = self._client.post(
            self._endpoint(service),
            json={"query": query, "variables": variables or {}},
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise HarviaAuthError(f"Harvia GraphQL error ({service}): {body['errors']}")
        return body.get("data") or {}

    # -- auth --------------------------------------------------------------
    def _client_id(self) -> str:
        if settings.harvia_cognito_client_id:
            return settings.harvia_cognito_client_id
        try:
            cfg = self._graphql("users", _CLIENT_QUERY, auth=False).get("getCognitoConfig") or {}
            cid = cfg.get("ClientId")
        except Exception as exc:  # noqa: BLE001
            raise HarviaAuthError(
                "Could not discover the MyHarvia Cognito client id; set "
                "HARVIA_COGNITO_CLIENT_ID (capture it from the app's traffic)."
            ) from exc
        if not cid:
            raise HarviaAuthError(
                "MyHarvia returned no Cognito client id; set HARVIA_COGNITO_CLIENT_ID."
            )
        return cid

    def login(self) -> str:
        """Cognito USER_PASSWORD_AUTH → IdToken. Raises with the AWS error body
        on failure (e.g. the pool requires SRP, or bad credentials)."""
        url = f"https://cognito-idp.{settings.harvia_region}.amazonaws.com/"
        payload = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": self._client_id(),
            "AuthParameters": {
                "USERNAME": settings.harvia_email,
                "PASSWORD": settings.harvia_password,
            },
        }
        resp = self._client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            },
        )
        if resp.status_code != 200:
            raise HarviaAuthError(f"Harvia auth failed: {resp.status_code} {resp.text[:300]}")
        result = resp.json().get("AuthenticationResult") or {}
        token = result.get("IdToken")
        if not token:
            raise HarviaAuthError(f"Harvia auth ok but no IdToken (challenge?): {resp.text[:300]}")
        self._id_token = token
        log.info("Authenticated to MyHarvia.")
        return token

    def _token(self) -> str:
        return self._id_token or self.login()

    # -- data --------------------------------------------------------------
    def devices(self) -> list[dict]:
        data = self._graphql("device", settings_or(_DEVICES_QUERY, "harvia_devices_query"))
        return data.get("getDevices") or []

    def device_data(self, device_id: str) -> dict:
        return self._graphql(
            "data",
            settings_or(_DATA_QUERY, "harvia_data_query"),
            {"deviceId": device_id},
        )

    def fetch_raw(self) -> dict:
        """Diagnostic: devices + their raw data payloads, for finalizing the
        query/normalizer against a live account (`healthos harvia-raw`)."""
        devs = self.devices()
        return {"devices": devs, "data": {d.get("id"): self.device_data(d.get("id")) for d in devs if d.get("id")}}

    def close(self) -> None:
        self._client.close()


def settings_or(default: str, attr: str) -> str:
    """An optional env override for a GraphQL query string (not in the typed
    Settings, read leniently so power users can patch a query without a code
    change)."""
    return getattr(settings, attr, None) or default


def _as_epoch(v) -> float | None:
    """Coerce a timestamp (epoch seconds/millis or ISO-8601) to epoch seconds."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)  # millis vs seconds
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _samples(raw: dict) -> list[dict]:
    """Pull the list of telemetry samples out of a (permissive) data payload."""
    if not isinstance(raw, dict):
        return []
    for key in ("getLatestData", "getData", "data", "items", "samples", "history"):
        v = raw.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):  # single sample
            return [v]
    return []


def _is_on(sample: dict) -> bool:
    for key in ("active", "heatOn", "heating", "on", "isOn"):
        if key in sample:
            return bool(sample[key])
    return False


def _sample_ts(sample: dict) -> float | None:
    for key in ("timestamp", "ts", "time", "date"):
        if key in sample:
            return _as_epoch(sample[key])
    return None


def sessions_from_samples(samples: list[dict]) -> list[tuple[float, float]]:
    """Collapse "heater on" telemetry samples into (start, end) epoch sessions,
    splitting whenever the gap between on-samples exceeds ``_SESSION_GAP_S``."""
    on = sorted(
        (ts for s in samples if _is_on(s) and (ts := _sample_ts(s)) is not None),
    )
    sessions: list[tuple[float, float]] = []
    start = prev = None
    for ts in on:
        if start is None:
            start = prev = ts
        elif ts - prev > _SESSION_GAP_S:
            sessions.append((start, prev))
            start = prev = ts
        else:
            prev = ts
    if start is not None:
        sessions.append((start, prev))
    return sessions


def normalize(raw_by_device: dict[str, dict], start: _date, end: _date) -> list[EventRecord]:
    """Turn raw device payloads into one confirmed sauna event per local day in
    [start, end], with total heating minutes as the value."""
    minutes_by_date: dict[_date, float] = {}
    for raw in raw_by_device.values():
        for s_ts, e_ts in sessions_from_samples(_samples(raw)):
            minutes = (e_ts - s_ts) / 60
            if minutes < _MIN_SESSION_MIN:
                continue
            day = datetime.fromtimestamp(s_ts, tz=timezone.utc).astimezone(settings.tz).date()
            if start <= day <= end:
                minutes_by_date[day] = minutes_by_date.get(day, 0.0) + minutes
    return [
        EventRecord(
            date=day,
            event_type="sauna",
            value=round(mins),
            confidence="confirmed",
            notes=f"Harvia: {round(mins)} min heating",
            source=SOURCE,
        )
        for day, mins in sorted(minutes_by_date.items())
    ]


def pull(start_date: _date, end_date: _date, client: HarviaClient | None = None) -> dict:
    """Sync entry point. No-op (empty) when Harvia isn't configured, so the
    nightly run isn't noisy for users without a connected sauna."""
    if not (settings.harvia_email and settings.harvia_password):
        return {}
    own = client is None
    client = client or HarviaClient()
    try:
        raw_by_device = {
            d.get("id"): client.device_data(d.get("id"))
            for d in client.devices()
            if d.get("id")
        }
    finally:
        if own:
            client.close()
    return {"events": normalize(raw_by_device, start_date, end_date)}

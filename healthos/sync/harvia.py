"""Harvia sauna client for the MyHarvia cloud.

Reverse-engineered from the community Home Assistant component
(github.com/RubenHarms/ha-harvia-xenio-wifi), which talks to the same backend
as the MyHarvia app. The real flow, verified against that source:

1. **Endpoint discovery** (unauthenticated): ``GET {base}/{service}/endpoint``
   for service in ``users``/``device``/``data`` returns that service's AWS
   AppSync GraphQL URL. The ``users`` response *also* carries the Cognito
   ``userPoolId`` / ``clientId`` / ``identityPoolId`` needed to log in.
2. **Auth**: AWS Cognito **SRP** (via ``pycognito``) → an IdToken.
3. **GraphQL**: POST to each discovered AppSync URL with ``authorization:
   <IdToken>``. The useful queries are ``getDeviceTree`` (your devices),
   ``getDeviceState`` (current desired/reported), and ``getLatestData`` (the
   newest data point: ``deviceId/timestamp/sessionId/type/data``).

Important architectural note: MyHarvia exposes only *current* state + the
*latest* data point, plus a live websocket subscription (``onDataUpdates``) —
there is **no history query**. So a nightly pull can't reliably catch a sauna
session; that needs a persistent websocket listener (built separately). This
module currently provides auth/discovery + the read queries and a ``fetch_raw``
diagnostic (``healthos harvia-raw``) so the live ``data`` shape can be captured
before the listener's session-detection is finalized.

Unset ``HARVIA_EMAIL`` / ``HARVIA_PASSWORD`` and the source is a clean no-op.
"""

from __future__ import annotations

import logging
import re
from datetime import date as _date
from datetime import datetime, timezone

import httpx

from ..config import settings
from .persistence import EventRecord

log = logging.getLogger(__name__)

SOURCE = "harvia"

# AppSync GraphQL services to discover. ``users`` must be first — it carries the
# Cognito config the other calls need.
_SERVICES = ("users", "device", "data", "events")

# Real queries from the reverse-engineered component (sent to the named service).
_Q_DEVICE_TREE = "query Query {\n  getDeviceTree\n}\n"
_Q_DEVICE_STATE = (
    "query Query($deviceId: ID!) {\n  getDeviceState(deviceId: $deviceId) {\n"
    "    desired\n    reported\n    timestamp\n    __typename\n  }\n}\n"
)
_Q_LATEST_DATA = (
    "query Query($deviceId: String!) {\n  getLatestData(deviceId: $deviceId) {\n"
    "    deviceId\n    timestamp\n    sessionId\n    type\n    data\n    __typename\n  }\n}\n"
)


class HarviaAuthError(RuntimeError):
    pass


class HarviaClient:
    """Cognito-SRP-authenticated AppSync client for MyHarvia."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        if not (settings.harvia_email and settings.harvia_password):
            raise HarviaAuthError(
                "Harvia credentials missing (HARVIA_EMAIL / HARVIA_PASSWORD)."
            )
        self._client = httpx.Client(timeout=30.0, transport=transport)
        self._endpoints: dict[str, dict] = {}
        self._id_token: str | None = None

    # -- discovery ---------------------------------------------------------
    def discover(self) -> dict[str, dict]:
        """Fetch each service's AppSync URL + (for ``users``) the Cognito config.
        Unauthenticated GETs, exactly as the app bootstraps itself."""
        if self._endpoints:
            return self._endpoints
        base = settings.harvia_endpoint_base.rstrip("/")
        for service in _SERVICES:
            resp = self._client.get(f"{base}/{service}/endpoint")
            if resp.status_code != 200:
                raise HarviaAuthError(
                    f"Harvia endpoint discovery failed for '{service}': "
                    f"{resp.status_code} {resp.text[:200]}"
                )
            self._endpoints[service] = resp.json()
        return self._endpoints

    # -- auth --------------------------------------------------------------
    def login(self) -> str:
        """Cognito SRP via pycognito → IdToken. The pool requires SRP (not a
        plain password grant), so we lean on pycognito rather than hand-rolling
        it. Raises with a clear message if the dependency or config is missing."""
        users = self.discover()["users"]
        pool_id = users.get("userPoolId")
        client_id = settings.harvia_cognito_client_id or users.get("clientId")
        if not (pool_id and client_id):
            raise HarviaAuthError(
                f"MyHarvia discovery missing Cognito config (got keys: {list(users)})."
            )
        try:
            from pycognito import Cognito
        except ImportError as exc:  # noqa: TRY003
            raise HarviaAuthError(
                "pycognito is required for Harvia auth — `pip install pycognito` "
                "(or reinstall the package) in the venv."
            ) from exc
        u = Cognito(
            pool_id,
            client_id,
            username=settings.harvia_email,
            user_pool_region=settings.harvia_region,
        )
        try:
            u.authenticate(password=settings.harvia_password)
        except Exception as exc:  # noqa: BLE001 - surface AWS error verbatim
            raise HarviaAuthError(f"Harvia Cognito SRP auth failed: {exc}") from exc
        if not u.id_token:
            raise HarviaAuthError("Harvia auth ok but no IdToken returned.")
        self._id_token = u.id_token
        log.info("Authenticated to MyHarvia.")
        return self._id_token

    def _token(self) -> str:
        return self._id_token or self.login()

    # -- graphql -----------------------------------------------------------
    def _graphql(self, service: str, query: str, variables: dict | None = None) -> dict:
        url = self.discover()[service]["endpoint"]
        resp = self._client.post(
            url,
            json={"query": query, "variables": variables or {}},
            headers={"authorization": self._token()},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise HarviaAuthError(f"Harvia GraphQL error ({service}): {body['errors']}")
        return body.get("data") or {}

    def device_tree(self) -> dict:
        """Your account's devices. The payload is a JSON-ish tree; ``device_ids``
        flattens out the ids."""
        return self._graphql("device", _Q_DEVICE_TREE)

    def device_state(self, device_id: str) -> dict:
        return self._graphql("device", _Q_DEVICE_STATE, {"deviceId": device_id})

    def latest_data(self, device_id: str) -> dict:
        return self._graphql("data", _Q_LATEST_DATA, {"deviceId": device_id})

    def fetch_raw(self) -> dict:
        """Diagnostic: device tree + each device's current state and latest data,
        so the live ``data`` shape can be captured (`healthos harvia-raw`)."""
        tree = self.device_tree()
        ids = device_ids(tree)
        return {
            "device_tree": tree,
            "devices": {
                did: {"state": self.device_state(did), "latest": self.latest_data(did)}
                for did in ids
            },
        }

    def close(self) -> None:
        self._client.close()


# UUID-ish device id, e.g. as it appears in the getDeviceTree blob.
_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def device_ids(tree: dict) -> list[str]:
    """Extract device ids from getDeviceTree (a JSON string or nested dict).
    Liberal — the tree shape isn't documented, so we pull any UUIDs we find."""
    import json

    raw = tree.get("getDeviceTree") if isinstance(tree, dict) else tree
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return list(dict.fromkeys(_ID_RE.findall(raw)))
    found = _ID_RE.findall(json.dumps(raw))
    return list(dict.fromkeys(found))


def pull(start_date: _date, end_date: _date, client: HarviaClient | None = None) -> dict:
    """Sync entry point. No-op when unconfigured.

    MyHarvia has no history API, so confirmed sauna sessions are captured by the
    persistent websocket listener, not this nightly pull — this stays a no-op
    (returning no events) until that listener lands, so the nightly run neither
    errors nor writes guesses.
    """
    if not (settings.harvia_email and settings.harvia_password):
        return {}
    return {"events": []}


# --- session helpers (used by the forthcoming listener) -------------------
# How long a stretch of "heater on" samples can gap before it's a new session.
_SESSION_GAP_S = 30 * 60
_MIN_SESSION_MIN = 5


def _as_epoch(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sessions_from_samples(
    samples: list[tuple[float, bool]],
) -> list[tuple[float, float]]:
    """Collapse (timestamp, heater_on) samples into (start, end) epoch sessions,
    splitting whenever the gap between on-samples exceeds ``_SESSION_GAP_S``.

    Kept here for the websocket listener: as ``onDataUpdates`` pushes samples,
    it can reuse this to decide when a heating session has ended.
    """
    on = sorted(ts for ts, is_on in samples if is_on)
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


def sauna_event(start_ts: float, end_ts: float) -> EventRecord | None:
    """A completed heating session -> a confirmed sauna day-event (local date of
    the start). Returns None for blips below the minimum duration."""
    minutes = (end_ts - start_ts) / 60
    if minutes < _MIN_SESSION_MIN:
        return None
    day = datetime.fromtimestamp(start_ts, tz=timezone.utc).astimezone(settings.tz).date()
    return EventRecord(
        date=day,
        event_type="sauna",
        value=round(minutes),
        confidence="confirmed",
        notes=f"Harvia: {round(minutes)} min heating",
        source=SOURCE,
    )

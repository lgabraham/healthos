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
session; capture has to be live. Rather than hold an AppSync websocket open, the
``harvia_monitor`` module polls ``getDeviceState`` (~every 60s) on the always-on
host and records a confirmed sauna event when the stove turns off — far less code
and equally reliable for 20–60 min sessions. This module provides auth/discovery,
the read queries, the ``reported``-shadow parsing + device identification the
monitor relies on, and a ``fetch_raw`` diagnostic (``healthos harvia-raw``).

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
    def _graphql(
        self, service: str, query: str, variables: dict | None = None, _retry: bool = True
    ) -> dict:
        """Run an AppSync query, re-authenticating once on an expired token.

        Cognito IdTokens expire after ~1 hour. Without this, the always-on
        sauna monitor would cache its first token forever and go permanently
        deaf ~1h after start — silently missing every session (there's no
        history API to recover them). On a 401/403 or an auth-typed GraphQL
        error we drop the cached token, re-login via SRP, and retry once.
        """
        url = self.discover()[service]["endpoint"]
        resp = self._client.post(
            url,
            json={"query": query, "variables": variables or {}},
            headers={"authorization": self._token()},
        )
        if resp.status_code in (401, 403) and _retry:
            self._id_token = None  # force a fresh SRP login on the retry
            return self._graphql(service, query, variables, _retry=False)
        resp.raise_for_status()
        body = resp.json()
        errors = body.get("errors")
        if errors:
            if _retry and _is_auth_error(errors):
                self._id_token = None
                return self._graphql(service, query, variables, _retry=False)
            raise HarviaAuthError(f"Harvia GraphQL error ({service}): {errors}")
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
        so the live ``data`` shape can be captured (`healthos harvia-raw`).

        Best-effort: each call is isolated so one failing query (e.g. a deviceId
        the resolver rejects) still lets the rest — and the all-important raw
        device tree — print."""

        def _try(fn, *a):
            try:
                return fn(*a)
            except Exception as exc:  # noqa: BLE001 - diagnostic, keep going
                return {"_error": str(exc)}

        tree = _try(self.device_tree)
        ids = device_ids(tree) if isinstance(tree, dict) else []
        return {
            "device_tree": tree,
            "device_ids": ids,
            "devices": {
                did: {
                    "state": _try(self.device_state, did),
                    "latest": _try(self.latest_data, did),
                }
                for did in ids
            },
        }

    def close(self) -> None:
        self._client.close()


def _is_auth_error(errors: list) -> bool:
    """True if an AppSync GraphQL error list looks like an expired/invalid token.

    Token expiry is normally surfaced as an HTTP 401 (handled separately); this
    covers the setups that instead return it in the 200 body as an
    ``UnauthorizedException`` errorType or a token/expired message. We match on
    those specifically — NOT on a bare "Unauthorized" message — because a
    resolver-level denial (e.g. querying the account's GROUP node) returns a
    plain "Unauthorized" that is permanent and must be skipped, not retried.
    """
    for err in errors or []:
        if not isinstance(err, dict):
            continue
        etype = str(err.get("errorType", "")).lower()
        msg = str(err.get("message", "")).lower()
        if "unauthorized" in etype or "token" in etype:
            return True
        if "token" in msg or "expired" in msg:
            return True
    return False


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


def reported_state(state: dict) -> dict:
    """Parse ``getDeviceState.reported`` (a JSON *string*) into a dict.

    Returns ``{}`` for anything unexpected (missing node, unparseable string),
    so callers can treat "no usable state" uniformly.
    """
    import json

    inner = state.get("getDeviceState") if isinstance(state, dict) else None
    if not isinstance(inner, dict):
        return {}
    reported = inner.get("reported")
    if isinstance(reported, str):
        try:
            reported = json.loads(reported)
        except json.JSONDecodeError:
            return {}
    return reported if isinstance(reported, dict) else {}


def is_active(state: dict) -> bool | None:
    """Whether the stove is on, from a ``getDeviceState`` payload.

    ``None`` when the shadow carries no ``active`` field (an empty/unprovisioned
    device), so the monitor can tell "off" apart from "not a real stove".
    """
    reported = reported_state(state)
    if "active" not in reported:
        return None
    return bool(reported["active"])


def identify_sauna_device(client: HarviaClient) -> str | None:
    """Pick the real sauna stove out of the account's device tree.

    The tree also contains a GROUP node (querying its state raises "Unauthorized")
    and can contain empty/unprovisioned devices (their reported shadow is a bare
    ``deviceId`` with no ``active`` flag). A real stove is the one whose state
    query succeeds *and* whose reported shadow exposes ``active`` — so we keep
    only that and skip the rest.
    """
    tree = client.device_tree()
    for did in device_ids(tree):
        try:
            state = client.device_state(did)
        except Exception:  # noqa: BLE001 - group node -> "Unauthorized"; skip it
            continue
        if is_active(state) is not None:
            return did
    return None


def pull(start_date: _date, end_date: _date, client: HarviaClient | None = None) -> dict:
    """Sync entry point. No-op when unconfigured.

    MyHarvia has no history API, so confirmed sauna sessions are captured live by
    the ``harvia_monitor`` poll loop, not this nightly pull — this stays a no-op
    (returning no events) so the nightly run neither errors nor writes guesses.
    """
    if not (settings.harvia_email and settings.harvia_password):
        return {}
    return {"events": []}


# --- session helpers (used by the monitor) --------------------------------
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

    The poll monitor tracks the active 1→0 edge directly, but this stays as the
    reducer for reconstructing sessions from a batch of samples (e.g. backfilling
    from a captured ``onDataUpdates`` stream).
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

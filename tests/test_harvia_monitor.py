"""Harvia poll monitor: reported-shadow parsing, device identification, and the
on/off session-edge logic (including restart recovery).

The client is driven with a mock transport and an injected IdToken (same pattern
as test_harvia); the monitor's clock and event sink are injected so the
transition logic runs without real time or a database.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

import healthos.sync.harvia as harvia
from healthos.sync.harvia_monitor import SaunaMonitor

BASE = "https://prod.myharvia-cloud.net"
REAL_ID = "bb79de41-693c-4791-9932-c719dd4acca4"
GROUP_ID = "3e4f408e-1111-2222-3333-444444444444"
EMPTY_ID = "646f2439-5555-6666-7777-888888888888"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "harvia_email", "me@example.com", raising=False)
    monkeypatch.setattr(settings, "harvia_password", "pw", raising=False)
    monkeypatch.setattr(settings, "harvia_endpoint_base", BASE, raising=False)
    monkeypatch.setattr(settings, "timezone", "UTC", raising=False)


def _discovery(service: str) -> dict:
    body = {"endpoint": f"https://{service}.appsync-api.eu-west-1.amazonaws.com/graphql"}
    if service == "users":
        body |= {"userPoolId": "eu-west-1_abc", "clientId": "cid-123"}
    return body


def _reported(active: int, device_id: str = REAL_ID) -> str:
    return json.dumps({"deviceId": device_id, "active": active, "displayName": "Home"})


# --- reported-shadow parsing ----------------------------------------------
def test_reported_state_parses_json_string():
    state = {"getDeviceState": {"reported": _reported(1), "desired": "{}"}}
    assert harvia.reported_state(state)["active"] == 1


def test_reported_state_handles_garbage():
    assert harvia.reported_state({"getDeviceState": {"reported": "not json"}}) == {}
    assert harvia.reported_state({}) == {}


def test_is_active_distinguishes_off_from_no_stove():
    assert harvia.is_active({"getDeviceState": {"reported": _reported(1)}}) is True
    assert harvia.is_active({"getDeviceState": {"reported": _reported(0)}}) is False
    # empty/unprovisioned device: bare deviceId, no `active` field
    bare = json.dumps({"deviceId": EMPTY_ID})
    assert harvia.is_active({"getDeviceState": {"reported": bare}}) is None


# --- device identification -------------------------------------------------
def _identify_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/endpoint"):
        return httpx.Response(200, json=_discovery(url.split("/")[-2]))
    body = json.loads(request.content)
    variables = body.get("variables", {})
    if "getDeviceTree" in body["query"]:
        tree = json.dumps([{"id": GROUP_ID}, {"id": EMPTY_ID}, {"id": REAL_ID}])
        return httpx.Response(200, json={"data": {"getDeviceTree": tree}})
    did = variables.get("deviceId")
    if did == GROUP_ID:  # group node -> Unauthorized, like the live account
        return httpx.Response(200, json={"errors": [{"message": "Unauthorized"}]})
    if did == EMPTY_ID:  # unprovisioned: bare deviceId, no `active`
        return httpx.Response(
            200, json={"data": {"getDeviceState": {"reported": json.dumps({"deviceId": did})}}}
        )
    return httpx.Response(200, json={"data": {"getDeviceState": {"reported": _reported(0)}}})


def _client(handler) -> harvia.HarviaClient:
    c = harvia.HarviaClient(transport=httpx.MockTransport(handler))
    c._id_token = "id-tok"
    return c


def test_identify_skips_group_and_empty_devices():
    assert harvia.identify_sauna_device(_client(_identify_handler)) == REAL_ID


# --- monitor session edge --------------------------------------------------
class FakeClient:
    """Returns queued reported `active` values, one per device_state() call."""

    def __init__(self, actives: list[int]):
        self._actives = list(actives)
        self.calls = 0

    def device_state(self, device_id):
        self.calls += 1
        active = self._actives.pop(0)
        return {"getDeviceState": {"reported": _reported(active)}}


def _monitor(actives, tmp_path, start_minute=0):
    """A monitor over a fake clock that advances 1 minute per poll."""
    clock = {"t": datetime(2026, 6, 1, 18, start_minute, tzinfo=timezone.utc).timestamp()}

    def now():
        t = clock["t"]
        clock["t"] += 60
        return t

    written: list = []
    m = SaunaMonitor(
        client=FakeClient(actives),
        state_path=tmp_path / "state.json",
        now=now,
        writer=written.append,
    )
    m._device_id = REAL_ID
    return m, written


def test_session_recorded_on_off_edge(tmp_path):
    # on for 25 polls (~25 min), then off -> one 25-minute event.
    m, written = _monitor([1] * 25 + [0], tmp_path)
    events = [m.poll_once() for _ in range(26)]
    recorded = [e for e in events if e is not None]
    assert len(recorded) == 1
    ev = recorded[0]
    assert ev.event_type == "sauna" and ev.confidence == "confirmed"
    assert ev.value == 25
    assert ev.date == date(2026, 6, 1)
    assert written == [[ev]]
    # state file cleared after the session closes
    assert not (tmp_path / "state.json").exists()


def test_short_blip_not_recorded(tmp_path):
    m, written = _monitor([1, 1, 0], tmp_path)  # ~2 min, under the 5-min floor
    events = [m.poll_once() for _ in range(3)]
    assert all(e is None for e in events)
    assert written == []


def test_in_progress_state_persisted_then_resumed(tmp_path):
    state = tmp_path / "state.json"
    # Six on-polls -> last_active is ~5 min past start (the recorded floor).
    m, _ = _monitor([1] * 6, tmp_path)
    for _ in range(6):
        m.poll_once()  # session in progress, last_active advancing
    saved = json.loads(state.read_text())
    assert saved["session_start"] is not None
    assert saved["device_id"] == REAL_ID

    # A fresh monitor (simulating a restart) loads the in-progress start.
    m2, written = _monitor([0], tmp_path, start_minute=40)
    assert m2._start == saved["session_start"]
    # recover() sees the stove now off -> closes using the last seen-active time.
    ev = m2.recover()
    assert ev is not None and ev.value == 5
    assert written == [[ev]]
    assert not state.exists()


def test_recover_keeps_running_session(tmp_path):
    m, _ = _monitor([1, 1], tmp_path)
    m.poll_once()
    m2, written = _monitor([1], tmp_path, start_minute=40)  # still on at restart
    assert m2.recover() is None  # nothing closed; keep counting
    assert written == []
    assert (tmp_path / "state.json").exists()

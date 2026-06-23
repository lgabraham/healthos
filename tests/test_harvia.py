"""Harvia (MyHarvia) sync: Cognito auth, session collapsing, normalization."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

import healthos.sync.harvia as harvia


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "harvia_email", "me@example.com", raising=False)
    monkeypatch.setattr(settings, "harvia_password", "pw", raising=False)
    monkeypatch.setattr(settings, "harvia_region", "eu-west-1", raising=False)
    monkeypatch.setattr(settings, "harvia_cognito_client_id", "client-123", raising=False)
    monkeypatch.setattr(settings, "timezone", "UTC", raising=False)


def _transport(handler):
    return httpx.MockTransport(handler)


def _epoch(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_login_uses_cognito_initiate_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "cognito-idp.eu-west-1.amazonaws.com" in str(request.url)
        assert request.headers["x-amz-target"].endswith("InitiateAuth")
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"AuthenticationResult": {"IdToken": "id-tok"}})

    client = harvia.HarviaClient(transport=_transport(handler))
    assert client.login() == "id-tok"
    assert seen["AuthFlow"] == "USER_PASSWORD_AUTH"
    assert seen["ClientId"] == "client-123"
    assert seen["AuthParameters"]["USERNAME"] == "me@example.com"


def test_login_failure_surfaces_aws_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"__type": "NotAuthorizedException"})

    client = harvia.HarviaClient(transport=_transport(handler))
    with pytest.raises(harvia.HarviaAuthError, match="400.*NotAuthorized"):
        client.login()


def test_sessions_from_samples_splits_on_gap():
    samples = [
        {"timestamp": _epoch(2026, 6, 1, 18, 0), "active": True},
        {"timestamp": _epoch(2026, 6, 1, 18, 10), "active": True},
        {"timestamp": _epoch(2026, 6, 1, 18, 20), "active": True},
        # off for an hour -> new session
        {"timestamp": _epoch(2026, 6, 1, 19, 30), "heatOn": False},
        {"timestamp": _epoch(2026, 6, 1, 20, 0), "heatOn": True},
        {"timestamp": _epoch(2026, 6, 1, 20, 12), "heatOn": True},
    ]
    sessions = harvia.sessions_from_samples(samples)
    assert len(sessions) == 2
    assert round((sessions[0][1] - sessions[0][0]) / 60) == 20
    assert round((sessions[1][1] - sessions[1][0]) / 60) == 12


def test_normalize_emits_confirmed_sauna_event_per_day():
    raw = {
        "getLatestData": [
            {"timestamp": _epoch(2026, 6, 1, 18, 0), "active": True},
            {"timestamp": _epoch(2026, 6, 1, 18, 25), "active": True},
            # too short to count
            {"timestamp": _epoch(2026, 6, 3, 7, 0), "active": True},
            {"timestamp": _epoch(2026, 6, 3, 7, 2), "active": True},
        ]
    }
    events = harvia.normalize({"dev-1": raw}, date(2026, 6, 1), date(2026, 6, 30))
    assert len(events) == 1  # only the 25-min session clears the floor
    ev = events[0]
    assert ev.date == date(2026, 6, 1)
    assert ev.event_type == "sauna"
    assert ev.confidence == "confirmed"
    assert ev.source == "harvia"
    assert ev.value == 25


def test_normalize_respects_date_window():
    raw = {"items": [
        {"ts": _epoch(2026, 5, 1, 18, 0), "on": True},
        {"ts": _epoch(2026, 5, 1, 18, 30), "on": True},
    ]}
    assert harvia.normalize({"d": raw}, date(2026, 6, 1), date(2026, 6, 30)) == []


def test_pull_noop_when_unconfigured(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "harvia_email", None, raising=False)
    assert harvia.pull(date(2026, 6, 1), date(2026, 6, 30)) == {}


def test_pull_end_to_end_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "cognito-idp" in url:
            return httpx.Response(200, json={"AuthenticationResult": {"IdToken": "id-tok"}})
        body = json.loads(request.content)
        if "/device/graphql" in url:
            return httpx.Response(200, json={"data": {"getDevices": [{"id": "dev-1"}]}})
        if "/data/graphql" in url:
            assert request.headers["authorization"] == "id-tok"
            assert body["variables"]["deviceId"] == "dev-1"
            return httpx.Response(200, json={"data": {"getLatestData": [
                {"timestamp": _epoch(2026, 6, 2, 19, 0), "active": True},
                {"timestamp": _epoch(2026, 6, 2, 19, 30), "active": True},
            ]}})
        raise AssertionError(f"unexpected url {url}")

    client = harvia.HarviaClient(transport=_transport(handler))
    out = harvia.pull(date(2026, 6, 1), date(2026, 6, 30), client=client)
    assert [e.event_type for e in out["events"]] == ["sauna"]
    assert out["events"][0].value == 30

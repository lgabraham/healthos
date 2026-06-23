"""Harvia (MyHarvia) client: endpoint discovery, GraphQL transport, device-id
extraction, and the session helpers used by the listener.

The live Cognito SRP login can't run offline, so auth is bypassed by injecting
an IdToken; everything downstream is exercised against a mock transport.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

import healthos.sync.harvia as harvia

BASE = "https://prod.myharvia-cloud.net"
DEVICE_GQL = "https://device.appsync-api.eu-west-1.amazonaws.com/graphql"
DATA_GQL = "https://data.appsync-api.eu-west-1.amazonaws.com/graphql"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "harvia_email", "me@example.com", raising=False)
    monkeypatch.setattr(settings, "harvia_password", "pw", raising=False)
    monkeypatch.setattr(settings, "harvia_region", "eu-west-1", raising=False)
    monkeypatch.setattr(settings, "harvia_cognito_client_id", None, raising=False)
    monkeypatch.setattr(settings, "harvia_endpoint_base", BASE, raising=False)
    monkeypatch.setattr(settings, "timezone", "UTC", raising=False)


def _discovery_response(service: str) -> dict:
    body = {"endpoint": f"https://{service}.appsync-api.eu-west-1.amazonaws.com/graphql"}
    if service == "users":
        body |= {"userPoolId": "eu-west-1_abc", "clientId": "cid-123",
                 "identityPoolId": "eu-west-1:pool"}
    return body


def _client_with(handler) -> harvia.HarviaClient:
    c = harvia.HarviaClient(transport=httpx.MockTransport(handler))
    c._id_token = "id-tok"  # bypass the live SRP login
    return c


def test_discover_fetches_each_service_unauthenticated():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert "authorization" not in request.headers  # bootstrap is unauthed
        service = str(request.url).split("/")[-2]
        return httpx.Response(200, json=_discovery_response(service))

    eps = _client_with(handler).discover()
    assert eps["users"]["clientId"] == "cid-123"
    assert eps["data"]["endpoint"] == DATA_GQL
    assert f"{BASE}/users/endpoint" in seen


def test_graphql_posts_to_discovered_url_with_token():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/endpoint"):
            return httpx.Response(200, json=_discovery_response(url.split("/")[-2]))
        captured["url"] = url
        captured["auth"] = request.headers.get("authorization")
        captured["query"] = json.loads(request.content)["query"]
        return httpx.Response(200, json={"data": {"getDeviceTree": "{}"}})

    _client_with(handler).device_tree()
    assert captured["url"] == DEVICE_GQL
    assert captured["auth"] == "id-tok"
    assert "getDeviceTree" in captured["query"]


def test_graphql_raises_on_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/endpoint"):
            return httpx.Response(200, json=_discovery_response(str(request.url).split("/")[-2]))
        return httpx.Response(200, json={"errors": [{"message": "nope"}]})

    with pytest.raises(harvia.HarviaAuthError, match="nope"):
        _client_with(handler).device_tree()


def test_device_ids_extracts_uuids_from_json_string():
    tree = {"getDeviceTree": json.dumps({"group": [
        {"id": "11111111-2222-3333-4444-555555555555"},
        {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
    ]})}
    assert harvia.device_ids(tree) == [
        "11111111-2222-3333-4444-555555555555",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    ]


def _epoch(y, mo, d, h, mi):
    from datetime import datetime, timezone

    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_sessions_from_samples_splits_on_gap():
    samples = [
        (_epoch(2026, 6, 1, 18, 0), True),
        (_epoch(2026, 6, 1, 18, 10), True),
        (_epoch(2026, 6, 1, 18, 20), True),
        (_epoch(2026, 6, 1, 19, 30), False),
        (_epoch(2026, 6, 1, 20, 0), True),
        (_epoch(2026, 6, 1, 20, 12), True),
    ]
    sessions = harvia.sessions_from_samples(samples)
    assert len(sessions) == 2
    assert round((sessions[0][1] - sessions[0][0]) / 60) == 20
    assert round((sessions[1][1] - sessions[1][0]) / 60) == 12


def test_sauna_event_from_session():
    ev = harvia.sauna_event(_epoch(2026, 6, 1, 18, 0), _epoch(2026, 6, 1, 18, 25))
    assert ev is not None
    assert ev.date == date(2026, 6, 1)
    assert ev.event_type == "sauna"
    assert ev.confidence == "confirmed"
    assert ev.source == "harvia"
    assert ev.value == 25


def test_sauna_event_ignores_blip():
    assert harvia.sauna_event(_epoch(2026, 6, 1, 18, 0), _epoch(2026, 6, 1, 18, 2)) is None


def test_pull_noop_when_unconfigured(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "harvia_email", None, raising=False)
    assert harvia.pull(date(2026, 6, 1), date(2026, 6, 30)) == {}


def test_pull_configured_returns_no_events_until_listener():
    # No history API -> the pull is intentionally event-free (listener captures).
    assert harvia.pull(date(2026, 6, 1), date(2026, 6, 30)) == {"events": []}

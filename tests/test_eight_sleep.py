"""Eight Sleep client: modern OAuth auth, trends fetch, error reporting."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

import healthos.sync.eight_sleep as es


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "eight_sleep_email", "me@example.com", raising=False)
    monkeypatch.setattr(settings, "eight_sleep_password", "pw", raising=False)
    monkeypatch.setattr(settings, "eight_sleep_client_id", None, raising=False)
    monkeypatch.setattr(settings, "eight_sleep_client_secret", None, raising=False)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_login_posts_password_grant_and_returns_user_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == es.AUTH_URL
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"access_token": "tok123", "userId": "u-42"})

    client = es.EightSleepClient(transport=_transport(handler))
    assert client.login() == "u-42"
    assert seen["grant_type"] == "password"
    assert seen["username"] == "me@example.com"
    assert seen["client_id"] == es.DEFAULT_CLIENT_ID


def test_login_failure_includes_server_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = es.EightSleepClient(transport=_transport(handler))
    with pytest.raises(es.EightSleepAuthError, match="400.*invalid_grant"):
        client.login()


def test_fetch_returns_sessions_with_query_date():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(es.AUTH_URL):
            return httpx.Response(200, json={"access_token": "tok", "userId": "u-1"})
        assert request.headers["authorization"] == "Bearer tok"
        assert "/users/u-1/trends" in str(request.url)
        return httpx.Response(
            200,
            json={
                "days": [
                    {
                        "day": "2026-06-07",
                        "sessions": [
                            {
                                "ts": "2026-06-07T06:30:00Z",
                                "score": 82,
                                "tnt": 3,
                                "tempBedC": [27.1, 27.4],
                                "stages": [
                                    {"stage": "light", "duration": 3600},
                                    {"stage": "deep", "duration": 5400},
                                    {"stage": "rem", "duration": 4500},
                                ],
                            }
                        ],
                    },
                    {"day": "2026-06-08", "score": 75, "sleepDuration": 25200},
                ]
            },
        )

    client = es.EightSleepClient(transport=_transport(handler))
    sessions = client.fetch(date(2026, 6, 7), date(2026, 6, 8))
    assert len(sessions) == 2  # one real session + one day-level fallback
    assert sessions[0]["_query_date"] == "2026-06-07"
    assert sessions[1]["_query_date"] == "2026-06-08"

    sleeps, points = es.normalize(sessions)
    assert len(sleeps) == 2
    first = sleeps[0]
    assert first.deep_minutes == 90
    assert first.rem_minutes == 75
    assert float(first.sleep_score) == 82
    metric_names = {p.metric for p in points}
    assert {"bed_temp", "toss_turn_count"} <= metric_names


def test_missing_credentials_raise(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "eight_sleep_email", None, raising=False)
    with pytest.raises(es.EightSleepAuthError, match="credentials missing"):
        es.EightSleepClient()

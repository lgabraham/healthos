"""Auth self-check ("doctor").

Reports, per provider, whether credentials are configured and whether a live
authenticated call succeeds — without ever returning secret values. Run it after
filling in .env (or Railway env vars) to confirm each integration is wired up:

    healthos doctor
    GET /api/admin/auth-status
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from .config import settings
from .tokenstore import load as load_tokens

log = logging.getLogger(__name__)


@dataclass
class ProviderStatus:
    provider: str
    configured: bool
    connected: bool | None  # None = not attempted (because not configured)
    detail: str

    @property
    def symbol(self) -> str:
        if not self.configured:
            return "○"  # not set up
        if self.connected is None:
            return "?"
        return "✓" if self.connected else "✗"


def check_whoop() -> ProviderStatus:
    has_app = bool(settings.whoop_client_id and settings.whoop_client_secret)
    access, refresh = load_tokens("whoop")
    has_tokens = bool(access or refresh)

    if not has_app and not has_tokens:
        return ProviderStatus(
            "whoop", False, None,
            "Set WHOOP_CLIENT_ID/SECRET, then authorize at /auth/whoop.",
        )
    if not has_tokens:
        return ProviderStatus(
            "whoop", False, None,
            "App credentials present but not authorized yet — visit /auth/whoop.",
        )
    try:
        from .sync.whoop import WhoopClient

        client = WhoopClient.from_store()
        profile = client.profile()
        client.close()
        name = profile.get("first_name") or profile.get("email") or "connected"
        return ProviderStatus("whoop", True, True, f"Authorized ({name}).")
    except Exception as exc:  # noqa: BLE001
        return ProviderStatus("whoop", True, False, f"Auth call failed: {exc}")


def check_garmin() -> ProviderStatus:
    configured = bool(settings.garmin_email and settings.garmin_password) or bool(
        settings.garmin_tokenstore
    )
    if not configured:
        return ProviderStatus(
            "garmin", False, None, "Set GARMIN_EMAIL and GARMIN_PASSWORD."
        )
    try:
        from .sync.garmin import GarminClient

        client = GarminClient()
        client.login()
        return ProviderStatus("garmin", True, True, "Logged in to Garmin Connect.")
    except ImportError:
        return ProviderStatus(
            "garmin", True, False, "garth not installed (uv pip install garth)."
        )
    except Exception as exc:  # noqa: BLE001
        return ProviderStatus("garmin", True, False, f"Login failed: {exc}")


def check_eight_sleep() -> ProviderStatus:
    configured = bool(settings.eight_sleep_email and settings.eight_sleep_password)
    if not configured:
        return ProviderStatus(
            "eight_sleep", False, None,
            "Set EIGHT_SLEEP_EMAIL and EIGHT_SLEEP_PASSWORD.",
        )
    try:
        from .sync.eight_sleep import EightSleepClient

        client = EightSleepClient()
        user_id = client.login()
        client.close()
        return ProviderStatus(
            "eight_sleep", True, True, f"Authenticated (user {user_id[:8]}…)."
        )
    except Exception as exc:  # noqa: BLE001
        return ProviderStatus("eight_sleep", True, False, str(exc))


CHECKS = {
    "whoop": check_whoop,
    "garmin": check_garmin,
    "eight_sleep": check_eight_sleep,
}


def check_all(only: str | None = None) -> list[dict]:
    """Check all providers, or just one — handy when a provider (Garmin) is
    rate-limiting and shouldn't be poked while testing the others."""
    names = [only] if only else list(CHECKS)
    return [asdict(CHECKS[n]()) for n in names]

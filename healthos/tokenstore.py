"""DB-backed OAuth token storage.

Tokens are read with an env-var fallback (so a freshly seeded .env still works)
and written back to the DB on the OAuth callback and on every refresh. This
removes the copy-paste-tokens-into-env step from onboarding: authorizing once —
even from a phone against the deployed callback URL — is enough.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert

from .config import settings
from .database import get_session
from .models import OAuthToken


def load(provider: str) -> tuple[str | None, str | None]:
    """Return (access_token, refresh_token) for a provider.

    Prefers DB-stored tokens; falls back to env vars (Whoop only) so the very
    first run after pasting tokens into .env still authenticates.
    """
    with get_session() as session:
        row = session.get(OAuthToken, provider)
        if row and (row.access_token or row.refresh_token):
            return row.access_token, row.refresh_token
    if provider == "whoop":
        return settings.whoop_access_token, settings.whoop_refresh_token
    return None, None


def save(provider: str, access_token: str | None, refresh_token: str | None) -> None:
    """Upsert tokens for a provider."""
    with get_session() as session:
        stmt = (
            pg_insert(OAuthToken)
            .values(
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            .on_conflict_do_update(
                index_elements=["provider"],
                set_={"access_token": access_token, "refresh_token": refresh_token},
            )
        )
        session.execute(stmt)

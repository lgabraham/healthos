"""Application settings loaded from environment variables / .env.

All configuration lives here so the rest of the app never reads os.environ
directly. Import the singleton ``settings`` (or call ``get_settings()``).
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Database -------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://healthos:healthos@localhost:5432/healthos",
        alias="DATABASE_URL",
    )

    # Whoop ----------------------------------------------------------------
    whoop_client_id: str | None = Field(default=None, alias="WHOOP_CLIENT_ID")
    whoop_client_secret: str | None = Field(default=None, alias="WHOOP_CLIENT_SECRET")
    whoop_redirect_uri: str = Field(
        default="http://localhost:8000/auth/whoop/callback", alias="WHOOP_REDIRECT_URI"
    )
    whoop_access_token: str | None = Field(default=None, alias="WHOOP_ACCESS_TOKEN")
    whoop_refresh_token: str | None = Field(default=None, alias="WHOOP_REFRESH_TOKEN")

    # Garmin ---------------------------------------------------------------
    garmin_email: str | None = Field(default=None, alias="GARMIN_EMAIL")
    garmin_password: str | None = Field(default=None, alias="GARMIN_PASSWORD")
    garmin_tokenstore: str | None = Field(default=None, alias="GARMIN_TOKENSTORE")

    # Eight Sleep ----------------------------------------------------------
    eight_sleep_email: str | None = Field(default=None, alias="EIGHT_SLEEP_EMAIL")
    eight_sleep_password: str | None = Field(default=None, alias="EIGHT_SLEEP_PASSWORD")

    # App ------------------------------------------------------------------
    timezone: str = Field(default="America/Los_Angeles", alias="TIMEZONE")
    sync_hour: int = Field(default=6, alias="SYNC_HOUR")
    port: int = Field(default=8000, alias="PORT")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")
    # Run the in-process nightly scheduler. Set false when an external cron owns
    # the schedule (e.g. an always-on host running `healthos sync`), so the two
    # don't double-sync — which matters for Garmin's rate limits.
    enable_scheduler: bool = Field(default=True, alias="ENABLE_SCHEDULER")

    @property
    def tz(self) -> ZoneInfo:
        """User's local timezone as a ZoneInfo object."""
        return ZoneInfo(self.timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def sync_db_url(self) -> str:
        """A psycopg (sync) SQLAlchemy URL.

        Accepts plain ``postgresql://`` URLs (e.g. Railway's) and upgrades them
        to the psycopg v3 driver that SQLAlchemy expects here.
        """
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

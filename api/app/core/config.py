"""Environment-driven application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Typed settings loaded from environment variables.

    The Docker Compose stack injects these values through ``env_file``.
    Values are never hardcoded in application code.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "production", "test"] = "production"
    log_level: str = "INFO"
    cors_allow_origins: str = "*"
    cors_allow_credentials: bool = False

    # PostgreSQL. The three credentials are required only when DATABASE_URL
    # is not provided; the model validator below enforces that rule.
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    postgres_host: str = "db"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    database_url: str | None = None

    # INETER scraping
    ineter_url: str = "https://webserver2.ineter.gob.ni/geofisica/sis/events/sismos.php"
    ineter_timeout_seconds: float = Field(default=25.0, gt=0, le=120)
    ineter_poll_interval_seconds: int = Field(default=120, ge=30, le=86_400)
    ineter_retries: int = Field(default=3, ge=1, le=10)
    ineter_retry_backoff_seconds: float = Field(default=1.5, ge=0, le=30)
    ineter_verify_tls: bool = True
    ineter_ca_bundle: str | None = (
        "certs/sectigo-public-server-authentication-ca-ov-r36.pem"
    )
    ineter_max_response_bytes: int = Field(default=5_242_880, ge=10_000)

    # Synchronization
    sync_enabled: bool = True
    sync_advisory_lock_key: int = Field(default=8_102_026, ge=1)

    # WebSocket
    ws_initial_events: int = Field(default=30, ge=0, le=200)
    ws_max_connections: int = Field(default=200, ge=1, le=10_000)
    ws_max_replay_events: int = Field(default=500, ge=1, le=10_000)
    ws_notification_replay_seconds: int = Field(default=300, ge=0, le=86_400)

    # Authentication & ISO 27001 session policy
    auth_register_rate_limit: int = Field(default=10, ge=1, le=100_000)
    auth_login_rate_limit: int = Field(default=20, ge=1, le=100_000)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    auth_token_expire_days: int = Field(default=30, ge=1, le=365)
    auth_max_failed_attempts: int = Field(default=5, ge=3, le=20)
    auth_lockout_minutes: int = Field(default=15, ge=1, le=1440)

    # Community reports
    reports_max_active: int = Field(default=100, ge=1, le=100)
    report_photo_max_bytes: int = Field(
        default=5_242_880,
        ge=1,
        le=5_242_880,
    )
    public_api_base_url: str | None = None

    # Supabase Storage
    supabase_url: str | None = None
    supabase_key: str | None = None
    supabase_publishable_key: str | None = None
    supabase_bucket: str = "Imagenes"
    supabase_s3_endpoint: str | None = None
    supabase_s3_region: str = "us-east-1"
    supabase_s3_access_key_id: str | None = None
    supabase_s3_secret_access_key: str | None = None

    # Emergency notifications derived from newly detected seismic events
    emergency_notifications_enabled: bool = True
    emergency_min_magnitude: float = Field(default=5.0, ge=-2, le=10)
    emergency_max_event_age_seconds: int = Field(default=1800, ge=0, le=86_400)

    @model_validator(mode="after")
    def _validate_database_configuration(self) -> "Settings":
        """Require either a full URL or the three PostgreSQL credentials."""
        if self.database_url:
            return self
        missing = [
            name
            for name in ("postgres_user", "postgres_password", "postgres_db")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                "Set DATABASE_URL or provide POSTGRES_USER, POSTGRES_PASSWORD "
                f"and POSTGRES_DB (missing: {', '.join(missing)})"
            )
        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return an async SQLAlchemy URL, allowing an explicit override."""
        if self.database_url:
            return self.database_url
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def cors_origins(self) -> list[str]:
        """Parse the comma-separated CORS origins setting."""
        origins = [origin.strip() for origin in self.cors_allow_origins.split(",")]
        return [origin for origin in origins if origin]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()  # type: ignore[call-arg]

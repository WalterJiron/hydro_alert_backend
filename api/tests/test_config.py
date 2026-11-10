import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_database_url_override_does_not_require_postgres_parts() -> None:
    url = "postgresql+asyncpg://user:secret@localhost:5432/events"

    settings = Settings(
        _env_file=None,
        database_url=url,
        app_env="test",
        sync_enabled=False,
    )

    assert settings.sqlalchemy_database_url == url


def test_postgres_parts_are_required_without_database_url(monkeypatch) -> None:
    for name in (
        "DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, app_env="test", sync_enabled=False)

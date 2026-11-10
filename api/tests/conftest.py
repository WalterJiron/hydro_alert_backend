from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator, Sequence
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from app.auth.infrastructure import orm as _auth_orm  # noqa: F401
from app.realtime.infrastructure import event_orm as _realtime_orm  # noqa: F401
from app.reports.infrastructure import orm as _reports_orm  # noqa: F401
from app.seismic.domain.entities import SeismicEvent
from app.seismic.infrastructure import orm as _orm  # noqa: F401
from tests.fakes import make_event

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "postgres_user": "test",
        "postgres_password": "test",
        "postgres_db": "test",
        "app_env": "test",
        "sync_enabled": False,
        "ineter_retry_backoff_seconds": 0,
        # Keep the functional suite below the production limits; the rate
        # limiting test overrides these explicitly.
        "auth_register_rate_limit": 10_000,
        "auth_login_rate_limit": 10_000,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def ineter_html() -> str:
    return (FIXTURES_DIR / "ineter_page.html").read_text(encoding="utf-8")


@pytest.fixture
def sample_events() -> Sequence[SeismicEvent]:
    return [
        make_event(hour=20, minute=26, latitude=12.934, longitude=-89.573, magnitude=3.1),
        make_event(hour=18, minute=10, latitude=14.384, longitude=-90.108, magnitude=4.2),
        make_event(day=7, hour=22, minute=5, latitude=12.294, longitude=-87.688, magnitude=2.5),
    ]


@pytest_asyncio.fixture
async def postgres_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL integration test skipped")

    schema = f"test_{uuid4().hex}"
    admin_engine = create_async_engine(url, poolclass=NullPool)
    test_engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )

    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        yield async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    finally:
        await test_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            )
        await admin_engine.dispose()

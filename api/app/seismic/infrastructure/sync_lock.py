"""PostgreSQL advisory lock for cross-instance synchronization exclusion."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import SyncLockUnavailableError

logger = logging.getLogger(__name__)


class PostgresAdvisoryLock:
    """Session-level advisory lock held on a dedicated connection.

    This complements the per-process asyncio lock. If the API is scaled to
    several containers, only one of them can run the INETER scrape at a time.
    """

    def __init__(self, engine: AsyncEngine, key: int) -> None:
        self._engine = engine
        self._key = key
        self._connection: AsyncConnection | None = None

    async def __aenter__(self) -> None:
        connection = await self._engine.connect()
        try:
            acquired = (
                await connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": self._key},
                )
            ).scalar_one()
            await connection.commit()
        except BaseException:
            await connection.close()
            raise

        if not acquired:
            await connection.close()
            raise SyncLockUnavailableError(
                "Another API instance is already synchronizing INETER events"
            )

        self._connection = connection
        logger.debug(
            "synchronization advisory lock acquired",
            extra={"event": "sync_lock_acquired", "lock_key": self._key},
        )

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": self._key},
            )
            await connection.commit()
            logger.debug(
                "synchronization advisory lock released",
                extra={"event": "sync_lock_released", "lock_key": self._key},
            )
        finally:
            await connection.close()

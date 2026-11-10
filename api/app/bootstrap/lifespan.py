"""Application lifespan: startup and graceful shutdown."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.bootstrap.container import ContainerFactory
from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_lifespan(settings: Settings, container_factory: ContainerFactory):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application startup",
            extra={
                "event": "application_startup",
                "environment": settings.app_env,
                "sync_enabled": settings.sync_enabled,
                "poll_interval_seconds": settings.ineter_poll_interval_seconds,
            },
        )
        container = container_factory(settings)
        app.state.container = container
        try:
            await container.start()
        except BaseException:
            await container.aclose()
            raise

        try:
            yield
        finally:
            app.state.container = None
            await container.aclose()

    return lifespan

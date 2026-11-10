"""Composition root: build concrete adapters and wire use cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.application.auth_service import AuthService
from app.auth.infrastructure.repository import (
    SqlAlchemyAuditLogger,
    SqlAlchemyAuthRepository,
)
from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter
from app.db.session import create_engine, create_session_factory
from app.realtime.application.connection_manager import ConnectionManager
from app.realtime.application.emergency_notifications import (
    EmergencyNotificationService,
)
from app.realtime.application.event_publisher import ConnectionManagerEventPublisher
from app.realtime.application.realtime_hub import RealtimeHub
from app.realtime.application.realtime_publisher import PersistentRealtimePublisher
from app.realtime.application.seismic_fanout import SeismicEventPublisherFanout
from app.realtime.infrastructure.event_repository import SqlAlchemyRealtimeEventStore
from app.reports.application.report_service import ReportService
from app.reports.domain.ports import PhotoStorage
from app.reports.infrastructure.repository import SqlAlchemyReportRepository
from app.reports.infrastructure.storage import (
    InMemoryPhotoStorage,
    SupabasePhotoStorage,
)
from app.seismic.application.sync_events import SyncSeismicEvents
from app.seismic.infrastructure.ineter_client import IneterHttpClient
from app.seismic.infrastructure.ineter_parser import IneterHtmlParser
from app.seismic.infrastructure.repository import SqlAlchemySeismicEventRepository
from app.seismic.infrastructure.sync_lock import PostgresAdvisoryLock
from app.seismic.infrastructure.sync_worker import SyncWorker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContainer:
    """Owns process-scoped resources and wired dependencies."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    repository: SqlAlchemySeismicEventRepository
    connection_manager: ConnectionManager
    publisher: ConnectionManagerEventPublisher
    realtime_hub: RealtimeHub
    realtime_events: SqlAlchemyRealtimeEventStore
    realtime_publisher: PersistentRealtimePublisher
    auth_service: AuthService
    report_service: ReportService
    photo_storage: PhotoStorage
    rate_limiter: InMemoryRateLimiter
    ineter_client: IneterHttpClient
    sync_use_case: SyncSeismicEvents
    sync_worker: SyncWorker | None

    async def start(self) -> None:
        try:
            await self.repository.ping()
            logger.info(
                "database connection established",
                extra={"event": "database_ready"},
            )
        except Exception:
            logger.exception(
                "database is not ready during startup",
                extra={"event": "database_not_ready"},
            )

        if self.sync_worker is not None:
            await self.sync_worker.start()

    async def aclose(self) -> None:
        if self.sync_worker is not None:
            await self.sync_worker.stop()
        await self.connection_manager.close_all()
        await self.realtime_hub.close_all()
        await self.ineter_client.aclose()
        if hasattr(self.photo_storage, "aclose"):
            await self.photo_storage.aclose()
        await self.engine.dispose()
        logger.info(
            "application resources released",
            extra={"event": "application_shutdown"},
        )


ContainerFactory = Callable[[Settings], ApplicationContainer]


def build_container(settings: Settings) -> ApplicationContainer:
    """Wire production adapters. Tests can inject an alternative factory."""
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    repository = SqlAlchemySeismicEventRepository(session_factory)

    connection_manager = ConnectionManager(
        max_connections=settings.ws_max_connections
    )
    publisher = ConnectionManagerEventPublisher(connection_manager)

    realtime_hub = RealtimeHub(
        max_connections=settings.ws_max_connections,
        max_replay_buffer=max(1_000, settings.ws_max_replay_events * 2),
    )
    realtime_events = SqlAlchemyRealtimeEventStore(session_factory)
    realtime_publisher = PersistentRealtimePublisher(
        store=realtime_events,
        hub=realtime_hub,
    )

    auth_service = AuthService(
        repository=SqlAlchemyAuthRepository(session_factory),
        audit_logger=SqlAlchemyAuditLogger(session_factory),
        token_expire_days=settings.auth_token_expire_days,
        max_failed_attempts=settings.auth_max_failed_attempts,
        lockout_minutes=settings.auth_lockout_minutes,
    )

    photo_storage: PhotoStorage
    if settings.supabase_url and settings.supabase_key:
        photo_storage = SupabasePhotoStorage(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_key,
            bucket=settings.supabase_bucket,
        )
    else:
        photo_storage = InMemoryPhotoStorage()

    report_service = ReportService(
        repository=SqlAlchemyReportRepository(session_factory),
        publisher=realtime_publisher,
        photo_storage=photo_storage,
        max_active=settings.reports_max_active,
        photo_max_bytes=settings.report_photo_max_bytes,
        public_api_base_url=settings.public_api_base_url,
    )
    rate_limiter = InMemoryRateLimiter(
        window_seconds=settings.auth_rate_limit_window_seconds
    )

    ineter_client = IneterHttpClient(settings)
    ineter_parser = IneterHtmlParser()
    distributed_lock = PostgresAdvisoryLock(
        engine,
        settings.sync_advisory_lock_key,
    )
    notifications = EmergencyNotificationService(realtime_publisher, settings)
    fanout = SeismicEventPublisherFanout(
        seismic=publisher,
        notifications=notifications,
    )
    sync_use_case = SyncSeismicEvents(
        fetcher=ineter_client,
        parser=ineter_parser,
        repository=repository,
        publisher=fanout,
        distributed_lock=distributed_lock,
    )
    sync_worker = (
        SyncWorker(
            sync_use_case,
            interval_seconds=settings.ineter_poll_interval_seconds,
        )
        if settings.sync_enabled
        else None
    )

    return ApplicationContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        repository=repository,
        connection_manager=connection_manager,
        publisher=publisher,
        realtime_hub=realtime_hub,
        realtime_events=realtime_events,
        realtime_publisher=realtime_publisher,
        auth_service=auth_service,
        report_service=report_service,
        photo_storage=photo_storage,
        rate_limiter=rate_limiter,
        ineter_client=ineter_client,
        sync_use_case=sync_use_case,
        sync_worker=sync_worker,
    )

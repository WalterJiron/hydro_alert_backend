"""In-memory test doubles for ports and the application container."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Sequence
from uuid import UUID

from app.auth.application.auth_service import AuthService
from app.auth.domain.entities import User
from app.core.config import Settings
from app.core.errors import (
    CedulaAlreadyRegisteredError,
    EmailAlreadyRegisteredError,
)
from app.core.rate_limit import InMemoryRateLimiter
from app.core.time import utc_now
from app.realtime.application.connection_manager import ConnectionManager
from app.realtime.application.emergency_notifications import (
    EmergencyNotificationService,
)
from app.realtime.application.event_publisher import ConnectionManagerEventPublisher
from app.realtime.application.realtime_hub import RealtimeHub
from app.realtime.application.realtime_publisher import PersistentRealtimePublisher
from app.realtime.application.seismic_fanout import SeismicEventPublisherFanout
from app.realtime.domain.events import (
    RealtimeChannel,
    RealtimeEvent,
    make_event_id,
    parse_event_id,
)
from app.realtime.domain.ports import ReplayResult
from app.reports.application.report_service import ReportService
from app.reports.domain.entities import Report, ReportPhoto
from app.reports.domain.ports import PhotoStorage
from app.reports.infrastructure.storage import InMemoryPhotoStorage
from app.seismic.domain.entities import ScrapedEvent, SeismicEvent
from app.seismic.domain.ports import (
    EventFilters,
    PaginatedEvents,
    UpsertResult,
)

def make_scraped(
    *,
    day: int = 8,
    hour: int = 20,
    minute: int = 26,
    latitude: float = 12.934,
    longitude: float = -89.573,
    depth: float | None = 23.0,
    magnitude: float | None = 3.1,
    location: str | None = "67 Km al suroeste de La Libertad, El Salvador",
    pais: str | None = None,
    status: str | None = "C",
    month: int = 11,
) -> ScrapedEvent:
    return ScrapedEvent(
        event_date=date(2026, month, day),
        event_time=time(hour, minute, 5),
        latitude=latitude,
        longitude=longitude,
        depth_km=depth,
        magnitude=magnitude,
        location=location,
        pais=pais,
        status=status,
    )


def make_event(**kwargs) -> SeismicEvent:
    registered_at = kwargs.pop("registered_at", datetime(2026, 11, 8, 12, tzinfo=UTC))
    return SeismicEvent.from_scraped(make_scraped(**kwargs), registered_at=registered_at)


class InMemorySeismicEventRepository:
    """Repository replacement used by HTTP, WebSocket and sync tests."""

    def __init__(self, events: Sequence[SeismicEvent] = ()) -> None:
        self.events: dict[UUID, SeismicEvent] = {event.id: event for event in events}
        self.fail_ping = False
        self.fail_list_recent = False
        self.fail_upsert = False

    async def list_recent(self, limit: int) -> Sequence[SeismicEvent]:
        if self.fail_list_recent:
            raise RuntimeError("simulated recent-events failure")
        return self._sorted()[:limit]

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        filters: EventFilters,
    ) -> PaginatedEvents:
        items = [
            event
            for event in self._sorted()
            if _matches_filters(event, filters)
        ]
        total = len(items)
        offset = (page - 1) * page_size
        return PaginatedEvents(
            items=items[offset : offset + page_size],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_by_id(self, event_id: object) -> SeismicEvent | None:
        return self.events.get(event_id)  # type: ignore[arg-type]

    async def count(self) -> int:
        return len(self.events)

    async def upsert_many(self, events: Sequence[SeismicEvent]) -> UpsertResult:
        if self.fail_upsert:
            raise RuntimeError("simulated persistence failure")

        created: list[SeismicEvent] = []
        updated: list[SeismicEvent] = []
        by_fingerprint = {event.fingerprint: event for event in self.events.values()}

        for event in events:
            existing = by_fingerprint.get(event.fingerprint)
            if existing is None:
                self.events[event.id] = event
                by_fingerprint[event.fingerprint] = event
                created.append(event)
            elif (
                existing.depth_km,
                existing.magnitude,
                existing.location,
                existing.pais,
                existing.status,
            ) != (
                event.depth_km,
                event.magnitude,
                event.location,
                event.pais,
                event.status,
            ):
                revised = SeismicEvent(
                    id=existing.id,
                    fingerprint=existing.fingerprint,
                    event_at=existing.event_at,
                    event_date=existing.event_date,
                    event_time=existing.event_time,
                    latitude=existing.latitude,
                    longitude=existing.longitude,
                    depth_km=event.depth_km,
                    magnitude=event.magnitude,
                    location=event.location,
                    pais=event.pais,
                    status=event.status,
                    source=existing.source,
                    source_timezone=event.source_timezone,
                    registered_at=existing.registered_at,
                    updated_at=utc_now(),
                )
                self.events[existing.id] = revised
                by_fingerprint[event.fingerprint] = revised
                updated.append(revised)

        return UpsertResult(created=created, updated=updated)

    async def ping(self) -> None:
        if self.fail_ping:
            raise RuntimeError("simulated database failure")

    def _sorted(self) -> list[SeismicEvent]:
        return sorted(
            self.events.values(),
            key=lambda event: (event.event_at, event.registered_at),
            reverse=True,
        )


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.created: list[SeismicEvent] = []
        self.updated: list[SeismicEvent] = []
        self.fail = fail

    async def publish_new(self, events: Sequence[SeismicEvent]) -> None:
        if self.fail:
            raise RuntimeError("simulated realtime failure")
        self.created.extend(events)

    async def publish_updated(self, events: Sequence[SeismicEvent]) -> None:
        if self.fail:
            raise RuntimeError("simulated realtime failure")
        self.updated.extend(events)


class FakeFetcher:
    def __init__(self, html: str = "", *, error: Exception | None = None) -> None:
        self.html = html
        self.error = error
        self.calls = 0

    async def fetch(self) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.html


class NullSyncLock:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> None:
        if self.unavailable:
            from app.core.errors import SyncLockUnavailableError

            raise SyncLockUnavailableError("simulated lock contention")
        self.entered += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.exited += 1


@dataclass
class FakeContainer:
    settings: Settings
    repository: InMemorySeismicEventRepository
    connection_manager: ConnectionManager
    publisher: ConnectionManagerEventPublisher
    realtime_hub: RealtimeHub
    realtime_events: InMemoryRealtimeEventStore
    realtime_publisher: PersistentRealtimePublisher
    auth_service: AuthService
    report_service: ReportService
    photo_storage: PhotoStorage
    rate_limiter: InMemoryRateLimiter
    notification_service: EmergencyNotificationService
    seismic_fanout: SeismicEventPublisherFanout
    sync_worker: object | None = None
    engine: object | None = None
    session_factory: object | None = None
    ineter_client: object | None = None
    sync_use_case: object | None = None

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        await self.connection_manager.close_all()
        await self.realtime_hub.close_all()


class InMemoryAuditLogger:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    async def log(
        self,
        *,
        action: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.logs.append({
            "action": action,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "details": details,
        })


def build_fake_container(
    settings: Settings,
    *,
    events: Sequence[SeismicEvent] = (),
) -> FakeContainer:
    repository = InMemorySeismicEventRepository(events)
    manager = ConnectionManager(max_connections=settings.ws_max_connections)
    publisher = ConnectionManagerEventPublisher(manager)

    realtime_hub = RealtimeHub(max_connections=settings.ws_max_connections)
    realtime_events = InMemoryRealtimeEventStore()
    realtime_publisher = PersistentRealtimePublisher(
        store=realtime_events,
        hub=realtime_hub,
    )
    notification_service = EmergencyNotificationService(
        realtime_publisher,
        settings,
    )
    seismic_fanout = SeismicEventPublisherFanout(
        seismic=publisher,
        notifications=notification_service,
    )
    auth_service = AuthService(
        InMemoryAuthRepository(),
        audit_logger=InMemoryAuditLogger(),
        token_expire_days=settings.auth_token_expire_days,
        max_failed_attempts=settings.auth_max_failed_attempts,
        lockout_minutes=settings.auth_lockout_minutes,
    )
    photo_storage = InMemoryPhotoStorage(public_api_base_url=settings.public_api_base_url)
    report_service = ReportService(
        repository=InMemoryReportRepository(),
        publisher=realtime_publisher,
        photo_storage=photo_storage,
        max_active=settings.reports_max_active,
        photo_max_bytes=settings.report_photo_max_bytes,
        public_api_base_url=settings.public_api_base_url,
    )
    return FakeContainer(
        settings=settings,
        repository=repository,
        connection_manager=manager,
        publisher=publisher,
        realtime_hub=realtime_hub,
        realtime_events=realtime_events,
        realtime_publisher=realtime_publisher,
        auth_service=auth_service,
        report_service=report_service,
        photo_storage=photo_storage,
        rate_limiter=InMemoryRateLimiter(
            window_seconds=settings.auth_rate_limit_window_seconds
        ),
        notification_service=notification_service,
        seismic_fanout=seismic_fanout,
    )


class InMemoryAuthRepository:
    def __init__(self) -> None:
        self.users_by_email: dict[str, User] = {}
        self.users_by_cedula: dict[str, User] = {}
        self.tokens: dict[str, str] = {}
        self.users_by_id: dict[str, User] = {}
        self.password_history: dict[str, list[str]] = {}

    async def find_by_email(self, email: str) -> User | None:
        return self.users_by_email.get(email)

    async def find_by_cedula(self, cedula_normalized: str) -> User | None:
        return self.users_by_cedula.get(cedula_normalized)

    async def create_user(self, user: User) -> User:
        if user.email in self.users_by_email:
            raise EmailAlreadyRegisteredError()
        if user.cedula_normalized in self.users_by_cedula:
            raise CedulaAlreadyRegisteredError()
        self.users_by_email[user.email] = user
        self.users_by_cedula[user.cedula_normalized] = user
        self.users_by_id[user.id] = user
        return user

    async def create_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime | None = None,
    ) -> None:
        self.tokens[token_hash] = user_id

    async def find_by_token_hash(self, token_hash: str) -> User | None:
        user_id = self.tokens.get(token_hash)
        if not user_id:
            return None
        user = self.users_by_id.get(user_id)
        if user and not user.is_active:
            return None
        return user

    async def record_login_failure(
        self,
        user_id: str,
        *,
        max_attempts: int = 5,
        lockout_minutes: int = 15,
    ) -> None:
        user = self.users_by_id.get(user_id)
        if user:
            from dataclasses import replace
            from datetime import timedelta
            from app.core.time import utc_now

            attempts = user.failed_login_attempts + 1
            locked = None
            if attempts >= max_attempts:
                locked = utc_now() + timedelta(minutes=lockout_minutes)
            updated = replace(user, failed_login_attempts=attempts, locked_until=locked)
            self.users_by_id[user_id] = updated
            self.users_by_email[user.email] = updated
            self.users_by_cedula[user.cedula_normalized] = updated

    async def record_login_success(self, user_id: str) -> None:
        user = self.users_by_id.get(user_id)
        if user:
            from dataclasses import replace

            updated = replace(user, failed_login_attempts=0, locked_until=None)
            self.users_by_id[user_id] = updated
            self.users_by_email[user.email] = updated
            self.users_by_cedula[user.cedula_normalized] = updated

    async def add_password_history(
        self,
        user_id: str,
        password_hash: str,
    ) -> None:
        self.password_history.setdefault(user_id, []).insert(0, password_hash)

    async def get_recent_password_hashes(
        self,
        user_id: str,
        limit: int = 5,
    ) -> Sequence[str]:
        return self.password_history.get(user_id, [])[:limit]


class InMemoryReportRepository:
    def __init__(self) -> None:
        self.reports: dict[str, Report] = {}

    async def create(
        self,
        report: Report,
        photo: ReportPhoto | None = None,
    ) -> Report:
        stored = Report(
            id=report.id,
            user_id=report.user_id,
            category=report.category,
            description=report.description,
            latitude=report.latitude,
            longitude=report.longitude,
            created_at=report.created_at,
            deleted_at=None,
            photo_url=report.photo_url,
        )
        self.reports[stored.id] = stored
        return stored

    async def list_active(self, limit: int) -> Sequence[Report]:
        active = [
            report
            for report in self.reports.values()
            if report.deleted_at is None
        ]
        active.sort(key=lambda report: (report.created_at, report.id), reverse=True)
        return active[:limit]

    async def get_active(self, report_id: str) -> Report | None:
        report = self.reports.get(report_id)
        if report is None or report.deleted_at is not None:
            return None
        return report

    async def deactivate(
        self,
        report_id: str,
        deleted_at: datetime,
    ) -> Report | None:
        report = await self.get_active(report_id)
        if report is None:
            return None
        from dataclasses import replace

        updated = replace(report, deleted_at=deleted_at)
        self.reports[report_id] = updated
        return updated


class InMemoryRealtimeEventStore:
    def __init__(self) -> None:
        self.events: list[RealtimeEvent] = []
        self._sequence = 0

    async def append(
        self,
        *,
        channel: RealtimeChannel,
        event: str,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> RealtimeEvent:
        self._sequence += 1
        stored = RealtimeEvent(
            seq=self._sequence,
            id=make_event_id(self._sequence),
            event=event,
            channel=channel,
            occurred_at=occurred_at,
            data=data,
        )
        self.events.append(stored)
        return stored

    async def last_sequence(self) -> int:
        return self._sequence

    async def replay(
        self,
        *,
        last_event_id: str | None,
        channels: Sequence[RealtimeChannel],
        max_events: int,
        notification_cutoff: datetime,
    ) -> ReplayResult:
        if last_event_id is None:
            return ReplayResult(events=(), resumed=True)
        last_sequence = parse_event_id(last_event_id)
        if last_sequence is None:
            return ReplayResult(events=(), resumed=False)
        if last_sequence > 0 and not any(
            event.id == last_event_id for event in self.events
        ):
            return ReplayResult(events=(), resumed=False)

        channel_values = {channel.value for channel in channels}
        selected = [
            event
            for event in self.events
            if event.seq > last_sequence
            and event.channel.value in channel_values
            and (
                event.channel is not RealtimeChannel.NOTIFICATIONS
                or event.occurred_at >= notification_cutoff
            )
        ]
        if len(selected) > max_events:
            return ReplayResult(events=(), resumed=False)
        return ReplayResult(events=tuple(selected), resumed=True)


def _matches_filters(event: SeismicEvent, filters: EventFilters) -> bool:
    if filters.from_at is not None and event.event_at < filters.from_at:
        return False
    if filters.to_at is not None and event.event_at > filters.to_at:
        return False
    if filters.min_magnitude is not None:
        return event.magnitude is not None and event.magnitude >= filters.min_magnitude
    return True


def paginate(items: Sequence[SeismicEvent], page: int, page_size: int) -> PaginatedEvents:
    total = len(items)
    offset = (page - 1) * page_size
    return PaginatedEvents(
        items=items[offset : offset + page_size],
        page=page,
        page_size=page_size,
        total=total,
    )

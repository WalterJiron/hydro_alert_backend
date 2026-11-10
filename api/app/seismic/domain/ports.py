"""Ports consumed by the seismic application layer.

Adapters in the infrastructure layer implement these protocols. The use case
therefore depends on abstractions (Dependency Inversion Principle).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Protocol, Sequence

from app.seismic.domain.entities import ScrapedEvent, SeismicEvent
from app.seismic.domain.scraping import ParseResult


@dataclass(frozen=True, slots=True)
class EventFilters:
    """Optional filters for historical queries."""

    from_at: datetime | None = None
    to_at: datetime | None = None
    min_magnitude: float | None = None


@dataclass(frozen=True, slots=True)
class PaginatedEvents:
    """Repository-level pagination result."""

    items: Sequence[SeismicEvent]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 0
        return ceil(self.total / self.page_size)

    @property
    def has_previous(self) -> bool:
        return self.page > 1 and self.total_pages > 0

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """Rows inserted or effectively modified by one synchronization pass."""

    created: Sequence[SeismicEvent] = ()
    updated: Sequence[SeismicEvent] = ()


class SeismicEventRepository(Protocol):
    """Persistence port for seismic events."""

    async def list_recent(self, limit: int) -> Sequence[SeismicEvent]: ...

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        filters: EventFilters,
    ) -> PaginatedEvents: ...

    async def get_by_id(self, event_id: object) -> SeismicEvent | None: ...

    async def count(self) -> int: ...

    async def upsert_many(self, events: Sequence[SeismicEvent]) -> UpsertResult: ...

    async def ping(self) -> None: ...


class SeismicEventPublisher(Protocol):
    """Realtime port. Implementations must not affect persistence."""

    async def publish_new(self, events: Sequence[SeismicEvent]) -> None: ...

    async def publish_updated(self, events: Sequence[SeismicEvent]) -> None: ...


class HtmlFetcher(Protocol):
    """Port for retrieving the INETER page."""

    async def fetch(self) -> str: ...


class HtmlParser(Protocol):
    """Pure HTML-to-domain parser port."""

    def parse(self, html: str) -> ParseResult: ...


class SyncLock(Protocol):
    """Distributed lock preventing concurrent synchronization runs."""

    async def __aenter__(self) -> None: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

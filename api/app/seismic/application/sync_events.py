"""Synchronize INETER events into PostgreSQL and publish changes.

This use case knows nothing about FastAPI, HTTP routes or WebSocket
internals. It depends only on ports, so scraping, persistence and realtime
communication remain independently replaceable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.core.errors import (
    InvalidSeismicEventError,
    ScrapingError,
    SyncLockUnavailableError,
)
from app.core.time import utc_now
from app.seismic.domain.entities import ScrapedEvent, SeismicEvent
from app.seismic.domain.ports import (
    HtmlFetcher,
    HtmlParser,
    SeismicEventPublisher,
    SeismicEventRepository,
    SyncLock,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """Observable result of one synchronization pass."""

    scraped: int
    skipped: int
    created: int
    updated: int
    unchanged: int
    duration_seconds: float
    finished_at: datetime


class SyncSeismicEvents:
    """Fetch, parse, validate, deduplicate, persist and publish events."""

    def __init__(
        self,
        *,
        fetcher: HtmlFetcher,
        parser: HtmlParser,
        repository: SeismicEventRepository,
        publisher: SeismicEventPublisher,
        distributed_lock: SyncLock,
    ) -> None:
        self._fetcher = fetcher
        self._parser = parser
        self._repository = repository
        self._publisher = publisher
        self._distributed_lock = distributed_lock
        self._running = asyncio.Lock()

    async def execute(self) -> SyncOutcome | None:
        """Run one pass.

        Returns ``None`` when another synchronization is already running in
        this process or in another API instance. All operational errors
        propagate so the worker can expose them through logs and health.
        """
        if self._running.locked():
            logger.info(
                "synchronization skipped because a local run is still active",
                extra={"event": "sync_skipped_local_lock"},
            )
            return None

        async with self._running:
            try:
                async with self._distributed_lock:
                    return await self._execute_locked()
            except SyncLockUnavailableError:
                logger.info(
                    "synchronization skipped because another instance holds the lock",
                    extra={"event": "sync_skipped_distributed_lock"},
                )
                return None

    async def _execute_locked(self) -> SyncOutcome:
        started = time.perf_counter()

        html = await self._fetcher.fetch()
        parse_result = self._parser.parse(html)
        _validate_parse_result(parse_result.candidates, len(parse_result.events))

        if parse_result.skipped:
            logger.warning(
                "some INETER candidate rows could not be parsed",
                extra={
                    "event": "ineter_parse_skipped",
                    "candidate_count": parse_result.candidates,
                    "parsed_count": len(parse_result.events),
                    "skipped_count": parse_result.skipped,
                    "examples": list(parse_result.warnings),
                },
            )

        unique = _to_unique_events(parse_result.events)
        upsert = await self._repository.upsert_many(list(unique.values()))

        await self._publish(upsert.created, upsert.updated)

        duration = time.perf_counter() - started
        unchanged = max(len(unique) - len(upsert.created) - len(upsert.updated), 0)
        outcome = SyncOutcome(
            scraped=len(parse_result.events),
            skipped=parse_result.skipped,
            created=len(upsert.created),
            updated=len(upsert.updated),
            unchanged=unchanged,
            duration_seconds=round(duration, 3),
            finished_at=utc_now(),
        )
        logger.info(
            "INETER synchronization completed",
            extra={
                "event": "sync_completed",
                "scraped_count": outcome.scraped,
                "skipped_count": outcome.skipped,
                "created_count": outcome.created,
                "updated_count": outcome.updated,
                "unchanged_count": outcome.unchanged,
                "duration_seconds": outcome.duration_seconds,
            },
        )
        return outcome

    async def _publish(
        self,
        created: Sequence[SeismicEvent],
        updated: Sequence[SeismicEvent],
    ) -> None:
        """Publish after commit without failing the persistence operation."""
        try:
            if created:
                await self._publisher.publish_new(created)
            if updated:
                await self._publisher.publish_updated(updated)
        except Exception:
            logger.exception(
                "seismic events were persisted but realtime publication failed",
                extra={"event": "realtime_publish_failed"},
            )


def _validate_parse_result(candidates: int, parsed: int) -> None:
    if candidates == 0:
        raise ScrapingError(
            "No seismic event anchors were found; the INETER page structure may have changed"
        )
    if parsed == 0:
        raise ScrapingError(
            "The INETER page contained event anchors but none produced a valid event"
        )


def _to_unique_events(scraped_events: tuple[ScrapedEvent, ...]) -> dict[str, SeismicEvent]:
    unique: dict[str, SeismicEvent] = {}
    for scraped in scraped_events:
        try:
            event = SeismicEvent.from_scraped(scraped)
        except InvalidSeismicEventError:
            logger.warning(
                "invalid INETER event discarded during normalization",
                extra={"event": "invalid_seismic_event"},
                exc_info=True,
            )
            continue
        unique[event.fingerprint] = event
    if not unique:
        raise ScrapingError("No valid seismic events remained after normalization")
    return unique

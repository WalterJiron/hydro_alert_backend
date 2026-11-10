"""PostgreSQL repository for seismic events."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import PersistenceError
from app.core.time import utc_now
from app.seismic.domain.entities import SeismicEvent
from app.seismic.domain.ports import (
    EventFilters,
    PaginatedEvents,
    UpsertResult,
)
from app.seismic.infrastructure.orm import SeismicEventORM

logger = logging.getLogger(__name__)


class SqlAlchemySeismicEventRepository:
    """Async repository using SQLAlchemy Core/ORM over asyncpg."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_recent(self, limit: int) -> Sequence[SeismicEvent]:
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(SeismicEventORM)
                    .order_by(
                        SeismicEventORM.event_at.desc(),
                        SeismicEventORM.registered_at.desc(),
                        SeismicEventORM.id.desc(),
                    )
                    .limit(limit)
                )
                return [_to_domain(row) for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise PersistenceError("Could not read recent seismic events") from exc

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        filters: EventFilters,
    ) -> PaginatedEvents:
        conditions = _filter_conditions(filters)
        try:
            async with self._session_factory() as session:
                total = (
                    await session.execute(
                        select(func.count())
                        .select_from(SeismicEventORM)
                        .where(*conditions)
                    )
                ).scalar_one()

                result = await session.execute(
                    select(SeismicEventORM)
                    .where(*conditions)
                    .order_by(
                        SeismicEventORM.event_at.desc(),
                        SeismicEventORM.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                items = [_to_domain(row) for row in result.scalars().all()]
                return PaginatedEvents(
                    items=items,
                    page=page,
                    page_size=page_size,
                    total=int(total),
                )
        except SQLAlchemyError as exc:
            raise PersistenceError("Could not query seismic events") from exc

    async def get_by_id(self, event_id: object) -> SeismicEvent | None:
        try:
            async with self._session_factory() as session:
                row = await session.get(SeismicEventORM, event_id)
                return _to_domain(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise PersistenceError("Could not read the seismic event") from exc

    async def count(self) -> int:
        try:
            async with self._session_factory() as session:
                total = (
                    await session.execute(
                        select(func.count()).select_from(SeismicEventORM)
                    )
                ).scalar_one()
                return int(total)
        except SQLAlchemyError as exc:
            raise PersistenceError("Could not count seismic events") from exc

    async def upsert_many(self, events: Sequence[SeismicEvent]) -> UpsertResult:
        """Insert only unseen events and update revised fields atomically.

        The unique fingerprint plus ``ON CONFLICT DO NOTHING`` prevents
        duplicates even if two workers race. A separate update pass allows
        INETER to revise magnitude/depth/location/status without producing a
        second record or a duplicate notification.
        """
        unique: dict[str, SeismicEvent] = {}
        for event in events:
            unique[event.fingerprint] = event
        if not unique:
            return UpsertResult()

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    existing_rows = (
                        await session.execute(
                            select(SeismicEventORM).where(
                                SeismicEventORM.fingerprint.in_(unique.keys())
                            )
                        )
                    ).scalars().all()
                    existing = {row.fingerprint: row for row in existing_rows}

                    to_insert = [
                        event
                        for fingerprint, event in unique.items()
                        if fingerprint not in existing
                    ]
                    to_update = [
                        (existing[fingerprint], event)
                        for fingerprint, event in unique.items()
                        if fingerprint in existing and _needs_update(existing[fingerprint], event)
                    ]

                    created: list[SeismicEvent] = []
                    if to_insert:
                        statement = (
                            pg_insert(SeismicEventORM)
                            .values([_to_values(event) for event in to_insert])
                            .on_conflict_do_nothing(
                                index_elements=[SeismicEventORM.fingerprint]
                            )
                            .returning(SeismicEventORM.fingerprint)
                        )
                        inserted = set(
                            (await session.execute(statement)).scalars().all()
                        )
                        created = [
                            event
                            for event in to_insert
                            if event.fingerprint in inserted
                        ]

                    updated: list[SeismicEvent] = []
                    if to_update:
                        now = utc_now()
                        for row, event in to_update:
                            row.depth_km = event.depth_km
                            row.magnitude = event.magnitude
                            row.location = event.location
                            row.pais = event.pais
                            row.status = event.status
                            row.source_timezone = event.source_timezone
                            row.updated_at = now
                        await session.flush()
                        updated = [_to_domain(row) for row, _ in to_update]

            if created or updated:
                logger.info(
                    "seismic events persisted",
                    extra={
                        "event": "seismic_events_persisted",
                        "created_count": len(created),
                        "updated_count": len(updated),
                    },
                )
            return UpsertResult(created=created, updated=updated)
        except SQLAlchemyError as exc:
            raise PersistenceError("Could not persist seismic events") from exc

    async def ping(self) -> None:
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise PersistenceError("Database health check failed") from exc


def _filter_conditions(filters: EventFilters) -> list[object]:
    conditions: list[object] = []
    if filters.from_at is not None:
        conditions.append(SeismicEventORM.event_at >= filters.from_at.astimezone(UTC))
    if filters.to_at is not None:
        conditions.append(SeismicEventORM.event_at <= filters.to_at.astimezone(UTC))
    if filters.min_magnitude is not None:
        conditions.append(SeismicEventORM.magnitude >= filters.min_magnitude)
    return conditions


def _to_values(event: SeismicEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "fingerprint": event.fingerprint,
        "event_at": event.event_at,
        "event_date": event.event_date,
        "event_time": event.event_time,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "depth_km": event.depth_km,
        "magnitude": event.magnitude,
        "location": event.location,
        "pais": event.pais,
        "status": event.status,
        "source": event.source,
        "source_timezone": event.source_timezone,
        "registered_at": event.registered_at,
        "updated_at": event.updated_at,
    }


def _to_domain(row: SeismicEventORM) -> SeismicEvent:
    return SeismicEvent(
        id=row.id,
        fingerprint=row.fingerprint,
        event_at=_as_utc(row.event_at),
        event_date=row.event_date,
        event_time=row.event_time,
        latitude=row.latitude,
        longitude=row.longitude,
        depth_km=row.depth_km,
        magnitude=row.magnitude,
        location=row.location,
        pais=row.pais,
        status=row.status,
        source=row.source,
        source_timezone=row.source_timezone,
        registered_at=_as_utc(row.registered_at),
        updated_at=_as_utc(row.updated_at),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _needs_update(row: SeismicEventORM, event: SeismicEvent) -> bool:
    return (
        not _same_float(row.depth_km, event.depth_km)
        or not _same_float(row.magnitude, event.magnitude)
        or (row.location or "") != (event.location or "")
        or (row.pais or "") != (event.pais or "")
        or (row.status or "") != (event.status or "")
        or (row.source_timezone or "") != (event.source_timezone or "")
    )


def _same_float(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)

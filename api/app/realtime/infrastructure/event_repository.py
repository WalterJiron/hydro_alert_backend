"""PostgreSQL event log used for at-least-once WebSocket replay."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import PersistenceError
from app.realtime.domain.events import (
    RealtimeChannel,
    RealtimeEvent,
    make_event_id,
    parse_event_id,
)
from app.realtime.domain.ports import ReplayResult
from app.realtime.infrastructure.event_orm import RealtimeEventORM


class SqlAlchemyRealtimeEventStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(
        self,
        *,
        channel: RealtimeChannel,
        event: str,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> RealtimeEvent:
        async with self._session_factory() as session:
            row = RealtimeEventORM(
                # The final id is derived from the sequence after flush. This
                # placeholder only needs to be unique and fit the column.
                id=f"tmp_{uuid4().hex[:20]}",
                channel=channel.value,
                event=event,
                occurred_at=occurred_at,
                data=data,
            )
            session.add(row)
            try:
                await session.flush()
                row.id = make_event_id(row.seq)
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                raise PersistenceError(
                    "Failed to record realtime event."
                ) from exc
        return _to_event(row)

    async def last_sequence(self) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(
                select(func.coalesce(func.max(RealtimeEventORM.seq), 0))
            )
        return int(value or 0)

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

        async with self._session_factory() as session:
            if last_sequence > 0:
                exists = await session.scalar(
                    select(RealtimeEventORM.seq).where(
                        RealtimeEventORM.id == last_event_id
                    )
                )
                if exists is None:
                    return ReplayResult(events=(), resumed=False)

            rows = (
                await session.scalars(
                    select(RealtimeEventORM)
                    .where(
                        RealtimeEventORM.seq > last_sequence,
                        RealtimeEventORM.channel.in_(
                            [channel.value for channel in channels]
                        ),
                        or_(
                            RealtimeEventORM.channel
                            != RealtimeChannel.NOTIFICATIONS.value,
                            RealtimeEventORM.occurred_at >= notification_cutoff,
                        ),
                    )
                    .order_by(RealtimeEventORM.seq.asc())
                    .limit(max_events + 1)
                )
            ).all()

        if len(rows) > max_events:
            # Too much history to replay safely. The client must reload REST.
            return ReplayResult(events=(), resumed=False)
        return ReplayResult(events=[_to_event(row) for row in rows], resumed=True)


def _to_event(row: RealtimeEventORM) -> RealtimeEvent:
    return RealtimeEvent(
        seq=row.seq,
        id=row.id,
        event=row.event,
        channel=RealtimeChannel(row.channel),
        occurred_at=row.occurred_at,
        data=row.data,
    )

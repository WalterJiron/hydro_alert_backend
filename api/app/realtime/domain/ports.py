"""Ports for the resumable realtime event stream."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence

from app.realtime.domain.events import RealtimeChannel, RealtimeEvent


@dataclass(frozen=True, slots=True)
class ReplayResult:
    events: Sequence[RealtimeEvent]
    resumed: bool


class RealtimeEventStore(Protocol):
    async def append(
        self,
        *,
        channel: RealtimeChannel,
        event: str,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> RealtimeEvent: ...

    async def last_sequence(self) -> int: ...

    async def replay(
        self,
        *,
        last_event_id: str | None,
        channels: Sequence[RealtimeChannel],
        max_events: int,
        notification_cutoff: datetime,
    ) -> ReplayResult: ...

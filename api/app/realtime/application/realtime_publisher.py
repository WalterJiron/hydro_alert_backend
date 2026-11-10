"""Persist realtime events before broadcasting, enabling replay."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.core.time import utc_now
from app.realtime.application.realtime_hub import RealtimeHub
from app.realtime.domain.events import RealtimeChannel
from app.realtime.domain.ports import RealtimeEventStore
from app.reports.domain.entities import Report
from app.reports.domain.serialization import iso_utc, report_payload

logger = logging.getLogger(__name__)


class PersistentRealtimePublisher:
    """Append to PostgreSQL, then broadcast to subscribed clients."""

    def __init__(
        self,
        *,
        store: RealtimeEventStore,
        hub: RealtimeHub,
    ) -> None:
        self._store = store
        self._hub = hub
        # Serialize append+broadcast so occurrence order and sequence order
        # agree even when two reports are created concurrently.
        self._publish_lock = asyncio.Lock()

    async def publish_report_created(self, report: Report) -> None:
        await self._publish(
            channel=RealtimeChannel.REPORTS,
            event="report.created",
            data=report_payload(report),
        )

    async def publish_report_deleted(self, report_id: str) -> None:
        await self._publish(
            channel=RealtimeChannel.REPORTS,
            event="report.deleted",
            data={"id": report_id},
        )

    async def publish_emergency_notification(
        self,
        data: dict[str, Any],
    ) -> None:
        await self._publish(
            channel=RealtimeChannel.NOTIFICATIONS,
            event="notification.created",
            data=data,
        )

    async def _publish(
        self,
        *,
        channel: RealtimeChannel,
        event: str,
        data: dict[str, Any],
        occurred_at: datetime | None = None,
    ) -> None:
        instant = occurred_at or utc_now()
        async with self._publish_lock:
            try:
                stored = await self._store.append(
                    channel=channel,
                    event=event,
                    occurred_at=instant,
                    data=data,
                )
                payload = stored.to_payload()
            except Exception:
                # Availability over durability: connected clients still get
                # the event, but a future resume will ask for a REST reload.
                logger.exception(
                    "realtime event could not be persisted; broadcasting only",
                    extra={"event": "realtime_event_persist_failed"},
                )
                payload = {
                    "event": event,
                    "id": f"evt_local_{uuid4().hex}",
                    "occurredAt": iso_utc(instant),
                    "data": data,
                }

            result = await self._hub.broadcast(channel, payload)
            if result.failed:
                logger.warning(
                    "realtime broadcast had failed deliveries",
                    extra={
                        "event": "realtime_broadcast_partial_failure",
                        "channel": channel.value,
                        "event_name": event,
                        "sent": result.sent,
                        "failed": result.failed,
                    },
                )

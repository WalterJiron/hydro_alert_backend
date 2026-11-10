"""Fan out seismic publication to the existing socket and notifications."""

from __future__ import annotations

import logging
from typing import Sequence

from app.realtime.application.emergency_notifications import (
    EmergencyNotificationService,
)
from app.seismic.domain.entities import SeismicEvent
from app.seismic.domain.ports import SeismicEventPublisher

logger = logging.getLogger(__name__)


class SeismicEventPublisherFanout:
    """Keep the seismic WebSocket behavior while adding emergency alerts."""

    def __init__(
        self,
        *,
        seismic: SeismicEventPublisher,
        notifications: EmergencyNotificationService,
    ) -> None:
        self._seismic = seismic
        self._notifications = notifications

    async def publish_new(self, events: Sequence[SeismicEvent]) -> None:
        await self._safe(self._seismic.publish_new(events), "seismic_new")
        await self._safe(
            self._notifications.on_new_seismic_events(events),
            "notifications_new",
        )

    async def publish_updated(self, events: Sequence[SeismicEvent]) -> None:
        await self._safe(self._seismic.publish_updated(events), "seismic_updated")

    async def _safe(self, operation, label: str) -> None:
        try:
            await operation
        except Exception:
            logger.exception(
                "realtime fanout branch failed",
                extra={"event": "realtime_fanout_failed", "branch": label},
            )

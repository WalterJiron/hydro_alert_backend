"""Turn newly detected strong earthquakes into emergency notifications."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from app.core.config import Settings
from app.core.time import utc_now
from app.realtime.application.realtime_publisher import PersistentRealtimePublisher
from app.realtime.domain.events import EmergencyNotificationData
from app.seismic.domain.entities import SeismicEvent

logger = logging.getLogger(__name__)


class EmergencyNotificationService:
    """Only events above the configured threshold and recent enough qualify."""

    def __init__(
        self,
        publisher: PersistentRealtimePublisher,
        settings: Settings,
    ) -> None:
        self._publisher = publisher
        self._settings = settings

    async def on_new_seismic_events(
        self,
        events: Sequence[SeismicEvent],
    ) -> None:
        if not self._settings.emergency_notifications_enabled:
            return

        now = utc_now()
        for event in events:
            magnitude = event.magnitude
            if magnitude is None:
                continue
            if magnitude < self._settings.emergency_min_magnitude:
                continue
            age_seconds = (now - event.event_at).total_seconds()
            if age_seconds > self._settings.emergency_max_event_age_seconds:
                continue

            await self._publisher.publish_emergency_notification(
                _notification_payload(event, now=now)
            )
            logger.info(
                "emergency notification published",
                extra={
                    "event": "emergency_notification_published",
                    "seismic_event_id": str(event.id),
                    "magnitude": magnitude,
                },
            )


def _notification_payload(
    event: SeismicEvent,
    *,
    now: datetime,
) -> dict[str, object]:
    magnitude = event.magnitude or 0.0
    place = event.pais or event.location or "la región"
    title = "Sismo fuerte detectado"
    body = (
        f"Magnitud {magnitude:.1f} cerca de {place}. "
        "Mantén la calma y sigue las indicaciones de las autoridades."
    )
    data = EmergencyNotificationData(
        eventId=f"ineter_{event.fingerprint}",
        title=title,
        body=body,
        magnitude=magnitude,
        place=place,
        latitude=event.latitude,
        longitude=event.longitude,
        url="https://www.ineter.gob.ni/",
        sentTime=now,
    )
    return data.model_dump(mode="json")

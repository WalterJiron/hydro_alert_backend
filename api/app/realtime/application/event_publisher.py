"""Adapter from seismic persistence events to WebSocket broadcasts."""

from __future__ import annotations

import logging
from typing import Sequence

from pydantic import ValidationError

from app.realtime.application.connection_manager import ConnectionManager
from app.realtime.domain.messages import WebSocketEnvelope, WsMessageType
from app.seismic.domain.entities import SeismicEvent
from app.seismic.presentation.schemas import SeismicEventView

logger = logging.getLogger(__name__)


class ConnectionManagerEventPublisher:
    """Broadcast new or revised events to every connected client.

    This adapter implements ``SeismicEventPublisher`` and keeps the sync use
    case independent from WebSocket details.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def publish_new(self, events: Sequence[SeismicEvent]) -> None:
        await self._publish(events, WsMessageType.NEW_EVENT)

    async def publish_updated(self, events: Sequence[SeismicEvent]) -> None:
        await self._publish(events, WsMessageType.UPDATED_EVENT)

    async def _publish(
        self,
        events: Sequence[SeismicEvent],
        message_type: WsMessageType,
    ) -> None:
        for event in events:
            try:
                view = SeismicEventView.model_validate(event)
            except ValidationError:
                logger.exception(
                    "seismic event could not be serialized for websocket delivery",
                    extra={"event": "ws_event_serialization_failed"},
                )
                continue

            envelope = WebSocketEnvelope.ok(message_type, view)
            result = await self._manager.broadcast(envelope.to_payload())
            if result.failed:
                logger.warning(
                    "websocket event broadcast had failed deliveries",
                    extra={
                        "event": "ws_broadcast_partial_failure",
                        "message_type": message_type.value,
                        "sent": result.sent,
                        "failed": result.failed,
                    },
                )

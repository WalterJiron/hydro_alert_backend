"""FastAPI WebSocket controller for seismic events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.bootstrap.dependencies import get_container_for_websocket
from app.core.time import utc_now
from app.realtime.application.connection_manager import (
    ConnectionLimitReachedError,
    ConnectionManager,
    ManagedConnection,
)
from app.realtime.domain.messages import (
    ClientMessage,
    ConnectionEstablishedData,
    PongData,
    WebSocketEnvelope,
    WsMessageType,
)
from app.realtime.presentation.schemas import InitialEventsData
from app.seismic.presentation.schemas import SeismicEventView

if TYPE_CHECKING:
    from app.bootstrap.container import ApplicationContainer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/seismic-events")
async def seismic_events_websocket(websocket: WebSocket) -> None:
    """Persistent stream of initial, new and revised seismic events."""
    container = get_container_for_websocket(websocket)
    manager = container.connection_manager

    try:
        connection = await manager.connect(websocket)
    except ConnectionLimitReachedError:
        return
    except Exception:
        logger.exception(
            "websocket handshake failed",
            extra={"event": "ws_handshake_failed"},
        )
        return

    try:
        await _send_established(
            manager,
            connection,
            initial_events_expected=container.settings.ws_initial_events > 0,
        )
        await _send_initial_events(container, manager, connection)
        await _receive_messages(websocket, manager, connection)
    except WebSocketDisconnect:
        logger.debug(
            "websocket disconnected by client",
            extra={"event": "ws_client_disconnect", "client_id": connection.id},
        )
    except Exception:
        logger.exception(
            "unexpected websocket error",
            extra={"event": "ws_unexpected_error", "client_id": connection.id},
        )
        await _safe_send(
            manager,
            connection.id,
            WebSocketEnvelope.failure(
                "internal_error",
                "The realtime connection encountered an unexpected error",
            ),
        )
        await _safe_close(websocket, code=1011, reason="Internal error")
    finally:
        await manager.disconnect(connection.id)


async def _send_established(
    manager: ConnectionManager,
    connection: ManagedConnection,
    *,
    initial_events_expected: bool,
) -> None:
    envelope = WebSocketEnvelope.ok(
        WsMessageType.CONNECTION_ESTABLISHED,
        ConnectionEstablishedData(
            client_id=connection.id,
            connected_at=connection.connected_at,
            initial_events_expected=initial_events_expected,
        ),
    )
    await manager.send_to(connection.id, envelope.to_payload())


async def _send_initial_events(
    container: ApplicationContainer,
    manager: ConnectionManager,
    connection: ManagedConnection,
) -> None:
    try:
        events = await container.repository.list_recent(
            container.settings.ws_initial_events
        )
        views = [SeismicEventView.model_validate(event) for event in events]
        envelope = WebSocketEnvelope.ok(
            WsMessageType.INITIAL_EVENTS,
            InitialEventsData(items=views, count=len(views)),
        )
        await manager.send_to(connection.id, envelope.to_payload())
    except Exception:
        logger.exception(
            "could not load initial websocket events",
            extra={"event": "ws_initial_events_failed", "client_id": connection.id},
        )
        await _safe_send(
            manager,
            connection.id,
            WebSocketEnvelope.failure(
                "initial_events_unavailable",
                "Initial seismic events are temporarily unavailable",
            ),
        )


async def _receive_messages(
    websocket: WebSocket,
    manager: ConnectionManager,
    connection: ManagedConnection,
) -> None:
    """Handle client pings and reject unsupported input without closing."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        raw_text = message.get("text")
        if raw_text is None:
            await _send_invalid_message(
                manager,
                connection.id,
                "Binary messages are not supported",
            )
            continue

        try:
            client_message = ClientMessage.model_validate_json(raw_text)
        except ValidationError:
            await _send_invalid_message(
                manager,
                connection.id,
                "Expected a JSON message with type='ping'",
            )
            continue

        if client_message.type == "ping":
            await manager.send_to(
                connection.id,
                WebSocketEnvelope.ok(
                    WsMessageType.PONG,
                    PongData(server_time=utc_now()),
                ).to_payload(),
            )


async def _send_invalid_message(
    manager: ConnectionManager,
    client_id: str,
    reason: str,
) -> None:
    await manager.send_to(
        client_id,
        WebSocketEnvelope.failure("invalid_message", reason).to_payload(),
    )


async def _safe_send(
    manager: ConnectionManager,
    client_id: str,
    envelope: WebSocketEnvelope,
) -> None:
    try:
        await manager.send_to(client_id, envelope.to_payload())
    except Exception:
        logger.debug(
            "failed to send websocket error envelope",
            extra={"event": "ws_error_send_failed", "client_id": client_id},
        )


async def _safe_close(websocket: WebSocket, *, code: int, reason: str) -> None:
    try:
        if websocket.application_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=code, reason=reason)
    except Exception:
        logger.debug(
            "failed to close websocket",
            extra={"event": "ws_close_failed"},
        )

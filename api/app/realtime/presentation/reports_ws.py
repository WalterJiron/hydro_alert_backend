"""Contractual HydroAlert WebSocket at ``/api/v1/ws``.

This endpoint is intentionally separate from ``/ws/seismic-events`` so the
existing seismic protocol remains untouched. It supports channel selection,
heartbeats and resumption from a stored event id.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.bootstrap.dependencies import get_container_for_websocket
from app.core.time import utc_now
from app.realtime.application.connection_manager import ConnectionLimitReachedError
from app.realtime.application.realtime_hub import RealtimeHub, RealtimeClient
from app.realtime.domain.events import (
    RealtimeChannel,
    make_event_id,
    parse_event_id,
)
from app.reports.domain.serialization import iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_VALID_CHANNELS = {channel.value: channel for channel in RealtimeChannel}


@router.websocket("/api/v1/ws")
@router.websocket("/ws")
async def reports_websocket(websocket: WebSocket) -> None:
    container = get_container_for_websocket(websocket)
    hub = container.realtime_hub

    channels = _parse_channels(websocket.query_params.get("channels"))
    if channels is None:
        await websocket.accept()
        await _send_error(
            websocket,
            code="invalid_channels",
            message="Requested channels are invalid.",
            retryable=False,
        )
        await _safe_close(websocket, code=1000, reason="Invalid channels")
        return

    raw_last_event_id = websocket.query_params.get("lastEventId")
    last_event_id = (
        raw_last_event_id.strip()
        if raw_last_event_id is not None and raw_last_event_id.strip()
        else None
    )
    if last_event_id is not None and parse_event_id(last_event_id) is None:
        await websocket.accept()
        await _send_error(
            websocket,
            code="invalid_last_event_id",
            message="Resumption event identifier is invalid.",
            retryable=False,
        )
        await _safe_close(websocket, code=1000, reason="Invalid lastEventId")
        return

    try:
        client = await hub.connect(
            websocket,
            frozenset(channels),
            # Buffer live events until the ready frame and any replay batch
            # have been delivered, so ordering is always ready -> data.
            replaying=True,
        )
    except ConnectionLimitReachedError:
        return
    except Exception:
        logger.exception(
            "reports websocket handshake failed",
            extra={"event": "ws_reports_handshake_failed"},
        )
        return

    try:
        await _serve_connection(
            container=container,
            hub=hub,
            client=client,
            channels=channels,
            last_event_id=last_event_id,
        )
    except WebSocketDisconnect:
        logger.debug(
            "reports websocket disconnected by client",
            extra={"event": "ws_reports_client_disconnect", "client_id": client.id},
        )
    except Exception:
        logger.exception(
            "unexpected reports websocket error",
            extra={"event": "ws_reports_unexpected_error", "client_id": client.id},
        )
        try:
            await hub.send_to(
                client.id,
                _error_payload(
                    "internal_error",
                    "Realtime connection encountered an unexpected error.",
                    retryable=True,
                ),
            )
        except Exception:
            pass
        await _safe_close(websocket, code=1011, reason="Internal error")
    finally:
        await hub.disconnect(client.id)


async def _serve_connection(
    *,
    container,
    hub: RealtimeHub,
    client: RealtimeClient,
    channels: tuple[RealtimeChannel, ...],
    last_event_id: str | None,
) -> None:
    now = utc_now()
    try:
        await container.realtime_events.last_sequence()
    except Exception:
        logger.exception(
            "could not obtain the realtime cursor",
            extra={"event": "ws_reports_cursor_failed", "client_id": client.id},
        )
        await hub.send_to(
            client.id,
            _error_payload(
                "internal_error",
                "Realtime service is currently unavailable.",
                retryable=True,
            ),
        )
        await _safe_close(client.websocket, code=1011, reason="Internal error")
        return

    replayed = ()
    resumed = True
    if last_event_id is not None:
        cutoff = now - timedelta(
            seconds=container.settings.ws_notification_replay_seconds
        )
        try:
            replay = await container.realtime_events.replay(
                last_event_id=last_event_id,
                channels=channels,
                max_events=container.settings.ws_max_replay_events,
                notification_cutoff=cutoff,
            )
            replayed = replay.events
            resumed = replay.resumed
        except Exception:
            logger.exception(
                "realtime replay failed; client must reload REST",
                extra={"event": "ws_reports_replay_failed", "client_id": client.id},
            )
            resumed = False

    ready = {
        "event": "connection.ready",
        # When resuming, echo the client's cursor so ready never collides with
        # an event that is about to be replayed. Without a cursor, use the
        # reserved zero id, which no stored event can occupy.
        "id": (
            last_event_id
            if last_event_id is not None and resumed
            else make_event_id(0)
        ),
        "occurredAt": iso_utc(now),
        "data": {
            "connectionId": client.id,
            "channels": [channel.value for channel in channels],
            "resumed": resumed,
            "serverTime": iso_utc(now),
        },
    }
    await hub.send_to(client.id, ready)

    sent_ids: set[str] = set()
    for event in replayed:
        payload = event.to_payload()
        if await hub.send_to(client.id, payload):
            sent_ids.add(event.id)

    await hub.end_replay(client.id, already_sent_ids=sent_ids)

    await _receive_messages_contract(websocket=client.websocket, hub=hub, client=client)


async def _receive_messages_contract(
    *,
    websocket: WebSocket,
    hub: RealtimeHub,
    client: RealtimeClient,
) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        raw_text = message.get("text")
        if raw_text is None:
            await hub.send_to(
                client.id,
                _error_payload(
                    "invalid_message",
                    "Los mensajes binarios no están soportados.",
                    retryable=True,
                ),
            )
            continue

        try:
            payload = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            await hub.send_to(
                client.id,
                _error_payload(
                    "invalid_message",
                    'Expected JSON message with {"action": "ping"}.',
                    retryable=True,
                ),
            )
            continue

        if isinstance(payload, dict) and (
            payload.get("action") == "ping" or payload.get("type") == "ping"
        ):
            server_time = utc_now()
            await hub.send_to(
                client.id,
                {
                    "event": "pong",
                    "occurredAt": iso_utc(server_time),
                    "data": {"serverTime": iso_utc(server_time)},
                },
            )
            continue

        await hub.send_to(
            client.id,
            _error_payload(
                "invalid_message",
                'Expected JSON message with {"action": "ping"}.',
                retryable=True,
            ),
        )


def _parse_channels(raw: str | None) -> tuple[RealtimeChannel, ...] | None:
    if raw is None:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(not part for part in parts):
        return None

    parsed: list[RealtimeChannel] = []
    for part in parts:
        channel = _VALID_CHANNELS.get(part)
        if channel is None:
            return None
        if channel not in parsed:
            parsed.append(channel)
    return tuple(parsed) if parsed else None


def _error_payload(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
    return {
        "event": "error",
        "occurredAt": iso_utc(utc_now()),
        "data": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }


async def _send_error(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    await websocket.send_json(
        _error_payload(code, message, retryable=retryable)
    )


async def _safe_close(websocket: WebSocket, *, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        logger.debug(
            "reports websocket close failed",
            extra={"event": "ws_reports_close_failed"},
        )

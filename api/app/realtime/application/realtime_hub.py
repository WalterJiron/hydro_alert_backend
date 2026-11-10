"""Channel-aware WebSocket hub for HydroAlert reports and notifications.

The seismic endpoint keeps its own manager and protocol. This hub only serves
``/api/v1/ws`` so the existing realtime contract cannot be affected.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from starlette.websockets import WebSocket

from app.core.time import utc_now
from app.realtime.application.connection_manager import ConnectionLimitReachedError
from app.realtime.domain.events import RealtimeChannel

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 64 * 1024


@dataclass(slots=True)
class RealtimeClient:
    id: str
    websocket: WebSocket
    channels: frozenset[RealtimeChannel]
    connected_at: datetime
    remote_address: str | None
    replaying: bool = False
    pending: list[dict[str, Any]] = field(default_factory=list)
    pending_overflow: bool = False
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True, slots=True)
class RealtimeBroadcastResult:
    sent: int
    failed: int
    buffered: int


class RealtimeHub:
    """Own connection lifecycle and ordered per-client delivery."""

    def __init__(
        self,
        *,
        max_connections: int,
        max_replay_buffer: int = 1_000,
    ) -> None:
        self._max_connections = max_connections
        self._max_replay_buffer = max_replay_buffer
        self._connections: dict[str, RealtimeClient] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        channels: frozenset[RealtimeChannel],
        *,
        replaying: bool = False,
    ) -> RealtimeClient:
        await websocket.accept()
        client = RealtimeClient(
            id=f"conn_{uuid4().hex}",
            websocket=websocket,
            channels=channels,
            connected_at=utc_now(),
            remote_address=_remote_address(websocket),
            replaying=replaying,
        )

        async with self._lock:
            full = len(self._connections) >= self._max_connections
            if not full:
                self._connections[client.id] = client

        if full:
            await websocket.close(
                code=1013,
                reason="Server is at WebSocket capacity",
            )
            logger.warning(
                "reports websocket rejected: capacity reached",
                extra={
                    "event": "ws_reports_connection_rejected",
                    "max_connections": self._max_connections,
                },
            )
            raise ConnectionLimitReachedError

        logger.info(
            "reports websocket connected",
            extra={
                "event": "ws_reports_connected",
                "client_id": client.id,
                "remote_address": client.remote_address,
                "channels": sorted(channel.value for channel in channels),
                "active_connections": len(self._connections),
            },
        )
        return client

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            client = self._connections.pop(client_id, None)
            active_connections = len(self._connections)
        if client is not None:
            logger.info(
                "reports websocket disconnected",
                extra={
                    "event": "ws_reports_disconnected",
                    "client_id": client_id,
                    "remote_address": client.remote_address,
                    "active_connections": active_connections,
                },
            )

    async def send_to(self, client_id: str, payload: dict[str, Any]) -> bool:
        async with self._lock:
            client = self._connections.get(client_id)
        if client is None:
            return False
        return await self._send(client, payload)

    async def broadcast(
        self,
        channel: RealtimeChannel,
        payload: dict[str, Any],
    ) -> RealtimeBroadcastResult:
        async with self._lock:
            targets = [
                client
                for client in self._connections.values()
                if channel in client.channels
            ]
            direct: list[RealtimeClient] = []
            buffered = 0
            for client in targets:
                if client.replaying:
                    if len(client.pending) >= self._max_replay_buffer:
                        client.pending_overflow = True
                    else:
                        client.pending.append(payload)
                        buffered += 1
                else:
                    direct.append(client)

        if direct:
            results = await asyncio.gather(
                *(self._send(client, payload) for client in direct)
            )
            sent = sum(1 for delivered in results if delivered)
        else:
            sent = 0
        return RealtimeBroadcastResult(
            sent=sent,
            failed=len(direct) - sent,
            buffered=buffered,
        )

    async def end_replay(
        self,
        client_id: str,
        *,
        already_sent_ids: set[str],
    ) -> None:
        """Flush events buffered while the historical replay was in progress."""
        while True:
            async with self._lock:
                client = self._connections.get(client_id)
                if client is None:
                    return
                if client.pending_overflow:
                    batch: list[dict[str, Any]] = []
                    overflow = True
                    client.replaying = False
                else:
                    batch = client.pending
                    client.pending = []
                    overflow = False
                    if not batch:
                        client.replaying = False
                        return
            if overflow:
                logger.warning(
                    "reports websocket replay buffer overflow; closing client",
                    extra={
                        "event": "ws_reports_replay_overflow",
                        "client_id": client_id,
                    },
                )
                await _close(client, code=1011, reason="Replay buffer overflow")
                await self.disconnect(client_id)
                return

            for payload in sorted(batch, key=lambda item: str(item.get("id", ""))):
                if str(payload.get("id", "")) in already_sent_ids:
                    continue
                if not await self._send(client, payload):
                    return

    async def close_all(
        self,
        *,
        code: int = 1001,
        reason: str = "Server shutdown",
    ) -> None:
        async with self._lock:
            clients = tuple(self._connections.values())
            self._connections.clear()
        if not clients:
            return
        await asyncio.gather(
            *(_close(client, code=code, reason=reason) for client in clients),
            return_exceptions=True,
        )
        logger.info(
            "all reports websocket connections closed",
            extra={"event": "ws_reports_close_all", "closed": len(clients)},
        )

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self._connections)

    async def _send(
        self,
        client: RealtimeClient,
        payload: dict[str, Any],
    ) -> bool:
        try:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            logger.exception(
                "reports websocket payload could not be serialized",
                extra={"event": "ws_reports_serialization_failed"},
            )
            return False

        if len(encoded) >= MAX_MESSAGE_BYTES:
            logger.error(
                "reports websocket payload exceeds the 64 KB limit",
                extra={
                    "event": "ws_reports_message_too_large",
                    "client_id": client.id,
                    "size_bytes": len(encoded),
                },
            )
            return False

        try:
            async with client.send_lock:
                await client.websocket.send_text(encoded.decode("utf-8"))
            return True
        except Exception as exc:
            logger.warning(
                "reports websocket delivery failed; removing client",
                extra={
                    "event": "ws_reports_delivery_failed",
                    "client_id": client.id,
                    "remote_address": client.remote_address,
                    "error_type": type(exc).__name__,
                },
            )
            await self.disconnect(client.id)
            return False


async def _close(client: RealtimeClient, *, code: int, reason: str) -> None:
    try:
        async with client.send_lock:
            await client.websocket.close(code=code, reason=reason)
    except Exception:
        logger.debug(
            "reports websocket close failed (already disconnected)",
            extra={"event": "ws_reports_close_failed", "client_id": client.id},
        )


def _remote_address(websocket: WebSocket) -> str | None:
    client = getattr(websocket, "client", None)
    if client is None:
        return None
    host = getattr(client, "host", None)
    port = getattr(client, "port", None)
    if host is None:
        return None
    return f"{host}:{port}" if port is not None else str(host)

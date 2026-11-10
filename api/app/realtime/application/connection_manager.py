"""Centralized WebSocket connection management.

The manager owns only connection lifecycle and delivery. It does not scrape,
query or persist seismic events.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from starlette.websockets import WebSocket

from app.core.time import utc_now

logger = logging.getLogger(__name__)


class ConnectionLimitReachedError(Exception):
    """Raised when the configured WebSocket capacity is exhausted."""


@dataclass(slots=True)
class ManagedConnection:
    id: str
    websocket: WebSocket
    connected_at: datetime
    remote_address: str | None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    sent: int
    failed: int


class ConnectionManager:
    """Track, send to and clean up connected WebSocket clients."""

    def __init__(self, *, max_connections: int) -> None:
        self._max_connections = max_connections
        self._connections: dict[str, ManagedConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> ManagedConnection:
        """Accept and register a client, enforcing the configured capacity."""
        await websocket.accept()
        connection = ManagedConnection(
            id=uuid4().hex,
            websocket=websocket,
            connected_at=utc_now(),
            remote_address=_remote_address(websocket),
        )

        async with self._lock:
            if len(self._connections) >= self._max_connections:
                full = True
            else:
                self._connections[connection.id] = connection
                full = False

        if full:
            await websocket.close(
                code=1013,
                reason="Server is at WebSocket capacity",
            )
            logger.warning(
                "websocket connection rejected: capacity reached",
                extra={
                    "event": "ws_connection_rejected",
                    "max_connections": self._max_connections,
                },
            )
            raise ConnectionLimitReachedError

        logger.info(
            "websocket client connected",
            extra={
                "event": "ws_connected",
                "client_id": connection.id,
                "remote_address": connection.remote_address,
                "active_connections": len(self._connections),
            },
        )
        return connection

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            connection = self._connections.pop(client_id, None)
            active_connections = len(self._connections)
        if connection is not None:
            logger.info(
                "websocket client disconnected",
                extra={
                    "event": "ws_disconnected",
                    "client_id": client_id,
                    "remote_address": connection.remote_address,
                    "active_connections": active_connections,
                },
            )

    async def send_to(self, client_id: str, payload: dict[str, Any]) -> bool:
        async with self._lock:
            connection = self._connections.get(client_id)
        if connection is None:
            return False
        return await self._send(connection, payload)

    async def broadcast(self, payload: dict[str, Any]) -> BroadcastResult:
        async with self._lock:
            connections = tuple(self._connections.values())

        if not connections:
            return BroadcastResult(sent=0, failed=0)

        results = await asyncio.gather(
            *(self._send(connection, payload) for connection in connections),
            return_exceptions=False,
        )
        sent = sum(1 for delivered in results if delivered)
        return BroadcastResult(sent=sent, failed=len(results) - sent)

    async def close_all(self, *, code: int = 1001, reason: str = "Server shutdown") -> None:
        async with self._lock:
            connections = tuple(self._connections.values())
            self._connections.clear()

        if not connections:
            return

        await asyncio.gather(
            *(
                _close_connection(connection, code=code, reason=reason)
                for connection in connections
            ),
            return_exceptions=True,
        )
        logger.info(
            "all websocket connections closed",
            extra={"event": "ws_close_all", "closed": len(connections)},
        )

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self._connections)

    async def _send(
        self,
        connection: ManagedConnection,
        payload: dict[str, Any],
    ) -> bool:
        try:
            async with connection.send_lock:
                await connection.websocket.send_json(payload)
            return True
        except Exception as exc:
            logger.warning(
                "websocket delivery failed; removing client",
                extra={
                    "event": "ws_delivery_failed",
                    "client_id": connection.id,
                    "remote_address": connection.remote_address,
                    "error_type": type(exc).__name__,
                },
            )
            await self.disconnect(connection.id)
            return False


async def _close_connection(
    connection: ManagedConnection,
    *,
    code: int,
    reason: str,
) -> None:
    try:
        async with connection.send_lock:
            await connection.websocket.close(code=code, reason=reason)
    except Exception:
        logger.debug(
            "websocket close failed (already disconnected)",
            extra={"event": "ws_close_failed", "client_id": connection.id},
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

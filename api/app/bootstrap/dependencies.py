"""FastAPI dependency accessors for the composition container."""

from __future__ import annotations

from fastapi import Request, WebSocket

from app.bootstrap.container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("Application container is not initialized")
    return container


def get_container_for_websocket(websocket: WebSocket) -> ApplicationContainer:
    container = getattr(websocket.app.state, "container", None)
    if container is None:
        raise RuntimeError("Application container is not initialized")
    return container

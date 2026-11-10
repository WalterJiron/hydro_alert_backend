"""Uniform JSON protocol shared by WebSocket clients and the server."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.time import utc_now

PROTOCOL_VERSION = "1.0"


class WsMessageType(StrEnum):
    CONNECTION_ESTABLISHED = "connection.established"
    INITIAL_EVENTS = "seismic.events.initial"
    NEW_EVENT = "seismic.event.new"
    UPDATED_EVENT = "seismic.event.updated"
    PONG = "connection.pong"
    ERROR = "error"


class WsStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class ConnectionEstablishedData(BaseModel):
    client_id: str
    protocol_version: str = PROTOCOL_VERSION
    connected_at: datetime
    initial_events_expected: bool


class PongData(BaseModel):
    server_time: datetime


class ErrorData(BaseModel):
    code: str
    message: str


class WebSocketEnvelope(BaseModel):
    """Envelope used for every server-to-client message."""

    type: WsMessageType
    status: WsStatus = WsStatus.OK
    data: dict[str, Any] | None = None
    error: ErrorData | None = None
    timestamp: datetime = Field(default_factory=utc_now)

    @classmethod
    def ok(
        cls,
        message_type: WsMessageType,
        data: BaseModel | dict[str, Any] | None = None,
    ) -> "WebSocketEnvelope":
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
        return cls(type=message_type, status=WsStatus.OK, data=payload)

    @classmethod
    def failure(cls, code: str, message: str) -> "WebSocketEnvelope":
        return cls(
            type=WsMessageType.ERROR,
            status=WsStatus.ERROR,
            error=ErrorData(code=code, message=message),
        )

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ClientMessage(BaseModel):
    """Only application-level ping is accepted from clients."""

    type: Literal["ping"]

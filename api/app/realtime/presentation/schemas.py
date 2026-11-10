"""Realtime payloads that embed seismic event views."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.seismic.presentation.schemas import SeismicEventView


class InitialEventsData(BaseModel):
    items: list[SeismicEventView]
    count: int


class ConnectionReadyData(BaseModel):
    connectionId: str
    channels: list[str]
    resumed: bool
    serverTime: datetime


class ConnectionReadyEnvelope(BaseModel):
    event: Literal["connection.ready"] = "connection.ready"
    id: str
    occurredAt: datetime
    data: ConnectionReadyData


class ReportsPongData(BaseModel):
    serverTime: datetime


class ReportsPongEnvelope(BaseModel):
    event: Literal["pong"] = "pong"
    occurredAt: datetime
    data: ReportsPongData


class ReportsErrorData(BaseModel):
    code: str
    message: str
    retryable: bool


class ReportsErrorEnvelope(BaseModel):
    event: Literal["error"] = "error"
    occurredAt: datetime
    data: ReportsErrorData = Field(description="Connection-level error details")

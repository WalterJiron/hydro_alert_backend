"""Realtime event envelope and channel identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.reports.domain.serialization import iso_utc

_EVENT_ID_RE = re.compile(r"^evt_(?P<sequence>\d{1,12})$")
EVENT_ID_WIDTH = 12


class RealtimeChannel(StrEnum):
    REPORTS = "reports"
    NOTIFICATIONS = "notifications"


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    seq: int
    id: str
    event: str
    channel: RealtimeChannel
    occurred_at: datetime
    data: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "id": self.id,
            "occurredAt": iso_utc(self.occurred_at),
            "data": self.data,
        }


def make_event_id(sequence: int) -> str:
    return f"evt_{sequence:0{EVENT_ID_WIDTH}d}"


def parse_event_id(value: str) -> int | None:
    match = _EVENT_ID_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    return int(match.group("sequence"))


class RealtimeEventEnvelope(BaseModel):
    """Machine-readable schema for every data event."""

    event: str
    id: str
    occurred_at: datetime = Field(alias="occurredAt")
    data: dict[str, Any]

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "event": "report.created",
                "id": "evt_000000000042",
                "occurredAt": "2026-11-08T15:30:01Z",
                "data": {
                    "id": "rep_01JABCDEF",
                    "category": "flood",
                    "description": "Calle inundada frente a la escuela.",
                    "latitude": 12.136389,
                    "longitude": -86.251389,
                    "photoUrl": None,
                    "createdAt": "2026-11-08T15:30:00Z",
                },
            }
        },
    }


class EmergencyNotificationData(BaseModel):
    """Payload of ``notification.created`` for a strong earthquake."""

    eventId: str
    type: Literal["emergency"] = "emergency"
    priority: Literal["critical"] = "critical"
    title: str
    body: str
    magnitude: float | None = None
    place: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    url: str | None = None
    sentTime: datetime

    model_config = {
        "json_schema_extra": {
            "example": {
                "eventId": "ineter_0123456789abcdef",
                "type": "emergency",
                "priority": "critical",
                "title": "Sismo fuerte detectado",
                "body": (
                    "Magnitud 6.1 cerca de Managua, Nicaragua. Mantén la "
                    "calma y sigue las indicaciones de las autoridades."
                ),
                "magnitude": 6.1,
                "place": "Managua, Nicaragua",
                "latitude": 12.136389,
                "longitude": -86.251389,
                "url": "https://www.ineter.gob.ni/",
                "sentTime": "2026-11-08T15:31:00Z",
            }
        }
    }

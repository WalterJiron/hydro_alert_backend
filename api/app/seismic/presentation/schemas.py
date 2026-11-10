"""Pydantic view models for seismic events."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SeismicEventView(BaseModel):
    """Serialized representation of a persisted event."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "14223d11-5959-4754-939f-9471e9eff061",
                "event_at": "2026-11-09T02:26:05Z",
                "event_date": "2026-11-08",
                "event_time": "20:26:05",
                "latitude": 12.934,
                "longitude": -89.573,
                "depth_km": 23.0,
                "magnitude": 3.1,
                "location": "67 Km al suroeste de La Libertad, El Salvador",
                "pais": "El Salvador",
                "status": "C",
                "source": "INETER",
                "source_timezone": "America/Managua",
                "registered_at": "2026-11-09T03:22:40.586458Z",
                "updated_at": "2026-11-09T03:22:40.586458Z",
            }
        },
    )

    id: UUID
    event_at: datetime = Field(description="Event instant normalized to UTC")
    event_date: date = Field(description="Published date in Nicaraguan local time")
    event_time: time = Field(description="Published time in Nicaraguan local time")
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    location: str | None = Field(
        description="Location text as published by INETER, including the country"
    )
    pais: str | None = Field(
        description="Canonical country extracted from the end of location",
        examples=["El Salvador"],
    )
    status: str | None
    source: str
    source_timezone: str
    registered_at: datetime
    updated_at: datetime


class PaginationMetadata(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PaginatedSeismicEventsResponse(BaseModel):
    items: list[SeismicEventView]
    pagination: PaginationMetadata

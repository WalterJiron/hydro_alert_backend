"""Pydantic views for the community report API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.reports.domain.entities import ReportCategory
from app.reports.domain.serialization import iso_utc


class ReportView(BaseModel):
    """Public report shape consumed by the mobile app."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "id": "rep_01JABCDEF",
                "category": "flood",
                "description": "Calle inundada frente a la escuela.",
                "latitude": 12.136389,
                "longitude": -86.251389,
                "photoUrl": (
                    "https://cdn.ejemplo.com/reports/rep_01JABCDEF.jpg"
                ),
                "createdAt": "2026-11-08T15:30:00Z",
            }
        },
    )

    id: str
    category: ReportCategory
    description: str
    latitude: float
    longitude: float
    photo_url: str | None = Field(
        alias="photoUrl",
        serialization_alias="photoUrl",
        description="Absolute HTTPS URL or a path relative to API_BASE_URL",
    )
    created_at: datetime = Field(
        alias="createdAt",
        serialization_alias="createdAt",
        description="Creation instant in ISO 8601 UTC",
    )

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        """Always emit the contract's trailing ``Z`` form."""
        return iso_utc(value)


class ActiveReportsResponse(BaseModel):
    data: list[ReportView]

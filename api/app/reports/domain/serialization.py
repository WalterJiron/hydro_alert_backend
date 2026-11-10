"""Serialization helpers shared by REST and WebSocket report payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from app.reports.domain.entities import Report


def iso_utc(value: datetime) -> str:
    """Format an aware instant as ISO 8601 with a trailing ``Z``."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def report_payload(report: Report) -> dict[str, object]:
    """The exact public report shape required by the mobile app."""
    return {
        "id": report.id,
        "category": report.category.value,
        "description": report.description,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "photoUrl": report.photo_url,
        "createdAt": iso_utc(report.created_at),
    }

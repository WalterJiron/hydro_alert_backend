"""Validation of community report fields and attached photos."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.errors import (
    InvalidReportError,
    ReportPhotoTooLargeError,
    UnsupportedPhotoError,
)
from app.reports.domain.entities import ReportCategory

MIN_DESCRIPTION_LENGTH = 10
MAX_DESCRIPTION_LENGTH = 500
MAX_PHOTO_BYTES = 5_242_880

_ALLOWED_PHOTO_TYPES = ("image/jpeg", "image/png", "image/webp")


@dataclass(frozen=True, slots=True)
class ValidatedReportInput:
    category: ReportCategory
    description: str
    latitude: float
    longitude: float


def validate_report_input(
    *,
    category: str,
    description: str,
    latitude: float,
    longitude: float,
) -> ValidatedReportInput:
    clean_category = _validate_category(category)
    clean_description = _validate_description(description)
    clean_latitude = _validate_coordinate(latitude, name="latitude", limit=90)
    clean_longitude = _validate_coordinate(longitude, name="longitude", limit=180)
    return ValidatedReportInput(
        category=clean_category,
        description=clean_description,
        latitude=clean_latitude,
        longitude=clean_longitude,
    )


def _validate_category(raw: str) -> ReportCategory:
    candidate = raw.strip().lower() if isinstance(raw, str) else ""
    try:
        return ReportCategory(candidate)
    except ValueError as exc:
        allowed = ", ".join(category.value for category in ReportCategory)
        raise InvalidReportError(
            f"Category must be one of: {allowed}."
        ) from exc


def _validate_description(raw: str) -> str:
    description = raw.strip() if isinstance(raw, str) else ""
    if len(description) < MIN_DESCRIPTION_LENGTH:
        raise InvalidReportError(
            f"Description must be at least {MIN_DESCRIPTION_LENGTH} characters."
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise InvalidReportError(
            f"Description cannot exceed {MAX_DESCRIPTION_LENGTH} characters."
        )
    return description


def _validate_coordinate(value: float, *, name: str, limit: int) -> float:
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidReportError(f"{name.capitalize()} must be a valid number.") from exc
    if not math.isfinite(coordinate) or not -limit <= coordinate <= limit:
        raise InvalidReportError(
            f"{name.capitalize()} must be between -{limit} and {limit}."
        )
    return coordinate


def detect_photo_content_type(data: bytes, *, max_bytes: int = MAX_PHOTO_BYTES) -> str:
    """Validate size and magic bytes; the filename is never trusted."""
    if len(data) > max_bytes:
        raise ReportPhotoTooLargeError(max_bytes)
    if not data:
        raise UnsupportedPhotoError()

    content_type = _sniff(data)
    if content_type is None:
        raise UnsupportedPhotoError()
    return content_type


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_allowed_content_type(content_type: str) -> bool:
    return content_type in _ALLOWED_PHOTO_TYPES

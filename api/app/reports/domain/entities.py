"""Community report entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReportCategory(StrEnum):
    FLOOD = "flood"
    DAMAGED_DRAIN = "damaged_drain"
    FALLEN_TREE = "fallen_tree"
    LANDSLIDE = "landslide"
    FIRE = "fire"
    EARTHQUAKE_DAMAGE = "earthquake_damage"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Report:
    id: str
    user_id: str
    category: ReportCategory
    description: str
    latitude: float
    longitude: float
    created_at: datetime
    deleted_at: datetime | None = None
    photo_url: str | None = None
    updated_at: datetime | None = None

    @property
    def has_photo(self) -> bool:
        """Functional derivation preserving 3NF (no redundant stored column)."""
        return self.photo_url is not None


@dataclass(frozen=True, slots=True)
class ReportPhoto:
    """In-memory representation of raw photo bytes during upload."""

    content_type: str
    data: bytes

"""Domain entities for seismic events.

The source publishes local Nicaraguan time. The domain keeps both the
published local date/time and a normalized UTC instant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timezone
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.core.errors import InvalidSeismicEventError
from app.core.time import utc_now
from app.seismic.domain.countries import extract_country

SOURCE_TIMEZONE = "America/Managua"
NICARAGUA_TZ = ZoneInfo(SOURCE_TIMEZONE)

MAX_LOCATION_LENGTH = 500
MAX_COUNTRY_LENGTH = 64
MAX_STATUS_LENGTH = 16


@dataclass(frozen=True, slots=True)
class ScrapedEvent:
    """A validated event exactly as extracted from the INETER page.

    ``depth_km`` and ``magnitude`` may be ``None`` when the source publishes
    a placeholder instead of a number. Coordinates, date and time are
    mandatory because they identify the event.
    """

    event_date: date
    event_time: time
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    location: str | None = None
    pais: str | None = None
    status: str | None = None
    source_timezone: str = SOURCE_TIMEZONE

    def __post_init__(self) -> None:
        self._validate()
        object.__setattr__(self, "location", _clean_optional_text(self.location, MAX_LOCATION_LENGTH))
        country = self.pais or extract_country(self.location)
        object.__setattr__(self, "pais", _clean_optional_text(country, MAX_COUNTRY_LENGTH))
        object.__setattr__(self, "status", _clean_optional_text(self.status, MAX_STATUS_LENGTH))

    def _validate(self) -> None:
        if not isinstance(self.event_date, date):
            raise InvalidSeismicEventError("event_date must be a date")
        if not isinstance(self.event_time, time):
            raise InvalidSeismicEventError("event_time must be a time")

        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise InvalidSeismicEventError(f"invalid latitude: {self.latitude!r}")
        if not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise InvalidSeismicEventError(f"invalid longitude: {self.longitude!r}")

        if self.depth_km is not None:
            if not math.isfinite(self.depth_km) or not 0 <= self.depth_km <= 1000:
                raise InvalidSeismicEventError(f"invalid depth_km: {self.depth_km!r}")
        if self.magnitude is not None:
            if not math.isfinite(self.magnitude) or not -2 <= self.magnitude <= 10:
                raise InvalidSeismicEventError(f"invalid magnitude: {self.magnitude!r}")

    @property
    def event_at(self) -> datetime:
        """Normalize the published local date/time to a UTC instant."""
        local_dt = datetime.combine(
            self.event_date,
            self.event_time,
            tzinfo=NICARAGUA_TZ,
        )
        return local_dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SeismicEvent:
    """A persisted seismic event."""

    id: UUID
    fingerprint: str
    event_at: datetime
    event_date: date
    event_time: time
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    location: str | None
    pais: str | None
    status: str | None
    source: str
    source_timezone: str
    registered_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if len(self.fingerprint) != 64:
            raise InvalidSeismicEventError("fingerprint must be a SHA-256 hex digest")
        if self.pais is not None and len(self.pais) > MAX_COUNTRY_LENGTH:
            raise InvalidSeismicEventError("pais exceeds the maximum length")
        if self.event_at.tzinfo is None:
            raise InvalidSeismicEventError("event_at must be timezone-aware")
        if self.registered_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise InvalidSeismicEventError("timestamps must be timezone-aware")
        object.__setattr__(self, "event_at", self.event_at.astimezone(UTC))
        object.__setattr__(self, "registered_at", self.registered_at.astimezone(UTC))
        object.__setattr__(self, "updated_at", self.updated_at.astimezone(UTC))

    @classmethod
    def from_scraped(
        cls,
        scraped: ScrapedEvent,
        *,
        registered_at: datetime | None = None,
        source: str = "INETER",
    ) -> "SeismicEvent":
        """Create a new persisted event and compute its stable identity."""
        now = (registered_at or utc_now()).astimezone(UTC)
        event_at = scraped.event_at
        return cls(
            id=uuid4(),
            fingerprint=build_fingerprint(event_at, scraped.latitude, scraped.longitude),
            event_at=event_at,
            event_date=scraped.event_date,
            event_time=scraped.event_time,
            latitude=scraped.latitude,
            longitude=scraped.longitude,
            depth_km=scraped.depth_km,
            magnitude=scraped.magnitude,
            location=scraped.location,
            pais=scraped.pais,
            status=scraped.status,
            source=source,
            source_timezone=scraped.source_timezone,
            registered_at=now,
            updated_at=now,
        )


def build_fingerprint(event_at: datetime, latitude: float, longitude: float) -> str:
    """Build a stable identity from the event instant and its epicenter.

    Depth, magnitude, status and location are intentionally excluded: INETER
    may revise those values after publication. A revision must update the
    existing record, not create a duplicate.

    The combination of second, latitude and longitude is unique for practical
    purposes in this source.
    """
    normalized = (
        f"{event_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"|{latitude:.6f}|{longitude:.6f}"
    )
    return sha256(normalized.encode("utf-8")).hexdigest()


def _clean_optional_text(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise InvalidSeismicEventError(
            f"text value exceeds {max_length} characters"
        )
    return cleaned

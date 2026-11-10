from datetime import UTC

import pytest

from app.core.errors import InvalidSeismicEventError
from app.seismic.domain.entities import ScrapedEvent, SeismicEvent
from tests.fakes import make_scraped


def test_event_is_normalized_to_utc() -> None:
    event = SeismicEvent.from_scraped(make_scraped(hour=20, minute=26))

    assert event.event_at.tzinfo is not None
    assert event.event_at.astimezone(UTC).isoformat() == "2026-11-09T02:26:05+00:00"
    assert event.event_date.isoformat() == "2026-11-08"
    assert event.source_timezone == "America/Managua"
    assert event.pais == "El Salvador"


def test_country_is_derived_from_location() -> None:
    scraped = make_scraped(
        location="53 Km al suroeste de Mechapa, Chinandega, Nicaragua"
    )

    assert scraped.pais == "Nicaragua"


def test_explicit_country_overrides_location_inference() -> None:
    scraped = make_scraped(
        location="67 Km al suroeste de La Libertad, El Salvador",
        pais="Nicaragua",
    )

    assert scraped.pais == "Nicaragua"


def test_fingerprint_ignores_revisable_fields() -> None:
    original = make_scraped(magnitude=3.1, location="Original location")
    revised = make_scraped(magnitude=4.4, depth=99.0, location="Revised location")

    original_event = SeismicEvent.from_scraped(original)
    revised_event = SeismicEvent.from_scraped(revised)

    assert original_event.fingerprint == revised_event.fingerprint
    assert original_event.id != revised_event.id


def test_fingerprint_changes_with_epicenter_or_time() -> None:
    base = SeismicEvent.from_scraped(make_scraped())
    other_coordinates = SeismicEvent.from_scraped(
        make_scraped(latitude=12.935, longitude=-89.573)
    )
    other_time = SeismicEvent.from_scraped(make_scraped(minute=27))

    assert base.fingerprint != other_coordinates.fingerprint
    assert base.fingerprint != other_time.fingerprint


@pytest.mark.parametrize("latitude", [91.0, -91.0, float("nan")])
def test_invalid_latitude_is_rejected(latitude: float) -> None:
    with pytest.raises(InvalidSeismicEventError):
        make_scraped(latitude=latitude)


def test_invalid_magnitude_is_rejected() -> None:
    with pytest.raises(InvalidSeismicEventError):
        make_scraped(magnitude=11.0)


def test_missing_optional_values_are_allowed() -> None:
    scraped = ScrapedEvent(
        event_date=make_scraped().event_date,
        event_time=make_scraped().event_time,
        latitude=12.0,
        longitude=-87.0,
        depth_km=None,
        magnitude=None,
        location=None,
        status=None,
    )

    event = SeismicEvent.from_scraped(scraped)
    assert event.depth_km is None
    assert event.magnitude is None
    assert event.location is None
    assert event.pais is None

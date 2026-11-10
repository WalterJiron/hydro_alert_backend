from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.seismic.domain.entities import SeismicEvent
from app.seismic.domain.ports import EventFilters
from app.seismic.infrastructure.orm import SeismicEventORM
from app.seismic.infrastructure.repository import SqlAlchemySeismicEventRepository
from tests.fakes import make_event, make_scraped


@pytest.mark.asyncio
async def test_insert_and_deduplicate(postgres_session_factory, sample_events) -> None:
    repository = SqlAlchemySeismicEventRepository(postgres_session_factory)

    first = await repository.upsert_many(sample_events)
    second = await repository.upsert_many(sample_events)

    assert len(first.created) == 3
    assert not first.updated
    assert not second.created
    assert not second.updated
    assert await repository.count() == 3

    stored = await repository.get_by_id(first.created[0].id)
    assert stored is not None
    assert stored.pais == "El Salvador"


@pytest.mark.asyncio
async def test_revision_updates_existing_row(postgres_session_factory) -> None:
    repository = SqlAlchemySeismicEventRepository(postgres_session_factory)
    original = make_event(
        hour=20,
        minute=26,
        magnitude=3.1,
        location="Original, Nicaragua",
    )
    await repository.upsert_many([original])

    revised = SeismicEvent.from_scraped(
        make_scraped(
            hour=20,
            minute=26,
            latitude=original.latitude,
            longitude=original.longitude,
            depth=40.0,
            magnitude=4.4,
            location="Revised, Costa Rica",
            status="C",
        )
    )
    result = await repository.upsert_many([revised])

    assert not result.created
    assert len(result.updated) == 1
    assert await repository.count() == 1

    stored = await repository.get_by_id(original.id)
    assert stored is not None
    assert stored.magnitude == 4.4
    assert stored.depth_km == 40.0
    assert stored.location == "Revised, Costa Rica"
    assert stored.pais == "Costa Rica"
    assert stored.registered_at == original.registered_at
    assert stored.updated_at >= original.updated_at


@pytest.mark.asyncio
async def test_pagination_and_filters(postgres_session_factory, sample_events) -> None:
    repository = SqlAlchemySeismicEventRepository(postgres_session_factory)
    await repository.upsert_many(sample_events)

    page = await repository.list_paginated(
        page=1,
        page_size=2,
        filters=EventFilters(),
    )
    assert page.total == 3
    assert page.total_pages == 2
    assert len(page.items) == 2
    assert page.has_next is True
    assert page.has_previous is False
    assert page.items[0].event_at >= page.items[1].event_at

    second_page = await repository.list_paginated(
        page=2,
        page_size=2,
        filters=EventFilters(),
    )
    assert len(second_page.items) == 1
    assert second_page.has_next is False
    assert second_page.has_previous is True

    filtered = await repository.list_paginated(
        page=1,
        page_size=10,
        filters=EventFilters(min_magnitude=3.0),
    )
    assert filtered.total == 2

    newest = await repository.list_recent(1)
    assert len(newest) == 1
    assert newest[0].event_at == page.items[0].event_at


@pytest.mark.asyncio
async def test_get_by_id_and_missing(postgres_session_factory, sample_events) -> None:
    repository = SqlAlchemySeismicEventRepository(postgres_session_factory)
    await repository.upsert_many(sample_events)

    stored = await repository.get_by_id(sample_events[0].id)
    assert stored is not None
    assert stored.id == sample_events[0].id
    assert await repository.get_by_id(uuid4()) is None
    await repository.ping()


@pytest.mark.asyncio
async def test_database_check_constraints(postgres_session_factory) -> None:
    event = make_event()
    invalid = SeismicEventORM(
        id=uuid4(),
        fingerprint="f" * 64,
        event_at=event.event_at,
        event_date=event.event_date,
        event_time=event.event_time,
        latitude=200.0,
        longitude=event.longitude,
        depth_km=event.depth_km,
        magnitude=event.magnitude,
        location=event.location,
        pais=event.pais,
        status=event.status,
        source="INETER",
        source_timezone="America/Managua",
        registered_at=event.registered_at,
        updated_at=event.updated_at,
    )

    with pytest.raises(IntegrityError):
        async with postgres_session_factory() as session:
            async with session.begin():
                session.add(invalid)

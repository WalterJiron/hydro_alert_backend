from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import utc_now
from app.realtime.domain.events import RealtimeChannel, make_event_id
from app.realtime.infrastructure.event_repository import (
    SqlAlchemyRealtimeEventStore,
)


@pytest.mark.asyncio
async def test_event_store_appends_and_replays_in_order(
    postgres_session_factory,
) -> None:
    store = SqlAlchemyRealtimeEventStore(postgres_session_factory)
    now = utc_now()

    first = await store.append(
        channel=RealtimeChannel.REPORTS,
        event="report.created",
        occurred_at=now,
        data={"id": "rep_1", "category": "flood"},
    )
    second = await store.append(
        channel=RealtimeChannel.NOTIFICATIONS,
        event="notification.created",
        occurred_at=now + timedelta(seconds=1),
        data={"type": "emergency", "title": "Sismo fuerte"},
    )
    third = await store.append(
        channel=RealtimeChannel.REPORTS,
        event="report.deleted",
        occurred_at=now + timedelta(seconds=2),
        data={"id": "rep_1"},
    )

    assert [first.id, second.id, third.id] == [
        make_event_id(1),
        make_event_id(2),
        make_event_id(3),
    ]
    assert await store.last_sequence() == 3

    replay = await store.replay(
        last_event_id=make_event_id(0),
        channels=(RealtimeChannel.REPORTS, RealtimeChannel.NOTIFICATIONS),
        max_events=100,
        notification_cutoff=now - timedelta(minutes=5),
    )
    assert replay.resumed is True
    assert [event.id for event in replay.events] == [
        first.id,
        second.id,
        third.id,
    ]
    assert replay.events[1].data == {
        "type": "emergency",
        "title": "Sismo fuerte",
    }


@pytest.mark.asyncio
async def test_event_store_filters_channels_and_old_notifications(
    postgres_session_factory,
) -> None:
    store = SqlAlchemyRealtimeEventStore(postgres_session_factory)
    now = utc_now()

    await store.append(
        channel=RealtimeChannel.NOTIFICATIONS,
        event="notification.created",
        occurred_at=now - timedelta(minutes=10),
        data={"type": "emergency", "title": "Alerta antigua"},
    )
    recent_notification = await store.append(
        channel=RealtimeChannel.NOTIFICATIONS,
        event="notification.created",
        occurred_at=now,
        data={"type": "emergency", "title": "Alerta reciente"},
    )
    report = await store.append(
        channel=RealtimeChannel.REPORTS,
        event="report.created",
        occurred_at=now,
        data={"id": "rep_2"},
    )

    only_reports = await store.replay(
        last_event_id=make_event_id(0),
        channels=(RealtimeChannel.REPORTS,),
        max_events=100,
        notification_cutoff=now - timedelta(minutes=5),
    )
    assert [event.id for event in only_reports.events] == [report.id]

    both = await store.replay(
        last_event_id=make_event_id(0),
        channels=(RealtimeChannel.REPORTS, RealtimeChannel.NOTIFICATIONS),
        max_events=100,
        notification_cutoff=now - timedelta(minutes=5),
    )
    assert [event.id for event in both.events] == [
        recent_notification.id,
        report.id,
    ]


@pytest.mark.asyncio
async def test_event_store_rejects_unknown_and_malformed_cursors(
    postgres_session_factory,
) -> None:
    store = SqlAlchemyRealtimeEventStore(postgres_session_factory)
    await store.append(
        channel=RealtimeChannel.REPORTS,
        event="report.created",
        occurred_at=utc_now(),
        data={"id": "rep_1"},
    )

    unknown = await store.replay(
        last_event_id=make_event_id(999),
        channels=(RealtimeChannel.REPORTS,),
        max_events=100,
        notification_cutoff=utc_now(),
    )
    assert unknown.resumed is False
    assert not unknown.events

    malformed = await store.replay(
        last_event_id="not-an-event",
        channels=(RealtimeChannel.REPORTS,),
        max_events=100,
        notification_cutoff=utc_now(),
    )
    assert malformed.resumed is False


@pytest.mark.asyncio
async def test_event_store_refuses_oversized_replay(
    postgres_session_factory,
) -> None:
    store = SqlAlchemyRealtimeEventStore(postgres_session_factory)
    for index in range(3):
        await store.append(
            channel=RealtimeChannel.REPORTS,
            event="report.created",
            occurred_at=utc_now(),
            data={"id": f"rep_{index}"},
        )

    replay = await store.replay(
        last_event_id=make_event_id(0),
        channels=(RealtimeChannel.REPORTS,),
        max_events=2,
        notification_cutoff=utc_now(),
    )
    assert replay.resumed is False
    assert not replay.events

    exact = await store.replay(
        last_event_id=make_event_id(0),
        channels=(RealtimeChannel.REPORTS,),
        max_events=3,
        notification_cutoff=utc_now(),
    )
    assert exact.resumed is True
    assert len(exact.events) == 3

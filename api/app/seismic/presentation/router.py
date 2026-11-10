"""REST views for historical consultation (not a CRUD replacement for WS)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.bootstrap.container import ApplicationContainer
from app.bootstrap.dependencies import get_container
from app.core.errors import InvalidQueryError, ResourceNotFoundError
from app.seismic.domain.entities import NICARAGUA_TZ
from app.seismic.domain.ports import EventFilters
from app.seismic.presentation.schemas import (
    PaginatedSeismicEventsResponse,
    PaginationMetadata,
    SeismicEventView,
)

router = APIRouter(prefix="/seismic-events", tags=["seismic-events"])


@router.get(
    "",
    response_model=PaginatedSeismicEventsResponse,
    summary="List historical seismic events with pagination",
)
async def list_seismic_events(
    container: Annotated[ApplicationContainer, Depends(get_container)],
    page: Annotated[int, Query(ge=1, description="One-based page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    from_date: Annotated[
        date | None,
        Query(description="Inclusive start date in Nicaraguan local time"),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(description="Inclusive end date in Nicaraguan local time"),
    ] = None,
    min_magnitude: Annotated[float | None, Query(ge=-2, le=10)] = None,
) -> PaginatedSeismicEventsResponse:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise InvalidQueryError("from_date must be earlier than or equal to to_date")

    filters = EventFilters(
        from_at=_start_of_local_day(from_date) if from_date else None,
        to_at=_end_of_local_day(to_date) if to_date else None,
        min_magnitude=min_magnitude,
    )
    result = await container.repository.list_paginated(
        page=page,
        page_size=page_size,
        filters=filters,
    )
    return PaginatedSeismicEventsResponse(
        items=[SeismicEventView.model_validate(event) for event in result.items],
        pagination=PaginationMetadata(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            total_pages=result.total_pages,
            has_next=result.has_next,
            has_previous=result.has_previous,
        ),
    )


@router.get(
    "/{event_id}",
    response_model=SeismicEventView,
    summary="Get one seismic event by its identifier",
)
async def get_seismic_event(
    event_id: UUID,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> SeismicEventView:
    event = await container.repository.get_by_id(event_id)
    if event is None:
        raise ResourceNotFoundError("seismic event", event_id)
    return SeismicEventView.model_validate(event)


def _start_of_local_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=NICARAGUA_TZ).astimezone(UTC)


def _end_of_local_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=NICARAGUA_TZ).astimezone(UTC)

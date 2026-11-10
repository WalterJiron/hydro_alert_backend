"""Service readiness and operational status."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app import __version__
from app.bootstrap.container import ApplicationContainer
from app.bootstrap.dependencies import get_container
from app.core.time import utc_now

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class DatabaseHealth(BaseModel):
    status: Literal["ok", "error"]


class RealtimeHealth(BaseModel):
    connected_clients: int
    seismic_clients: int = 0
    reports_clients: int = 0


class SyncHealth(BaseModel):
    enabled: bool
    running: bool
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    consecutive_failures: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    timestamp: datetime
    database: DatabaseHealth
    sync: SyncHealth
    realtime: RealtimeHealth


@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="Readiness check including database and worker state",
)
async def health(
    response: Response,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> HealthResponse:
    database_ok = True
    try:
        await container.repository.ping()
    except Exception:
        database_ok = False
        logger.warning(
            "health check could not reach PostgreSQL",
            extra={"event": "health_database_error"},
        )

    if not database_ok:
        response.status_code = 503

    worker_status = (
        container.sync_worker.status()
        if container.sync_worker is not None
        else None
    )
    connections = await container.connection_manager.connection_count()
    report_connections = await container.realtime_hub.connection_count()

    return HealthResponse(
        status="ok" if database_ok else "degraded",
        service="seismic-events-api",
        version=__version__,
        timestamp=utc_now(),
        database=DatabaseHealth(status="ok" if database_ok else "error"),
        sync=SyncHealth(
            enabled=worker_status is not None,
            running=worker_status.running if worker_status else False,
            last_run_at=worker_status.last_run_at if worker_status else None,
            last_success_at=worker_status.last_success_at if worker_status else None,
            last_error=(
                worker_status.last_error[:300]
                if worker_status and worker_status.last_error
                else None
            ),
            consecutive_failures=(
                worker_status.consecutive_failures if worker_status else 0
            ),
        ),
        realtime=RealtimeHealth(
            connected_clients=connections + report_connections,
            seismic_clients=connections,
            reports_clients=report_connections,
        ),
    )

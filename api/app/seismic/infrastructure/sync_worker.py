"""Background polling worker, independent from client connections."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from app.core.time import utc_now
from app.seismic.application.sync_events import SyncOutcome, SyncSeismicEvents

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncWorkerStatus:
    """Immutable health/status snapshot."""

    running: bool
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    last_outcome: SyncOutcome | None


class SyncWorker:
    """Run the synchronization use case on a fixed interval.

    HTTP and database operations are asynchronous, so the event loop keeps
    serving REST and WebSocket clients while INETER is being scraped.
    """

    def __init__(
        self,
        use_case: SyncSeismicEvents,
        *,
        interval_seconds: int,
    ) -> None:
        self._use_case = use_case
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None
        self._consecutive_failures = 0
        self._last_outcome: SyncOutcome | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="ineter-sync-worker",
        )
        logger.info(
            "INETER synchronization worker started",
            extra={
                "event": "sync_worker_started",
                "interval_seconds": self._interval_seconds,
            },
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=10)
        except TimeoutError:
            logger.warning(
                "synchronization worker did not stop in time; cancelling",
                extra={"event": "sync_worker_cancel"},
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None
            logger.info(
                "INETER synchronization worker stopped",
                extra={"event": "sync_worker_stopped"},
            )

    def status(self) -> SyncWorkerStatus:
        return SyncWorkerStatus(
            running=self._task is not None and not self._task.done(),
            last_run_at=self._last_run_at,
            last_success_at=self._last_success_at,
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
            last_outcome=self._last_outcome,
        )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                outcome = await self._use_case.execute()
                self._last_success_at = utc_now()
                self._consecutive_failures = 0
                self._last_error = None
                self._last_outcome = outcome
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"[:500]
                logger.exception(
                    "INETER synchronization failed",
                    extra={
                        "event": "sync_failed",
                        "consecutive_failures": self._consecutive_failures,
                    },
                )
            finally:
                self._last_run_at = utc_now()

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue

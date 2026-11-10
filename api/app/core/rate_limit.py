"""Small in-memory fixed-window rate limiter for public auth endpoints.

The API runs as a single process in this deployment. A shared store (Redis)
can replace this adapter later without changing the routers: they only depend
on :class:`InMemoryRateLimiter.hit`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from math import ceil
from typing import Callable


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class InMemoryRateLimiter:
    """Track hits per key inside a moving window."""

    def __init__(
        self,
        *,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, *, limit: int) -> RateLimitDecision:
        """Record one attempt and report whether the caller may continue."""
        now = self._clock()
        cutoff = now - self._window_seconds

        async with self._lock:
            hits = [stamp for stamp in self._hits.get(key, ()) if stamp > cutoff]
            if len(hits) >= limit:
                retry_after = max(1, ceil(self._window_seconds - (now - hits[0])))
                self._hits[key] = hits
                return RateLimitDecision(False, retry_after)

            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10_000:
                self._prune(cutoff)
            return RateLimitDecision(True, 0)

    def _prune(self, cutoff: float) -> None:
        expired = [
            key
            for key, stamps in self._hits.items()
            if not stamps or stamps[-1] <= cutoff
        ]
        for key in expired:
            self._hits.pop(key, None)

"""Timezone-aware clock helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC instant with timezone information."""
    return datetime.now(tz=UTC)

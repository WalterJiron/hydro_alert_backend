"""Scraping value objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.seismic.domain.entities import ScrapedEvent


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Outcome of parsing one INETER HTML document.

    ``candidates`` counts anchors that look like seismic events, while
    ``skipped`` counts candidates that could not be validated. This lets the
    caller distinguish "the page has no events" from "the page structure
    changed".
    """

    events: tuple[ScrapedEvent, ...] = ()
    candidates: int = 0
    skipped: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

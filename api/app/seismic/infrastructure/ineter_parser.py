"""Parser for the INETER seismic events HTML page.

Source structure (verified 2026-11-08):
    <a href="javascript:ver_mapa(1,12.934,-89.573);" ...>
        <PRE>26/11/08 20:26:05 12.934 -89.573  23 3.1
        <span class='estiloC'>C</span>  67 Km al suroeste de La Libertad, El Salvador</PRE>
    </a>

The parser is intentionally isolated from HTTP and persistence. It never
invents missing values: optional fields are returned as ``None``.
"""

from __future__ import annotations

import re
from datetime import date, time

from bs4 import BeautifulSoup

from app.seismic.domain.entities import ScrapedEvent
from app.seismic.domain.scraping import ParseResult

_VER_MAPA_RE = re.compile(
    r"ver_mapa\(\s*(?P<id>\d+)\s*,\s*(?P<lat>-?\d+(?:\.\d+)?)"
    r"\s*,\s*(?P<lon>-?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)

_EVENT_LINE_RE = re.compile(
    r"^\s*"
    r"(?P<year>\d{2})/(?P<month>\d{2})/(?P<day>\d{2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\s+"
    r"(?P<latitude>-?\d+(?:\.\d+)?)\s+"
    r"(?P<longitude>-?\d+(?:\.\d+)?)\s+"
    r"(?P<depth>-?\d+(?:\.\d+)?|(?:-{1,3}|—|–))\s+"
    r"(?P<magnitude>-?\d+(?:\.\d+)?|(?:-{1,3}|—|–))"
    r"\s*(?P<tail>.*)$",
    re.DOTALL,
)

_STATUS_INFERENCE_RE = re.compile(r"^(?P<status>[A-Za-z])\s+(?=\d)")
_STATUS_TOKEN_RE = re.compile(r"^[A-Za-z]{1,3}$")
_MAX_WARNINGS = 10


class IneterHtmlParser:
    """Extract validated events from the INETER HTML document."""

    def parse(self, html: str) -> ParseResult:
        soup = BeautifulSoup(html, "html.parser")
        events: list[ScrapedEvent] = []
        warnings: list[str] = []
        candidates = 0
        skipped = 0

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", ""))
            match = _VER_MAPA_RE.search(href)
            if match is None:
                continue

            candidates += 1
            pre = anchor.find("pre")
            if pre is None:
                skipped += 1
                _append_warning(warnings, f"candidate {candidates}: missing <PRE>")
                continue

            status = _extract_status(pre)
            line_match = _EVENT_LINE_RE.match(pre.get_text(" ", strip=True))
            if line_match is None:
                skipped += 1
                _append_warning(warnings, f"candidate {candidates}: unexpected event format")
                continue

            try:
                event = _build_event(line_match, status)
            except (TypeError, ValueError, OverflowError) as exc:
                skipped += 1
                _append_warning(warnings, f"candidate {candidates}: {exc}")
                continue

            events.append(event)

        return ParseResult(
            events=tuple(events),
            candidates=candidates,
            skipped=skipped,
            warnings=tuple(warnings),
        )


def _extract_status(pre: object) -> str | None:
    find = getattr(pre, "find", None)
    if find is None:
        return None
    span = find("span")
    if span is None:
        return None
    status = " ".join(str(span.get_text(" ", strip=True)).split())
    if not _STATUS_TOKEN_RE.fullmatch(status):
        return None
    return status


def _build_event(match: re.Match[str], status: str | None) -> ScrapedEvent:
    published_date = date(
        2000 + int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
    )
    published_time = time(
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
    )

    tail = match.group("tail").strip()
    if status:
        tail = _remove_leading_status(tail, status)
    else:
        inferred = _STATUS_INFERENCE_RE.match(tail)
        if inferred:
            status = inferred.group("status")
            tail = tail[inferred.end() :].strip()

    return ScrapedEvent(
        event_date=published_date,
        event_time=published_time,
        latitude=float(match.group("latitude")),
        longitude=float(match.group("longitude")),
        depth_km=_optional_float(match.group("depth")),
        magnitude=_optional_float(match.group("magnitude")),
        location=tail or None,
        status=status,
    )


def _remove_leading_status(tail: str, status: str) -> str:
    if tail.upper().startswith(status.upper()):
        remainder = tail[len(status) :]
        if not remainder or remainder[0].isspace():
            return remainder.strip()
    return tail


def _optional_float(raw: str) -> float | None:
    if not raw or not re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return None
    return float(raw)


def _append_warning(warnings: list[str], message: str) -> None:
    if len(warnings) < _MAX_WARNINGS:
        warnings.append(message)

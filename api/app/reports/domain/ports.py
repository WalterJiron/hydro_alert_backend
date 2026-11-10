"""Ports consumed by the report application layer."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from app.reports.domain.entities import Report


class PhotoStorage(Protocol):
    """Port for external object storage (e.g. Supabase Storage / S3)."""

    async def upload_photo(
        self,
        *,
        report_id: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """Upload image bytes and return the canonical public CDN URL."""
        ...

    async def get_photo(
        self,
        report_id: str,
    ) -> tuple[bytes, str] | None:
        """Retrieve photo bytes directly if stored locally or in memory."""
        ...

    async def delete_photo(self, photo_url: str) -> None:
        """Delete image from storage if needed."""
        ...


class ReportRepository(Protocol):
    """Persistence port for community report metadata."""

    async def create(self, report: Report) -> Report: ...

    async def list_active(self, limit: int) -> Sequence[Report]: ...

    async def get_active(self, report_id: str) -> Report | None: ...

    async def deactivate(
        self,
        report_id: str,
        deleted_at: datetime,
    ) -> Report | None: ...


class ReportEventPublisher(Protocol):
    """Realtime port. Persistence failures must not delete the report."""

    async def publish_report_created(self, report: Report) -> None: ...

    async def publish_report_deleted(self, report_id: str) -> None: ...

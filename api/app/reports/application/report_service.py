"""Create, list and deactivate community reports."""

from __future__ import annotations

import logging
from uuid import uuid4

from app.auth.domain.entities import User
from app.core.errors import ForbiddenError, ResourceNotFoundError
from app.core.time import utc_now
from app.reports.domain.entities import Report
from app.reports.domain.ports import (
    PhotoStorage,
    ReportEventPublisher,
    ReportRepository,
)
from app.reports.domain.validation import (
    MAX_PHOTO_BYTES,
    detect_photo_content_type,
    validate_report_input,
)

logger = logging.getLogger(__name__)


class ReportService:
    def __init__(
        self,
        *,
        repository: ReportRepository,
        publisher: ReportEventPublisher,
        photo_storage: PhotoStorage,
        max_active: int = 100,
        photo_max_bytes: int = MAX_PHOTO_BYTES,
        public_api_base_url: str | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._photo_storage = photo_storage
        self._max_active = max_active
        self._photo_max_bytes = photo_max_bytes
        self._public_api_base_url = public_api_base_url

    async def create(
        self,
        *,
        user: User,
        category: str,
        description: str,
        latitude: float,
        longitude: float,
        photo_data: bytes | None = None,
    ) -> Report:
        validated = validate_report_input(
            category=category,
            description=description,
            latitude=latitude,
            longitude=longitude,
        )

        report_id = f"rep_{uuid4().hex}"
        photo_url: str | None = None

        if photo_data:
            content_type = detect_photo_content_type(
                photo_data,
                max_bytes=self._photo_max_bytes,
            )
            photo_url = await self._photo_storage.upload_photo(
                report_id=report_id,
                data=photo_data,
                content_type=content_type,
            )

        report = Report(
            id=report_id,
            user_id=user.id,
            category=validated.category,
            description=validated.description,
            latitude=validated.latitude,
            longitude=validated.longitude,
            created_at=utc_now(),
            photo_url=photo_url,
        )
        stored = await self._repository.create(report)

        try:
            await self._publisher.publish_report_created(stored)
        except Exception:
            logger.exception(
                "report persisted but realtime publication failed",
                extra={"event": "report_publish_failed", "report_id": stored.id},
            )
        return stored

    async def list_active(self) -> list[Report]:
        reports = await self._repository.list_active(self._max_active)
        return list(reports)

    async def delete(self, report_id: str, *, user: User) -> Report:
        report = await self._repository.get_active(report_id)
        if report is None:
            raise ResourceNotFoundError("report", report_id)
        if report.user_id != user.id:
            raise ForbiddenError("Only the author can delete this report.")

        deleted = await self._repository.deactivate(report_id, utc_now())
        if deleted is None:
            raise ResourceNotFoundError("report", report_id)

        if report.photo_url:
            try:
                await self._photo_storage.delete_photo(report.photo_url)
            except Exception:
                logger.warning(
                    "failed to delete report photo from storage",
                    extra={"report_id": report_id},
                )

        try:
            await self._publisher.publish_report_deleted(report_id)
        except Exception:
            logger.exception(
                "report deleted but realtime publication failed",
                extra={"event": "report_delete_publish_failed", "report_id": report_id},
            )
        return deleted

    async def get_photo_url(self, report_id: str) -> str | None:
        report = await self._repository.get_active(report_id)
        if report is None:
            return None
        return report.photo_url

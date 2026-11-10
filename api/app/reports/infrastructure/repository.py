"""PostgreSQL adapter for community reports."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import PersistenceError
from app.reports.domain.entities import Report, ReportCategory
from app.reports.infrastructure.orm import ReportORM

logger = logging.getLogger(__name__)


class SqlAlchemyReportRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, report: Report) -> Report:
        async with self._session_factory() as session:
            session.add(
                ReportORM(
                    id=report.id,
                    user_id=report.user_id,
                    category_key=report.category.value,
                    description=report.description,
                    latitude=report.latitude,
                    longitude=report.longitude,
                    photo_url=report.photo_url,
                    created_at=report.created_at,
                    deleted_at=None,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                logger.exception(
                    "report could not be persisted",
                    extra={"event": "report_persist_failed"},
                )
                raise PersistenceError(
                    "Failed to save report."
                ) from exc
        return Report(
            id=report.id,
            user_id=report.user_id,
            category=report.category,
            description=report.description,
            latitude=report.latitude,
            longitude=report.longitude,
            created_at=report.created_at,
            photo_url=report.photo_url,
        )

    async def list_active(self, limit: int) -> Sequence[Report]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(ReportORM)
                    .where(ReportORM.deleted_at.is_(None))
                    .order_by(
                        ReportORM.created_at.desc(),
                        ReportORM.id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        return [_to_report(row) for row in rows]

    async def get_active(self, report_id: str) -> Report | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ReportORM).where(
                    ReportORM.id == report_id,
                    ReportORM.deleted_at.is_(None),
                )
            )
        return _to_report(row) if row is not None else None

    async def deactivate(
        self,
        report_id: str,
        deleted_at: datetime,
    ) -> Report | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ReportORM)
                .where(
                    ReportORM.id == report_id,
                    ReportORM.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                return None
            row.deleted_at = deleted_at
            row.updated_at = deleted_at
            try:
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.exception(
                    "report could not be deactivated",
                    extra={"event": "report_deactivate_failed"},
                )
                raise PersistenceError(
                    "Failed to delete report."
                ) from exc
        return _to_report(row)


def _to_report(row: ReportORM) -> Report:
    return Report(
        id=row.id,
        user_id=row.user_id,
        category=ReportCategory(row.category_key),
        description=row.description,
        latitude=row.latitude,
        longitude=row.longitude,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
        photo_url=row.photo_url,
        updated_at=row.updated_at,
    )

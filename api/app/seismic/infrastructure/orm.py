"""SQLAlchemy ORM mapping for seismic events."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SeismicEventORM(Base):
    """Persistent representation of one INETER event."""

    __tablename__ = "seismic_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[time] = mapped_column(Time(), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    depth_km: Mapped[float | None] = mapped_column(Float(), nullable=True)
    magnitude: Mapped[float | None] = mapped_column(Float(), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pais: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="INETER",
        server_default=text("'INETER'"),
    )
    source_timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="America/Managua",
        server_default=text("'America/Managua'"),
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_seismic_events_fingerprint"),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_seismic_events_latitude",
        ),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_seismic_events_longitude",
        ),
        CheckConstraint(
            "depth_km IS NULL OR depth_km >= 0",
            name="ck_seismic_events_depth",
        ),
        CheckConstraint(
            "magnitude IS NULL OR (magnitude >= -2 AND magnitude <= 10)",
            name="ck_seismic_events_magnitude",
        ),
    )

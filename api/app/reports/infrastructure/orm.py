"""SQLAlchemy mappings for reports, report categories, and storage references."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReportCategoryORM(Base):
    """Normalized lookup table for community report categories (3NF).

    Instead of a CHECK constraint with hardcoded values, categories live in
    their own table so the domain is extensible without schema migration.
    The ``key`` column is the FK target used by ``reports.category_key``.
    """

    __tablename__ = "report_categories"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ReportORM(Base):
    """Normalized representation of community reports (3NF & ISO 27001).

    * ``category_key`` references ``report_categories.key`` (proper 3NF FK).
    * Photos are hosted externally in Supabase Storage; only the canonical
      public URI is persisted, eliminating BYTEA bloat.
    * ``updated_at`` supports audit trail requirements.
    """

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_key: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("report_categories.key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(description) BETWEEN 10 AND 500",
            name="ck_reports_description_length",
        ),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_reports_latitude",
        ),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_reports_longitude",
        ),
    )

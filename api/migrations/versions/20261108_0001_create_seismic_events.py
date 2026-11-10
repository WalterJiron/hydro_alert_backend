"""Create the seismic events table.

Revision ID: 20261108_0001
Revises:
Create Date: 2026-11-08 00:00:00

The fingerprint is a SHA-256 of the event instant and epicenter. It is the
natural identity used to prevent duplicate inserts while allowing INETER to
revise depth, magnitude, status or location without creating a second row.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261108_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seismic_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("depth_km", sa.Float(), nullable=True),
        sa.Column("magnitude", sa.Float(), nullable=True),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'INETER'"),
        ),
        sa.Column(
            "source_timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'America/Managua'"),
        ),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_seismic_events_latitude",
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_seismic_events_longitude",
        ),
        sa.CheckConstraint(
            "depth_km IS NULL OR depth_km >= 0",
            name="ck_seismic_events_depth",
        ),
        sa.CheckConstraint(
            "magnitude IS NULL OR (magnitude >= -2 AND magnitude <= 10)",
            name="ck_seismic_events_magnitude",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fingerprint",
            name="uq_seismic_events_fingerprint",
        ),
    )
    op.create_index(
        "ix_seismic_events_event_at",
        "seismic_events",
        ["event_at"],
        unique=False,
    )
    op.create_index(
        "ix_seismic_events_magnitude",
        "seismic_events",
        ["magnitude"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seismic_events_magnitude", table_name="seismic_events")
    op.drop_index("ix_seismic_events_event_at", table_name="seismic_events")
    op.drop_table("seismic_events")

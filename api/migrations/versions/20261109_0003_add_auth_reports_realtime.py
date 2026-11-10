"""Add reporter accounts, community reports and the realtime event log.

Revision ID: 20261109_0003
Revises: 20261109_0002
Create Date: 2026-11-09 04:30:00

The ``realtime_events`` table is append-only and gives WebSocket clients an
ordered, resumable cursor. Report photos live in a separate table so history
queries never load binary payloads.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261109_0003"
down_revision: Union[str, None] = "20261109_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("cedula_normalized", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 3 AND 80",
            name="ck_users_name_length",
        ),
        sa.CheckConstraint(
            "char_length(email) BETWEEN 3 AND 254",
            name="ck_users_email_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint(
            "cedula_normalized",
            name="uq_users_cedula_normalized",
        ),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_tokens_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_auth_tokens_user_id",
        "auth_tokens",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=48), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "has_photo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "category IN ('flood', 'damaged_drain', 'fallen_tree', "
            "'landslide', 'fire', 'earthquake_damage', 'other')",
            name="ck_reports_category",
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 10 AND 500",
            name="ck_reports_description_length",
        ),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_reports_latitude",
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_reports_longitude",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_reports_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"], unique=False)
    op.create_index(
        "ix_reports_created_at",
        "reports",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reports_deleted_at",
        "reports",
        ["deleted_at"],
        unique=False,
    )

    op.create_table(
        "report_photos",
        sa.Column("report_id", sa.String(length=48), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            "byte_size > 0 AND byte_size <= 5242880",
            name="ck_report_photos_size",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name="fk_report_photos_report_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id"),
    )

    op.create_table(
        "realtime_events",
        sa.Column(
            "seq",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("id", name="uq_realtime_events_id"),
    )
    op.create_index(
        "ix_realtime_events_channel_seq",
        "realtime_events",
        ["channel", "seq"],
        unique=False,
    )
    op.create_index(
        "ix_realtime_events_occurred_at",
        "realtime_events",
        ["occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("realtime_events")
    op.drop_table("report_photos")
    op.drop_table("reports")
    op.drop_table("auth_tokens")
    op.drop_table("users")

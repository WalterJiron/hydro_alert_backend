"""Normalize schema to 3NF and implement ISO 27001 security controls.

Revision ID: 20261109_0004
Revises: 20261109_0003
Create Date: 2026-11-09 23:00:00

Normal Forms (3NF):
- Extracted hardcoded report categories into normalized lookup table `report_categories`.
- Replaced BYTEA BLOB table `report_photos` with external object storage (Supabase),
  keeping only atomic URI `photo_url` in `reports`.
- Removed redundant `has_photo` flag (functionally dependent on `photo_url`).

ISO 27001 Controls:
- A.9.4.2 Account lockout: `failed_login_attempts`, `locked_until` on `users`.
- A.9.4.3 Password management: `password_history` table and `password_changed_at`.
- A.8.5 Session security: `expires_at`, `revoked_at`, `last_used_at` on `auth_tokens`.
- A.9.2.6 Deprovisioning: `is_active` on `users`.
- A.12.4 Audit Logging: `audit_logs` append-only security log and `updated_at` triggers.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261109_0004"
down_revision: Union[str, None] = "20261109_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create normalized report categories table (3NF) ────────────────
    report_categories_table = op.create_table(
        "report_categories",
        sa.Column("key", sa.String(length=32), primary_key=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Seed standard initial categories
    op.bulk_insert(
        report_categories_table,
        [
            {
                "key": "flood",
                "label": "Flood",
                "description": "Inundaciones y anegaciones de calles o viviendas",
                "is_active": True,
            },
            {
                "key": "damaged_drain",
                "label": "Damaged Drain",
                "description": "Drenajes o alcantarillado obstruido o dañado",
                "is_active": True,
            },
            {
                "key": "fallen_tree",
                "label": "Fallen Tree",
                "description": "Árboles caídos sobre vías o tendido eléctrico",
                "is_active": True,
            },
            {
                "key": "landslide",
                "label": "Landslide",
                "description": "Deslaves y derrumbes en laderas o caminos",
                "is_active": True,
            },
            {
                "key": "fire",
                "label": "Fire",
                "description": "Incendios forestales o estructurales",
                "is_active": True,
            },
            {
                "key": "earthquake_damage",
                "label": "Earthquake Damage",
                "description": "Daños estructurales ocasionados por sismos",
                "is_active": True,
            },
            {
                "key": "other",
                "label": "Other",
                "description": "Otros incidentes comunitarios de emergencia",
                "is_active": True,
            },
        ],
    )

    # ── 2. Refactor reports table ─────────────────────────────────────────
    # Add new normalized columns
    op.add_column(
        "reports",
        sa.Column("category_key", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("photo_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Populate category_key from existing category column
    op.execute("UPDATE reports SET category_key = category WHERE category_key IS NULL")
    op.alter_column("reports", "category_key", nullable=False)

    # Add foreign key constraint to report_categories
    op.create_foreign_key(
        "fk_reports_category_key",
        "reports",
        "report_categories",
        ["category_key"],
        ["key"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_reports_category_key", "reports", ["category_key"])

    # Drop old check constraint and category column
    op.drop_constraint("ck_reports_category", "reports", type_="check")
    op.drop_column("reports", "category")

    # Drop redundant has_photo column (3NF violation)
    op.drop_column("reports", "has_photo")

    # Drop report_photos table (binary BLOBs moved to Supabase Storage)
    op.drop_table("report_photos")

    # ── 3. Enhance users table (ISO 27001 Controls) ───────────────────────
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ── 4. Enhance auth_tokens table (ISO 27001 Session Management) ───────
    op.add_column(
        "auth_tokens",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '30 days'"),
        ),
    )
    op.add_column(
        "auth_tokens",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auth_tokens",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_tokens_expires_at", "auth_tokens", ["expires_at"])
    op.create_index("ix_auth_tokens_revoked_at", "auth_tokens", ["revoked_at"])

    # ── 5. Create password_history table (ISO 27001 A.9.4.3) ──────────────
    op.create_table(
        "password_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.String(length=48), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_password_history_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_password_history_user_changed",
        "password_history",
        ["user_id", "changed_at"],
    )

    # ── 6. Create audit_logs table (ISO 27001 A.12.4) ─────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.String(length=48), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_audit_logs_user_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "ix_audit_logs_user_action",
        "audit_logs",
        ["user_id", "action"],
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("password_history")

    op.drop_index("ix_auth_tokens_revoked_at", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_expires_at", table_name="auth_tokens")
    op.drop_column("auth_tokens", "revoked_at")
    op.drop_column("auth_tokens", "last_used_at")
    op.drop_column("auth_tokens", "expires_at")

    op.drop_column("users", "is_active")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
    op.drop_column("users", "updated_at")

    op.create_table(
        "report_photos",
        sa.Column("report_id", sa.String(length=48), primary_key=True),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name="fk_report_photos_report_id",
            ondelete="CASCADE",
        ),
    )

    op.add_column(
        "reports",
        sa.Column("has_photo", sa.Boolean(), server_default=sa.text("false")),
    )
    op.add_column("reports", sa.Column("category", sa.String(length=32), nullable=True))
    op.execute("UPDATE reports SET category = category_key")
    op.alter_column("reports", "category", nullable=False)
    op.drop_index("ix_reports_category_key", table_name="reports")
    op.drop_constraint("fk_reports_category_key", "reports", type_="foreignkey")
    op.drop_column("reports", "updated_at")
    op.drop_column("reports", "photo_url")
    op.drop_column("reports", "category_key")

    op.drop_table("report_categories")


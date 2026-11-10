"""SQLAlchemy mappings for reporter accounts, bearer tokens, password
history and security audit log (ISO 27001 controls).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ── Users (ISO 27001 A.9.2) ────────────────────────────────────────────

class UserORM(Base):
    """User account entity adhering to 3NF and ISO 27001 security controls.

    * ``failed_login_attempts`` / ``locked_until`` → A.9.4.2 account lockout
    * ``password_changed_at``                       → A.9.4.3 password rotation
    * ``is_active``                                 → A.9.2.6 user deprovisioning
    * ``updated_at``                                → A.12.4  audit trail
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    cedula_normalized: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(name) BETWEEN 3 AND 80",
            name="ck_users_name_length",
        ),
        CheckConstraint(
            "char_length(email) BETWEEN 3 AND 254",
            name="ck_users_email_length",
        ),
    )


# ── Auth tokens (ISO 27001 A.8.5 / A.9.4.2) ───────────────────────────

class AuthTokenORM(Base):
    """Bearer session token with expiration, revocation and usage tracking.

    * ``expires_at``   → A.8.5  token lifetime enforcement
    * ``revoked_at``   → A.9.4.2 immediate session termination
    * ``last_used_at`` → A.12.4 activity monitoring
    """

    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


# ── Password history (ISO 27001 A.9.4.3) ───────────────────────────────

class PasswordHistoryORM(Base):
    """Stores previous password hashes to prevent reuse.

    ISO 27001 A.9.4.3 requires that users cannot reuse recent passwords
    when changing their credentials.  The application checks the last N
    entries before accepting a new password.
    """

    __tablename__ = "password_history"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_password_history_user_changed", "user_id", "changed_at"),
    )


# ── Security audit log (ISO 27001 A.12.4) ──────────────────────────────

class AuditLogORM(Base):
    """Immutable, append-only security event log.

    Records security-relevant actions such as login attempts, account
    lockouts, password changes, and report mutations.  Each entry carries
    the actor identity, an event code, an optional IP address, and free-form
    JSON details.

    ISO 27001 A.12.4 – Logging and monitoring.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(48),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_logs_user_action", "user_id", "action"),
    )

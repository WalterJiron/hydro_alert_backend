"""PostgreSQL adapter for accounts, tokens, password history and audit log."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.domain.entities import User
from app.auth.infrastructure.orm import (
    AuditLogORM,
    AuthTokenORM,
    PasswordHistoryORM,
    UserORM,
)
from app.core.errors import (
    CedulaAlreadyRegisteredError,
    EmailAlreadyRegisteredError,
    PersistenceError,
)
from app.core.time import utc_now

logger = logging.getLogger(__name__)


class SqlAlchemyAuthRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ── User lookup ─────────────────────────────────────────────────────

    async def find_by_email(self, email: str) -> User | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserORM).where(UserORM.email == email)
            )
            return _to_user(row) if row is not None else None

    async def find_by_cedula(self, cedula_normalized: str) -> User | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserORM).where(
                    UserORM.cedula_normalized == cedula_normalized
                )
            )
            return _to_user(row) if row is not None else None

    # ── User creation ───────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        async with self._session_factory() as session:
            session.add(
                UserORM(
                    id=user.id,
                    name=user.name,
                    email=user.email,
                    cedula_normalized=user.cedula_normalized,
                    password_hash=user.password_hash,
                    created_at=user.created_at,
                    updated_at=user.created_at,
                    failed_login_attempts=0,
                    locked_until=None,
                    password_changed_at=user.created_at,
                    is_active=True,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise _map_unique_error(exc) from exc
        return user

    # ── Token management ────────────────────────────────────────────────

    async def create_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                AuthTokenORM(
                    token_hash=token_hash,
                    user_id=user_id,
                    created_at=created_at,
                    expires_at=expires_at,
                    last_used_at=None,
                    revoked_at=None,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                logger.exception(
                    "could not persist an authentication token",
                    extra={"event": "auth_token_persist_failed"},
                )
                raise PersistenceError(
                    "Failed to create user session."
                ) from exc

    async def find_by_token_hash(self, token_hash: str) -> User | None:
        now = utc_now()
        async with self._session_factory() as session:
            token_row = await session.scalar(
                select(AuthTokenORM).where(
                    AuthTokenORM.token_hash == token_hash,
                    AuthTokenORM.revoked_at.is_(None),
                    AuthTokenORM.expires_at > now,
                )
            )
            if token_row is None:
                return None

            user_row = await session.scalar(
                select(UserORM).where(
                    UserORM.id == token_row.user_id,
                    UserORM.is_active.is_(True),
                )
            )
            if user_row is None:
                return None

            token_row.last_used_at = now
            try:
                await session.commit()
            except Exception:
                await session.rollback()

            return _to_user(user_row)

    # ── Account lockout (ISO 27001 A.9.4.2) ─────────────────────────────

    async def record_login_failure(
        self,
        user_id: str,
        *,
        max_attempts: int = 5,
        lockout_minutes: int = 15,
    ) -> None:
        now = utc_now()
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserORM).where(UserORM.id == user_id).with_for_update()
            )
            if row is not None:
                row.failed_login_attempts += 1
                row.updated_at = now
                if row.failed_login_attempts >= max_attempts:
                    row.locked_until = now + timedelta(minutes=lockout_minutes)
                    logger.warning(
                        "user account temporarily locked due to failed login attempts",
                        extra={
                            "user_id": user_id,
                            "locked_until": row.locked_until.isoformat(),
                        },
                    )
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()

    async def record_login_success(self, user_id: str) -> None:
        now = utc_now()
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserORM).where(UserORM.id == user_id).with_for_update()
            )
            if row is not None:
                row.failed_login_attempts = 0
                row.locked_until = None
                row.updated_at = now
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()

    # ── Password history (ISO 27001 A.9.4.3) ────────────────────────────

    async def add_password_history(
        self,
        user_id: str,
        password_hash: str,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                PasswordHistoryORM(
                    user_id=user_id,
                    password_hash=password_hash,
                    changed_at=utc_now(),
                )
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                logger.warning(
                    "failed to record password history entry",
                    extra={"user_id": user_id},
                )

    async def get_recent_password_hashes(
        self,
        user_id: str,
        limit: int = 5,
    ) -> Sequence[str]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(PasswordHistoryORM.password_hash)
                    .where(PasswordHistoryORM.user_id == user_id)
                    .order_by(PasswordHistoryORM.changed_at.desc())
                    .limit(limit)
                )
            ).all()
        return list(rows)


# ── Audit log adapter (ISO 27001 A.12.4) ───────────────────────────────

class SqlAlchemyAuditLogger:
    """Append-only security event writer."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def log(
        self,
        *,
        action: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                AuditLogORM(
                    user_id=user_id,
                    action=action,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details=details,
                )
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                logger.warning(
                    "failed to persist audit log entry",
                    extra={"action": action, "user_id": user_id},
                )


# ── Mappers ─────────────────────────────────────────────────────────────

def _to_user(row: UserORM) -> User:
    return User(
        id=row.id,
        name=row.name,
        email=row.email,
        cedula_normalized=row.cedula_normalized,
        password_hash=row.password_hash,
        created_at=row.created_at,
        updated_at=row.updated_at,
        failed_login_attempts=row.failed_login_attempts,
        locked_until=row.locked_until,
        password_changed_at=row.password_changed_at,
        is_active=row.is_active,
    )


def _map_unique_error(exc: IntegrityError) -> Exception:
    message = str(exc).lower()
    if "cedula" in message:
        return CedulaAlreadyRegisteredError()
    if "email" in message:
        return EmailAlreadyRegisteredError()
    return PersistenceError("Failed to save user account.")

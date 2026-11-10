"""Persistence and password/token ports for account authentication."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, Sequence

from app.auth.domain.entities import User


class AuthRepository(Protocol):
    """Persistence port for users and opaque session tokens."""

    async def find_by_email(self, email: str) -> User | None: ...

    async def find_by_cedula(self, cedula_normalized: str) -> User | None: ...

    async def create_user(self, user: User) -> User: ...

    async def create_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    async def find_by_token_hash(self, token_hash: str) -> User | None: ...

    async def record_login_failure(
        self,
        user_id: str,
        *,
        max_attempts: int = 5,
        lockout_minutes: int = 15,
    ) -> None: ...

    async def record_login_success(self, user_id: str) -> None: ...

    # ── Password history (ISO 27001 A.9.4.3) ───────────────────────────

    async def add_password_history(
        self,
        user_id: str,
        password_hash: str,
    ) -> None: ...

    async def get_recent_password_hashes(
        self,
        user_id: str,
        limit: int = 5,
    ) -> Sequence[str]: ...


class AuditLogger(Protocol):
    """Port for security audit logging (ISO 27001 A.12.4)."""

    async def log(
        self,
        *,
        action: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...

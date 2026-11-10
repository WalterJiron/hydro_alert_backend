"""Registration, login and bearer-token authentication use cases (ISO 27001)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from app.auth.domain.entities import User
from app.auth.domain.ports import AuditLogger, AuthRepository
from app.auth.domain.security import (
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.auth.domain.validation import (
    normalize_email,
    validate_registration,
)
from app.core.errors import (
    CedulaAlreadyRegisteredError,
    EmailAlreadyRegisteredError,
    ForbiddenError,
    InvalidCredentialsError,
    InvalidLoginError,
    InvalidRegistrationError,
    InvalidTokenError,
)
from app.core.time import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthResult:
    """The public result of a successful register or login operation."""

    user: User
    token: str


class AuthService:
    """Application service for reporter accounts."""

    def __init__(
        self,
        repository: AuthRepository,
        *,
        audit_logger: AuditLogger | None = None,
        token_expire_days: int = 30,
        max_failed_attempts: int = 5,
        lockout_minutes: int = 15,
        password_history_limit: int = 5,
    ) -> None:
        self._repository = repository
        self._audit = audit_logger
        self._token_expire_days = token_expire_days
        self._max_failed_attempts = max_failed_attempts
        self._lockout_minutes = lockout_minutes
        self._password_history_limit = password_history_limit

    # ── Registration ────────────────────────────────────────────────────

    async def register(
        self,
        *,
        name: str,
        email: str,
        password: str,
        cedula: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthResult:
        validated = validate_registration(
            name=name,
            email=email,
            password=password,
            cedula=cedula,
        )

        if await self._repository.find_by_email(validated.email) is not None:
            raise EmailAlreadyRegisteredError()
        if (
            await self._repository.find_by_cedula(validated.cedula_normalized)
            is not None
        ):
            raise CedulaAlreadyRegisteredError()

        now = utc_now()
        hashed = hash_password(validated.password)
        user = User(
            id=f"usr_{uuid4().hex}",
            name=validated.name,
            email=validated.email,
            cedula_normalized=validated.cedula_normalized,
            password_hash=hashed,
            created_at=now,
            updated_at=now,
            failed_login_attempts=0,
            locked_until=None,
            password_changed_at=now,
            is_active=True,
        )
        created = await self._repository.create_user(user)

        # Save initial password to history (ISO 27001 A.9.4.3)
        await self._repository.add_password_history(created.id, hashed)

        token = await self._issue_token(created)
        logger.info(
            "reporter account registered",
            extra={"event": "auth_registered", "user_id": created.id},
        )
        await self._audit_log(
            action="user_registered",
            user_id=created.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return AuthResult(user=created, token=token)

    # ── Login ───────────────────────────────────────────────────────────

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthResult:
        if not isinstance(email, str) or not email.strip():
            raise InvalidLoginError("Email is required.")
        try:
            normalized_email = normalize_email(email)
        except InvalidRegistrationError as exc:
            raise InvalidLoginError(str(exc)) from exc
        if not isinstance(password, str) or not password:
            raise InvalidLoginError("Password is required.")

        user = await self._repository.find_by_email(normalized_email)
        if user is None:
            raise InvalidCredentialsError()

        now = utc_now()
        if user.locked_until and user.locked_until > now:
            logger.warning(
                "login attempt on locked account",
                extra={
                    "user_id": user.id,
                    "locked_until": user.locked_until.isoformat(),
                },
            )
            await self._audit_log(
                action="login_attempt_locked",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise ForbiddenError(
                "Account is temporarily locked due to too many failed "
                "attempts. Try again later."
            )

        if not verify_password(password, user.password_hash):
            await self._repository.record_login_failure(
                user.id,
                max_attempts=self._max_failed_attempts,
                lockout_minutes=self._lockout_minutes,
            )
            await self._audit_log(
                action="login_failed",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidCredentialsError()

        await self._repository.record_login_success(user.id)
        token = await self._issue_token(user)
        logger.info(
            "reporter account logged in",
            extra={"event": "auth_logged_in", "user_id": user.id},
        )
        await self._audit_log(
            action="login_success",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return AuthResult(user=user, token=token)

    # ── Token validation ────────────────────────────────────────────────

    async def authenticate(self, token: str) -> User:
        candidate = token.strip() if isinstance(token, str) else ""
        if not candidate or len(candidate) > 512:
            raise InvalidTokenError()

        user = await self._repository.find_by_token_hash(hash_token(candidate))
        if user is None:
            raise InvalidTokenError()
        return user

    # ── Internal helpers ────────────────────────────────────────────────

    async def _issue_token(self, user: User) -> str:
        token = generate_token()
        now = utc_now()
        expires_at = now + timedelta(days=self._token_expire_days)
        await self._repository.create_token(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=expires_at,
        )
        return token

    async def _audit_log(
        self,
        *,
        action: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict | None = None,
    ) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.log(
                action=action,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
            )
        except Exception:
            # Audit failures must never crash the primary flow.
            logger.warning(
                "audit log write failed",
                extra={"action": action, "user_id": user_id},
            )


def public_user(user: User) -> dict[str, str]:
    """Serialize only the fields the mobile app is allowed to see."""
    return {"id": user.id, "name": user.name, "email": user.email}

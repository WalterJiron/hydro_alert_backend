"""FastAPI dependencies shared by authenticated endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.domain.entities import User
from app.bootstrap.container import ApplicationContainer
from app.bootstrap.dependencies import get_container
from app.core.errors import InvalidTokenError, RateLimitExceededError

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Enter the opaque bearer token (e.g. hl_...)",
)


def _client_address(request: Request) -> str:
    client = request.client
    return client.host if client is not None else "unknown"


async def enforce_register_rate_limit(
    request: Request,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> None:
    decision = await container.rate_limiter.hit(
        f"register:{_client_address(request)}",
        limit=container.settings.auth_register_rate_limit,
    )
    if not decision.allowed:
        raise RateLimitExceededError(decision.retry_after_seconds)


async def enforce_login_rate_limit(
    request: Request,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> None:
    decision = await container.rate_limiter.hit(
        f"login:{_client_address(request)}",
        limit=container.settings.auth_login_rate_limit,
    )
    if not decision.allowed:
        raise RateLimitExceededError(decision.retry_after_seconds)


async def get_current_user(
    container: Annotated[ApplicationContainer, Depends(get_container)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Resolve the reporter from an ``Authorization: Bearer <token>`` header."""
    if credentials is None:
        raise InvalidTokenError()

    if credentials.scheme.casefold() != "bearer":
        raise InvalidTokenError()

    token = credentials.credentials.strip()
    if not token:
        raise InvalidTokenError()

    return await container.auth_service.authenticate(token)

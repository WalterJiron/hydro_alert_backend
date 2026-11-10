"""Public registration and login endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.application.auth_service import AuthService, public_user
from app.auth.presentation.dependencies import (
    enforce_login_rate_limit,
    enforce_register_rate_limit,
)
from app.auth.presentation.schemas import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    UserView,
)
from app.bootstrap.container import ApplicationContainer
from app.bootstrap.dependencies import get_container

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    summary="Register a community reporter account",
    dependencies=[Depends(enforce_register_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> AuthResponse:
    result = await container.auth_service.register(
        name=payload.name,
        email=payload.email,
        password=payload.password,
        cedula=payload.cedula,
    )
    return _auth_response(result)


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=200,
    summary="Log in with an existing reporter account",
    dependencies=[Depends(enforce_login_rate_limit)],
)
async def login(
    payload: LoginRequest,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> AuthResponse:
    result = await container.auth_service.login(
        email=payload.email,
        password=payload.password,
    )
    return _auth_response(result)


def _auth_response(result) -> AuthResponse:
    return AuthResponse(
        token=result.token,
        user=UserView(**public_user(result.user)),
    )

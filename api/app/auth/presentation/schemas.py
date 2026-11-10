"""Authentication presentation schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    cedula: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Nombre completo",
                "email": "usuario@ejemplo.com",
                "password": "contraseñaSegura",
                "cedula": "001-100186-0001Z",
            }
        }
    )


class LoginRequest(BaseModel):
    email: str
    password: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "usuario@ejemplo.com",
                "password": "contraseñaSegura",
            }
        }
    )


class UserView(BaseModel):
    """Public account fields. The cédula and password are never included."""

    id: str
    name: str
    email: str


class AuthResponse(BaseModel):
    token: str = Field(description="Opaque bearer token used by POST /reports")
    user: UserView

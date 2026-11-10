from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.app_factory import create_app
from app.core.config import Settings
from tests.conftest import make_settings
from tests.fakes import FakeContainer, build_fake_container

CEDULA_ONE = "001-100186-0001Z"
CEDULA_TWO = "001-010190-0002A"
CEDULA_THREE = "002-150595-0003B"


def build_client(settings: Settings) -> tuple[TestClient, FakeContainer]:
    container = build_fake_container(settings)
    app = create_app(settings, container_factory=lambda _: container)
    return TestClient(app), container


def register_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "María López",
        "email": "maria@ejemplo.com",
        "password": "contraseñaSegura",
        "cedula": CEDULA_ONE,
    }
    payload.update(overrides)
    return payload


def test_register_returns_opaque_token_and_public_user(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        response = client.post(
            "/api/v1/auth/register",
            json=register_payload(
                name="  María López  ",
                email="MARIA@Ejemplo.COM",
            ),
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["token"].startswith("hl_")
    assert set(payload["user"]) == {"id", "name", "email"}
    assert payload["user"]["id"].startswith("usr_")
    assert payload["user"]["name"] == "María López"
    assert payload["user"]["email"] == "maria@ejemplo.com"
    assert "cedula" not in response.text
    assert "password" not in response.text
    assert CEDULA_ONE not in response.text


def test_duplicate_email_returns_409(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        first = client.post("/api/v1/auth/register", json=register_payload())
        duplicate = client.post(
            "/api/v1/auth/register",
            json=register_payload(
                email="MARIA@EJEMPLO.COM",
                cedula=CEDULA_TWO,
            ),
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    body = duplicate.json()
    assert body["error"]["code"] == "email_already_registered"
    assert "message" in body
    assert body["message"] == "Email is already registered."


def test_auth_endpoints_work_without_api_prefix(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        register_res = client.post(
            "/auth/register",
            json=register_payload(email="sin_prefijo@ejemplo.com", cedula=CEDULA_THREE),
        )
        login_res = client.post(
            "/auth/login",
            json={
                "email": "sin_prefijo@ejemplo.com",
                "password": "contraseñaSegura",
            },
        )

    assert register_res.status_code == 201
    assert login_res.status_code == 200


def test_duplicate_cedula_returns_409_even_without_hyphens(
    settings: Settings,
) -> None:
    client, _ = build_client(settings)
    with client:
        first = client.post("/api/v1/auth/register", json=register_payload())
        duplicate = client.post(
            "/api/v1/auth/register",
            json=register_payload(
                email="otra@ejemplo.com",
                cedula="0011001860001Z",
            ),
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "cedula_already_registered"


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "  a  "},
        {"name": "x" * 81},
        {"email": "sin-arroba"},
        {"email": ""},
        {"password": "corta"},
        {"password": ""},
        {"cedula": ""},
        {"cedula": "12345"},
        {"cedula": "001-320186-0001Z"},
        {"cedula": "001-100186-00012"},
    ],
)
def test_invalid_registration_fields_return_400(
    settings: Settings,
    overrides: dict[str, object],
) -> None:
    client, _ = build_client(settings)
    with client:
        response = client.post(
            "/api/v1/auth/register",
            json=register_payload(**overrides),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_registration"


def test_missing_field_returns_400_for_auth(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        response = client.post(
            "/api/v1/auth/register",
            json={"name": "María López", "email": "maria@ejemplo.com"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_login_returns_a_new_token(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        registered = client.post("/api/v1/auth/register", json=register_payload())
        logged_in = client.post(
            "/api/v1/auth/login",
            json={
                "email": "MARIA@ejemplo.com",
                "password": "contraseñaSegura",
            },
        )

    assert logged_in.status_code == 200
    assert logged_in.json()["user"] == registered.json()["user"]
    assert logged_in.json()["token"] != registered.json()["token"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("maria@ejemplo.com", "contraseñaIncorrecta"),
        ("nadie@ejemplo.com", "contraseñaSegura"),
    ],
)
def test_invalid_login_returns_401(
    settings: Settings,
    email: str,
    password: str,
) -> None:
    client, _ = build_client(settings)
    with client:
        client.post("/api/v1/auth/register", json=register_payload())
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_body_validation_returns_400(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "maria@ejemplo.com"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_registration_rate_limit(settings: Settings) -> None:
    limited = make_settings(auth_register_rate_limit=1)
    client, _ = build_client(limited)
    with client:
        first = client.post("/api/v1/auth/register", json=register_payload())
        second = client.post(
            "/api/v1/auth/register",
            json=register_payload(
                email="otra@ejemplo.com",
                cedula=CEDULA_TWO,
            ),
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert second.headers["Retry-After"]


def test_login_rate_limit(settings: Settings) -> None:
    limited = make_settings(auth_login_rate_limit=1)
    client, _ = build_client(limited)
    with client:
        client.post("/api/v1/auth/register", json=register_payload())
        first = client.post(
            "/api/v1/auth/login",
            json={"email": "maria@ejemplo.com", "password": "contraseñaSegura"},
        )
        second = client.post(
            "/api/v1/auth/login",
            json={"email": "maria@ejemplo.com", "password": "contraseñaSegura"},
        )

    assert first.status_code == 200
    assert second.status_code == 429


def test_account_lockout_after_max_failed_attempts(settings: Settings) -> None:
    settings = make_settings(auth_max_failed_attempts=3, auth_login_rate_limit=100)
    client, container = build_client(settings)
    with client:
        client.post("/api/v1/auth/register", json=register_payload())

        # 3 failed attempts
        for _ in range(3):
            res = client.post(
                "/api/v1/auth/login",
                json={"email": "maria@ejemplo.com", "password": "wrong-password"},
            )
            assert res.status_code == 401

        # 4th attempt: account should be locked (403 Forbidden)
        locked_res = client.post(
            "/api/v1/auth/login",
            json={"email": "maria@ejemplo.com", "password": "contraseñaSegura"},
        )
        assert locked_res.status_code == 403
        assert locked_res.json()["error"]["code"] == "forbidden"
        assert "locked" in locked_res.json()["error"]["message"].lower()


def test_password_history_recorded_on_registration(settings: Settings) -> None:
    client, container = build_client(settings)
    with client:
        res = client.post("/api/v1/auth/register", json=register_payload())
        assert res.status_code == 201
        user_id = res.json()["user"]["id"]

        history = container.auth_service._repository.password_history.get(user_id)
        assert history is not None
        assert len(history) == 1


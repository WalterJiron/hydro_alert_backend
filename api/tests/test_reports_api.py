from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.bootstrap.app_factory import create_app
from app.core.config import Settings
from tests.conftest import make_settings
from tests.fakes import FakeContainer, build_fake_container

from tests.test_auth_api import (
    CEDULA_ONE,
    CEDULA_TWO,
    build_client,
    register_payload,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"hydroalert-test-photo"


def register(client: TestClient, **overrides: object) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json=register_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def report_form(**overrides: object) -> dict[str, object]:
    form: dict[str, object] = {
        "category": "flood",
        "description": "Calle inundada frente a la escuela.",
        "latitude": "12.136389",
        "longitude": "-86.251389",
    }
    form.update(overrides)
    return form


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_creating_a_report_requires_a_valid_token(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        missing = client.post("/api/v1/reports", data=report_form())
        invalid = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers=auth("hl_invalid-token"),
        )
        wrong_scheme = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers={"Authorization": "Token hl_invalid-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_token"
    assert "message" in missing.json()
    assert invalid.status_code == 401
    assert wrong_scheme.status_code == 401


def test_reports_endpoints_work_without_api_prefix(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        created = client.post(
            "/reports",
            data=report_form(),
            headers=auth(token),
        )
        active = client.get("/reports/active")

    assert created.status_code == 201
    assert active.status_code == 200
    assert len(active.json()["data"]) == 1
    client, _ = build_client(settings)
    with client:
        missing = client.post("/api/v1/reports", data=report_form())
        invalid = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers=auth("hl_invalid-token"),
        )
        wrong_scheme = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers={"Authorization": "Token hl_invalid-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_token"
    assert invalid.status_code == 401
    assert wrong_scheme.status_code == 401


def test_create_and_read_public_report_without_photo(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        created = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers=auth(token),
        )
        active = client.get("/api/v1/reports/active")

    assert created.status_code == 201
    body = created.json()
    assert body["id"].startswith("rep_")
    assert body["category"] == "flood"
    assert body["description"] == "Calle inundada frente a la escuela."
    assert body["latitude"] == 12.136389
    assert body["longitude"] == -86.251389
    assert body["photoUrl"] is None
    assert body["createdAt"].endswith("Z")
    assert datetime.fromisoformat(body["createdAt"]).tzinfo is not None
    assert "cedula" not in created.text
    assert "user" not in body

    assert active.status_code == 200
    assert active.json() == {"data": [body]}


def test_create_report_with_png_and_serve_photo(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        created = client.post(
            "/api/v1/reports",
            data=report_form(category="fallen_tree"),
            files={"photo": ("tree.png", PNG_BYTES, "image/png")},
            headers=auth(token),
        )
        body = created.json()
        photo = client.get(body["photoUrl"])

    assert created.status_code == 201
    assert body["photoUrl"] == f"/api/v1/reports/photos/{body['id']}"
    assert photo.status_code == 200
    assert photo.content == PNG_BYTES
    assert photo.headers["content-type"] == "image/png"


def test_absolute_photo_url_uses_public_base(settings: Settings) -> None:
    settings = make_settings(
        public_api_base_url="https://cdn.ejemplo.com/api/v1"
    )
    client, _ = build_client(settings)
    with client:
        token = register(client)
        created = client.post(
            "/api/v1/reports",
            data=report_form(),
            files={"photo": ("tree.png", PNG_BYTES, "image/png")},
            headers=auth(token),
        )

    assert created.status_code == 201
    assert created.json()["photoUrl"] == (
        "https://cdn.ejemplo.com/api/v1/reports/"
        f"photos/{created.json()['id']}"
    )


def test_unsupported_photo_is_rejected(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        response = client.post(
            "/api/v1/reports",
            data=report_form(),
            files={"photo": ("fake.gif", b"GIF89a-not-allowed", "image/gif")},
            headers=auth(token),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_photo"


def test_photo_over_five_megabytes_returns_413(settings: Settings) -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (5_242_880 + 1)
    client, _ = build_client(settings)
    with client:
        token = register(client)
        response = client.post(
            "/api/v1/reports",
            data=report_form(),
            files={"photo": ("big.png", oversized, "image/png")},
            headers=auth(token),
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "photo_too_large"


def test_invalid_report_fields_are_rejected(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        bad_category = client.post(
            "/api/v1/reports",
            data=report_form(category="meteor"),
            headers=auth(token),
        )
        short_description = client.post(
            "/api/v1/reports",
            data=report_form(description="corto"),
            headers=auth(token),
        )
        long_description = client.post(
            "/api/v1/reports",
            data=report_form(description="x" * 501),
            headers=auth(token),
        )
        bad_latitude = client.post(
            "/api/v1/reports",
            data=report_form(latitude="91"),
            headers=auth(token),
        )
        missing_fields = client.post(
            "/api/v1/reports",
            data={"category": "flood"},
            headers=auth(token),
        )

    assert bad_category.status_code == 422
    assert bad_category.json()["error"]["code"] == "invalid_report"
    assert short_description.status_code == 422
    assert short_description.json()["error"]["code"] == "invalid_report"
    assert long_description.status_code == 422
    assert bad_latitude.status_code == 422
    assert missing_fields.status_code == 422


def test_active_reports_are_newest_first_and_capped(settings: Settings) -> None:
    settings = make_settings(reports_max_active=2)
    client, _ = build_client(settings)
    with client:
        token = register(client)
        ids = []
        for category in ("flood", "fire", "landslide"):
            created = client.post(
                "/api/v1/reports",
                data=report_form(
                    category=category,
                    description=f"Reporte comunitario de {category}.",
                ),
                headers=auth(token),
            )
            assert created.status_code == 201
            ids.append(created.json()["id"])

        active = client.get("/api/v1/reports/active")

    data = active.json()["data"]
    assert len(data) == 2
    assert [item["id"] for item in data] == [ids[2], ids[1]]


def test_only_the_author_can_delete_a_report(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        owner = register(client)
        other = register(
            client,
            email="otra@ejemplo.com",
            cedula=CEDULA_TWO,
        )
        created = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers=auth(owner),
        )
        report_id = created.json()["id"]

        forbidden = client.delete(
            f"/api/v1/reports/{report_id}",
            headers=auth(other),
        )
        deleted = client.delete(
            f"/api/v1/reports/{report_id}",
            headers=auth(owner),
        )
        active = client.get("/api/v1/reports/active")
        deleted_again = client.delete(
            f"/api/v1/reports/{report_id}",
            headers=auth(owner),
        )

    assert forbidden.status_code == 403
    assert deleted.status_code == 204
    assert active.json() == {"data": []}
    assert deleted_again.status_code == 404


def test_deleting_requires_a_token(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        response = client.delete("/api/v1/reports/rep_unknown")

    assert response.status_code == 401


def test_a_second_account_uses_a_different_cedula(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        register(client)
        second = client.post(
            "/api/v1/auth/register",
            json=register_payload(
                email="segunda@ejemplo.com",
                cedula=CEDULA_TWO,
            ),
        )

    assert second.status_code == 201

from fastapi.testclient import TestClient

from app.bootstrap.app_factory import create_app
from app.core.config import Settings
from tests.conftest import make_settings
from tests.fakes import FakeContainer, build_fake_container


def build_client(
    settings: Settings,
    *,
    events=(),
) -> tuple[TestClient, FakeContainer]:
    container = build_fake_container(settings, events=events)
    app = create_app(settings, container_factory=lambda _: container)
    return TestClient(app), container


def test_liveness(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_paginated_history(settings: Settings, sample_events) -> None:
    client, _ = build_client(settings, events=sample_events)
    with client:
        response = client.get("/api/v1/seismic-events?page=1&page_size=2")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["items"][0]["pais"] == "El Salvador"
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 3,
        "total_pages": 2,
        "has_next": True,
        "has_previous": False,
    }


def test_date_and_magnitude_filters(settings: Settings, sample_events) -> None:
    client, _ = build_client(settings, events=sample_events)
    with client:
        by_date = client.get(
            "/api/v1/seismic-events?from_date=2026-11-08&to_date=2026-11-08"
        )
        by_magnitude = client.get("/api/v1/seismic-events?min_magnitude=3.0")

    assert by_date.status_code == 200
    assert by_date.json()["pagination"]["total"] == 2
    assert by_magnitude.status_code == 200
    assert by_magnitude.json()["pagination"]["total"] == 2


def test_invalid_date_range(settings: Settings, sample_events) -> None:
    client, _ = build_client(settings, events=sample_events)
    with client:
        response = client.get(
            "/api/v1/seismic-events?from_date=2026-11-09&to_date=2026-11-08"
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_query"


def test_detail_and_not_found(settings: Settings, sample_events) -> None:
    event = sample_events[0]
    client, _ = build_client(settings, events=sample_events)
    with client:
        found = client.get(f"/api/v1/seismic-events/{event.id}")
        missing = client.get("/api/v1/seismic-events/00000000-0000-0000-0000-000000000000")

    assert found.status_code == 200
    assert found.json()["id"] == str(event.id)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_health_endpoint(settings: Settings, sample_events) -> None:
    client, _ = build_client(settings, events=sample_events)
    with client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"]["status"] == "ok"
    assert payload["realtime"]["connected_clients"] == 0


def test_health_degraded_when_database_fails(settings: Settings) -> None:
    client, container = build_client(settings)
    container.repository.fail_ping = True
    with client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"]["status"] == "error"

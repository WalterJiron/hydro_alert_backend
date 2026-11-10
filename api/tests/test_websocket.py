from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bootstrap.app_factory import create_app
from app.core.config import Settings
from tests.conftest import make_settings
from tests.fakes import FakeContainer, build_fake_container, make_event


def build_websocket_app(
    settings: Settings,
    *,
    events=(),
) -> tuple[FastAPI, FakeContainer]:
    container = build_fake_container(settings, events=events)
    app = create_app(settings, container_factory=lambda _: container)
    new_event = make_event(
        day=6,
        hour=7,
        minute=15,
        latitude=11.111,
        longitude=-86.222,
        magnitude=4.8,
        location="Nuevo evento de prueba, Nicaragua",
    )

    @app.post("/__test__/broadcast")
    async def broadcast() -> dict[str, bool]:
        await container.publisher.publish_new([new_event])
        return {"ok": True}

    @app.post("/__test__/broadcast-update")
    async def broadcast_update() -> dict[str, bool]:
        revised = make_event(
            day=6,
            hour=7,
            minute=15,
            latitude=11.111,
            longitude=-86.222,
            magnitude=5.0,
            location="Evento revisado de prueba, Nicaragua",
        )
        await container.publisher.publish_updated([revised])
        return {"ok": True}

    @app.get("/__test__/connection-count")
    async def connection_count() -> dict[str, int]:
        return {"count": await container.connection_manager.connection_count()}

    return app, container


def receive_initial_messages(websocket) -> tuple[dict, dict]:
    established = websocket.receive_json()
    initial = websocket.receive_json()
    return established, initial


def test_connection_protocol_ping_and_invalid_message(
    settings: Settings,
    sample_events,
) -> None:
    app, _ = build_websocket_app(settings, events=sample_events)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/seismic-events") as websocket:
            established, initial = receive_initial_messages(websocket)

            assert established["type"] == "connection.established"
            assert established["status"] == "ok"
            assert established["data"]["client_id"]
            assert established["data"]["protocol_version"] == "1.0"
            assert established["timestamp"]

            assert initial["type"] == "seismic.events.initial"
            assert initial["status"] == "ok"
            assert initial["data"]["count"] == 3
            assert len(initial["data"]["items"]) == 3

            websocket.send_json({"type": "ping"})
            pong = websocket.receive_json()
            assert pong["type"] == "connection.pong"
            assert pong["status"] == "ok"

            websocket.send_text("not-json")
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["status"] == "error"
            assert error["error"]["code"] == "invalid_message"


def test_new_event_is_broadcast_to_multiple_clients(
    settings: Settings,
    sample_events,
) -> None:
    app, _ = build_websocket_app(settings, events=sample_events)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/seismic-events") as first:
            receive_initial_messages(first)
            with client.websocket_connect("/ws/seismic-events") as second:
                receive_initial_messages(second)

                response = client.post("/__test__/broadcast")
                first_message = first.receive_json()
                second_message = second.receive_json()

                assert response.status_code == 200
                assert first_message["type"] == "seismic.event.new"
                assert second_message["type"] == "seismic.event.new"
                assert first_message["data"]["magnitude"] == 4.8
                assert first_message["data"]["pais"] == "Nicaragua"
                assert (
                    second_message["data"]["location"]
                    == "Nuevo evento de prueba, Nicaragua"
                )
                assert second_message["data"]["pais"] == "Nicaragua"


def test_one_client_disconnect_does_not_affect_others(
    settings: Settings,
    sample_events,
) -> None:
    app, _ = build_websocket_app(settings, events=sample_events)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/seismic-events") as survivor:
            receive_initial_messages(survivor)

            with client.websocket_connect("/ws/seismic-events") as leaving:
                receive_initial_messages(leaving)

            client.post("/__test__/broadcast")
            message = survivor.receive_json()
            assert message["type"] == "seismic.event.new"

        count = client.get("/__test__/connection-count")
        assert count.json()["count"] == 0


def test_initial_events_failure_does_not_close_connection(
    settings: Settings,
) -> None:
    app, container = build_websocket_app(settings)
    container.repository.fail_list_recent = True

    with TestClient(app) as client:
        with client.websocket_connect("/ws/seismic-events") as websocket:
            established = websocket.receive_json()
            assert established["type"] == "connection.established"

            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["error"]["code"] == "initial_events_unavailable"

            websocket.send_json({"type": "ping"})
            assert websocket.receive_json()["type"] == "connection.pong"


def test_updated_event_message(settings: Settings, sample_events) -> None:
    app, _ = build_websocket_app(settings, events=sample_events)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/seismic-events") as websocket:
            receive_initial_messages(websocket)
            client.post("/__test__/broadcast-update")
            message = websocket.receive_json()

    assert message["type"] == "seismic.event.updated"
    assert message["data"]["magnitude"] == 5.0
    assert message["data"]["pais"] == "Nicaragua"

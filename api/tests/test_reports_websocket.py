from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.bootstrap.app_factory import create_app
from app.core.config import Settings
from app.core.time import utc_now
from app.realtime.domain.events import RealtimeChannel
from tests.conftest import make_settings
from tests.fakes import build_fake_container, make_event
from tests.test_auth_api import build_client, register_payload
from tests.test_reports_api import auth, register, report_form

WS_URL = "/api/v1/ws"


def test_connection_ready_and_heartbeat(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        with client.websocket_connect(
            f"{WS_URL}?channels=reports,notifications"
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["event"] == "connection.ready"
            assert ready["id"] == "evt_000000000000"
            assert ready["occurredAt"]
            assert ready["data"]["connectionId"].startswith("conn_")
            assert ready["data"]["channels"] == ["reports", "notifications"]
            assert ready["data"]["resumed"] is True
            assert ready["data"]["serverTime"]

            websocket.send_json(
                {"action": "ping", "sentAt": "2026-11-08T15:30:00Z"}
            )
            pong = websocket.receive_json()
            assert pong["event"] == "pong"
            assert pong["occurredAt"]
            assert pong["data"]["serverTime"]
            assert "id" not in pong

            websocket.send_text("not-json")
            error = websocket.receive_json()
            assert error["event"] == "error"
            assert error["data"]["code"] == "invalid_message"
            assert error["data"]["retryable"] is True


def test_reports_websocket_alias_at_root_ws(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        with client.websocket_connect("/ws?channels=reports") as websocket:
            ready = websocket.receive_json()
            assert ready["event"] == "connection.ready"
            assert ready["data"]["channels"] == ["reports"]


def test_missing_channels_is_rejected(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        with client.websocket_connect(WS_URL) as websocket:
            error = websocket.receive_json()
            assert error["event"] == "error"
            assert error["data"]["code"] == "invalid_channels"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_unknown_channel_is_rejected(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        with client.websocket_connect(
            f"{WS_URL}?channels=reports,weather"
        ) as websocket:
            error = websocket.receive_json()
            assert error["data"]["code"] == "invalid_channels"


def test_malformed_last_event_id_is_rejected(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        with client.websocket_connect(
            f"{WS_URL}?channels=reports&lastEventId=not-an-event"
        ) as websocket:
            error = websocket.receive_json()
            assert error["event"] == "error"
            assert error["data"]["code"] == "invalid_last_event_id"


def test_created_report_is_broadcast(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        with client.websocket_connect(
            f"{WS_URL}?channels=reports,notifications"
        ) as websocket:
            websocket.receive_json()

            created = client.post(
                "/api/v1/reports",
                data=report_form(),
                headers=auth(token),
            )
            event = websocket.receive_json()

    assert created.status_code == 201
    report = created.json()
    assert event["event"] == "report.created"
    assert event["id"].startswith("evt_")
    assert event["occurredAt"]
    assert event["data"] == report


def test_deleted_report_is_broadcast(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        created = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers=auth(token),
        )
        report_id = created.json()["id"]

        with client.websocket_connect(
            f"{WS_URL}?channels=reports"
        ) as websocket:
            websocket.receive_json()
            deleted = client.delete(
                f"/api/v1/reports/{report_id}",
                headers=auth(token),
            )
            event = websocket.receive_json()

    assert deleted.status_code == 204
    assert event["event"] == "report.deleted"
    assert event["data"] == {"id": report_id}


def test_resume_replays_events_after_last_event_id(settings: Settings) -> None:
    client, container = build_client(settings)
    with client:
        token = register(client)
        first = client.post(
            "/api/v1/reports",
            data=report_form(),
            headers=auth(token),
        ).json()
        second = client.post(
            "/api/v1/reports",
            data=report_form(
                category="fire",
                description="Incendio controlado en el mercado central.",
            ),
            headers=auth(token),
        ).json()

        stored = list(container.realtime_events.events)
        assert len(stored) == 2

        with client.websocket_connect(
            f"{WS_URL}?channels=reports&lastEventId={stored[0].id}"
        ) as websocket:
            ready = websocket.receive_json()
            replayed = websocket.receive_json()

            assert ready["data"]["resumed"] is True
            assert ready["id"] == stored[0].id
            assert replayed["event"] == "report.created"
            assert replayed["id"] == stored[1].id
            assert replayed["data"] == second

            websocket.send_json({"action": "ping"})
            assert websocket.receive_json()["event"] == "pong"

    assert first["id"] != second["id"]


def test_unknown_last_event_id_disables_resume(settings: Settings) -> None:
    client, _ = build_client(settings)
    with client:
        token = register(client)
        with client.websocket_connect(
            f"{WS_URL}?channels=reports&lastEventId=evt_999999999999"
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["event"] == "connection.ready"
            assert ready["data"]["resumed"] is False

            client.post(
                "/api/v1/reports",
                data=report_form(),
                headers=auth(token),
            )
            event = websocket.receive_json()
            assert event["event"] == "report.created"


def test_emergency_notification_is_broadcast(settings: Settings) -> None:
    settings = make_settings(emergency_max_event_age_seconds=86_400)
    container = build_fake_container(settings)
    app = create_app(settings, container_factory=lambda _: container)

    @app.post("/__test__/strong-quake")
    async def strong_quake() -> dict[str, bool]:
        quake = replace(
            make_event(
                magnitude=6.1,
                location="12 Km al sur de Managua, Nicaragua",
            ),
            event_at=utc_now(),
        )
        await container.seismic_fanout.publish_new([quake])
        return {"ok": True}

    with TestClient(app) as client:
        with client.websocket_connect(
            f"{WS_URL}?channels=notifications"
        ) as websocket:
            websocket.receive_json()
            client.post("/__test__/strong-quake")
            event = websocket.receive_json()

    assert event["event"] == "notification.created"
    assert event["id"].startswith("evt_")
    data = event["data"]
    assert data["type"] == "emergency"
    assert data["priority"] == "critical"
    assert data["magnitude"] == 6.1
    assert data["title"]
    assert data["body"]
    assert data["eventId"].startswith("ineter_")
    assert data["sentTime"]


def test_old_notifications_are_not_replayed(settings: Settings) -> None:
    client, container = build_client(settings)

    import asyncio

    asyncio.run(
        container.realtime_events.append(
            channel=RealtimeChannel.NOTIFICATIONS,
            event="notification.created",
            occurred_at=utc_now() - timedelta(minutes=10),
            data={"type": "emergency", "title": "Alerta antigua"},
        )
    )

    with client:
        with client.websocket_connect(
            f"{WS_URL}?channels=reports,notifications&lastEventId=evt_000000000000"
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["data"]["resumed"] is True

            websocket.send_json({"action": "ping"})
            # The only thing after ready must be the pong: the old emergency
            # notification was filtered out of the replay window.
            assert websocket.receive_json()["event"] == "pong"


def test_emergency_notification_filtering(settings: Settings) -> None:
    settings = make_settings(emergency_max_event_age_seconds=60)
    container = build_fake_container(settings)
    old = replace(
        make_event(magnitude=6.8, location="Viejo, Nicaragua"),
        event_at=utc_now() - timedelta(hours=2),
    )
    weak = replace(
        make_event(magnitude=4.2, location="Leve, Nicaragua"),
        event_at=utc_now(),
    )
    fresh = replace(
        make_event(magnitude=5.5, location="Fuerte, Nicaragua"),
        event_at=utc_now(),
    )

    import asyncio

    asyncio.run(
        container.notification_service.on_new_seismic_events([old, weak, fresh])
    )

    events = container.realtime_events.events
    assert len(events) == 1
    assert events[0].channel is RealtimeChannel.NOTIFICATIONS
    assert events[0].data["type"] == "emergency"
    assert events[0].data["magnitude"] == 5.5


def test_notifications_are_not_sent_to_reports_only_clients(
    settings: Settings,
) -> None:
    settings = make_settings(emergency_max_event_age_seconds=86_400)
    container = build_fake_container(settings)
    app = create_app(settings, container_factory=lambda _: container)

    @app.post("/__test__/strong-quake")
    async def strong_quake() -> dict[str, bool]:
        quake = replace(
            make_event(magnitude=6.3, location="Managua, Nicaragua"),
            event_at=utc_now(),
        )
        await container.seismic_fanout.publish_new([quake])
        return {"ok": True}

    with TestClient(app) as client:
        token = register(
            client,
            email="reportes@ejemplo.com",
            cedula="001-010190-0002A",
        )
        with client.websocket_connect(f"{WS_URL}?channels=reports") as websocket:
            websocket.receive_json()
            client.post("/__test__/strong-quake")
            client.post(
                "/api/v1/reports",
                data=report_form(),
                headers=auth(token),
            )
            event = websocket.receive_json()

    assert event["event"] == "report.created"

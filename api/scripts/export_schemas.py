"""Export the public response schemas from the Pydantic models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure 'app' is importable when executed directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from app.auth.presentation.schemas import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
)
from app.realtime.domain.events import (
    EmergencyNotificationData,
    RealtimeEventEnvelope,
)
from app.realtime.domain.messages import WebSocketEnvelope
from app.realtime.presentation.schemas import (
    ConnectionReadyEnvelope,
    ReportsErrorEnvelope,
    ReportsPongEnvelope,
)
from app.reports.presentation.schemas import ActiveReportsResponse, ReportView
from app.seismic.presentation.schemas import (
    PaginatedSeismicEventsResponse,
    SeismicEventView,
)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"

SCHEMAS: dict[str, type[BaseModel]] = {
    "seismic-event.schema.json": SeismicEventView,
    "paginated-seismic-events.schema.json": PaginatedSeismicEventsResponse,
    "websocket-envelope.schema.json": WebSocketEnvelope,
    "auth-register-request.schema.json": RegisterRequest,
    "auth-login-request.schema.json": LoginRequest,
    "auth-response.schema.json": AuthResponse,
    "report.schema.json": ReportView,
    "active-reports.schema.json": ActiveReportsResponse,
    "realtime-event.schema.json": RealtimeEventEnvelope,
    "realtime-connection-ready.schema.json": ConnectionReadyEnvelope,
    "realtime-pong.schema.json": ReportsPongEnvelope,
    "realtime-error.schema.json": ReportsErrorEnvelope,
    "emergency-notification.schema.json": EmergencyNotificationData,
}


def export_schemas(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    """Write one JSON Schema file per public response model."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, model in SCHEMAS.items():
        path = output_dir / filename
        schema = model.model_json_schema()
        path.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main() -> None:
    for path in export_schemas():
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

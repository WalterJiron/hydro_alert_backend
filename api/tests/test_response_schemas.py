import json
from pathlib import Path

from scripts.export_schemas import OUTPUT_DIR, SCHEMAS


def test_exported_json_schemas_are_current() -> None:
    for filename, model in SCHEMAS.items():
        path = OUTPUT_DIR / filename
        assert path.is_file(), f"missing generated schema: {path}"

        checked_in = json.loads(path.read_text(encoding="utf-8"))
        assert checked_in == model.model_json_schema(), (
            f"{filename} is outdated; run python -m scripts.export_schemas"
        )


def test_event_schema_documents_country_field() -> None:
    schema = json.loads(
        (OUTPUT_DIR / "seismic-event.schema.json").read_text(encoding="utf-8")
    )

    assert "pais" in schema["properties"]
    assert schema["properties"]["pais"]["description"]
    assert schema["properties"]["pais"]["examples"] == ["El Salvador"]

import pytest

from app.seismic.domain.countries import extract_country


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (
            "67 Km al suroeste de La Libertad, El Salvador",
            "El Salvador",
        ),
        (
            "24 Km al noreste de Cuilapa, Guatemala",
            "Guatemala",
        ),
        (
            "53 Km al suroeste de Mechapa, Chinandega, Nicaragua",
            "Nicaragua",
        ),
        (
            "53 Km al noroeste de Rosario, Costa Rica",
            "Costa Rica",
        ),
        (
            "19 Km al norte de La Ceiba, Honduras",
            "Honduras",
        ),
        (
            "104 Km al oeste de El Gancho México",
            "México",
        ),
        (
            "106 Km al suroeste de El Gancho Mexico",
            "México",
        ),
        (
            "1 Km al sur de Huehuete, Nicaragua ",
            "Nicaragua",
        ),
        (
            "4 Km al sur de Desembocadura de Río Chiriqui Viejo, Panamá",
            "Panamá",
        ),
        (
            "10 Km al sur de Punta Gorda, Belize",
            "Belice",
        ),
    ],
)
def test_extracts_country_from_location(location: str, expected: str) -> None:
    assert extract_country(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        None,
        "",
        "   ",
        "67 Km al suroeste de La Libertad",
        "Lugar sin país identificable",
        "100 Km al oeste de Costa Ricana",
    ],
)
def test_unknown_or_missing_country_returns_none(location: str | None) -> None:
    assert extract_country(location) is None

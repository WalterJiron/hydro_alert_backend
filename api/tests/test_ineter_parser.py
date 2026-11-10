from datetime import date, time

from app.seismic.infrastructure.ineter_parser import IneterHtmlParser


def test_parses_controlled_ineter_fixture(ineter_html: str) -> None:
    result = IneterHtmlParser().parse(ineter_html)

    assert result.candidates == 5
    assert result.skipped == 1
    assert len(result.events) == 4
    assert result.warnings

    first = result.events[0]
    assert first.event_date == date(2026, 11, 8)
    assert first.event_time == time(20, 26, 5)
    assert first.event_at.isoformat() == "2026-11-09T02:26:05+00:00"
    assert first.latitude == 12.934
    assert first.longitude == -89.573
    assert first.depth_km == 23.0
    assert first.magnitude == 3.1
    assert first.location == "67 Km al suroeste de La Libertad, El Salvador"
    assert first.pais == "El Salvador"
    assert first.status == "C"

    missing_location = result.events[1]
    assert missing_location.location is None
    assert missing_location.pais is None
    assert missing_location.status == "C"

    missing_numbers = result.events[2]
    assert missing_numbers.depth_km is None
    assert missing_numbers.magnitude is None
    assert missing_numbers.status == "A"
    assert missing_numbers.location == (
        "53 Km al suroeste de Mechapa, Chinandega, Nicaragua"
    )
    assert missing_numbers.pais == "Nicaragua"

    without_status = result.events[3]
    assert without_status.status is None
    assert without_status.location == "55 Km al suroeste de Jiquilillo, Nicaragua"
    assert without_status.pais == "Nicaragua"


def test_decodes_html_entities() -> None:
    html = """
    <a href="javascript:ver_mapa(1,8.293,-82.690);"><PRE>
    26/11/07 07:58:14  8.293 -82.690  21 3.4
    <span class='estiloC'>C</span>
    4 Km al sur de Desembocadura de R&iacute;o Chiriqui Viejo, Panam&aacute;
    </PRE></a>
    """
    result = IneterHtmlParser().parse(html)

    assert len(result.events) == 1
    assert result.events[0].location == (
        "4 Km al sur de Desembocadura de Río Chiriqui Viejo, Panamá"
    )
    assert result.events[0].pais == "Panamá"


def test_parses_country_without_comma() -> None:
    html = """
    <a href="javascript:ver_mapa(1,14.459,-93.213);"><PRE>
    26/11/08 09:26:38 14.459 -93.213 5 3.9
    <span class='estiloC'>C</span> 104 Km al oeste de El Gancho México
    </PRE></a>
    """
    result = IneterHtmlParser().parse(html)

    assert len(result.events) == 1
    assert result.events[0].location == "104 Km al oeste de El Gancho México"
    assert result.events[0].pais == "México"


def test_unexpected_page_returns_no_candidates() -> None:
    result = IneterHtmlParser().parse("<html><body><p>Mantenimiento</p></body></html>")

    assert result.events == ()
    assert result.candidates == 0
    assert result.skipped == 0


def test_candidate_with_invalid_date_is_skipped() -> None:
    html = """
    <a href="javascript:ver_mapa(1,12.0,-87.0);">
      <PRE>26/13/40 99:99:99 12.0 -87.0 10 3.0</PRE>
    </a>
    """
    result = IneterHtmlParser().parse(html)

    assert result.candidates == 1
    assert result.skipped == 1
    assert result.events == ()

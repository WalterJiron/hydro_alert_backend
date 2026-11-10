"""Country extraction for INETER free-text locations.

INETER publishes the country as the last part of the location string, usually
after a comma, but sometimes without one (for example ``El Gancho México``).
The source text is preserved in ``location`` and this module derives a
canonical ``pais`` value for structured responses and filtering.
"""

from __future__ import annotations

import unicodedata

KNOWN_COUNTRIES: tuple[str, ...] = (
    "Belice",
    "Colombia",
    "Costa Rica",
    "Cuba",
    "Ecuador",
    "El Salvador",
    "Estados Unidos",
    "Guatemala",
    "Haití",
    "Honduras",
    "Jamaica",
    "México",
    "Nicaragua",
    "Panamá",
    "Puerto Rico",
    "República Dominicana",
    "Venezuela",
)

_COUNTRY_ALIASES: dict[str, str] = {
    "belize": "Belice",
    "ee uu": "Estados Unidos",
    "ee. uu": "Estados Unidos",
    "ee.uu": "Estados Unidos",
    "eeuu": "Estados Unidos",
    "estados unidos de america": "Estados Unidos",
    "usa": "Estados Unidos",
}


def _normalize(value: str) -> str:
    """Lowercase and remove accents so source variants match consistently."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return without_accents.casefold()


def _build_suffixes() -> tuple[tuple[str, str], ...]:
    by_normalized: dict[str, str] = {
        _normalize(country): country for country in KNOWN_COUNTRIES
    }
    by_normalized.update(
        {
            _normalize(alias): country
            for alias, country in _COUNTRY_ALIASES.items()
        }
    )
    return tuple(
        sorted(by_normalized.items(), key=lambda item: len(item[0]), reverse=True)
    )


_COUNTRY_SUFFIXES = _build_suffixes()


def extract_country(location: str | None) -> str | None:
    """Return the canonical country at the end of a location, if recognized.

    Matching is accent- and case-insensitive. A suffix only counts when it is
    preceded by a boundary (whitespace, comma, or the start of the string), so
    place names that merely contain a country name are not misclassified.
    """
    if location is None:
        return None

    normalized = _normalize(location).strip(" \t\r\n,.;:!?")
    if not normalized:
        return None

    for suffix, country in _COUNTRY_SUFFIXES:
        if not normalized.endswith(suffix):
            continue

        prefix = normalized[: -len(suffix)]
        if prefix and (prefix[-1].isalnum() or prefix[-1] == "_"):
            continue
        return country

    return None

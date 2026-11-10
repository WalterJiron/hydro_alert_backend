"""Validation rules for registration and login payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.core.errors import InvalidRegistrationError
from app.core.time import utc_now

MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 80
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
MAX_EMAIL_LENGTH = 254

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# Official Nicaraguan identifier: 3-digit municipality, 6-digit birth date
# (DDMMYY), 4-digit sequence and one check letter. Hyphens are optional so a
# value typed without separators is still accepted as-is.
_CEDULA_RE = re.compile(
    r"^(?P<municipality>\d{3})-?(?P<birth>\d{6})-?(?P<sequence>\d{4})"
    r"(?P<letter>[A-Za-z])$"
)


@dataclass(frozen=True, slots=True)
class ValidatedRegistration:
    name: str
    email: str
    password: str
    cedula: str
    cedula_normalized: str


def validate_registration(
    *,
    name: str,
    email: str,
    password: str,
    cedula: str,
) -> ValidatedRegistration:
    """Validate every registration field and return normalized values."""
    clean_name = _validate_name(name)
    clean_email = normalize_email(email)
    _validate_password(password)
    canonical_cedula, normalized_cedula = normalize_cedula(cedula)
    return ValidatedRegistration(
        name=clean_name,
        email=clean_email,
        password=password,
        cedula=canonical_cedula,
        cedula_normalized=normalized_cedula,
    )


def _validate_name(raw: str) -> str:
    if not isinstance(raw, str):
        raise InvalidRegistrationError("Name is required.")
    name = raw.strip()
    if len(name) < MIN_NAME_LENGTH:
        raise InvalidRegistrationError(
            f"Name must be at least {MIN_NAME_LENGTH} characters."
        )
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidRegistrationError(
            f"Name cannot exceed {MAX_NAME_LENGTH} characters."
        )
    return name


def normalize_email(raw: str) -> str:
    if not isinstance(raw, str):
        raise InvalidRegistrationError("Email is required.")
    email = raw.strip().lower()
    if not email or len(email) > MAX_EMAIL_LENGTH or not _EMAIL_RE.fullmatch(email):
        raise InvalidRegistrationError("Email format is invalid.")
    return email


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not password.strip():
        raise InvalidRegistrationError("Password is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidRegistrationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidRegistrationError(
            f"Password cannot exceed {MAX_PASSWORD_LENGTH} characters."
        )


def normalize_cedula(raw: str) -> tuple[str, str]:
    """Return the canonical display value and a separator-free unique key."""
    if not isinstance(raw, str):
        raise InvalidRegistrationError("Cédula is required.")
    candidate = raw.strip()
    if not candidate:
        raise InvalidRegistrationError("Cédula is required.")

    match = _CEDULA_RE.fullmatch(candidate)
    if match is None:
        raise InvalidRegistrationError(
            "Cédula must match the official Nicaraguan format "
            "(000-000000-0000A)."
        )

    birth = match.group("birth")
    day = int(birth[0:2])
    month = int(birth[2:4])
    two_digit_year = int(birth[4:6])
    current_year = utc_now().year
    year = (
        1900 + two_digit_year
        if two_digit_year > current_year % 100
        else 2000 + two_digit_year
    )
    try:
        birth_date = date(year, month, day)
    except ValueError as exc:
        raise InvalidRegistrationError(
            "Birth date included in cédula is invalid."
        ) from exc
    if birth_date > utc_now().date() or year < 1900:
        raise InvalidRegistrationError(
            "Birth date included in cédula is invalid."
        )

    municipality = match.group("municipality")
    sequence = match.group("sequence")
    letter = match.group("letter").upper()
    canonical = f"{municipality}-{birth}-{sequence}{letter}"
    normalized = f"{municipality}{birth}{sequence}{letter}"
    return canonical, normalized

"""Domain entities for community report accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class User:
    """A registered reporter with ISO 27001 security & audit fields.

    ``cedula_normalized`` is persisted only for uniqueness and identity
    association. It is never serialized by any presentation layer.
    """

    id: str
    name: str
    email: str
    cedula_normalized: str
    password_hash: str
    created_at: datetime
    updated_at: datetime | None = None
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    password_changed_at: datetime | None = None
    is_active: bool = True

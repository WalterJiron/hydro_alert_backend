from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.domain.entities import User
from app.auth.domain.security import hash_password, hash_token
from app.auth.infrastructure.repository import SqlAlchemyAuthRepository
from app.core.errors import (
    CedulaAlreadyRegisteredError,
    EmailAlreadyRegisteredError,
    PersistenceError,
)
from app.core.time import utc_now
from app.reports.domain.entities import Report, ReportCategory, ReportPhoto
from app.reports.infrastructure.repository import SqlAlchemyReportRepository

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"postgres-photo"


def make_user(
    *,
    email: str = "maria@ejemplo.com",
    cedula: str = "0011001860001Z",
    user_id: str = "usr_postgres_0001",
) -> User:
    return User(
        id=user_id,
        name="María López",
        email=email,
        cedula_normalized=cedula,
        password_hash=hash_password("contraseñaSegura"),
        created_at=utc_now(),
    )


def make_report(
    *,
    report_id: str,
    user_id: str,
    category: ReportCategory = ReportCategory.FLOOD,
    created_at: datetime | None = None,
) -> Report:
    return Report(
        id=report_id,
        user_id=user_id,
        category=category,
        description=f"Reporte comunitario {report_id}.",
        latitude=12.136389,
        longitude=-86.251389,
        created_at=created_at or utc_now(),
    )


@pytest.mark.asyncio
async def test_auth_repository_users_and_tokens(postgres_session_factory) -> None:
    repository = SqlAlchemyAuthRepository(postgres_session_factory)
    user = make_user()

    created = await repository.create_user(user)
    assert created == user

    by_email = await repository.find_by_email("maria@ejemplo.com")
    assert by_email is not None
    assert by_email.id == user.id
    assert by_email.cedula_normalized == "0011001860001Z"

    by_cedula = await repository.find_by_cedula("0011001860001Z")
    assert by_cedula is not None
    assert by_cedula.email == "maria@ejemplo.com"

    assert await repository.find_by_email("nadie@ejemplo.com") is None
    assert await repository.find_by_cedula("9999999999999Z") is None

    token = "hl_test-token"
    await repository.create_token(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=utc_now(),
        expires_at=utc_now() + timedelta(days=30),
    )
    authenticated = await repository.find_by_token_hash(hash_token(token))
    assert authenticated is not None
    assert authenticated.id == user.id
    assert await repository.find_by_token_hash(hash_token("hl_other")) is None


@pytest.mark.asyncio
async def test_auth_repository_maps_unique_violations(
    postgres_session_factory,
) -> None:
    repository = SqlAlchemyAuthRepository(postgres_session_factory)
    await repository.create_user(make_user())

    with pytest.raises(EmailAlreadyRegisteredError):
        await repository.create_user(
            make_user(
                user_id="usr_postgres_0002",
                cedula="0010101900002A",
            )
        )

    with pytest.raises(CedulaAlreadyRegisteredError):
        await repository.create_user(
            make_user(
                user_id="usr_postgres_0003",
                email="otra@ejemplo.com",
            )
        )


@pytest.mark.asyncio
async def test_report_repository_photos_and_active_listing(
    postgres_session_factory,
) -> None:
    auth_repository = SqlAlchemyAuthRepository(postgres_session_factory)
    user = await auth_repository.create_user(make_user())
    repository = SqlAlchemyReportRepository(postgres_session_factory)

    older = make_report(
        report_id="rep_postgres_0001",
        user_id=user.id,
        created_at=utc_now() - timedelta(minutes=5),
    )
    newer = Report(
        id="rep_postgres_0002",
        user_id=user.id,
        category=ReportCategory.FIRE,
        description="Reporte comunitario rep_postgres_0002.",
        latitude=12.136389,
        longitude=-86.251389,
        created_at=utc_now(),
        photo_url="https://qqncbiiqtqpoitzfzvwj.supabase.co/storage/v1/object/public/Imagenes/reports/rep_postgres_0002.png",
    )
    await repository.create(older)
    await repository.create(newer)

    active = await repository.list_active(limit=100)
    assert [report.id for report in active] == [newer.id, older.id]
    assert active[0].has_photo is True
    assert active[1].has_photo is False

    stored = await repository.get_active(newer.id)
    assert stored is not None
    assert stored.category is ReportCategory.FIRE
    assert stored.photo_url == newer.photo_url

    deleted = await repository.deactivate(older.id, utc_now())
    assert deleted is not None
    assert deleted.deleted_at is not None
    assert await repository.get_active(older.id) is None
    assert await repository.deactivate(older.id, utc_now()) is None
    assert [report.id for report in await repository.list_active(100)] == [
        newer.id
    ]


@pytest.mark.asyncio
async def test_report_repository_enforces_foreign_key(
    postgres_session_factory,
) -> None:
    repository = SqlAlchemyReportRepository(postgres_session_factory)
    with pytest.raises(PersistenceError):
        await repository.create(
            make_report(
                report_id="rep_postgres_orphan",
                user_id="usr_missing",
            )
        )

    # The failed insert must not leave a half-written row behind.
    assert await repository.get_active("rep_postgres_orphan") is None

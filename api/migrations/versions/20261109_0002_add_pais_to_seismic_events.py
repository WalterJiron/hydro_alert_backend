"""Add the country column and backfill it from stored locations.

Revision ID: 20261109_0002
Revises: 20261108_0001
Create Date: 2026-11-09 00:00:00

The country is the last part of the INETER location string. The raw location
is kept unchanged; ``pais`` is a structured, canonical extraction useful for
responses and filters. Existing rows are backfilled during the migration so
the first synchronization cycle does not emit updates only for this field.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261109_0002"
down_revision: Union[str, None] = "20261108_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "seismic_events",
        sa.Column("pais", sa.String(length=64), nullable=True),
    )

    from app.seismic.domain.countries import extract_country

    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, location FROM seismic_events "
                "WHERE location IS NOT NULL AND pais IS NULL"
            )
        )
        .mappings()
        .all()
    )
    updates: list[dict[str, object]] = []
    for row in rows:
        pais = extract_country(row["location"])
        if pais is not None:
            updates.append({"id": row["id"], "pais": pais})
    if updates:
        bind.execute(
            sa.text(
                "UPDATE seismic_events SET pais = :pais WHERE id = :id"
            ),
            updates,
        )


def downgrade() -> None:
    op.drop_column("seismic_events", "pais")

"""Phase 13.9: tenant_id retrofit for legacy tables.

Adds ``tenant_id`` (default ``'default'``) to every legacy table from
Phase 11 and earlier that did not yet carry the column:

  - jobs
  - applications
  - applicant_profile
  - bullet_pool
  - qa_bank

The server default backfills existing rows. New rows continue to
default to ``'default'`` until Phase 18 lights up real multi-tenancy.

Per D026, this turns D020's discipline ("every new table from Phase 12
onward carries ``tenant_id``") into a schema-level guarantee before
Phase 14 begins. Existing query paths are intentionally NOT forced to
filter on ``tenant_id`` -- they keep today's global-read behavior --
but every new Phase 14+ code path must thread an explicit tenant
context.

Revision ID: d8a5c2f1e9b3
Revises: c7d3a91b4e2f
Create Date: 2026-05-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8a5c2f1e9b3"
down_revision: str | Sequence[str] | None = "c7d3a91b4e2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TENANT_DEFAULT = sa.text("'default'")
_LEGACY_TABLES: tuple[str, ...] = (
    "jobs",
    "applications",
    "applicant_profile",
    "bullet_pool",
    "qa_bank",
)


def upgrade() -> None:
    for table in _LEGACY_TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                nullable=False,
                server_default=_TENANT_DEFAULT,
            ),
        )


def downgrade() -> None:
    for table in _LEGACY_TABLES:
        op.drop_column(table, "tenant_id")

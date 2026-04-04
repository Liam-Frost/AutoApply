"""Add missing tracking columns to jobs and applications.

Revision ID: b2f9f1c5d3a4
Revises: 0412f55aac77
Create Date: 2026-04-03 23:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2f9f1c5d3a4"
down_revision: str | Sequence[str] | None = "0412f55aac77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("jobs", sa.Column("source_id", sa.String(length=200), nullable=True))
    op.create_index(op.f("ix_jobs_source_id"), "jobs", ["source_id"], unique=False)

    op.add_column(
        "applications",
        sa.Column(
            "state_history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("applications", sa.Column("fields_filled", sa.Integer(), nullable=True))
    op.add_column("applications", sa.Column("fields_total", sa.Integer(), nullable=True))
    op.add_column(
        "applications",
        sa.Column(
            "files_uploaded",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "applications",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "applications",
        sa.Column("outcome_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("applications", "outcome_updated_at")
    op.drop_column("applications", "updated_at")
    op.drop_column("applications", "files_uploaded")
    op.drop_column("applications", "fields_total")
    op.drop_column("applications", "fields_filled")
    op.drop_column("applications", "state_history")

    op.drop_index(op.f("ix_jobs_source_id"), table_name="jobs")
    op.drop_column("jobs", "source_id")

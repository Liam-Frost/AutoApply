"""Phase 15.1: source_resumes table.

Stores uploaded original resumes as first-class source artifacts --
distinct from the user's profile YAML (which is the *evidence* pool)
and from generated outputs in ``resume_versions``. A source resume is
the editable thing the user uploaded; Phase 15.2 patches it in
``docx`` mode, and Phase 15.5's materials router decides whether to
patch this row or fall back to a LaTeX template package.

Columns:

* ``source_type`` -- ``docx`` / ``latex`` / ``pdf``. PDF imports feed
  *fact extraction only* (per D024); they are not editable.
* ``editable`` -- BOOL. True for ``docx`` and ``latex``; False for
  ``pdf``. Materials router consults this to short-circuit to
  ``generate_from_template`` when the requested source is not
  editable.
* ``checksum`` -- SHA256 of the uploaded bytes. Re-uploading the same
  file is detected via ``(tenant_id, checksum)`` unique.
* ``storage_path`` -- relative path under ``data/source_resumes/``
  resolved at runtime through ``src.core.config.PROJECT_ROOT``. No
  absolute paths cross the API boundary (mirrors D013 for templates).
* ``extracted_structure`` -- best-effort JSON snapshot of sections /
  bullets parsed from the original. For DOCX we read paragraph
  styles; for LaTeX we record section command positions; for PDF we
  record headings extracted by the existing resume_importer.

Per D026: ``tenant_id`` is required from day one.

Revision ID: a3b9d52e7c41
Revises: f2c5d83a91b6
Create Date: 2026-05-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3b9d52e7c41"
down_revision: str | Sequence[str] | None = "f2c5d83a91b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    op.create_table(
        "source_resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("original_filename", sa.String(length=400), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=400), nullable=False),
        sa.Column(
            "extracted_structure",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_resumes"),
        sa.UniqueConstraint(
            "tenant_id", "checksum", name="uq_source_resumes_tenant_checksum"
        ),
        sa.CheckConstraint(
            "source_type IN ('docx', 'latex', 'pdf')",
            name="ck_source_resumes_source_type",
        ),
    )
    op.create_index(
        "ix_source_resumes_tenant_type",
        "source_resumes",
        ["tenant_id", "source_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_resumes_tenant_type", table_name="source_resumes")
    op.drop_table("source_resumes")

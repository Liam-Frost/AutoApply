"""Phase 17.8: user_documents table (Document Library).

First-class, user-facing document library. Distinct from
``source_resumes`` (an internal Phase 15.1 artifact used only by the
materials router). Every row in ``user_documents`` is one of:

* ``origin='uploaded'`` -- the user uploaded the file via the
  /api/documents/upload endpoint or during profile creation.
* ``origin='profile_import'`` -- created as a side effect of
  /api/profile/upload-resume.
* ``origin='generated_promoted'`` -- the user promoted a generated
  material (resume / cover letter) into the library so they can use
  it as a base for future generations.

Columns:

* ``document_type`` -- ``resume`` / ``cover_letter``.
* ``source_type`` -- ``docx`` / ``latex`` / ``pdf`` / ``txt``. PDF is
  not editable (D024 carries over from source_resumes).
* ``editable`` -- BOOL. False for ``pdf``, True otherwise. The
  materials router consults this to short-circuit to
  ``generate_from_template`` when patching would fail.
* ``origin`` -- provenance enum (see above).
* ``display_name`` -- user-facing label, distinct from
  ``original_filename`` so renames don't break checksum dedup.
* ``checksum`` -- SHA256 of the bytes. Unique per
  (tenant_id, document_type, checksum) so the same DOCX can live as
  both a resume and a cover letter base if a user does that, but
  re-uploading the same file as the same type is a no-op.
* ``storage_path`` -- relative path under
  ``data/user_documents/<tenant>/<document_type>/`` resolved through
  ``PROJECT_ROOT`` (mirrors D013).
* ``source_application_id`` -- nullable FK to ``applications.id``,
  set when ``origin='generated_promoted'``. Lets us walk back to "I
  generated this for the Stripe role".
* ``source_job_snapshot_id`` -- nullable JD snapshot id, paired with
  ``source_application_id`` for the same provenance.

Per D026: ``tenant_id`` is required from day one.

Revision ID: e7c3a5b91f48
Revises: c9e1f3a7b8d4
Create Date: 2026-05-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c3a5b91f48"
down_revision: str | Sequence[str] | None = "c9e1f3a7b8d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    op.create_table(
        "user_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "origin",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'uploaded'"),
        ),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("original_filename", sa.String(length=400), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=400), nullable=False),
        sa.Column(
            "extracted_structure",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "source_application_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "source_job_snapshot_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_user_documents"),
        sa.ForeignKeyConstraint(
            ["source_application_id"],
            ["applications.id"],
            name="fk_user_documents_application",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_type",
            "checksum",
            name="uq_user_documents_tenant_type_checksum",
        ),
        sa.CheckConstraint(
            "document_type IN ('resume', 'cover_letter')",
            name="ck_user_documents_document_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('docx', 'latex', 'pdf', 'txt')",
            name="ck_user_documents_source_type",
        ),
        sa.CheckConstraint(
            "origin IN ('uploaded', 'profile_import', 'generated_promoted')",
            name="ck_user_documents_origin",
        ),
    )
    op.create_index(
        "ix_user_documents_tenant_type_created",
        "user_documents",
        ["tenant_id", "document_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_documents_tenant_type_created", table_name="user_documents"
    )
    op.drop_table("user_documents")

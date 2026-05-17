"""Phase 17.2: review_queue table.

The batch run that prepares reviewable applications. Phase 17.1's
``plan_run`` orchestrator generates materials and queues the
``application.prepare`` task; the prepare task's body (wired in 17.3 +
later) creates one row here per ready-to-review job. The operator's
approve / reject decision moves the row through the state machine:

    pending → approved → submitted
            ↓             ↘
            rejected       stale (Phase 17.5 pre-submit gate)
            ↑
            stale  (via "refresh materials" UI button)

Columns:

* ``tenant_id``         -- Phase 13.9 multi-tenant retrofit.
* ``job_id`` / ``job_snapshot_id`` -- Phase 13 audit binding (nullable;
  intentionally NOT a FK so a row stays visible to the operator even
  after the underlying ``jobs`` / ``job_snapshots`` rows are purged
  by retention. ``company`` + ``title`` are denormalised on the row
  itself so the kanban renders without joining.
* ``run_id``            -- groups entries from the same plan_run for
  the 17.6 morning digest. Free-form to avoid yet-another FK; the
  orchestrator emits UUID4 strings.
* ``materials_path``    -- where the resume / cover-letter artifacts
  live (relative project path; the 17.3 popover serves previews
  through ``/api/artifacts/download``).
* ``score_breakdown``   -- Phase 16.1 ``ScoreBreakdown.to_dict()``
  snapshot so the "Why was this surfaced?" tooltip doesn't have to
  re-score.
* ``company`` / ``title`` -- denormalised for the kanban card; cheaper
  than joining ``jobs`` on every list query.
* ``status``            -- ``pending`` | ``approved`` | ``submitted`` |
  ``rejected`` | ``stale``. CHECK constrained at the DB level so a
  rogue UPDATE can't write a typo.
* ``decision``          -- audit field; what the operator clicked
  ("approve" / "reject" / "submit" / "refresh" / "stale"). Distinct
  from ``status`` because ``status`` reflects current state while
  ``decision`` records the last action.
* ``reason``            -- operator's free-text rationale.
* ``reviewer``          -- who acted (email / username). Phase 18 auth
  will fill this from the session.

Indexes target the kanban board query "all pending entries for tenant
X ordered by created_at DESC" + the digest's "all entries from this
run_id" lookup. The unique constraint enforces "one pending entry per
(tenant, job, snapshot)" so the orchestrator's idempotency check
fires at the DB level too.

Revision ID: b7d9a1e4f3c2
Revises: a3b9d52e7c41
Create Date: 2026-05-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d9a1e4f3c2"
down_revision: str | Sequence[str] | None = "a3b9d52e7c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    op.create_table(
        "review_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            nullable=False,
            server_default=_TENANT_DEFAULT,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("materials_path", sa.String(length=400), nullable=True),
        sa.Column(
            "score_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer", sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_review_queue"),
        sa.UniqueConstraint(
            "tenant_id",
            "job_id",
            "job_snapshot_id",
            "status",
            name="uq_review_queue_pending_per_snapshot",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'submitted', 'rejected', 'stale')",
            name="ck_review_queue_status",
        ),
    )
    op.create_index(
        "ix_review_queue_tenant_status_created",
        "review_queue",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_review_queue_job",
        "review_queue",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_queue_run_id",
        "review_queue",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_review_queue_run_id", table_name="review_queue")
    op.drop_index("ix_review_queue_job", table_name="review_queue")
    op.drop_index(
        "ix_review_queue_tenant_status_created", table_name="review_queue"
    )
    op.drop_table("review_queue")

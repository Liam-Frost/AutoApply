"""Phase 17.2 codex fix: narrow review_queue uniqueness to pending rows.

The original ``uq_review_queue_pending_per_snapshot`` constraint
applied to ALL statuses, not just pending. That caused a benign-
looking issue to ferment across multiple nightly runs:

  Run 1: insert (t, j, s, status='pending') → approve → submit → row
         is now (t, j, s, 'submitted').
  Run 2: insert (t, j, s, status='pending') -- OK because no other
         pending row exists.
  Run 2 approve → tries to UPDATE to (t, j, s, 'approved') -- OK if
         no other approved row exists. But once submitted, the UPDATE
         to ``submitted`` collides with Run 1's row at the unique
         constraint and the operator's submit click hits an
         IntegrityError.

The fix is a **partial unique index** scoped to ``status = 'pending'``.
That preserves the orchestrator's "one pending row per snapshot"
idempotency without blocking downstream lifecycle transitions across
multiple runs. PostgreSQL supports partial indexes natively
(``CREATE UNIQUE INDEX ... WHERE``), so this migration replaces the
table-level UNIQUE with a partial unique index.

Revision ID: c9e1f3a7b8d4
Revises: b7d9a1e4f3c2
Create Date: 2026-05-16 08:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9e1f3a7b8d4"
down_revision: str | Sequence[str] | None = "b7d9a1e4f3c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PARTIAL_INDEX_NAME = "ux_review_queue_pending_per_snapshot"
_OLD_CONSTRAINT = "uq_review_queue_pending_per_snapshot"


def upgrade() -> None:
    # Drop the table-level UNIQUE introduced in b7d9a1e4f3c2.
    op.drop_constraint(_OLD_CONSTRAINT, "review_queue", type_="unique")
    # Re-add as a partial unique index so the "one pending row per
    # snapshot" rule only fires while a row IS pending.
    op.create_index(
        _PARTIAL_INDEX_NAME,
        "review_queue",
        ["tenant_id", "job_id", "job_snapshot_id"],
        unique=True,
        postgresql_where="status = 'pending'",
    )


def downgrade() -> None:
    op.drop_index(_PARTIAL_INDEX_NAME, table_name="review_queue")
    op.create_unique_constraint(
        _OLD_CONSTRAINT,
        "review_queue",
        ["tenant_id", "job_id", "job_snapshot_id", "status"],
    )

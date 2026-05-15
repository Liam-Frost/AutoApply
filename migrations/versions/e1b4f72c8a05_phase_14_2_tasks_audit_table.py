"""Phase 14.2: durable tasks audit table.

Celery's result backend is treated as transient (results expire in 1
day; a worker bouncing can lose state). The authoritative record of
"which tasks existed, who created them, how many times they retried,
what they produced" lives in this Postgres table. Celery signals
(:func:`task_prerun_handler`, :func:`task_postrun_handler`,
:func:`task_failure_handler`, :func:`task_retry_handler`) keep this
table in sync.

Columns:

  * ``celery_task_id`` -- Celery's UUID for this enqueue. Indexed for
    ``autoapply tasks inspect <id>``.
  * ``idempotency_key`` -- caller-supplied; the AutoApplyTask base
    class short-circuits if a row with this key already reached a
    terminal status. ``(tenant_id, idempotency_key)`` is unique.
  * ``status`` -- ``queued / running / waiting_human / succeeded /
    failed / cancelled``. ``waiting_human`` is the parking lot for
    HITL (Phase 14.4); a worker is released as soon as the row
    transitions into it.
  * ``parent_task_id`` -- if a task spawned a child via the agent
    boundary's allow-listed enqueue tool, this points to the parent
    row.
  * ``trace_id`` -- links to the Phase 8.3 trace store entry for
    drill-down.
  * ``payload`` -- JSON snapshot of the enqueue args; Pydantic models
    are responsible for validating shape (Phase 14.6 task definitions).
  * ``last_error`` -- short stacktrace summary; the full trace lives
    in :attr:`trace_id`.

Per D026 / D020: ``tenant_id`` is required from day one.

Revision ID: e1b4f72c8a05
Revises: d8a5c2f1e9b3
Create Date: 2026-05-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1b4f72c8a05"
down_revision: str | Sequence[str] | None = "d8a5c2f1e9b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("queue", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "parent_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", name="fk_tasks_parent", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_tasks_tenant_idempotency_key"
        ),
    )
    op.create_index("ix_tasks_celery_task_id", "tasks", ["celery_task_id"], unique=False)
    op.create_index(
        "ix_tasks_tenant_status",
        "tasks",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )
    op.create_index("ix_tasks_kind", "tasks", ["tenant_id", "kind"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_kind", table_name="tasks")
    op.drop_index("ix_tasks_tenant_status", table_name="tasks")
    op.drop_index("ix_tasks_celery_task_id", table_name="tasks")
    op.drop_table("tasks")

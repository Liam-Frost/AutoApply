"""Phase 14.4: HITL gate queue table.

Replaces the single-process file backend (``data/agent_gate/*.json``)
with a Postgres-backed approval queue that lives alongside the Phase
14.2 ``tasks`` audit table. The two tables are linked via
``gate_queue.task_id`` so the trace viewer (Phase 14.9) can walk from
a paused task to the human decision and back.

Status lifecycle::

    pending → approved → submitted
    pending → rejected
    pending → expired      (TTL elapsed without decision)

The expired status is reserved for the optional sweep job (Phase 14.5
maintenance cron); it is not used by the gate API itself.

Per D026: when a worker returns ``needs_human``, the AutoApplyTask
base class flips the task's audit row to ``waiting_human`` AND
inserts a ``pending`` row here. The worker is released immediately;
the user's approval at ``/api/gate/{id}/approve`` enqueues a ``resume``
task under the original idempotency key.

Revision ID: f2c5d83a91b6
Revises: e1b4f72c8a05
Create Date: 2026-05-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2c5d83a91b6"
down_revision: str | Sequence[str] | None = "e1b4f72c8a05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    op.create_table(
        "gate_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", name="fk_gate_queue_task", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=120), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_gate_queue"),
    )
    op.create_index(
        "ix_gate_queue_tenant_status",
        "gate_queue",
        ["tenant_id", "status", "requested_at"],
        unique=False,
    )
    op.create_index("ix_gate_queue_task", "gate_queue", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_gate_queue_task", table_name="gate_queue")
    op.drop_index("ix_gate_queue_tenant_status", table_name="gate_queue")
    op.drop_table("gate_queue")

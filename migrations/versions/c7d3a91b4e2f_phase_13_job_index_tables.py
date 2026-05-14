"""Phase 13.1: Job Index & Freshness Engine tables.

Adds:
  - job_postings: stable entity per (source, source_id) -- the "thing applied to"
  - job_snapshots: immutable content-versioned snapshot of a posting (content_hash)
  - search_queries: normalized search condition + freshness metadata
  - search_results: many-to-many between a query and the postings it returned
  - refresh_tasks: priority queue consumed by the Phase 14 scheduler
  - applications.job_snapshot_id: audit binding back to the exact JD applied against

Every new table carries `tenant_id` (default "default" until Phase 18). See D020.

Revision ID: c7d3a91b4e2f
Revises: b2f9f1c5d3a4
Create Date: 2026-05-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d3a91b4e2f"
down_revision: str | Sequence[str] | None = "b2f9f1c5d3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TENANT_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column(
            "latest_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "source", "source_id", name="uq_job_postings_tenant_source"
        ),
    )
    op.create_index(
        "ix_job_postings_tenant_state",
        "job_postings",
        ["tenant_id", "state"],
    )
    op.create_index(
        "ix_job_postings_company",
        "job_postings",
        ["tenant_id", "company"],
    )

    op.create_table(
        "job_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column(
            "posting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", name="fk_job_snapshots_posting"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("employment_type", sa.String(length=50), nullable=True),
        sa.Column("seniority", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("application_url", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "posting_id", "content_hash", name="uq_job_snapshots_posting_hash"
        ),
    )
    op.create_index(
        "ix_job_snapshots_posting_scraped",
        "job_snapshots",
        ["posting_id", "scraped_at"],
    )

    op.create_foreign_key(
        "fk_job_postings_latest_snapshot",
        "job_postings",
        "job_snapshots",
        ["latest_snapshot_id"],
        ["id"],
        use_alter=True,
    )

    op.create_table(
        "search_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("normalized_key", sa.String(length=64), nullable=False),
        sa.Column("raw_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'fresh'"),
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_pages", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "source", "normalized_key", name="uq_search_queries_tenant_key"
        ),
    )
    op.create_index(
        "ix_search_queries_status",
        "search_queries",
        ["tenant_id", "status"],
    )

    op.create_table(
        "search_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column(
            "query_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_queries.id", name="fk_search_results_query", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "posting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", name="fk_search_results_posting", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "query_id", "posting_id", name="uq_search_results_query_posting"
        ),
    )
    op.create_index(
        "ix_search_results_query",
        "search_results",
        ["query_id"],
    )

    op.create_table(
        "refresh_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.String(length=64), nullable=False, server_default=_TENANT_DEFAULT
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "priority",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'normal'"),
        ),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_refresh_tasks_pending",
        "refresh_tasks",
        ["tenant_id", "status", "priority", "scheduled_for"],
    )

    op.add_column(
        "applications",
        sa.Column("job_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_applications_job_snapshot",
        "applications",
        "job_snapshots",
        ["job_snapshot_id"],
        ["id"],
    )
    op.create_index(
        "ix_applications_job_snapshot",
        "applications",
        ["job_snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_applications_job_snapshot", table_name="applications")
    op.drop_constraint("fk_applications_job_snapshot", "applications", type_="foreignkey")
    op.drop_column("applications", "job_snapshot_id")

    op.drop_index("ix_refresh_tasks_pending", table_name="refresh_tasks")
    op.drop_table("refresh_tasks")

    op.drop_index("ix_search_results_query", table_name="search_results")
    op.drop_table("search_results")

    op.drop_index("ix_search_queries_status", table_name="search_queries")
    op.drop_table("search_queries")

    op.drop_constraint(
        "fk_job_postings_latest_snapshot", "job_postings", type_="foreignkey"
    )
    op.drop_index("ix_job_snapshots_posting_scraped", table_name="job_snapshots")
    op.drop_table("job_snapshots")

    op.drop_index("ix_job_postings_company", table_name="job_postings")
    op.drop_index("ix_job_postings_tenant_state", table_name="job_postings")
    op.drop_table("job_postings")

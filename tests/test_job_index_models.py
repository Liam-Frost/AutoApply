"""Phase 13.1: smoke tests for the Job Index ORM mappings and migration metadata.

Heavyweight DB integration is exercised end-to-end by Phase 13.4+ tests against
a live Postgres; here we just confirm the declarative tables exist, the
expected columns are wired up, and the foreign keys point at the right
referents so an accidental edit to ``src/core/models.py`` fails loudly.
"""

from __future__ import annotations

import importlib

import pytest

models = importlib.import_module("src.core.models")


@pytest.mark.parametrize(
    ("cls_name", "table_name"),
    [
        ("JobPosting", "job_postings"),
        ("JobSnapshot", "job_snapshots"),
        ("SearchQuery", "search_queries"),
        ("SearchResult", "search_results"),
        ("RefreshTask", "refresh_tasks"),
    ],
)
def test_phase13_tables_registered(cls_name: str, table_name: str) -> None:
    cls = getattr(models, cls_name)
    assert cls.__tablename__ == table_name


def test_every_phase13_table_carries_tenant_id() -> None:
    for cls_name in ("JobPosting", "JobSnapshot", "SearchQuery", "SearchResult", "RefreshTask"):
        cls = getattr(models, cls_name)
        assert "tenant_id" in cls.__table__.columns, (
            f"{cls_name} must carry tenant_id (D020)"
        )
        assert cls.__table__.columns["tenant_id"].nullable is False


def test_job_snapshot_unique_per_content_hash() -> None:
    unique = {tuple(sorted(c.name for c in u.columns)) for u in models.JobSnapshot.__table__.constraints if hasattr(u, "columns") and (getattr(u, "name", None) or "").startswith("uq_")}
    assert ("content_hash", "posting_id") in {tuple(sorted(k)) for k in unique}


def test_application_has_snapshot_fk() -> None:
    col = models.Application.__table__.columns["job_snapshot_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "job_snapshots"
    assert col.nullable is True


def test_search_query_unique_per_tenant_source_key() -> None:
    unique = {
        tuple(sorted(c.name for c in u.columns))
        for u in models.SearchQuery.__table__.constraints
        if hasattr(u, "columns") and (getattr(u, "name", None) or "").startswith("uq_")
    }
    assert ("normalized_key", "source", "tenant_id") in {tuple(sorted(k)) for k in unique}

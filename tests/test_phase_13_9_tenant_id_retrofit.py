"""Phase 13.9: tenant_id retrofit migration smoke tests.

These guard the D026 invariant: every table reachable from
``Base.metadata`` carries a non-null ``tenant_id`` column. Phase 13.9
backfilled this onto the five legacy tables that pre-dated D020; this
test makes sure no later table sneaks in without it.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

models = importlib.import_module("src.core.models")
database = importlib.import_module("src.core.database")


_LEGACY_TABLES_RETROFITTED = (
    "Job",
    "Application",
    "ApplicantProfile",
    "BulletPool",
    "QABank",
)


@pytest.mark.parametrize("cls_name", _LEGACY_TABLES_RETROFITTED)
def test_legacy_table_carries_tenant_id(cls_name: str) -> None:
    cls = getattr(models, cls_name)
    columns = cls.__table__.columns
    assert "tenant_id" in columns, f"{cls_name} must carry tenant_id after Phase 13.9 (D026)"
    column = columns["tenant_id"]
    assert column.nullable is False
    assert column.default is not None and column.default.arg == models.TENANT_DEFAULT


def test_every_table_in_metadata_carries_tenant_id() -> None:
    """Catch-all: any future table must declare tenant_id from day one (D020 + D026)."""
    missing = [
        table.name
        for table in database.Base.metadata.tables.values()
        if "tenant_id" not in table.columns
    ]
    assert not missing, (
        f"tables missing tenant_id (D026 violation): {missing}. "
        "Every table reachable from Base.metadata must carry tenant_id."
    )


def test_phase_13_9_migration_file_exists() -> None:
    """The retrofit migration must be on disk so ``alembic upgrade`` picks it up."""
    versions = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    candidates = list(versions.glob("*phase_13_9_tenant_id_retrofit*.py"))
    assert candidates, "Phase 13.9 retrofit migration file missing under migrations/versions/"

    content = candidates[0].read_text(encoding="utf-8")
    # Revision must chain off the Phase 13 head (c7d3a91b4e2f).
    match = re.search(r"down_revision[^=]*=\s*['\"]([^'\"]+)['\"]", content)
    assert match is not None, "down_revision not declared in migration"
    assert match.group(1) == "c7d3a91b4e2f"

    # Migration must add tenant_id to all five legacy tables.
    for table in ("jobs", "applications", "applicant_profile", "bullet_pool", "qa_bank"):
        assert table in content, f"migration does not mention legacy table {table!r}"
    assert "tenant_id" in content

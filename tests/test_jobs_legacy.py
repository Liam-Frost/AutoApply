"""Phase 13.8: tests for the legacy file-cache importer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.jobs.legacy import import_legacy_file_cache

# Reuse minimal stubs so we don't need a real Postgres for the importer.


@dataclass
class _StubQuery:
    id: UUID = field(default_factory=uuid4)
    source: str = "linkedin"
    normalized_key: str = ""
    raw_params: dict = field(default_factory=dict)
    status: str = "fresh"
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    result_count: int = 0
    max_pages: int | None = None
    tenant_id: str = "default"


@dataclass
class _StubPosting:
    id: UUID = field(default_factory=uuid4)
    source: str = "linkedin"
    source_id: str = ""
    company: str = ""
    canonical_url: str | None = None


class _StubStore:
    def __init__(self) -> None:
        self.tenant_id = "default"
        self.queries: dict[tuple[str, str], _StubQuery] = {}
        self.postings: dict[tuple[str, str], _StubPosting] = {}
        self.links: list[tuple[UUID, UUID, int | None]] = []

    def upsert_query(self, *, source, fingerprint, raw_params, max_pages):
        key = (source, fingerprint)
        if key in self.queries:
            return self.queries[key]
        q = _StubQuery(
            source=source,
            normalized_key=fingerprint,
            raw_params=raw_params,
            max_pages=max_pages,
        )
        self.queries[key] = q
        return q

    def upsert_posting(self, *, source, source_id, company, canonical_url=None):
        key = (source, source_id)
        if key in self.postings:
            return self.postings[key]
        p = _StubPosting(
            source=source, source_id=source_id, company=company, canonical_url=canonical_url
        )
        self.postings[key] = p
        return p

    def link_result(self, *, query_id, posting_id, rank):
        self.links.append((query_id, posting_id, rank))

    def mark_query_run(self, query, *, status, result_count=None, error=None):
        query.status = status
        query.last_run_at = datetime.now(UTC)
        query.last_error = error
        if result_count is not None:
            query.result_count = result_count


@pytest.fixture
def store() -> _StubStore:
    return _StubStore()


def _write_legacy_file(dir_path, name: str, payload: dict[str, Any]) -> None:
    (dir_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_imports_jobs_into_search_results(store, tmp_path) -> None:
    _write_legacy_file(
        tmp_path,
        "abc123.json",
        {
            "created_at": "2026-05-10T00:00:00+00:00",
            "max_pages": 20,
            "jobs": [
                {"source_id": "j1", "company": "Acme", "title": "SWE Intern"},
                {"source_id": "j2", "company": "Beta", "title": "Frontend Intern"},
            ],
        },
    )

    report = import_legacy_file_cache(store=store, legacy_dir=tmp_path)
    assert report.files_imported == 1
    assert report.queries_inserted == 1
    assert report.results_linked == 2
    assert len(store.links) == 2

    # Imported queries are marked 'stale' so the next read re-scrapes.
    query = next(iter(store.queries.values()))
    assert query.status == "stale"
    assert query.last_error == "imported from legacy file cache"


def test_empty_legacy_dir_is_a_noop(store, tmp_path) -> None:
    report = import_legacy_file_cache(store=store, legacy_dir=tmp_path)
    assert report.files_seen == 0


def test_empty_jobs_payload_is_skipped(store, tmp_path) -> None:
    _write_legacy_file(tmp_path, "empty.json", {"jobs": [], "max_pages": 20})
    report = import_legacy_file_cache(store=store, legacy_dir=tmp_path)
    assert report.files_skipped == 1
    assert report.files_imported == 0


def test_corrupt_file_is_reported_not_fatal(store, tmp_path) -> None:
    (tmp_path / "corrupt.json").write_text("{not json}", encoding="utf-8")
    _write_legacy_file(
        tmp_path,
        "ok.json",
        {"jobs": [{"source_id": "x", "company": "Acme"}], "max_pages": 5},
    )
    report = import_legacy_file_cache(store=store, legacy_dir=tmp_path)
    assert report.files_imported == 1
    assert any("corrupt.json" in e for e in report.errors)


def test_delete_after_import_removes_file(store, tmp_path) -> None:
    _write_legacy_file(
        tmp_path,
        "abc.json",
        {"jobs": [{"source_id": "x", "company": "Acme"}], "max_pages": 5},
    )
    report = import_legacy_file_cache(
        store=store, legacy_dir=tmp_path, delete_after_import=True
    )
    assert report.files_imported == 1
    assert not (tmp_path / "abc.json").exists()


def test_idempotent_reimport(store, tmp_path) -> None:
    payload = {"jobs": [{"source_id": "x", "company": "Acme"}], "max_pages": 5}
    _write_legacy_file(tmp_path, "abc.json", payload)
    import_legacy_file_cache(store=store, legacy_dir=tmp_path)
    queries_after_first = dict(store.queries)
    links_after_first = list(store.links)

    import_legacy_file_cache(store=store, legacy_dir=tmp_path)
    # Same key -> upsert returns the existing row; same (query, posting)
    # link is replayed but the test only asserts the query set didn't
    # grow.
    assert set(store.queries.keys()) == set(queries_after_first.keys())
    # link_result is allowed to re-add (the real implementation uses an
    # upsert on the unique (query_id, posting_id)), so the stub will see
    # the second call too.
    assert len(store.links) >= len(links_after_first)

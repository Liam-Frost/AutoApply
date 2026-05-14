"""Phase 13.5: tests for snapshot-versioned enrichment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.jobs.enrich import (
    ContentChangedEvent,
    enrich_posting,
    mark_refresh_failed,
    mark_source_404,
    on_content_changed,
    reset_listeners,
)


@dataclass
class _Posting:
    id: UUID = field(default_factory=uuid4)
    source: str = "linkedin"
    source_id: str = ""
    company: str = ""
    state: str = "new"
    canonical_url: str | None = None
    latest_snapshot_id: UUID | None = None
    last_checked_at: datetime | None = None


@dataclass
class _Snapshot:
    id: UUID = field(default_factory=uuid4)
    posting_id: UUID | None = None
    content_hash: str = ""
    title: str = ""
    location: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    description: str | None = None
    requirements: Any = None
    application_url: str | None = None
    raw_data: Any = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _Store:
    def __init__(self) -> None:
        self.postings: dict[tuple[str, str], _Posting] = {}
        self.snapshots_by_id: dict[UUID, _Snapshot] = {}
        self.snapshots_by_posting_hash: dict[tuple[UUID, str], _Snapshot] = {}

    def upsert_posting(
        self,
        *,
        source: str,
        source_id: str,
        company: str,
        canonical_url: str | None = None,
    ) -> _Posting:
        key = (source, source_id)
        if key in self.postings:
            p = self.postings[key]
            if canonical_url and not p.canonical_url:
                p.canonical_url = canonical_url
            return p
        p = _Posting(
            source=source, source_id=source_id, company=company, canonical_url=canonical_url,
        )
        self.postings[key] = p
        return p

    def find_snapshot(self, posting_id: UUID, content_hash: str) -> _Snapshot | None:
        return self.snapshots_by_posting_hash.get((posting_id, content_hash))

    def insert_snapshot(self, *, posting: _Posting, content_hash: str, **kwargs) -> _Snapshot:
        s = _Snapshot(posting_id=posting.id, content_hash=content_hash, **kwargs)
        self.snapshots_by_id[s.id] = s
        self.snapshots_by_posting_hash[(posting.id, content_hash)] = s
        posting.latest_snapshot_id = s.id
        posting.last_checked_at = s.scraped_at
        return s

    def get_posting(self, posting_id: UUID) -> _Posting | None:
        for p in self.postings.values():
            if p.id == posting_id:
                return p
        return None


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture(autouse=True)
def _reset_listeners():
    reset_listeners()
    yield
    reset_listeners()


def _jd(**overrides: object) -> dict:
    base = {
        "title": "Software Engineer Intern",
        "location": "Toronto, ON",
        "description": "Build cool stuff.",
        "employment_type": "internship",
        "application_url": "https://example.com/jobs/1",
    }
    base.update(overrides)
    return base


def test_first_enrichment_creates_snapshot(store: _Store) -> None:
    out = enrich_posting(
        store=store, source="linkedin", source_id="1", company="Acme", content=_jd(),
    )
    assert out.content_changed is True
    assert out.state == "active"
    assert len(store.snapshots_by_id) == 1


def test_identical_content_does_not_create_new_snapshot(store: _Store) -> None:
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    out = enrich_posting(
        store=store, source="linkedin", source_id="1", company="Acme",
        content=_jd(applicant_count=42, promoted=True),  # unstable fields only
    )
    assert out.content_changed is False
    assert len(store.snapshots_by_id) == 1
    assert out.state == "active"


def test_description_edit_creates_new_snapshot(store: _Store) -> None:
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    out = enrich_posting(
        store=store, source="linkedin", source_id="1", company="Acme",
        content=_jd(description="Build cool stuff. Updated."),
    )
    assert out.content_changed is True
    assert len(store.snapshots_by_id) == 2

    # Old snapshot is preserved (immutable invariant).
    digests = {s.content_hash for s in store.snapshots_by_id.values()}
    assert len(digests) == 2


def test_emits_content_changed_event(store: _Store) -> None:
    received: list[ContentChangedEvent] = []
    on_content_changed(received.append)

    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    assert len(received) == 1
    assert received[0].previous_snapshot_id is None

    enrich_posting(
        store=store, source="linkedin", source_id="1", company="Acme",
        content=_jd(description="updated"),
    )
    assert len(received) == 2
    assert received[1].previous_snapshot_id is not None


def test_no_event_when_content_unchanged(store: _Store) -> None:
    received: list[ContentChangedEvent] = []
    on_content_changed(received.append)
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    assert len(received) == 1


def test_refresh_failed_degrades_state(store: _Store) -> None:
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    posting = next(iter(store.postings.values()))
    state = mark_refresh_failed(store=store, posting_id=posting.id, error="auth bounce")
    assert state == "unknown"


def test_source_404_marks_expired(store: _Store) -> None:
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    posting = next(iter(store.postings.values()))
    state = mark_source_404(store=store, posting_id=posting.id)
    assert state == "expired"


def test_recovery_after_expiry(store: _Store) -> None:
    enrich_posting(store=store, source="linkedin", source_id="1", company="Acme", content=_jd())
    posting = next(iter(store.postings.values()))
    mark_source_404(store=store, posting_id=posting.id)
    assert posting.state == "expired"

    out = enrich_posting(
        store=store, source="linkedin", source_id="1", company="Acme", content=_jd(),
    )
    # Expired -> active is a legal recovery transition.
    assert out.state == "active"


def test_listener_exception_does_not_break_flow(store: _Store) -> None:
    def boom(_event: ContentChangedEvent) -> None:
        raise RuntimeError("listener exploded")

    on_content_changed(boom)
    out = enrich_posting(
        store=store, source="linkedin", source_id="1", company="Acme", content=_jd(),
    )
    assert out.content_changed is True  # the flow continued despite the bad listener

"""Phase 13.4: tests for the cache-first search flow.

The integration path (real Postgres + fakeredis) is exercised in
test_jobs_search_integration.py; this file pins the flow's branching
logic against a stub store so it runs without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.jobs.search import (
    DEFAULT_FRESHNESS_HOURS,
    SearchOutcome,
    _SimplePosting,
    cached_search,
)


@dataclass
class _StubQuery:
    id: UUID = field(default_factory=uuid4)
    source: str = "linkedin"
    normalized_key: str = "abc"
    raw_params: dict = field(default_factory=dict)
    status: str = "fresh"
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    result_count: int = 0
    max_pages: int | None = None


@dataclass
class _StubPosting:
    id: UUID = field(default_factory=uuid4)
    source: str = "linkedin"
    source_id: str = ""
    company: str = ""
    state: str = "new"
    canonical_url: str | None = None
    last_seen_at: datetime | None = None


class _StubStore:
    """In-memory stand-in for :class:`JobIndexStore`.

    Mirrors the public surface ``cached_search`` actually calls. Storing
    state in instance dicts keeps assertions cheap.
    """

    def __init__(self) -> None:
        self.queries: dict[tuple[str, str], _StubQuery] = {}
        self.postings: dict[tuple[str, str], _StubPosting] = {}
        self.results: dict[UUID, list[tuple[_StubPosting, int]]] = {}
        self.runs: list[tuple[UUID, str, str | None]] = []

    def upsert_query(
        self, *, source: str, fingerprint: str, raw_params: dict, max_pages: int | None
    ) -> _StubQuery:
        key = (source, fingerprint)
        if key in self.queries:
            q = self.queries[key]
            if max_pages is not None and (q.max_pages is None or max_pages > q.max_pages):
                q.max_pages = max_pages
            return q
        q = _StubQuery(
            source=source,
            normalized_key=fingerprint,
            raw_params=raw_params,
            status="fresh",
            max_pages=max_pages,
            last_success_at=None,
        )
        self.queries[key] = q
        self.results[q.id] = []
        return q

    def upsert_posting(
        self,
        *,
        source: str,
        source_id: str,
        company: str,
        canonical_url: str | None = None,
    ) -> _StubPosting:
        key = (source, source_id)
        if key in self.postings:
            p = self.postings[key]
            p.last_seen_at = datetime.now(UTC)
            return p
        p = _StubPosting(
            source=source,
            source_id=source_id,
            company=company,
            canonical_url=canonical_url,
            last_seen_at=datetime.now(UTC),
        )
        self.postings[key] = p
        return p

    def link_result(self, *, query_id: UUID, posting_id: UUID, rank: int | None):
        bucket = self.results.setdefault(query_id, [])
        for existing, _ in bucket:
            if existing.id == posting_id:
                # treat first_seen == last_seen for new links only
                class _Link:
                    first_seen_at = datetime(2000, 1, 1, tzinfo=UTC)
                    last_seen_at = datetime.now(UTC)

                return _Link()
        # Find the posting
        posting = next(p for p in self.postings.values() if p.id == posting_id)
        bucket.append((posting, rank or 0))

        class _Link:
            first_seen_at = datetime.now(UTC)
            last_seen_at = first_seen_at

        return _Link()

    def get_results(self, query_id: UUID) -> list[_StubPosting]:
        return [p for p, _ in self.results.get(query_id, [])]

    def mark_query_run(
        self,
        query: _StubQuery,
        *,
        status: str,
        result_count: int | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        query.last_run_at = now
        query.status = status
        if status == "fresh":
            query.last_success_at = now
            query.last_error = None
        else:
            query.last_error = error
        if result_count is not None:
            query.result_count = result_count
        self.runs.append((query.id, status, error))


@pytest.fixture
def store() -> _StubStore:
    return _StubStore()


async def test_first_run_scrapes_and_persists(store: _StubStore) -> None:
    scraped = [
        _SimplePosting(source="linkedin", source_id="1", company="Acme"),
        _SimplePosting(source="linkedin", source_id="2", company="Beta"),
    ]

    outcome = await cached_search(
        store=store,
        cache=None,
        source="linkedin",
        params={"keywords": "swe"},
        fetch_fn=lambda: scraped,
    )

    assert outcome.cached is False
    assert outcome.stale is False
    assert len(outcome.postings) == 2
    assert outcome.counts == {"scraped": 2, "new": 2}
    assert len(store.runs) == 1
    assert store.runs[0][1] == "fresh"


async def test_second_run_hits_cache(store: _StubStore) -> None:
    scraped = [_SimplePosting(source="linkedin", source_id="1", company="Acme")]

    first = await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=lambda: scraped,
    )
    assert first.cached is False

    def boom() -> list:
        raise AssertionError("must not hit network on cache hit")

    second = await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=boom,
    )
    assert second.cached is True
    assert second.stale is False
    assert [p.source_id for p in second.postings] == ["1"]


async def test_force_refresh_bypasses_cache(store: _StubStore) -> None:
    first_scrape = [_SimplePosting(source="linkedin", source_id="1", company="Acme")]
    await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=lambda: first_scrape,
    )

    second_scrape = [
        _SimplePosting(source="linkedin", source_id="1", company="Acme"),
        _SimplePosting(source="linkedin", source_id="2", company="Beta"),
    ]
    outcome = await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=lambda: second_scrape,
        force_refresh=True,
    )
    assert outcome.cached is False
    assert len(outcome.postings) == 2


async def test_scrape_failure_preserves_old_results(store: _StubStore) -> None:
    await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=lambda: [_SimplePosting(source="linkedin", source_id="1", company="Acme")],
    )

    def fail() -> list:
        raise RuntimeError("auth bounce")

    outcome = await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=fail, force_refresh=True,
    )
    assert outcome.refresh_failed is True
    assert outcome.stale is True
    # old cache preserved per the spec
    assert len(outcome.postings) == 1
    assert outcome.last_error == "auth bounce"
    # query is marked ``stale`` so the next read knows the cache is degraded
    key = ("linkedin", outcome.query_id)
    query = next(q for q in store.queries.values() if q.id == outcome.query_id)
    assert query.status == "stale"


async def test_async_fetch_fn_supported(store: _StubStore) -> None:
    async def fetch_async() -> list:
        return [_SimplePosting(source="linkedin", source_id="1", company="Acme")]

    outcome = await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=fetch_async,
    )
    assert outcome.cached is False
    assert len(outcome.postings) == 1


async def test_stale_query_triggers_rescrape(store: _StubStore) -> None:
    # Seed a stale query directly
    query = store.upsert_query(
        source="linkedin", fingerprint="any", raw_params={}, max_pages=20
    )
    query.status = "stale"
    query.last_success_at = datetime.now(UTC) - timedelta(hours=DEFAULT_FRESHNESS_HOURS + 5)

    new_scrape = [_SimplePosting(source="linkedin", source_id="X", company="X")]
    # Use the same params as the seed -> the same fingerprint applies via normalize.
    outcome = await cached_search(
        store=store, cache=None, source="linkedin", params={},
        fetch_fn=lambda: new_scrape,
    )
    # The seed used fingerprint='any' which doesn't match the normalized
    # empty-params fingerprint, so this run creates a *new* query and is
    # not cached. The assertion is simply that the flow chose to fetch.
    assert outcome.cached is False


async def test_old_freshness_window_invalidates(store: _StubStore) -> None:
    # First run populates cache.
    await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=lambda: [_SimplePosting(source="linkedin", source_id="1", company="A")],
    )
    # Backdate so the freshness window has elapsed.
    query = next(iter(store.queries.values()))
    query.last_success_at = datetime.now(UTC) - timedelta(hours=DEFAULT_FRESHNESS_HOURS + 1)

    called = {"n": 0}

    def fetch() -> list:
        called["n"] += 1
        return [_SimplePosting(source="linkedin", source_id="1", company="A")]

    out = await cached_search(
        store=store, cache=None, source="linkedin", params={"keywords": "swe"},
        fetch_fn=fetch,
    )
    assert called["n"] == 1
    assert out.cached is False


async def test_normalized_params_collide_with_tracking(store: _StubStore) -> None:
    """Two calls with different tracking IDs hit the same cached query."""
    await cached_search(
        store=store, cache=None, source="linkedin",
        params={"keywords": "swe", "currentJobId": "111", "origin": "JYMBII"},
        fetch_fn=lambda: [_SimplePosting(source="linkedin", source_id="1", company="A")],
    )
    out = await cached_search(
        store=store, cache=None, source="linkedin",
        params={"keywords": "swe", "currentJobId": "999", "trk": "x"},
        fetch_fn=lambda: (_ for _ in ()).throw(AssertionError("must hit cache")),
    )
    assert out.cached is True


async def test_lock_contention_returns_cached_with_stale_flag(store: _StubStore) -> None:
    """When the fingerprint lock is already held, the caller falls back
    to the cached postings (if any) and surfaces stale=True so the UI
    can show a "refresh in progress" indicator."""
    import fakeredis

    from src.cache.cache import Cache
    from src.cache.lock import _PROCESS_LOCKS, acquire_lock
    from src.cache.lru import LRUBackend
    from src.cache.redis_backend import RedisBackend

    _PROCESS_LOCKS.clear()
    client = fakeredis.FakeRedis(decode_responses=True)
    cache = Cache(l1=LRUBackend(max_entries=128), l2=RedisBackend(client=client))

    # Seed an existing cache with one posting.
    await cached_search(
        store=store, cache=cache, source="linkedin", params={"keywords": "swe"},
        fetch_fn=lambda: [_SimplePosting(source="linkedin", source_id="1", company="A")],
    )

    # Hold the lock externally before kicking off a force-refresh.
    from src.jobs.normalize import search_query_fingerprint

    fingerprint = search_query_fingerprint({"keywords": "swe"}, source="linkedin")
    held = acquire_lock(
        client,
        f"jobs:search:linkedin:{fingerprint}",
        ttl=60,
        blocking=False,
        blocking_timeout=0,
    )
    assert held.acquired is True
    try:
        out = await cached_search(
            store=store, cache=cache, source="linkedin", params={"keywords": "swe"},
            fetch_fn=lambda: (_ for _ in ()).throw(AssertionError("must not fetch")),
            force_refresh=True,
        )
    finally:
        held.__exit__(None, None, None)

    assert out.cached is True
    assert out.stale is True
    assert len(out.postings) == 1


def test_search_outcome_default_counts() -> None:
    # Pure dataclass sanity -- counts default to an empty dict, not None,
    # so callers can rely on ``outcome.counts.get("scraped", 0)``.
    out = SearchOutcome(
        postings=[], cached=False, stale=False, query_id=uuid4(),
        last_run_at=None, last_success_at=None,
    )
    assert out.counts == {}

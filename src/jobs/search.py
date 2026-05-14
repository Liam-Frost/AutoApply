"""Phase 13.4: cache-first search flow with distributed lock.

The function :func:`cached_search` is the only thing intake callers (the
LinkedIn search wrapper, future ATS-wide search) should reach for. It
implements the documented Phase 13 behaviour:

  1. Normalize the incoming params and look up the matching ``SearchQuery``
     by (tenant_id, source, normalized_key).
  2. If the query exists, its ``status == "fresh"``, and the caller did
     not pass ``force_refresh=True``: return the cached postings without
     touching the network.
  3. Otherwise acquire a Phase 12 distributed lock on the fingerprint
     (so two concurrent submissions of the same search don't double-fetch),
     run the user-supplied ``fetch_fn``, persist the returned postings as
     ``search_results`` rows, and stamp ``last_run_at`` / ``status``.
  4. On scrape failure the *old* cached results are preserved -- the
     query's ``last_error`` is set and ``status`` flips to ``stale`` so
     the next read knows the cache is degraded, but
     ``cached_search(...).postings`` still returns the previous run's
     rows so the UI doesn't go blank during a LinkedIn auth bounce.

The function is intentionally framework-agnostic. ``fetch_fn`` can be
sync or async; the wrapper does not know about Playwright or httpx,
and unit tests stub it with a list literal.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Iterable, Protocol

from src.cache import Cache
from src.jobs.normalize import normalize_search_key, search_query_fingerprint
from src.jobs.store import JobIndexStore

logger = logging.getLogger("autoapply.jobs.search")

# How long a cache-first hit is considered "fresh" by default. Per-context
# overrides live in Phase 13.6; this value is the floor used when the
# query row alone is consulted.
DEFAULT_FRESHNESS_HOURS = 24

# Default lock TTL around a scrape. Larger than the typical LinkedIn
# search budget so a slow page doesn't get the lock yanked while the
# scrape is still in flight; smaller than the scheduler's task lease.
DEFAULT_LOCK_TTL_S = 600


class ScrapedPosting(Protocol):
    """Shape of an item ``fetch_fn`` is expected to return.

    Both the dataclass below and the existing ``intake.schema.RawJob``
    satisfy this protocol by attribute access.
    """

    source: str
    source_id: str
    company: str
    application_url: str | None


@dataclass
class _SimplePosting:
    source: str
    source_id: str
    company: str
    application_url: str | None = None


FetchFn = Callable[[], Iterable[ScrapedPosting] | Awaitable[Iterable[ScrapedPosting]]]


@dataclass
class SearchOutcome:
    """Result of a :func:`cached_search` call.

    ``postings`` is the list of ``JobPosting`` rows (cache hit or fresh).
    ``cached`` is True iff no network call happened. ``stale`` is True
    iff the most recent scrape failed and we're falling back to the
    previous run's rows. ``query_id`` is the persisted ``SearchQuery``
    UUID so the caller can refresh / drill in later.
    """

    postings: list[Any]
    cached: bool
    stale: bool
    query_id: Any
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None = None
    refresh_failed: bool = False
    counts: dict[str, int] = field(default_factory=dict)


async def cached_search(
    *,
    store: JobIndexStore,
    cache: Cache | None,
    source: str,
    params: dict[str, Any],
    fetch_fn: FetchFn,
    max_pages: int | None = None,
    force_refresh: bool = False,
    freshness_hours: int = DEFAULT_FRESHNESS_HOURS,
    lock_ttl: int = DEFAULT_LOCK_TTL_S,
    now: datetime | None = None,
) -> SearchOutcome:
    """Cache-first search. See module docstring for the contract."""
    now = now or datetime.now(UTC)
    normalized = normalize_search_key(params, source=source)
    fingerprint = search_query_fingerprint(params, source=source)
    query = store.upsert_query(
        source=source,
        fingerprint=fingerprint,
        raw_params=normalized,
        max_pages=max_pages,
    )

    cache_hit = _can_serve_from_cache(
        query=query,
        force_refresh=force_refresh,
        freshness_hours=freshness_hours,
        now=now,
    )
    if cache_hit:
        postings = store.get_results(query.id)
        logger.info(
            "Job index cache hit: source=%s key=%s n=%d", source, fingerprint[:12], len(postings),
        )
        return SearchOutcome(
            postings=postings,
            cached=True,
            stale=False,
            query_id=query.id,
            last_run_at=query.last_run_at,
            last_success_at=query.last_success_at,
            last_error=None,
            counts={"cached": len(postings)},
        )

    lock_key = f"jobs:search:{source}:{fingerprint}"
    cache_lock = cache.lock(lock_key, ttl=lock_ttl) if cache is not None else _NullLock()
    with cache_lock as handle:
        if cache is not None and not handle.acquired:
            # Somebody else is scraping the same query. Return whatever's
            # already cached and surface ``stale=True`` so the UI shows
            # a "refresh in progress" spinner.
            logger.info(
                "Job index lock contention: returning previous results for %s", fingerprint[:12]
            )
            postings = store.get_results(query.id)
            return SearchOutcome(
                postings=postings,
                cached=True,
                stale=True,
                query_id=query.id,
                last_run_at=query.last_run_at,
                last_success_at=query.last_success_at,
                last_error="another worker is refreshing this query",
                refresh_failed=False,
                counts={"cached": len(postings)},
            )

        # Re-check inside the lock: a concurrent writer may have
        # populated fresh results while we were waiting.
        if not force_refresh and _can_serve_from_cache(
            query=query,
            force_refresh=False,
            freshness_hours=freshness_hours,
            now=now,
        ):
            postings = store.get_results(query.id)
            return SearchOutcome(
                postings=postings,
                cached=True,
                stale=False,
                query_id=query.id,
                last_run_at=query.last_run_at,
                last_success_at=query.last_success_at,
                last_error=None,
                counts={"cached": len(postings)},
            )

        try:
            scraped = fetch_fn()
            if inspect.isawaitable(scraped):
                scraped = await scraped
            scraped_list = list(scraped)
        except Exception as exc:  # noqa: BLE001 -- bounded; we surface the message
            logger.warning("Search scrape failed for %s: %s", fingerprint[:12], exc)
            store.mark_query_run(query, status="stale", error=str(exc))
            postings = store.get_results(query.id)
            return SearchOutcome(
                postings=postings,
                cached=bool(postings),
                stale=True,
                query_id=query.id,
                last_run_at=query.last_run_at,
                last_success_at=query.last_success_at,
                last_error=str(exc),
                refresh_failed=True,
                counts={"cached": len(postings), "scraped": 0},
            )

        # Persist scraped postings + (re-)link to this query. We do NOT
        # delete old links here -- the search-results table is "every
        # posting this query ever returned" so the UI can diff "new vs
        # previously-seen". Phase 14's cache_eviction job is the only
        # writer that prunes.
        new_count = 0
        kept_postings: list[Any] = []
        for rank, item in enumerate(scraped_list):
            posting = store.upsert_posting(
                source=item.source,
                source_id=item.source_id,
                company=item.company,
                canonical_url=getattr(item, "application_url", None),
            )
            link = store.link_result(
                query_id=query.id, posting_id=posting.id, rank=rank
            )
            if link.first_seen_at == link.last_seen_at:
                new_count += 1
            kept_postings.append(posting)

        store.mark_query_run(query, status="fresh", result_count=len(scraped_list))
        return SearchOutcome(
            postings=kept_postings,
            cached=False,
            stale=False,
            query_id=query.id,
            last_run_at=query.last_run_at,
            last_success_at=query.last_success_at,
            last_error=None,
            refresh_failed=False,
            counts={"scraped": len(scraped_list), "new": new_count},
        )


def _can_serve_from_cache(
    *,
    query: Any,
    force_refresh: bool,
    freshness_hours: int,
    now: datetime,
) -> bool:
    if force_refresh:
        return False
    if query.status != "fresh":
        return False
    if query.last_success_at is None:
        return False
    return (now - query.last_success_at) < timedelta(hours=freshness_hours)


class _NullLock:
    """Stand-in used when the caller passes ``cache=None`` (tests, CLI scripts).

    Mirrors the ``AcquiredLock`` context-manager surface but always
    reports ``acquired=True`` so the search flow takes the scrape path.
    """

    acquired = True
    scope = "none"

    def __enter__(self) -> _NullLock:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

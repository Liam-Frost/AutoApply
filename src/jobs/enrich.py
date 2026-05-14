"""Phase 13.5: snapshot-versioned JD enrichment.

The contract is:

  scrape -> normalize -> content_hash
    -> if hash matches latest snapshot: no-op, return existing
    -> else: insert new JobSnapshot row, point posting.latest_snapshot_id
       at it, emit a ``job.content_changed`` event.

The function lives outside ``src/jobs/search.py`` because enrichment can
be triggered from three different places (the inline detail fetch in
LinkedIn search, the scheduler's ``jd_health_check`` job, the agent's
``jd_lookup`` tool in Phase 15) and they all need the same versioning
behaviour. Existing snapshots are NEVER mutated -- that's the whole
point of the audit binding from ``applications.job_snapshot_id``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from src.jobs.normalize import content_hash, normalize_job_content
from src.jobs.state import next_state
from src.jobs.store import JobIndexStore

logger = logging.getLogger("autoapply.jobs.enrich")

# Listeners registered via ``on_content_changed`` receive a
# ``ContentChangedEvent`` for every NEW snapshot row. Subscribers in
# downstream phases:
#   Phase 14 -- enqueue follow-up tasks when a JD's must-have skills
#               or visa flag change
#   Phase 17 -- flag the related ApplicationRecord for review
ContentChangedListener = Callable[["ContentChangedEvent"], None]
_LISTENERS: list[ContentChangedListener] = []


@dataclass
class ContentChangedEvent:
    posting_id: Any
    snapshot_id: Any
    previous_snapshot_id: Any | None
    content_hash: str
    scraped_at: datetime


@dataclass
class EnrichResult:
    snapshot_id: Any
    posting_id: Any
    content_hash: str
    content_changed: bool
    state: str


def on_content_changed(listener: ContentChangedListener) -> ContentChangedListener:
    """Register a listener. Returned for decorator-style use."""
    _LISTENERS.append(listener)
    return listener


def reset_listeners() -> None:
    """Test helper: drop all registered listeners."""
    _LISTENERS.clear()


def enrich_posting(
    *,
    store: JobIndexStore,
    source: str,
    source_id: str,
    company: str,
    content: dict[str, Any],
) -> EnrichResult:
    """Persist a scraped JD as a (possibly new) JobSnapshot.

    The function returns whether a new snapshot was created
    (``content_changed=True``) so the caller can decide whether to fan
    out downstream work (re-run filters, mark applications for review).

    Idempotent: scraping the same JD twice in a row produces one
    snapshot, not two. The state machine is driven via the
    ``enriched_ok`` event so callers don't have to manage it.
    """
    posting = store.upsert_posting(
        source=source,
        source_id=source_id,
        company=company,
        canonical_url=content.get("application_url"),
    )

    normalized = normalize_job_content(content)
    digest = content_hash(content)
    existing = store.find_snapshot(posting.id, digest)
    previous_snapshot_id = posting.latest_snapshot_id

    if existing is not None:
        # Snapshot already present -- still drive the state machine
        # forward because we successfully reached the source.
        _advance_state(posting, event="enriched_ok")
        posting.last_checked_at = datetime.now(UTC)
        return EnrichResult(
            snapshot_id=existing.id,
            posting_id=posting.id,
            content_hash=digest,
            content_changed=False,
            state=posting.state,
        )

    snapshot = store.insert_snapshot(
        posting=posting,
        content_hash=digest,
        title=normalized.get("title") or content.get("title") or "",
        location=normalized.get("location") or content.get("location"),
        employment_type=content.get("employment_type"),
        seniority=content.get("seniority"),
        description=content.get("description"),
        requirements=content.get("requirements"),
        application_url=content.get("application_url"),
        raw_data=content.get("raw_data") or content,
    )
    _advance_state(posting, event="enriched_ok")

    event = ContentChangedEvent(
        posting_id=posting.id,
        snapshot_id=snapshot.id,
        previous_snapshot_id=previous_snapshot_id,
        content_hash=digest,
        scraped_at=snapshot.scraped_at,
    )
    _emit(event)

    return EnrichResult(
        snapshot_id=snapshot.id,
        posting_id=posting.id,
        content_hash=digest,
        content_changed=True,
        state=posting.state,
    )


def mark_refresh_failed(
    *,
    store: JobIndexStore,
    posting_id: Any,
    error: str,
) -> str:
    """Apply a ``refresh_failed`` transition for transient scrape failures.

    Returns the new state. Caller is responsible for the session commit.
    """
    posting = store.get_posting(posting_id)
    if posting is None:
        raise LookupError(f"posting {posting_id} not found")
    _advance_state(posting, event="refresh_failed")
    posting.last_checked_at = datetime.now(UTC)
    logger.info("Posting %s -> %s (refresh_failed: %s)", posting_id, posting.state, error)
    return posting.state


def mark_source_404(*, store: JobIndexStore, posting_id: Any) -> str:
    """Apply a ``source_404`` transition when the JD is gone at the source."""
    posting = store.get_posting(posting_id)
    if posting is None:
        raise LookupError(f"posting {posting_id} not found")
    _advance_state(posting, event="source_404")
    posting.last_checked_at = datetime.now(UTC)
    return posting.state


def _advance_state(posting: Any, *, event: str) -> None:
    transition = next_state(posting.state, event)  # type: ignore[arg-type]
    posting.state = transition.state


def _emit(event: ContentChangedEvent) -> None:
    for listener in list(_LISTENERS):
        try:
            listener(event)
        except Exception as exc:  # noqa: BLE001 -- listeners are best-effort
            logger.warning("content_changed listener raised: %s", exc, exc_info=True)

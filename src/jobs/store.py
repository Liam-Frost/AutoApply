"""Phase 13.4: persistence facade for the Job Index.

Wraps the SQLAlchemy ORM models from ``src.core.models`` behind a single
``JobIndexStore`` class so the search flow, enrichment pipeline, and
freshness queries don't all duplicate the same upsert / lookup idioms.

The methods take a live ``Session`` so the caller controls commit
boundaries -- the search flow opens one session per query, the
scheduler opens one per task. The store does **not** commit; the
caller is expected to ``with session.begin(): ...``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.models import (
    TENANT_DEFAULT,
    JobPosting,
    JobSnapshot,
    RefreshTask,
    SearchQuery,
    SearchResult,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PostingRef:
    """Subset of ``JobPosting`` columns the search flow needs to hand back to callers.

    Used so the public surface doesn't leak the ORM instance and force
    the caller to keep the session open longer than necessary.
    """

    id: UUID
    source: str
    source_id: str
    company: str
    state: str
    canonical_url: str | None
    latest_snapshot_id: UUID | None


class JobIndexStore:
    def __init__(self, session: Session, *, tenant_id: str = TENANT_DEFAULT) -> None:
        self.session = session
        self.tenant_id = tenant_id

    # -- Search queries --------------------------------------------------

    def find_query(self, source: str, fingerprint: str) -> SearchQuery | None:
        stmt = select(SearchQuery).where(
            SearchQuery.tenant_id == self.tenant_id,
            SearchQuery.source == source,
            SearchQuery.normalized_key == fingerprint,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_query(
        self,
        *,
        source: str,
        fingerprint: str,
        raw_params: dict[str, Any],
        max_pages: int | None,
    ) -> SearchQuery:
        existing = self.find_query(source, fingerprint)
        if existing is not None:
            # ``raw_params`` is intentionally NOT overwritten on every
            # hit -- the first writer wins so we keep a stable record
            # of what the original caller actually passed. ``max_pages``
            # ratchets up so a later "wider" request expands coverage
            # without shrinking it on the next "narrower" request.
            if max_pages is not None and (
                existing.max_pages is None or max_pages > existing.max_pages
            ):
                existing.max_pages = max_pages
            return existing

        query = SearchQuery(
            tenant_id=self.tenant_id,
            source=source,
            normalized_key=fingerprint,
            raw_params=raw_params,
            status="fresh",
            max_pages=max_pages,
        )
        self.session.add(query)
        self.session.flush()
        return query

    def mark_query_run(
        self,
        query: SearchQuery,
        *,
        status: str,
        result_count: int | None = None,
        error: str | None = None,
    ) -> None:
        now = _utcnow()
        query.last_run_at = now
        query.status = status
        if status == "fresh":
            query.last_success_at = now
            query.last_error = None
        else:
            query.last_error = error
        if result_count is not None:
            query.result_count = result_count

    # -- Postings -------------------------------------------------------

    def upsert_posting(
        self,
        *,
        source: str,
        source_id: str,
        company: str,
        canonical_url: str | None = None,
    ) -> JobPosting:
        stmt = select(JobPosting).where(
            JobPosting.tenant_id == self.tenant_id,
            JobPosting.source == source,
            JobPosting.source_id == source_id,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        now = _utcnow()
        if existing is not None:
            existing.last_seen_at = now
            if canonical_url and not existing.canonical_url:
                existing.canonical_url = canonical_url
            return existing

        posting = JobPosting(
            tenant_id=self.tenant_id,
            source=source,
            source_id=source_id,
            company=company,
            canonical_url=canonical_url,
            first_seen_at=now,
            last_seen_at=now,
            state="new",
        )
        self.session.add(posting)
        self.session.flush()
        return posting

    def get_posting(self, posting_id: UUID) -> JobPosting | None:
        return self.session.get(JobPosting, posting_id)

    # -- Search <-> Posting links ---------------------------------------

    def link_result(
        self,
        *,
        query_id: UUID,
        posting_id: UUID,
        rank: int | None,
    ) -> SearchResult:
        stmt = select(SearchResult).where(
            SearchResult.query_id == query_id,
            SearchResult.posting_id == posting_id,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        now = _utcnow()
        if existing is not None:
            existing.last_seen_at = now
            if rank is not None:
                existing.rank = rank
            return existing

        link = SearchResult(
            tenant_id=self.tenant_id,
            query_id=query_id,
            posting_id=posting_id,
            rank=rank,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.session.add(link)
        self.session.flush()
        return link

    def get_results(self, query_id: UUID) -> list[JobPosting]:
        stmt = (
            select(JobPosting)
            .join(SearchResult, SearchResult.posting_id == JobPosting.id)
            .where(SearchResult.query_id == query_id)
            .order_by(SearchResult.rank.nulls_last(), SearchResult.first_seen_at)
        )
        return list(self.session.execute(stmt).scalars())

    # -- Snapshots ------------------------------------------------------

    def find_snapshot(self, posting_id: UUID, content_hash: str) -> JobSnapshot | None:
        stmt = select(JobSnapshot).where(
            JobSnapshot.posting_id == posting_id,
            JobSnapshot.content_hash == content_hash,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def insert_snapshot(
        self,
        *,
        posting: JobPosting,
        content_hash: str,
        title: str,
        location: str | None,
        employment_type: str | None,
        seniority: str | None,
        description: str | None,
        requirements: dict | None,
        application_url: str | None,
        raw_data: dict | None,
    ) -> JobSnapshot:
        snapshot = JobSnapshot(
            tenant_id=self.tenant_id,
            posting_id=posting.id,
            content_hash=content_hash,
            title=title,
            location=location,
            employment_type=employment_type,
            seniority=seniority,
            description=description,
            requirements=requirements,
            application_url=application_url,
            raw_data=raw_data,
            scraped_at=_utcnow(),
        )
        self.session.add(snapshot)
        self.session.flush()
        posting.latest_snapshot_id = snapshot.id
        posting.last_checked_at = snapshot.scraped_at
        return snapshot

    # -- Refresh task queue --------------------------------------------

    def enqueue_refresh(
        self,
        *,
        kind: str,
        target_id: UUID | None,
        priority: str = "normal",
        payload: dict | None = None,
        scheduled_for: datetime | None = None,
    ) -> RefreshTask:
        task = RefreshTask(
            tenant_id=self.tenant_id,
            kind=kind,
            priority=priority,
            target_id=target_id,
            payload=payload,
            status="pending",
            scheduled_for=scheduled_for or _utcnow(),
        )
        self.session.add(task)
        self.session.flush()
        return task

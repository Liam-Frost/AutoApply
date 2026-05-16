"""Phase 17.5 -- pre-submit hard gate tests.

The gate is the single guardrail between the operator clicking
'approve & submit' and the worker firing ``application.submit``.
It must:

* Refuse to fire for entries not in ``approved`` (returns
  ``missing_binding`` so the kanban doesn't try to short-circuit it).
* Refuse for entries with no ``job_id`` (search-only mode).
* Block on ``expired`` / ``archived`` postings -- and flip the entry
  to ``rejected`` so the kanban shows the terminal outcome.
* Block on stale snapshots ( > 6h per the ``before_submit`` budget)
  -- and flip the entry to ``stale`` so the operator can refresh.
* Clear when the posting is in a healthy state with a fresh
  ``last_checked_at``.
* Honour ``auto_mutate=False`` for read-only probes.

The gate writes through the application-layer helpers we tested in
17.2; the round-trip here is against the real dev Postgres so a
schema drift surfaces as a test failure.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.application.review import CreateEntryArgs, create_entry
from src.application.review import (
    approve as approve_entry,
)
from src.core.config import get_db_url, load_config
from src.core.models import JobPosting, JobSnapshot, ReviewQueueEntry
from src.review.pre_submit_gate import (
    PreSubmitGateResult,
    run_pre_submit_gate,
)

_TENANT_PREFIX = "test-psg-"


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    # Clean up only the rows we touched -- prefixed tenant ids keep us
    # from stomping on parallel test runs.
    s.execute(
        sa_delete(ReviewQueueEntry).where(
            ReviewQueueEntry.tenant_id.like(f"{_TENANT_PREFIX}%")
        )
    )
    # Cleanup order matters under the FK constraints:
    #   posting.latest_snapshot_id -> snapshots.id (would block snapshot
    #     deletion if we tried snapshots first)
    #   snapshots.posting_id -> postings.id (would block posting
    #     deletion if snapshots still reference it)
    # So: drop postings first (clears the latest_snapshot_id FK), then
    # snapshots (which can now go).
    from sqlalchemy import update as sa_update  # noqa: PLC0415

    s.execute(
        sa_update(JobPosting)
        .where(JobPosting.tenant_id.like(f"{_TENANT_PREFIX}%"))
        .values(latest_snapshot_id=None)
    )
    s.execute(
        sa_delete(JobSnapshot).where(
            JobSnapshot.tenant_id.like(f"{_TENANT_PREFIX}%")
        )
    )
    s.execute(
        sa_delete(JobPosting).where(
            JobPosting.tenant_id.like(f"{_TENANT_PREFIX}%")
        )
    )
    s.commit()
    s.close()


def _tenant() -> str:
    return f"{_TENANT_PREFIX}{uuid.uuid4().hex[:8]}"


def _make_posting(
    session: Session,
    *,
    tenant: str,
    state: str = "active",
    last_checked_at: datetime | None = None,
    source_id: str | None = None,
) -> JobPosting:
    posting = JobPosting(
        id=uuid.uuid4(),
        tenant_id=tenant,
        source="greenhouse",
        source_id=source_id or f"src-{uuid.uuid4().hex[:8]}",
        company="Acme",
        state=state,
        last_checked_at=last_checked_at,
    )
    session.add(posting)
    session.flush()
    return posting


def _seed_approved_entry(
    session: Session,
    *,
    tenant: str,
    posting: JobPosting | None = None,
) -> ReviewQueueEntry:
    job_id = posting.id if posting else uuid.uuid4()
    entry = create_entry(
        session,
        CreateEntryArgs(
            tenant_id=tenant,
            job_id=job_id,
            job_snapshot_id=uuid.uuid4(),
            materials_path=None,
            score_breakdown={"final_score": 0.62},
            company=posting.company if posting else "Acme",
            title="SWE Intern",
        ),
    )
    session.flush()
    approve_entry(session, entry.id, reviewer="alice")
    session.flush()
    return entry


# --------------------------------------------------------------------------- #
# Short-circuits                                                              #
# --------------------------------------------------------------------------- #


class TestShortCircuits:
    def test_missing_entry_returns_missing_binding(self, db_session: Session):
        result = run_pre_submit_gate(db_session, uuid.uuid4())
        assert isinstance(result, PreSubmitGateResult)
        assert result.allowed is False
        assert result.action == "missing_binding"

    def test_pending_entry_blocked(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(
            db_session,
            CreateEntryArgs(
                tenant_id=tenant,
                job_id=uuid.uuid4(),
                job_snapshot_id=uuid.uuid4(),
                materials_path=None,
                score_breakdown=None,
                company="X",
                title="Y",
            ),
        )
        db_session.commit()
        # Status is still 'pending' -- the gate must refuse.
        result = run_pre_submit_gate(db_session, entry.id)
        assert result.action == "missing_binding"
        assert "approved" in result.reason

    def test_entry_without_job_id_blocked(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(
            db_session,
            CreateEntryArgs(
                tenant_id=tenant,
                job_id=None,
                job_snapshot_id=None,
                materials_path=None,
                score_breakdown=None,
                company="X",
                title="Y",
            ),
        )
        approve_entry(db_session, entry.id)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id)
        assert result.action == "missing_binding"
        assert "job_id" in result.reason

    def test_missing_job_posting_returns_missing_binding(
        self, db_session: Session
    ):
        """Entry points at a job_id that's been retention-purged."""
        tenant = _tenant()
        entry = _seed_approved_entry(db_session, tenant=tenant)
        db_session.commit()
        # Don't insert a JobPosting -- the FK isn't enforced (we
        # dropped it in 17.2 on purpose).
        result = run_pre_submit_gate(db_session, entry.id)
        assert result.action == "missing_binding"


# --------------------------------------------------------------------------- #
# Lifecycle states                                                            #
# --------------------------------------------------------------------------- #


class TestLifecycleStates:
    def test_expired_posting_flips_entry_to_rejected(self, db_session: Session):
        tenant = _tenant()
        posting = _make_posting(db_session, tenant=tenant, state="expired")
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()

        result = run_pre_submit_gate(db_session, entry.id)
        db_session.commit()

        assert result.allowed is False
        assert result.action == "expired"
        # The gate auto-mutated to rejected.
        refreshed = db_session.get(ReviewQueueEntry, entry.id)
        assert refreshed.status == "rejected"

    def test_archived_posting_flips_entry_to_rejected(self, db_session: Session):
        tenant = _tenant()
        posting = _make_posting(db_session, tenant=tenant, state="archived")
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id)
        db_session.commit()
        assert result.action == "expired"
        assert db_session.get(ReviewQueueEntry, entry.id).status == "rejected"

    def test_auto_mutate_false_skips_state_change(self, db_session: Session):
        tenant = _tenant()
        posting = _make_posting(db_session, tenant=tenant, state="expired")
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id, auto_mutate=False)
        assert result.action == "expired"
        # Read-only probe -- entry stays approved.
        assert db_session.get(ReviewQueueEntry, entry.id).status == "approved"


# --------------------------------------------------------------------------- #
# Freshness                                                                   #
# --------------------------------------------------------------------------- #


class TestFreshness:
    def test_fresh_snapshot_allows(self, db_session: Session):
        tenant = _tenant()
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(hours=1),
        )
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id, now=now)
        assert result.allowed is True
        assert result.action == "allow"
        assert result.freshness is not None
        # entry stays approved -- the route is the one that flips to submitted.
        assert db_session.get(ReviewQueueEntry, entry.id).status == "approved"

    def test_stale_snapshot_flips_entry_to_stale(self, db_session: Session):
        tenant = _tenant()
        now = datetime.now(UTC)
        # before_submit budget is 6h; 8h is comfortably over.
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(hours=8),
        )
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()

        result = run_pre_submit_gate(db_session, entry.id, now=now)
        db_session.commit()

        assert result.allowed is False
        assert result.action == "refresh"
        # The gate flipped the entry so the kanban surfaces it again.
        assert db_session.get(ReviewQueueEntry, entry.id).status == "stale"
        assert result.freshness is not None
        assert result.freshness.should_refresh is True
        assert result.freshness.budget_hours == 6

    def test_exactly_at_budget_is_stale(self, db_session: Session):
        """6h exactly is at the edge -- :func:`should_refresh` returns
        True at ``>= budget``, so the gate must too."""
        tenant = _tenant()
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(hours=6),
        )
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id, now=now)
        assert result.action == "refresh"

    def test_no_last_checked_at_treated_as_stale(self, db_session: Session):
        tenant = _tenant()
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=None,
        )
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id)
        assert result.allowed is False
        assert result.action == "refresh"


# --------------------------------------------------------------------------- #
# Result shape                                                                #
# --------------------------------------------------------------------------- #


def _make_snapshot(
    session: Session, *, tenant: str, posting: JobPosting, label: str
) -> JobSnapshot:
    snap = JobSnapshot(
        id=uuid.uuid4(),
        tenant_id=tenant,
        posting_id=posting.id,
        content_hash=f"hash-{label}-{uuid.uuid4().hex[:8]}",
        title=posting.company,
    )
    session.add(snap)
    session.flush()
    return snap


class TestSnapshotMismatch:
    """Codex round-3 P1: even when last_checked_at is fresh, the gate
    must block when entry.job_snapshot_id != posting.latest_snapshot_id
    -- the materials were generated against an older JD version."""

    def test_snapshot_mismatch_marks_stale(self, db_session: Session):
        tenant = _tenant()
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(minutes=10),
        )
        # Real snapshot rows so the FK to job_snapshots is satisfied.
        old_snap_row = _make_snapshot(
            db_session, tenant=tenant, posting=posting, label="old"
        )
        new_snap_row = _make_snapshot(
            db_session, tenant=tenant, posting=posting, label="new"
        )
        # Posting now points at the new snapshot; the review entry was
        # bound to the old one when materials were generated.
        posting.latest_snapshot_id = new_snap_row.id
        db_session.commit()

        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        entry.job_snapshot_id = old_snap_row.id
        db_session.commit()

        result = run_pre_submit_gate(db_session, entry.id, now=now)
        db_session.commit()

        assert result.allowed is False
        assert result.action == "refresh"
        assert "re-scraped" in result.reason
        # Auto-mutated to stale.
        assert db_session.get(ReviewQueueEntry, entry.id).status == "stale"

    def test_matching_snapshot_passes(self, db_session: Session):
        tenant = _tenant()
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(minutes=10),
        )
        snap_row = _make_snapshot(
            db_session, tenant=tenant, posting=posting, label="only"
        )
        posting.latest_snapshot_id = snap_row.id
        db_session.commit()

        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        entry.job_snapshot_id = snap_row.id
        db_session.commit()

        result = run_pre_submit_gate(db_session, entry.id, now=now)
        assert result.allowed is True
        assert result.action == "allow"

    def test_null_entry_snapshot_id_does_not_block(self, db_session: Session):
        """Review entries created in search-only mode have no snapshot
        binding -- don't force-block them on that alone (the freshness
        check still fires)."""
        tenant = _tenant()
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(minutes=10),
        )
        snap_row = _make_snapshot(
            db_session, tenant=tenant, posting=posting, label="latest"
        )
        posting.latest_snapshot_id = snap_row.id
        db_session.commit()

        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        entry.job_snapshot_id = None  # search-only
        db_session.commit()

        result = run_pre_submit_gate(db_session, entry.id, now=now)
        assert result.allowed is True


class TestResultShape:
    def test_to_dict_round_trip(self, db_session: Session):
        tenant = _tenant()
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant=tenant,
            state="active",
            last_checked_at=now - timedelta(hours=1),
        )
        entry = _seed_approved_entry(db_session, tenant=tenant, posting=posting)
        db_session.commit()
        result = run_pre_submit_gate(db_session, entry.id, now=now)
        d = result.to_dict()
        assert d["allowed"] is True
        assert d["action"] == "allow"
        assert d["freshness"]["budget_hours"] == 6
        assert d["entry_id"] == str(entry.id)


# --------------------------------------------------------------------------- #
# Submit route integration                                                    #
# --------------------------------------------------------------------------- #


class TestSubmitRoute:
    """End-to-end through ``POST /api/review/{id}/submit``.

    The route must call into the gate, mutate the entry per the
    verdict, and (on allow) enqueue ``application.submit``. We patch
    Celery so no broker is required.
    """

    def test_submit_blocked_when_not_approved(self, db_session: Session):
        from fastapi.testclient import TestClient

        from src.web.app import create_app

        client = TestClient(create_app())
        entry = create_entry(
            db_session,
            CreateEntryArgs(
                tenant_id="default",
                job_id=uuid.uuid4(),
                job_snapshot_id=uuid.uuid4(),
                materials_path=None,
                score_breakdown=None,
                company="X",
                title="Y",
            ),
        )
        db_session.commit()
        try:
            response = client.post(
                f"/api/review/{entry.id}/submit", json={"reviewer": "alice"}
            )
            assert response.status_code == 409
        finally:
            db_session.execute(
                sa_delete(ReviewQueueEntry).where(
                    ReviewQueueEntry.id == entry.id
                )
            )
            db_session.commit()

    def test_submit_blocked_when_stale(self, db_session: Session, monkeypatch):
        """Stale snapshot -> gate flips to stale, route returns 200 with
        ``ok=False`` + structured gate verdict the UI renders as
        'Refresh required'."""
        from fastapi.testclient import TestClient

        from src.web.app import create_app

        client = TestClient(create_app())
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant="default",
            state="active",
            last_checked_at=now - timedelta(hours=12),
        )
        entry = _seed_approved_entry(db_session, tenant="default", posting=posting)
        db_session.commit()
        try:
            response = client.post(
                f"/api/review/{entry.id}/submit", json={"reviewer": "alice"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is False
            assert body["gate"]["action"] == "refresh"
            assert body["entry"]["status"] == "stale"
        finally:
            db_session.execute(
                sa_delete(ReviewQueueEntry).where(
                    ReviewQueueEntry.id == entry.id
                )
            )
            db_session.execute(
                sa_delete(JobPosting).where(JobPosting.id == posting.id)
            )
            db_session.commit()

    def test_submit_clear_flips_to_submitted(
        self, db_session: Session, monkeypatch
    ):
        from fastapi.testclient import TestClient

        # Stub out celery_app.send_task so the route doesn't try to
        # hit Redis. We just need it to return an object with .id.
        class _StubResult:
            id = "stub-task-id"

        class _StubCelery:
            @staticmethod
            def send_task(*_a, **_kw):
                return _StubResult()

        import src.tasks.app as celery_mod

        monkeypatch.setattr(celery_mod, "celery_app", _StubCelery())

        from src.web.app import create_app

        client = TestClient(create_app())
        now = datetime.now(UTC)
        posting = _make_posting(
            db_session,
            tenant="default",
            state="active",
            last_checked_at=now - timedelta(hours=1),
        )
        entry = _seed_approved_entry(db_session, tenant="default", posting=posting)
        db_session.commit()
        try:
            response = client.post(
                f"/api/review/{entry.id}/submit", json={"reviewer": "alice"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is True
            assert body["gate"]["action"] == "allow"
            assert body["entry"]["status"] == "submitted"
            # Task id surfaced for the UI
            assert body["submit_task_id"] == "stub-task-id"
        finally:
            db_session.execute(
                sa_delete(ReviewQueueEntry).where(
                    ReviewQueueEntry.id == entry.id
                )
            )
            db_session.execute(
                sa_delete(JobPosting).where(JobPosting.id == posting.id)
            )
            db_session.commit()

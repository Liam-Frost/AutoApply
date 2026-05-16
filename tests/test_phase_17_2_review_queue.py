"""Phase 17.2: review_queue model + state machine + use cases.

The state-machine half is pure-Python and exercised in isolation.
The use-case half round-trips against the real dev Postgres -- same
pattern as Phase 14.4 gate tests -- so a schema regression surfaces
as a test failure rather than a runtime crash in the worker.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.application import review as review_app
from src.application.review import (
    BulkResult,
    CreateEntryArgs,
    bulk_approve,
    bulk_reject_by_filter,
    create_entry,
    get_entry,
    list_entries,
    mark_stale,
    mark_submitted,
    refresh_stale,
    serialize_entry,
)
from src.core.config import get_db_url, load_config
from src.core.models import ReviewQueueEntry
from src.review.state_machine import (
    ALLOWED_TRANSITIONS,
    REVIEW_STATUSES,
    TERMINAL_STATUSES,
    InvalidTransitionError,
    is_valid_transition,
    next_status,
)

# --------------------------------------------------------------------------- #
# State machine (pure Python)                                                 #
# --------------------------------------------------------------------------- #


class TestStateMachine:
    def test_known_statuses(self):
        assert set(REVIEW_STATUSES) == {
            "pending",
            "approved",
            "submitted",
            "rejected",
            "stale",
        }

    def test_pending_can_become_approved_rejected_stale(self):
        assert is_valid_transition("pending", "approved")
        assert is_valid_transition("pending", "rejected")
        assert is_valid_transition("pending", "stale")
        # but not directly to submitted -- approval is required first
        assert not is_valid_transition("pending", "submitted")

    def test_approved_can_become_submitted_rejected_stale(self):
        assert is_valid_transition("approved", "submitted")
        assert is_valid_transition("approved", "rejected")
        assert is_valid_transition("approved", "stale")

    def test_stale_can_become_pending_or_rejected(self):
        assert is_valid_transition("stale", "pending")
        assert is_valid_transition("stale", "rejected")
        # not directly to approved or submitted -- the refresh path
        # re-runs materials generation first
        assert not is_valid_transition("stale", "approved")
        assert not is_valid_transition("stale", "submitted")

    def test_submitted_is_terminal(self):
        assert ALLOWED_TRANSITIONS["submitted"] == frozenset()
        for dst in REVIEW_STATUSES:
            assert not is_valid_transition("submitted", dst)

    def test_rejected_is_terminal(self):
        assert ALLOWED_TRANSITIONS["rejected"] == frozenset()
        for dst in REVIEW_STATUSES:
            assert not is_valid_transition("rejected", dst)

    def test_terminal_statuses_set(self):
        assert TERMINAL_STATUSES == frozenset({"submitted", "rejected"})

    def test_next_status_raises_on_bad_edge(self):
        with pytest.raises(InvalidTransitionError) as exc:
            next_status("submitted", "pending")
        assert exc.value.src == "submitted"
        assert exc.value.dst == "pending"

    def test_next_status_returns_dst_on_good_edge(self):
        assert next_status("pending", "approved") == "approved"

    def test_unknown_source_status_is_invalid(self):
        assert not is_valid_transition("nonsense", "pending")
        with pytest.raises(InvalidTransitionError):
            next_status("nonsense", "pending")


# --------------------------------------------------------------------------- #
# DB round-trip fixtures                                                      #
# --------------------------------------------------------------------------- #

_TENANT_PREFIX = "test-rq-"


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.execute(
        sa_delete(ReviewQueueEntry).where(
            ReviewQueueEntry.tenant_id.like(f"{_TENANT_PREFIX}%")
        )
    )
    s.commit()
    s.close()


def _tenant() -> str:
    return f"{_TENANT_PREFIX}{uuid.uuid4().hex[:8]}"


def _make_args(
    tenant: str,
    *,
    company: str = "Acme",
    title: str = "SWE Intern",
    job_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    run_id: str | None = None,
) -> CreateEntryArgs:
    # Default to fresh UUIDs per call so each test row has its own
    # (tenant, job_id, snapshot_id) tuple. The orchestrator passes
    # real ids; only the idempotency test deliberately reuses them.
    return CreateEntryArgs(
        tenant_id=tenant,
        job_id=job_id if job_id is not None else uuid.uuid4(),
        job_snapshot_id=snapshot_id if snapshot_id is not None else uuid.uuid4(),
        materials_path=None,
        score_breakdown={"final_score": 0.62},
        company=company,
        title=title,
        run_id=run_id,
    )


# --------------------------------------------------------------------------- #
# create_entry + serialize                                                    #
# --------------------------------------------------------------------------- #


class TestCreateEntry:
    def test_inserts_pending_row(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        fetched = get_entry(db_session, entry.id)
        assert fetched is not None
        assert fetched.status == "pending"
        assert fetched.company == "Acme"

    def test_create_entry_is_idempotent_on_pending(self, db_session: Session):
        """Repeated calls with the same (tenant, job, snapshot) tuple
        return the existing pending row rather than inserting a
        duplicate -- the orchestrator can legitimately re-fire."""
        tenant = _tenant()
        job_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()
        a = create_entry(
            db_session, _make_args(tenant, job_id=job_id, snapshot_id=snapshot_id)
        )
        db_session.commit()
        b = create_entry(
            db_session, _make_args(tenant, job_id=job_id, snapshot_id=snapshot_id)
        )
        db_session.commit()
        assert a.id == b.id

    def test_serialize_entry_shape(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        out = serialize_entry(entry)
        for key in (
            "id",
            "tenant_id",
            "job_id",
            "job_snapshot_id",
            "status",
            "company",
            "title",
            "created_at",
        ):
            assert key in out
        # All ids must be strings (JSON-friendly)
        assert isinstance(out["id"], str)


# --------------------------------------------------------------------------- #
# Transitions                                                                 #
# --------------------------------------------------------------------------- #


class TestTransitions:
    def test_approve_then_submit_round_trip(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()

        approved = review_app.approve(db_session, entry.id, reviewer="alice")
        assert approved.status == "approved"
        assert approved.reviewer == "alice"
        assert approved.reviewed_at is not None
        db_session.commit()

        submitted = mark_submitted(db_session, entry.id, reviewer="alice")
        assert submitted.status == "submitted"
        assert submitted.submitted_at is not None
        db_session.commit()

    def test_reject_terminal(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        rejected = review_app.reject(db_session, entry.id, reason="not a fit")
        assert rejected.status == "rejected"
        assert rejected.reason == "not a fit"
        db_session.commit()
        # Cannot un-reject.
        with pytest.raises(InvalidTransitionError):
            review_app.approve(db_session, entry.id)

    def test_pending_to_submitted_blocked(self, db_session: Session):
        """Approval is required before submission -- the pre-submit
        gate (Phase 17.5) only fires for ``approved`` entries."""
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        with pytest.raises(InvalidTransitionError):
            mark_submitted(db_session, entry.id)

    def test_stale_round_trip(self, db_session: Session):
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        stale = mark_stale(db_session, entry.id, reason="snapshot expired")
        assert stale.status == "stale"
        assert stale.reason == "snapshot expired"
        db_session.commit()
        refreshed = refresh_stale(db_session, entry.id, reviewer="bob")
        assert refreshed.status == "pending"
        db_session.commit()

    def test_approved_to_stale_allowed(self, db_session: Session):
        """The pre-submit gate fires AFTER approval; the entry can
        legitimately go from approved → stale."""
        tenant = _tenant()
        entry = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        review_app.approve(db_session, entry.id)
        db_session.commit()
        stale = mark_stale(db_session, entry.id, reason="age>6h")
        assert stale.status == "stale"

    def test_get_entry_returns_none_for_missing(self, db_session: Session):
        assert get_entry(db_session, uuid.uuid4()) is None

    def test_get_entry_returns_none_for_bad_uuid(self, db_session: Session):
        assert get_entry(db_session, "not-a-uuid") is None

    def test_approve_raises_lookup_error_for_missing(self, db_session: Session):
        with pytest.raises(LookupError):
            review_app.approve(db_session, uuid.uuid4())


# --------------------------------------------------------------------------- #
# Listing                                                                     #
# --------------------------------------------------------------------------- #


class TestListing:
    def test_list_filters_by_status(self, db_session: Session):
        tenant = _tenant()
        a = create_entry(db_session, _make_args(tenant, company="A"))
        b = create_entry(db_session, _make_args(tenant, company="B"))
        c = create_entry(db_session, _make_args(tenant, company="C"))
        db_session.commit()
        review_app.approve(db_session, a.id)
        review_app.reject(db_session, b.id)
        db_session.commit()
        # c stays pending
        pending = list_entries(db_session, tenant_id=tenant, status="pending")
        approved = list_entries(db_session, tenant_id=tenant, status="approved")
        rejected = list_entries(db_session, tenant_id=tenant, status="rejected")
        assert {e.id for e in pending} == {c.id}
        assert {e.id for e in approved} == {a.id}
        assert {e.id for e in rejected} == {b.id}

    def test_list_filters_by_tenant(self, db_session: Session):
        tenant_a = _tenant()
        tenant_b = _tenant()
        create_entry(db_session, _make_args(tenant_a))
        create_entry(db_session, _make_args(tenant_b))
        db_session.commit()
        a_rows = list_entries(db_session, tenant_id=tenant_a)
        b_rows = list_entries(db_session, tenant_id=tenant_b)
        assert all(e.tenant_id == tenant_a for e in a_rows)
        assert all(e.tenant_id == tenant_b for e in b_rows)
        assert len(a_rows) == 1
        assert len(b_rows) == 1


# --------------------------------------------------------------------------- #
# Bulk ops (17.4)                                                             #
# --------------------------------------------------------------------------- #


class TestBulkOps:
    def test_bulk_approve_aggregates_per_id_results(self, db_session: Session):
        tenant = _tenant()
        a = create_entry(db_session, _make_args(tenant))
        b = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        result = bulk_approve(db_session, [a.id, b.id])
        assert isinstance(result, BulkResult)
        assert set(result.succeeded) == {str(a.id), str(b.id)}
        assert result.failed == []
        db_session.commit()

    def test_bulk_approve_reports_failed_transitions(self, db_session: Session):
        tenant = _tenant()
        a = create_entry(db_session, _make_args(tenant))
        b = create_entry(db_session, _make_args(tenant))
        db_session.commit()
        review_app.reject(db_session, b.id)
        db_session.commit()
        result = bulk_approve(db_session, [a.id, b.id])
        assert str(a.id) in result.succeeded
        assert any(f["id"] == str(b.id) for f in result.failed)

    def test_bulk_reject_by_company(self, db_session: Session):
        tenant = _tenant()
        a = create_entry(db_session, _make_args(tenant, company="BlocklistedCo"))
        b = create_entry(db_session, _make_args(tenant, company="OtherCo"))
        c = create_entry(db_session, _make_args(tenant, company="blocklistedco"))
        db_session.commit()
        result = bulk_reject_by_filter(
            db_session, tenant_id=tenant, company="blocklist", reason="hard-no"
        )
        # Case-insensitive substring match should hit a + c, not b.
        ids = set(result.succeeded)
        assert str(a.id) in ids
        assert str(c.id) in ids
        assert str(b.id) not in ids
        db_session.commit()

    def test_bulk_reject_by_title_keyword(self, db_session: Session):
        tenant = _tenant()
        a = create_entry(db_session, _make_args(tenant, title="Senior Manager"))
        b = create_entry(db_session, _make_args(tenant, title="SWE Intern"))
        db_session.commit()
        result = bulk_reject_by_filter(
            db_session, tenant_id=tenant, keyword_in_title="manager"
        )
        assert str(a.id) in result.succeeded
        assert str(b.id) not in result.succeeded

    def test_bulk_reject_by_filter_only_acts_on_pending(self, db_session: Session):
        tenant = _tenant()
        a = create_entry(db_session, _make_args(tenant, company="X"))
        b = create_entry(db_session, _make_args(tenant, company="X"))
        db_session.commit()
        review_app.approve(db_session, b.id)
        db_session.commit()
        result = bulk_reject_by_filter(db_session, tenant_id=tenant, company="X")
        # Only the pending one gets bulk-rejected.
        assert str(a.id) in result.succeeded
        assert str(b.id) not in result.succeeded
        # b stays approved
        assert get_entry(db_session, b.id).status == "approved"


# --------------------------------------------------------------------------- #
# Migration head pin                                                          #
# --------------------------------------------------------------------------- #


class TestPartialUniqueOnPending:
    """Codex round-3 P2 -- the unique index applies only when
    status='pending' so the same snapshot can pass through the lifecycle
    multiple times across nightly runs."""

    def test_can_resurface_same_snapshot_after_terminal(
        self, db_session: Session
    ):
        tenant = _tenant()
        job_id = uuid.uuid4()
        snap_id = uuid.uuid4()
        a = create_entry(
            db_session,
            _make_args(tenant, job_id=job_id, snapshot_id=snap_id),
        )
        db_session.commit()
        review_app.reject(db_session, a.id)
        db_session.commit()

        # Run two of the orchestrator picks up the same snapshot.
        # Under the old full-row UNIQUE this would already collide on
        # ('pending') vs ('rejected') because the old constraint
        # included ``status``; with the partial-on-pending index, the
        # second insert succeeds because no pending row exists for
        # (tenant, job, snapshot).
        b = create_entry(
            db_session,
            _make_args(tenant, job_id=job_id, snapshot_id=snap_id),
        )
        db_session.commit()
        assert b.id != a.id
        # And we can transition this one independently of the old.
        review_app.approve(db_session, b.id)
        db_session.commit()
        assert db_session.get(ReviewQueueEntry, b.id).status == "approved"


def test_review_queue_table_exists(engine):
    """If the migration didn't run, the dev DB won't have the table.
    This is the only test that talks to the DB directly without going
    through the ORM helpers; it's a cheap sanity check."""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    assert "review_queue" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("review_queue")}
    # Pin the columns the route handler + UI rely on.
    for required in (
        "id",
        "tenant_id",
        "job_id",
        "job_snapshot_id",
        "run_id",
        "materials_path",
        "score_breakdown",
        "company",
        "title",
        "status",
        "decision",
        "reason",
        "created_at",
        "reviewed_at",
        "submitted_at",
        "reviewer",
    ):
        assert required in cols, f"missing column: {required}"

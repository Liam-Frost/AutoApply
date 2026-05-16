"""Phase 17.3 + 17.4 -- /api/review route wire-up tests.

Use-case behaviour is covered by ``test_phase_17_2_review_queue``;
this file is about the FastAPI wiring: shapes, status codes, tenant
isolation, and the single-item + bulk surfaces.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.application.review import CreateEntryArgs, create_entry
from src.core.config import get_db_url, load_config
from src.core.models import ReviewQueueEntry

_TENANT_PREFIX = "test-rqr-"
# The route helper falls back to ``"default"`` when the tenant
# ContextVar is unset; in CI we don't run with auth, so every row
# we create has to use tenant_id="default" for the routes to see it.
ROUTE_TENANT = "default"


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.execute(
        sa_delete(ReviewQueueEntry).where(
            ReviewQueueEntry.tenant_id.in_([ROUTE_TENANT, f"{_TENANT_PREFIX}other"])
        )
    )
    s.commit()
    s.close()


@pytest.fixture
def client() -> TestClient:
    from src.web.app import create_app

    return TestClient(create_app())


def _seed(session: Session, *, tenant: str = ROUTE_TENANT, **overrides) -> ReviewQueueEntry:
    args = CreateEntryArgs(
        tenant_id=tenant,
        job_id=overrides.get("job_id", uuid.uuid4()),
        job_snapshot_id=overrides.get("snapshot_id", uuid.uuid4()),
        materials_path=overrides.get("materials_path"),
        score_breakdown=overrides.get("score_breakdown", {"final_score": 0.55}),
        company=overrides.get("company", "Acme"),
        title=overrides.get("title", "SWE Intern"),
        run_id=overrides.get("run_id"),
    )
    entry = create_entry(session, args)
    session.commit()
    return entry


# --------------------------------------------------------------------------- #
# Read routes                                                                 #
# --------------------------------------------------------------------------- #


class TestReadRoutes:
    def test_list_returns_entries(self, db_session: Session, client: TestClient):
        _seed(db_session)
        _seed(db_session)
        response = client.get("/api/review")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert isinstance(body["entries"], list)
        assert len(body["entries"]) >= 2
        for entry in body["entries"]:
            assert "id" in entry
            assert "status" in entry

    def test_list_filters_by_status(self, db_session: Session, client: TestClient):
        _seed(db_session)  # pending
        # Mark one approved at the DB level so route filtering picks it up.
        approved = _seed(db_session)
        approved.status = "approved"
        db_session.commit()

        response = client.get("/api/review?status=approved")
        assert response.status_code == 200
        entries = response.json()["entries"]
        assert all(e["status"] == "approved" for e in entries)

    def test_get_entry_404_for_missing(self, client: TestClient):
        response = client.get(f"/api/review/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_get_entry_404_for_other_tenant(
        self, db_session: Session, client: TestClient
    ):
        entry = _seed(db_session, tenant=f"{_TENANT_PREFIX}other")
        response = client.get(f"/api/review/{entry.id}")
        # Cross-tenant access returns 404, not 403, so we don't leak
        # whether the id exists.
        assert response.status_code == 404

    def test_get_entry_happy_path(self, db_session: Session, client: TestClient):
        entry = _seed(db_session)
        response = client.get(f"/api/review/{entry.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["entry"]["id"] == str(entry.id)


# --------------------------------------------------------------------------- #
# Single-item transitions                                                     #
# --------------------------------------------------------------------------- #


class TestSingleItemTransitions:
    def test_approve_route(self, db_session: Session, client: TestClient):
        entry = _seed(db_session)
        response = client.post(
            f"/api/review/{entry.id}/approve",
            json={"reviewer": "alice", "reason": "looks good"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["entry"]["status"] == "approved"
        assert body["entry"]["reviewer"] == "alice"

    def test_reject_route(self, db_session: Session, client: TestClient):
        entry = _seed(db_session)
        response = client.post(
            f"/api/review/{entry.id}/reject",
            json={"reviewer": "bob", "reason": "wrong stack"},
        )
        assert response.status_code == 200
        assert response.json()["entry"]["status"] == "rejected"

    def test_invalid_transition_returns_409(
        self, db_session: Session, client: TestClient
    ):
        """Approving a rejected entry is a forbidden state-machine
        transition; the route maps that to 409 with the source/dst in
        the message."""
        entry = _seed(db_session)
        entry.status = "rejected"
        db_session.commit()
        response = client.post(
            f"/api/review/{entry.id}/approve", json={"reviewer": "x"}
        )
        assert response.status_code == 409
        assert "rejected" in response.json().get("detail", "")

    def test_refresh_route_stale_to_pending(
        self, db_session: Session, client: TestClient
    ):
        entry = _seed(db_session)
        entry.status = "stale"
        db_session.commit()
        response = client.post(
            f"/api/review/{entry.id}/refresh", json={"reviewer": "alice"}
        )
        assert response.status_code == 200
        assert response.json()["entry"]["status"] == "pending"

    def test_missing_entry_returns_404(self, client: TestClient):
        response = client.post(
            f"/api/review/{uuid.uuid4()}/approve", json={"reviewer": "x"}
        )
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Bulk routes (17.4)                                                          #
# --------------------------------------------------------------------------- #


class TestBulkRoutes:
    def test_bulk_approve_envelope(self, db_session: Session, client: TestClient):
        a = _seed(db_session)
        b = _seed(db_session)
        response = client.post(
            "/api/review/bulk/approve",
            json={"entry_ids": [str(a.id), str(b.id)], "reviewer": "alice"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert set(body["succeeded"]) == {str(a.id), str(b.id)}
        assert body["failed"] == []

    def test_bulk_reject_aggregates_failures(
        self, db_session: Session, client: TestClient
    ):
        a = _seed(db_session)
        b = _seed(db_session)
        # b is already approved AND submitted -- now terminal; reject
        # should fail for it but succeed for a.
        b.status = "submitted"
        db_session.commit()
        response = client.post(
            "/api/review/bulk/reject",
            json={"entry_ids": [str(a.id), str(b.id)]},
        )
        assert response.status_code == 200
        body = response.json()
        assert str(a.id) in body["succeeded"]
        assert any(f["id"] == str(b.id) for f in body["failed"])

    def test_bulk_approve_requires_entry_ids(self, client: TestClient):
        response = client.post("/api/review/bulk/approve", json={"entry_ids": []})
        assert response.status_code == 400

    def test_bulk_skips_other_tenants(
        self, db_session: Session, client: TestClient
    ):
        """An attacker passing a known cross-tenant id should not be
        able to flip it -- the route filters out non-owned ids
        silently (they don't show up in succeeded OR failed)."""
        mine = _seed(db_session)
        theirs = _seed(db_session, tenant=f"{_TENANT_PREFIX}other")
        response = client.post(
            "/api/review/bulk/approve",
            json={"entry_ids": [str(mine.id), str(theirs.id)]},
        )
        body = response.json()
        assert str(mine.id) in body["succeeded"]
        # theirs filtered out -- not in succeeded OR failed.
        all_ids = set(body["succeeded"]) | {f["id"] for f in body["failed"]}
        assert str(theirs.id) not in all_ids

    def test_bulk_reject_by_filter_company(
        self, db_session: Session, client: TestClient
    ):
        a = _seed(db_session, company="BlocklistedCo")
        b = _seed(db_session, company="OtherCo")
        response = client.post(
            "/api/review/bulk/reject-by-filter",
            json={"company": "blocklisted", "reason": "hard-no"},
        )
        assert response.status_code == 200
        body = response.json()
        assert str(a.id) in body["succeeded"]
        assert str(b.id) not in body["succeeded"]

    def test_bulk_reject_by_filter_requires_predicate(self, client: TestClient):
        response = client.post(
            "/api/review/bulk/reject-by-filter", json={}
        )
        assert response.status_code == 400

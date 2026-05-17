"""Phase 17.6 -- morning digest tests.

The digest is purely a read-side aggregation -- it consumes
``data/plan_runs/*.json`` produced by the Phase 17.1 orchestrator
+ a ``count(*)`` group-by-status over the Phase 17.2 review_queue.

Test split:

* Persistence / filename helpers (pure Python on tmp_path).
* Window filtering (filename prefix + tenant guard).
* ``compute_digest`` aggregation (with real Postgres for the queue
  counts; plan run reports via tmp_path).
* Headline string generation.
* Beat schedule + KNOWN_TASK_NAMES + ``/api/digest`` route smoke.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.application.review import CreateEntryArgs, create_entry
from src.core.config import get_db_url, load_config
from src.core.models import ReviewQueueEntry
from src.orchestration.digest import (
    DigestPayload,
    compute_digest,
    load_reports_in_window,
    persist_plan_run_report,
    plan_runs_dir,
)
from src.orchestration.plan_run import PlanRunReport

_TENANT_PREFIX = "test-dg-"


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


def _make_report(
    *,
    tenant_id: str,
    started_at: datetime,
    status: str = "ok",
    total_jobs_seen: int = 10,
    qualified: int = 5,
    disqualified: int = 5,
    borderline: int = 2,
    selected: int = 3,
    materials_task_ids: list[str] | None = None,
    estimated_cost_usd: float = 0.0,
    errors: list[str] | None = None,
) -> PlanRunReport:
    return PlanRunReport(
        run_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        profile_id="default",
        search_profile_id=None,
        status=status,
        started_at=started_at.isoformat(),
        finished_at=(started_at + timedelta(minutes=1)).isoformat(),
        duration_seconds=60.0,
        top_n=10,
        total_jobs_seen=total_jobs_seen,
        qualified=qualified,
        disqualified=disqualified,
        borderline=borderline,
        selected=selected,
        materials_task_ids=materials_task_ids or [],
        application_prepare_task_ids=[],
        errors=errors or [],
        estimated_cost_usd=estimated_cost_usd,
    )


# --------------------------------------------------------------------------- #
# Persistence helpers                                                         #
# --------------------------------------------------------------------------- #


class TestPersistence:
    def test_persist_writes_under_plan_runs(self, tmp_path: Path):
        report = _make_report(
            tenant_id="t1",
            started_at=datetime(2026, 5, 16, 23, 0, 0, tzinfo=UTC),
        )
        path = persist_plan_run_report(report, root=tmp_path)
        assert path.exists()
        # Filename starts with the iso timestamp.
        assert path.name.startswith("20260516T230000Z-")
        assert path.parent == plan_runs_dir(tmp_path)

    def test_persist_idempotent_on_same_run_id(self, tmp_path: Path):
        ts = datetime(2026, 5, 16, 23, 0, 0, tzinfo=UTC)
        report = _make_report(tenant_id="t1", started_at=ts)
        a = persist_plan_run_report(report, root=tmp_path)
        b = persist_plan_run_report(report, root=tmp_path)
        assert a == b
        assert sum(1 for _ in plan_runs_dir(tmp_path).iterdir()) == 1


# --------------------------------------------------------------------------- #
# Window loading                                                              #
# --------------------------------------------------------------------------- #


class TestWindowLoading:
    def test_loads_only_in_window(self, tmp_path: Path):
        now = datetime(2026, 5, 16, 10, 0, 0, tzinfo=UTC)
        in_window = _make_report(
            tenant_id="t1", started_at=now - timedelta(hours=5)
        )
        out_window_old = _make_report(
            tenant_id="t1", started_at=now - timedelta(hours=48)
        )
        out_window_future = _make_report(
            tenant_id="t1", started_at=now + timedelta(hours=1)
        )
        for r in (in_window, out_window_old, out_window_future):
            persist_plan_run_report(r, root=tmp_path)

        loaded = load_reports_in_window(
            since=now - timedelta(hours=24), until=now, root=tmp_path
        )
        assert {r.run_id for r in loaded} == {in_window.run_id}

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        loaded = load_reports_in_window(
            since=datetime.now(UTC) - timedelta(hours=24),
            until=datetime.now(UTC),
            root=tmp_path,
        )
        assert loaded == []

    def test_skips_unparseable_filenames(self, tmp_path: Path):
        d = plan_runs_dir(tmp_path)
        d.mkdir(parents=True)
        (d / "garbage.json").write_text("{}")
        loaded = load_reports_in_window(
            since=datetime(2020, 1, 1, tzinfo=UTC),
            until=datetime(2030, 1, 1, tzinfo=UTC),
            root=tmp_path,
        )
        assert loaded == []

    def test_skips_corrupt_json(self, tmp_path: Path):
        d = plan_runs_dir(tmp_path)
        d.mkdir(parents=True)
        (d / "20260516T230000Z-deadbeef.json").write_text("not json")
        loaded = load_reports_in_window(
            since=datetime(2020, 1, 1, tzinfo=UTC),
            until=datetime(2030, 1, 1, tzinfo=UTC),
            root=tmp_path,
        )
        assert loaded == []


# --------------------------------------------------------------------------- #
# compute_digest aggregation                                                  #
# --------------------------------------------------------------------------- #


class TestComputeDigest:
    def test_no_runs_yields_zero_payload_with_headline(
        self, db_session: Session, tmp_path: Path
    ):
        tenant = _tenant()
        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, root=tmp_path
        )
        assert isinstance(payload, DigestPayload)
        assert payload.runs == 0
        assert payload.total_jobs_seen == 0
        assert "No plan runs" in payload.headline

    def test_aggregates_reports_in_window(
        self, db_session: Session, tmp_path: Path
    ):
        tenant = _tenant()
        now = datetime.now(UTC)
        # Two in-window successful runs.
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=8),
                total_jobs_seen=12,
                qualified=7,
                disqualified=5,
                selected=3,
                materials_task_ids=["m1", "m2", "m3"],
                estimated_cost_usd=0.18,
            ),
            root=tmp_path,
        )
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=2),
                total_jobs_seen=8,
                qualified=4,
                disqualified=4,
                selected=2,
                materials_task_ids=["m4", "m5"],
                estimated_cost_usd=0.06,
            ),
            root=tmp_path,
        )
        # Out-of-window report -- must not contribute.
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=30),
                total_jobs_seen=99,
            ),
            root=tmp_path,
        )
        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, now=now, root=tmp_path
        )
        assert payload.runs == 2
        assert payload.total_jobs_seen == 20
        assert payload.qualified == 11
        assert payload.disqualified == 9
        assert payload.selected == 5
        assert payload.materials_enqueued == 5
        assert payload.estimated_cost_usd == 0.24

    def test_isolates_by_tenant(self, db_session: Session, tmp_path: Path):
        tenant = _tenant()
        other = _tenant()
        now = datetime.now(UTC)
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=2),
                total_jobs_seen=10,
            ),
            root=tmp_path,
        )
        persist_plan_run_report(
            _make_report(
                tenant_id=other,
                started_at=now - timedelta(hours=2),
                total_jobs_seen=999,
            ),
            root=tmp_path,
        )
        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, now=now, root=tmp_path
        )
        # Other tenant's report must not leak in.
        assert payload.total_jobs_seen == 10

    def test_counts_errors_and_paused_runs(
        self, db_session: Session, tmp_path: Path
    ):
        tenant = _tenant()
        now = datetime.now(UTC)
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=1),
                status="error",
                errors=["search failed"],
            ),
            root=tmp_path,
        )
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=2),
                status="paused",
            ),
            root=tmp_path,
        )
        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, now=now, root=tmp_path
        )
        assert payload.errors == 1
        assert payload.paused_runs == 1

    def test_review_queue_status_counts_live(
        self, db_session: Session, tmp_path: Path
    ):
        tenant = _tenant()
        # Three pending, one approved.
        for _ in range(3):
            create_entry(
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
        approved = create_entry(
            db_session,
            CreateEntryArgs(
                tenant_id=tenant,
                job_id=uuid.uuid4(),
                job_snapshot_id=uuid.uuid4(),
                materials_path=None,
                score_breakdown=None,
                company="Z",
                title="W",
            ),
        )
        approved.status = "approved"
        db_session.commit()

        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, root=tmp_path
        )
        assert payload.review_queue_status["pending"] == 3
        assert payload.review_queue_status["approved"] == 1


# --------------------------------------------------------------------------- #
# Headline                                                                    #
# --------------------------------------------------------------------------- #


class TestHeadline:
    def test_headline_omits_cost_when_zero(
        self, db_session: Session, tmp_path: Path
    ):
        tenant = _tenant()
        now = datetime.now(UTC)
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=2),
                total_jobs_seen=5,
                qualified=2,
            ),
            root=tmp_path,
        )
        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, now=now, root=tmp_path
        )
        assert "$" not in payload.headline
        assert "5 new jobs" in payload.headline
        assert "2 passed filter" in payload.headline

    def test_headline_includes_cost(
        self, db_session: Session, tmp_path: Path
    ):
        tenant = _tenant()
        now = datetime.now(UTC)
        persist_plan_run_report(
            _make_report(
                tenant_id=tenant,
                started_at=now - timedelta(hours=2),
                total_jobs_seen=12,
                qualified=7,
                estimated_cost_usd=0.21,
            ),
            root=tmp_path,
        )
        payload = compute_digest(
            db_session, tenant_id=tenant, window_hours=24, now=now, root=tmp_path
        )
        assert "$0.21" in payload.headline


# --------------------------------------------------------------------------- #
# Beat schedule + task wiring                                                 #
# --------------------------------------------------------------------------- #


class TestBeatWiring:
    def test_morning_digest_entry_at_0800(self):
        from src.tasks.beat import get_schedule

        schedule = get_schedule()
        assert "morning_digest" in schedule
        entry = schedule["morning_digest"]
        assert entry["task"] == "notifications.morning_digest"
        assert entry["schedule"].hour == {8}
        assert entry["schedule"].minute == {0}

    def test_morning_digest_in_known_task_names(self):
        from src.tasks.tasks import KNOWN_TASK_NAMES

        assert "notifications.morning_digest" in KNOWN_TASK_NAMES


# --------------------------------------------------------------------------- #
# API route                                                                   #
# --------------------------------------------------------------------------- #


class TestDigestRoute:
    def test_route_returns_envelope(self):
        from src.web.app import create_app

        client = TestClient(create_app())
        response = client.get("/api/digest")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert "digest" in body
        assert "headline" in body["digest"]
        assert "review_queue_status" in body["digest"]

    def test_route_clamps_window_hours(self):
        from src.web.app import create_app

        client = TestClient(create_app())
        # 9999 should be clamped down to the max (168 = one week).
        response = client.get("/api/digest?window_hours=9999")
        assert response.status_code == 200

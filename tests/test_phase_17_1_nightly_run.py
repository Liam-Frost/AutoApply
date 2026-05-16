"""Phase 17.1 -- nightly_run orchestrator tests.

The orchestrator is dependency-injected: ``run_nightly`` accepts
``search_fn`` / ``score_fn`` / ``enqueue_fn`` / ``pause_root`` /
``now`` so the suite doesn't need a real Redis, Postgres, or
LinkedIn session. The contract under test:

* Pause sentinel short-circuits before search; report status="paused".
* Search returning zero jobs short-circuits with status="no_results".
* Search raising is captured into ``errors`` -- the report still
  comes back so the Phase 17.6 digest has something to show.
* Score raising is captured similarly.
* Top-N is honoured against the qualified pool (disqualified jobs
  never reach enqueue).
* Each selected job produces TWO enqueue calls (materials.generate +
  application.prepare), in that order, threaded with the right
  payload shape.
* ``application.submit`` is NEVER enqueued (the orchestrator hard-
  stops at ``application.prepare``; submission is the Phase 17.5
  pre-submit-gated, human-approved path).
* ``dry_run=True`` runs everything except enqueue.
* The borderline counter counts qualified jobs in [0.4, 0.6].
* The Celery task wrapper validates payload + calls into the
  orchestrator + returns the report dict.
* Beat schedule registers the new ``nightly_run`` entry pointing at
  ``orchestration.nightly_run`` on the search queue.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.orchestration.nightly_run import (
    NIGHTLY_PAUSE_SENTINEL_NAME,
    NightlyRunError,
    NightlyRunReport,
    nightly_pause_sentinel_path,
    nightly_run_is_paused,
    run_nightly,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class _Breakdown:
    job_id: str
    final_score: float = 0.6
    disqualified: bool = False
    company: str = "Acme"
    title: str = "SWE Intern"


@dataclass
class _SearchRecorder:
    """Captures the search call so tests can assert on kwargs."""

    return_jobs: list[Any] = field(default_factory=list)
    raise_exc: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        return {"jobs": list(self.return_jobs)}


@dataclass
class _Enqueuer:
    """Captures every enqueue call. Returns deterministic ids so we
    can assert the report references them in order."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    raise_for: set[str] = field(default_factory=set)

    def __call__(self, task_name: str, payload: dict[str, Any]) -> str:
        if task_name in self.raise_for:
            raise RuntimeError(f"broker down for {task_name}")
        self.calls.append((task_name, dict(payload)))
        return f"task-{len(self.calls)}"


def _async(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Pause sentinel (17.7 plumbing)                                              #
# --------------------------------------------------------------------------- #


class TestPauseSentinel:
    def test_path_under_data(self, tmp_path: Path):
        p = nightly_pause_sentinel_path(tmp_path)
        assert p == tmp_path / "data" / NIGHTLY_PAUSE_SENTINEL_NAME

    def test_paused_when_sentinel_exists(self, tmp_path: Path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / NIGHTLY_PAUSE_SENTINEL_NAME).write_text("paused")
        assert nightly_run_is_paused(tmp_path)

    def test_not_paused_by_default(self, tmp_path: Path):
        assert not nightly_run_is_paused(tmp_path)


# --------------------------------------------------------------------------- #
# run_nightly -- short-circuits                                               #
# --------------------------------------------------------------------------- #


class TestRunNightlyShortCircuits:
    def test_missing_tenant_id_raises_programmer_error(self):
        """``tenant_id`` is required; this is a programmer error, not a
        runtime failure -- raise NightlyRunError rather than folding it
        into the report."""
        with pytest.raises(NightlyRunError):
            _async(run_nightly(tenant_id=""))

    def test_paused_short_circuits_before_search(self, tmp_path: Path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / NIGHTLY_PAUSE_SENTINEL_NAME).write_text("paused")
        search = _SearchRecorder()
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                search_fn=search,
                score_fn=lambda jobs, _pid: [],
                enqueue_fn=_Enqueuer(),
            )
        )
        assert report.status == "paused"
        assert search.calls == []  # never called

    def test_no_results_returns_no_results_status(self, tmp_path: Path):
        search = _SearchRecorder(return_jobs=[])
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                search_fn=search,
                score_fn=lambda jobs, _pid: [],
                enqueue_fn=_Enqueuer(),
            )
        )
        assert report.status == "no_results"
        assert report.total_jobs_seen == 0

    def test_search_exception_recorded_in_errors(self, tmp_path: Path):
        search = _SearchRecorder(raise_exc=RuntimeError("linkedin auth expired"))
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                search_fn=search,
                score_fn=lambda jobs, _pid: [],
                enqueue_fn=_Enqueuer(),
            )
        )
        assert report.status == "error"
        assert any("linkedin auth expired" in e for e in report.errors)

    def test_score_exception_recorded_in_errors(self, tmp_path: Path):
        search = _SearchRecorder(return_jobs=[{"id": "j1"}])

        def boom(jobs, _pid):
            raise RuntimeError("profile missing")

        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                search_fn=search,
                score_fn=boom,
                enqueue_fn=_Enqueuer(),
            )
        )
        assert report.status == "error"
        assert any("profile missing" in e for e in report.errors)


# --------------------------------------------------------------------------- #
# run_nightly -- happy path                                                   #
# --------------------------------------------------------------------------- #


class TestRunNightlyHappyPath:
    def test_top_n_capped_qualified_pool(self, tmp_path: Path):
        jobs = [{"id": f"j{i}"} for i in range(5)]
        bds = [_Breakdown(job_id=f"j{i}", final_score=0.7 - 0.05 * i) for i in range(5)]
        enq = _Enqueuer()
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=3,
                search_fn=_SearchRecorder(return_jobs=jobs),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        assert report.status == "ok"
        assert report.selected == 3
        # 3 selected * 2 enqueues each.
        assert len(enq.calls) == 6
        assert len(report.materials_task_ids) == 3
        assert len(report.application_prepare_task_ids) == 3

    def test_disqualified_jobs_never_reach_enqueue(self, tmp_path: Path):
        jobs = [{"id": "ok"}, {"id": "blocked"}]
        bds = [
            _Breakdown(job_id="ok", final_score=0.55),
            _Breakdown(job_id="blocked", final_score=0.0, disqualified=True),
        ]
        enq = _Enqueuer()
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=10,
                search_fn=_SearchRecorder(return_jobs=jobs),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        assert report.qualified == 1
        assert report.disqualified == 1
        assert report.selected == 1
        # No "blocked" job_id in the enqueue calls.
        for _name, payload in enq.calls:
            assert payload.get("job_id") != "blocked"
            assert payload.get("application_id") != "blocked"

    def test_enqueue_payload_shape(self, tmp_path: Path):
        bds = [_Breakdown(job_id="j-7", final_score=0.55)]
        enq = _Enqueuer()
        _async(
            run_nightly(
                tenant_id="t1",
                profile_id="primary",
                pause_root=tmp_path,
                top_n=1,
                search_fn=_SearchRecorder(return_jobs=[{"id": "j-7"}]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        # Order matters: materials.generate is the parent; application.prepare
        # rides after so a worker observing the audit row sees the
        # parent's task_id first.
        names = [c[0] for c in enq.calls]
        assert names == ["materials.generate", "application.prepare"]
        # materials payload
        mat_payload = enq.calls[0][1]
        assert mat_payload["job_id"] == "j-7"
        assert mat_payload["profile_id"] == "primary"
        assert "resume" in mat_payload["document_types"]
        assert "cover_letter" in mat_payload["document_types"]
        # application.prepare payload
        prep_payload = enq.calls[1][1]
        assert prep_payload["application_id"] == "j-7"

    def test_never_enqueues_application_submit(self, tmp_path: Path):
        """Hard rule: nightly_run never auto-submits. If a regression
        adds application.submit to the orchestrator, this test fails."""
        bds = [_Breakdown(job_id="x", final_score=0.55)]
        enq = _Enqueuer()
        _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=5,
                search_fn=_SearchRecorder(return_jobs=[{"id": "x"}]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        names = [c[0] for c in enq.calls]
        assert "application.submit" not in names
        assert "application.fill" not in names

    def test_dry_run_skips_enqueue(self, tmp_path: Path):
        bds = [_Breakdown(job_id="x", final_score=0.7)]
        enq = _Enqueuer()
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=1,
                dry_run=True,
                search_fn=_SearchRecorder(return_jobs=[{"id": "x"}]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        assert report.status == "ok"
        assert report.dry_run is True
        assert report.selected == 1
        assert enq.calls == []
        assert report.materials_task_ids == []

    def test_borderline_counter_counts_qualified_in_band(self, tmp_path: Path):
        bds = [
            _Breakdown(job_id="a", final_score=0.3),  # below band
            _Breakdown(job_id="b", final_score=0.4),  # in band (low edge)
            _Breakdown(job_id="c", final_score=0.55),  # in band
            _Breakdown(job_id="d", final_score=0.6),  # in band (high edge)
            _Breakdown(job_id="e", final_score=0.75),  # above band
            _Breakdown(job_id="f", final_score=0.5, disqualified=True),  # excluded
        ]
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=10,
                search_fn=_SearchRecorder(return_jobs=[{"id": b.job_id} for b in bds]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=_Enqueuer(),
            )
        )
        assert report.borderline == 3  # b, c, d -- f excluded by disqualified

    def test_partial_enqueue_failure_keeps_report_status_error(self, tmp_path: Path):
        bds = [_Breakdown(job_id="x", final_score=0.55)]
        enq = _Enqueuer(raise_for={"application.prepare"})
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=1,
                search_fn=_SearchRecorder(return_jobs=[{"id": "x"}]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        # materials succeeded; application.prepare failed.
        assert report.status == "error"
        assert report.materials_task_ids == ["task-1"]
        assert report.application_prepare_task_ids == []
        assert any("application.prepare" in e for e in report.errors)


# --------------------------------------------------------------------------- #
# NightlyRunReport shape                                                      #
# --------------------------------------------------------------------------- #


class TestNightlyRunReportShape:
    def test_to_dict_round_trip(self):
        report = NightlyRunReport(
            run_id="r1",
            tenant_id="t1",
            profile_id="default",
            search_profile_id=None,
            status="ok",
            started_at="2026-05-16T23:00:00+00:00",
            finished_at="2026-05-16T23:01:00+00:00",
            duration_seconds=60.0,
            top_n=10,
            total_jobs_seen=42,
            qualified=7,
            disqualified=35,
            borderline=2,
            selected=5,
            materials_task_ids=["a", "b", "c", "d", "e"],
            application_prepare_task_ids=["f", "g", "h", "i", "j"],
            errors=[],
            estimated_cost_usd=0.0,
            dry_run=False,
        )
        d = report.to_dict()
        assert d["run_id"] == "r1"
        assert d["status"] == "ok"
        assert d["qualified"] == 7
        assert d["borderline"] == 2
        # Lists are JSON-friendly (no datetime / dataclass leaks)
        for tid in d["materials_task_ids"]:
            assert isinstance(tid, str)


# --------------------------------------------------------------------------- #
# Celery task wrapper                                                         #
# --------------------------------------------------------------------------- #


class TestCeleryTaskWrapper:
    @patch("src.orchestration.nightly_run.run_nightly")
    def test_task_invokes_orchestrator_with_payload(self, mock_run):
        async def fake(**kwargs):
            return NightlyRunReport(
                run_id="r",
                tenant_id=kwargs["tenant_id"],
                profile_id=kwargs.get("profile_id", "default"),
                search_profile_id=kwargs.get("search_profile_id"),
                status="ok",
                started_at="x",
                finished_at="y",
                duration_seconds=1.0,
                top_n=kwargs.get("top_n", 10),
                dry_run=kwargs.get("dry_run", False),
            )

        mock_run.side_effect = fake

        from src.tasks.tasks import orchestration_nightly_run

        # Invoke the function directly (we don't need the Celery
        # bound-self machinery for the contract test).
        out = orchestration_nightly_run.run(profile_id="primary", top_n=3)
        assert out["profile_id"] == "primary"
        assert out["top_n"] == 3
        assert out["status"] == "ok"

    def test_invalid_payload_raises_terminal_error(self):
        """``top_n`` must be int; the AutoApplyTask layer converts
        Pydantic validation errors into TypeError so Celery does not
        retry forever."""
        from src.tasks.tasks import orchestration_nightly_run

        with pytest.raises(TypeError):
            orchestration_nightly_run.run(top_n="not-an-int")


# --------------------------------------------------------------------------- #
# Beat schedule wiring                                                        #
# --------------------------------------------------------------------------- #


class TestBeatSchedule:
    def test_nightly_run_entry_registered(self):
        from src.tasks.beat import get_schedule

        schedule = get_schedule()
        assert "nightly_run" in schedule
        entry = schedule["nightly_run"]
        assert entry["task"] == "orchestration.nightly_run"
        # Plan calls for 23:00 cron.
        assert entry["schedule"].hour == {23}
        assert entry["schedule"].minute == {0}
        # Lands on the search queue (orchestrator is heavy; we don't
        # want it blocking maintenance / materials workers).
        assert entry["options"]["queue"] == "search"

    def test_known_task_names_include_orchestration(self):
        from src.tasks.tasks import KNOWN_TASK_NAMES

        assert "orchestration.nightly_run" in KNOWN_TASK_NAMES


# --------------------------------------------------------------------------- #
# Now-injection                                                               #
# --------------------------------------------------------------------------- #


class TestCliCommands:
    def test_pause_resume_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Phase 17.7 wires `autoapply pause-nightly` / `resume-nightly`
        to the sentinel helper. Round-trip them and confirm the
        orchestrator short-circuits between."""
        from click.testing import CliRunner

        from src.cli.cmd_nightly import (
            pause_nightly_cmd,
            resume_nightly_cmd,
        )

        # Re-root the sentinel under tmp_path for the duration of this
        # test. The helper imports PROJECT_ROOT at call time, so
        # patching it on the module is the cleanest seam.
        from src.orchestration import nightly_run as nr_mod

        def _path():
            return tmp_path / "data" / NIGHTLY_PAUSE_SENTINEL_NAME

        monkeypatch.setattr(nr_mod, "nightly_pause_sentinel_path", lambda root=None: _path())
        # The CLI module captured the helper at import time -- patch
        # there as well so the click command sees the override.
        import src.cli.cmd_nightly as cli_mod

        monkeypatch.setattr(cli_mod, "nightly_pause_sentinel_path", lambda: _path())

        runner = CliRunner()

        # Pause.
        result = runner.invoke(pause_nightly_cmd, [])
        assert result.exit_code == 0
        assert _path().exists()
        assert nr_mod.nightly_run_is_paused(tmp_path)

        # Resume.
        result = runner.invoke(resume_nightly_cmd, [])
        assert result.exit_code == 0
        assert not _path().exists()
        assert not nr_mod.nightly_run_is_paused(tmp_path)

    def test_pause_is_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from click.testing import CliRunner

        import src.cli.cmd_nightly as cli_mod
        from src.cli.cmd_nightly import pause_nightly_cmd

        path = tmp_path / "data" / NIGHTLY_PAUSE_SENTINEL_NAME
        monkeypatch.setattr(cli_mod, "nightly_pause_sentinel_path", lambda: path)

        runner = CliRunner()
        for _ in range(3):
            result = runner.invoke(pause_nightly_cmd, [])
            assert result.exit_code == 0
        assert path.exists()


class TestCodexFixes:
    """Pin the three codex review findings:
      * P1: dict -> RawJob coercion before scoring.
      * P1: review_queue rows are persisted from the orchestrator.
      * P2: top_n=0 or negative selects nothing.
    """

    def test_top_n_zero_selects_nothing(self, tmp_path: Path):
        bds = [_Breakdown(job_id=f"j{i}", final_score=0.7) for i in range(5)]
        enq = _Enqueuer()
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=0,
                search_fn=_SearchRecorder(
                    return_jobs=[{"id": b.job_id} for b in bds]
                ),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        # Codex P2: top_n=0 must mean "select none", not "no cap".
        assert report.selected == 0
        assert enq.calls == []

    def test_top_n_negative_selects_nothing(self, tmp_path: Path):
        bds = [_Breakdown(job_id="j", final_score=0.7)]
        enq = _Enqueuer()
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=-1,
                search_fn=_SearchRecorder(return_jobs=[{"id": "j"}]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=enq,
            )
        )
        assert report.selected == 0
        assert enq.calls == []

    def test_coerce_job_to_rawjob_handles_dict(self):
        """Codex P1: dicts coming back from search_jobs (serialize_job
        output) must be convertible into RawJob before scoring."""
        from src.intake.schema import RawJob
        from src.orchestration.nightly_run import _coerce_job_to_rawjob

        payload = {
            "id": "00000000-0000-0000-0000-000000000001",
            "source": "greenhouse",
            "source_id": "j1",
            "company": "Acme",
            "title": "SWE Intern",
            "employment_type": "internship",
            "seniority": "internship",
            "description": "...",
            "ats_type": "greenhouse",
            "match_score": 0.5,  # serialize_job flat field RawJob rejects
            "disqualified": False,
            "raw_data": {},
        }
        out = _coerce_job_to_rawjob(payload)
        assert isinstance(out, RawJob)

    def test_coerce_job_to_rawjob_passes_through_rawjob(self):
        from src.intake.schema import RawJob
        from src.orchestration.nightly_run import _coerce_job_to_rawjob

        raw = RawJob(
            source="greenhouse",
            source_id="j1",
            company="Acme",
            title="SWE",
        )
        assert _coerce_job_to_rawjob(raw) is raw

    def test_coerce_job_to_rawjob_drops_malformed(self):
        from src.orchestration.nightly_run import _coerce_job_to_rawjob

        # Missing required ``source_id`` -> RawJob construction fails ->
        # helper returns None so scoring just skips this row.
        assert _coerce_job_to_rawjob({"company": "X"}) is None

    def test_review_entries_persisted_for_selected_jobs(self, tmp_path: Path):
        """Codex P1: the orchestrator must populate review_queue so the
        kanban shows last night's matches even though
        application.prepare is a stub."""
        import uuid as _uuid

        from sqlalchemy import create_engine
        from sqlalchemy import delete as sa_delete
        from sqlalchemy.orm import sessionmaker

        from src.core.config import get_db_url, load_config
        from src.core.models import ReviewQueueEntry

        tenant = f"test-nr-{_uuid.uuid4().hex[:6]}"

        @dataclass
        class _BDWithTitle:
            job_id: str
            final_score: float = 0.6
            disqualified: bool = False
            company: str = "Acme"
            title: str = "SWE Intern"

            def to_dict(self):
                return {"final_score": self.final_score}

        engine = create_engine(get_db_url(load_config()))
        session_local = sessionmaker(bind=engine)

        try:
            job_uuid = _uuid.uuid4()
            bds = [_BDWithTitle(job_id=str(job_uuid), final_score=0.7)]
            report = _async(
                run_nightly(
                    tenant_id=tenant,
                    pause_root=tmp_path,
                    top_n=5,
                    search_fn=_SearchRecorder(return_jobs=[{"id": str(job_uuid)}]),
                    score_fn=lambda jobs, _pid: bds,
                    enqueue_fn=_Enqueuer(),
                )
            )
            assert report.status == "ok"
            assert len(report.review_entry_ids) == 1
            with session_local() as session:
                rows = session.query(ReviewQueueEntry).filter(
                    ReviewQueueEntry.tenant_id == tenant
                ).all()
                assert len(rows) == 1
                assert rows[0].status == "pending"
                assert rows[0].company == "Acme"
                assert rows[0].title == "SWE Intern"
                assert rows[0].run_id == report.run_id
        finally:
            with session_local() as cleanup:
                cleanup.execute(
                    sa_delete(ReviewQueueEntry).where(
                        ReviewQueueEntry.tenant_id == tenant
                    )
                )
                cleanup.commit()

    def test_dry_run_does_not_persist_review_entries(self, tmp_path: Path):
        """Even though we now persist from the orchestrator, dry_run
        stays a true rehearsal -- no DB writes, no enqueue."""
        bds = [_Breakdown(job_id="x", final_score=0.7)]
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=1,
                dry_run=True,
                search_fn=_SearchRecorder(return_jobs=[{"id": "x"}]),
                score_fn=lambda jobs, _pid: bds,
                enqueue_fn=_Enqueuer(),
            )
        )
        assert report.review_entry_ids == []


class TestNowInjection:
    def test_duration_uses_injected_clock(self, tmp_path: Path):
        ticks = iter(
            [
                datetime(2026, 5, 16, 23, 0, 0, tzinfo=UTC),
                datetime(2026, 5, 16, 23, 1, 30, tzinfo=UTC),
            ]
        )
        report = _async(
            run_nightly(
                tenant_id="t1",
                pause_root=tmp_path,
                top_n=0,
                search_fn=_SearchRecorder(return_jobs=[{"id": "x"}]),
                score_fn=lambda jobs, _pid: [_Breakdown(job_id="x", final_score=0.7)],
                enqueue_fn=_Enqueuer(),
                now=lambda: next(ticks),
            )
        )
        assert report.duration_seconds == 90.0

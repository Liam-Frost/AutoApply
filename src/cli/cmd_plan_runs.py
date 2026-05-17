"""Phase 17 ``autoapply plan-runs`` CLI group.

Subcommands:

* ``autoapply plan-runs run`` -- fire the orchestrator synchronously
  for an ad-hoc test or a manual plan tick. Honours the pause
  sentinel; supports ``--dry-run`` for the search+score-only
  rehearsal.
* ``autoapply plan-runs enqueue`` -- queue the Celery task without
  blocking on it. Returns the task id.
* ``autoapply plan-runs status`` -- print the current pause state.
* ``autoapply pause-plan-runs`` / ``autoapply resume-plan-runs`` -- Phase
  17.7 kill switch. ``pause`` creates the sentinel; ``resume`` removes
  it. These are top-level commands rather than nested under
  ``plan-runs`` so scripts can pause all scheduled application batches.
"""

from __future__ import annotations

import asyncio
import json
import sys

import click

from src.orchestration.plan_run import (
    plan_run_pause_sentinel_path,
    plan_runs_paused,
    run_plan,
)


@click.group(name="plan-runs")
def plan_runs_cmd() -> None:
    """Phase 17 plan_run orchestrator commands."""


@plan_runs_cmd.command("run")
@click.option("--tenant", default="default", help="Tenant id for the run.")
@click.option("--profile", default="default", help="Applicant profile id.")
@click.option(
    "--search-profile",
    default=None,
    help="Saved search profile id (defaults to the applicant profile).",
)
@click.option(
    "--top-n",
    type=int,
    default=10,
    help="Max qualified jobs to enqueue materials.generate + application.prepare for.",
)
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    help="Run search+score but skip enqueue.",
)
def plan_run_cmd(
    tenant: str, profile: str, search_profile: str | None, top_n: int, dry_run: bool
) -> None:
    """Run one plan pass synchronously and print the report JSON."""
    report = asyncio.run(
        run_plan(
            tenant_id=tenant,
            profile_id=profile,
            search_profile_id=search_profile,
            top_n=top_n,
            dry_run=dry_run,
        )
    )
    click.echo(json.dumps(report.to_dict(), indent=2, default=str))
    if report.status == "error":
        sys.exit(2)


@plan_runs_cmd.command("enqueue")
@click.option("--profile", default="default", help="Applicant profile id.")
@click.option("--search-profile", default=None)
@click.option("--top-n", type=int, default=10)
@click.option("--dry-run/--no-dry-run", default=False)
def plan_run_enqueue_cmd(
    profile: str, search_profile: str | None, top_n: int, dry_run: bool
) -> None:
    """Queue the Celery task without blocking on it. Prints the task id."""
    from src.tasks.app import celery_app

    payload = {
        "profile_id": profile,
        "search_profile_id": search_profile,
        "top_n": top_n,
        "dry_run": dry_run,
    }
    async_result = celery_app.send_task(
        "orchestration.plan_run", kwargs=payload
    )
    click.echo(json.dumps({"task_id": str(async_result.id)}))


@plan_runs_cmd.command("status")
def plan_run_status_cmd() -> None:
    """Print pause-sentinel status."""
    paused = plan_runs_paused()
    path = plan_run_pause_sentinel_path()
    click.echo(
        json.dumps(
            {"paused": paused, "sentinel_path": str(path)},
            indent=2,
        )
    )


@click.command("pause-plan-runs")
@click.option(
    "--clear-pending/--keep-pending",
    default=False,
    help=(
        "When set, bulk-reject all pending review_queue entries (for "
        "vacation pauses where you don't want a backlog to come back to). "
        "Approved / submitted / rejected / stale rows are left alone."
    ),
)
@click.option("--tenant", default="default", help="Tenant id (when --clear-pending).")
def pause_plan_runs_cmd(clear_pending: bool, tenant: str) -> None:
    """Phase 17.7 kill switch: create the pause sentinel.

    Idempotent. While the sentinel exists, ``run_plan`` short-
    circuits with ``status="paused"`` -- both the Beat-driven tick and
    any manual ``autoapply plan-runs run`` invocation. The sentinel is a
    plain file under ``data/`` so an operator can also touch it by hand.

    ``--clear-pending`` is the 'going on vacation' affordance the plan
    calls for: bulk-reject every pending review_queue row so the
    operator doesn't return to a stale N-deep queue. Already-approved
    entries are NOT cleared (a paused user who already greenlit those
    still wants them submitted manually when they get back).
    """
    path = plan_run_pause_sentinel_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("paused\n", encoding="utf-8")

    cleared = 0
    if clear_pending:
        # Lazy import: avoid pulling SQLAlchemy in for the no-clear path.
        from src.application.review import bulk_reject_by_filter  # noqa: PLC0415
        from src.core.database import get_session_factory  # noqa: PLC0415

        factory = get_session_factory()
        with factory() as session, session.begin():
            # company=None + keyword=None would fail the use-case
            # validation, so use a wildcard via empty string match in
            # ILIKE -- but the helper validates against both being
            # blank. Use a sentinel that matches everything: pass a
            # single character that ILIKE treats as a wildcard wrapped
            # by '%'. Simpler: do the bulk-reject manually here.
            from sqlalchemy import select  # noqa: PLC0415

            from src.application.review import bulk_reject  # noqa: PLC0415
            from src.core.models import ReviewQueueEntry  # noqa: PLC0415

            del bulk_reject_by_filter  # not used; we want a tighter query
            rows = (
                session.execute(
                    select(ReviewQueueEntry.id).where(
                        ReviewQueueEntry.tenant_id == tenant,
                        ReviewQueueEntry.status == "pending",
                    )
                )
                .scalars()
                .all()
            )
            result = bulk_reject(
                session,
                rows,
                reviewer="pause-plan-runs",
                reason="paused for vacation",
            )
            cleared = len(result.succeeded)

    click.echo(
        json.dumps(
            {
                "paused": True,
                "sentinel_path": str(path),
                "cleared_pending": cleared,
            }
        )
    )


@click.command("resume-plan-runs")
def resume_plan_runs_cmd() -> None:
    """Lift the Phase 17.7 pause sentinel. Idempotent."""
    path = plan_run_pause_sentinel_path()
    if path.exists():
        path.unlink()
    click.echo(json.dumps({"paused": False, "sentinel_path": str(path)}))

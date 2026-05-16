"""Phase 17 ``autoapply nightly`` CLI group.

Subcommands:

* ``autoapply nightly run`` -- fire the orchestrator synchronously
  for an ad-hoc test or a manual nightly tick. Honours the pause
  sentinel; supports ``--dry-run`` for the search+score-only
  rehearsal.
* ``autoapply nightly enqueue`` -- queue the Celery task without
  blocking on it. Returns the task id.
* ``autoapply nightly status`` -- print the current pause state.
* ``autoapply pause-nightly`` / ``autoapply resume-nightly`` -- Phase
  17.7 kill switch. ``pause`` creates the sentinel; ``resume`` removes
  it. These are top-level commands rather than nested under
  ``nightly`` so the plan's literal ``autoapply pause-nightly`` works.
"""

from __future__ import annotations

import asyncio
import json
import sys

import click

from src.orchestration.nightly_run import (
    nightly_pause_sentinel_path,
    nightly_run_is_paused,
    run_nightly,
)


@click.group(name="nightly")
def nightly_cmd() -> None:
    """Phase 17 nightly_run orchestrator commands."""


@nightly_cmd.command("run")
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
    help="Run search+score but skip enqueue (useful before bedtime to preview the queue).",
)
def nightly_run_cmd(
    tenant: str, profile: str, search_profile: str | None, top_n: int, dry_run: bool
) -> None:
    """Run one nightly pass synchronously and print the report JSON."""
    report = asyncio.run(
        run_nightly(
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


@nightly_cmd.command("enqueue")
@click.option("--profile", default="default", help="Applicant profile id.")
@click.option("--search-profile", default=None)
@click.option("--top-n", type=int, default=10)
@click.option("--dry-run/--no-dry-run", default=False)
def nightly_enqueue_cmd(
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
        "orchestration.nightly_run", kwargs=payload
    )
    click.echo(json.dumps({"task_id": str(async_result.id)}))


@nightly_cmd.command("status")
def nightly_status_cmd() -> None:
    """Print pause-sentinel status."""
    paused = nightly_run_is_paused()
    path = nightly_pause_sentinel_path()
    click.echo(
        json.dumps(
            {"paused": paused, "sentinel_path": str(path)},
            indent=2,
        )
    )


@click.command("pause-nightly")
def pause_nightly_cmd() -> None:
    """Phase 17.7 kill switch: create the pause sentinel.

    Idempotent. While the sentinel exists, ``run_nightly`` short-
    circuits with ``status="paused"`` -- both the Beat-driven tick and
    any manual ``autoapply nightly run`` invocation. The sentinel is a
    plain file under ``data/`` so an operator can also touch it by hand.
    """
    path = nightly_pause_sentinel_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("paused\n", encoding="utf-8")
    click.echo(json.dumps({"paused": True, "sentinel_path": str(path)}))


@click.command("resume-nightly")
def resume_nightly_cmd() -> None:
    """Lift the Phase 17.7 pause sentinel. Idempotent."""
    path = nightly_pause_sentinel_path()
    if path.exists():
        path.unlink()
    click.echo(json.dumps({"paused": False, "sentinel_path": str(path)}))

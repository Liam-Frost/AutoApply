"""``autoapply schedule ...`` (Phase 14.7).

Inspect + ad-hoc trigger Beat-driven schedules. The schedule itself
lives in :mod:`src.tasks.beat`; this CLI reads it and exposes a way
to enqueue any entry on demand without waiting for the next tick.
"""

from __future__ import annotations

import json
from typing import Any

import click

from src.tasks import celery_app
from src.tasks.beat import get_schedule


@click.group("schedule")
def schedule_cmd() -> None:
    """Inspect Beat schedule and trigger entries on demand."""


@schedule_cmd.command("list")
@click.option("--json", "as_json", is_flag=True)
def schedule_list(as_json: bool) -> None:
    """Show every Beat entry."""
    rows = []
    for name, entry in get_schedule().items():
        rows.append(
            {
                "name": name,
                "task": entry["task"],
                "schedule": _render_schedule(entry["schedule"]),
                "queue": entry.get("options", {}).get("queue", "maintenance"),
            }
        )
    if as_json:
        click.echo(json.dumps(rows, default=str))
        return
    if not rows:
        click.echo("no schedule entries")
        return
    click.echo(f"{'name':<28}  {'task':<32}  {'queue':<12}  schedule")
    for r in rows:
        click.echo(f"{r['name']:<28}  {r['task']:<32}  {r['queue']:<12}  {r['schedule']}")


@schedule_cmd.command("run-now")
@click.argument("entry_name")
def schedule_run_now(entry_name: str) -> None:
    """Enqueue a Beat entry immediately. Workers consume it normally."""
    schedule = get_schedule()
    if entry_name not in schedule:
        click.echo(f"no such schedule entry: {entry_name}", err=True)
        raise SystemExit(1)
    entry = schedule[entry_name]
    task_name: str = str(entry["task"])
    queue = entry.get("options", {}).get("queue", "maintenance")
    celery_app.send_task(
        task_name,
        queue=queue,
        headers={"x-autoapply-tenant": "default"},
    )
    click.echo(f"enqueued {task_name} on queue '{queue}'")


def _render_schedule(schedule: Any) -> str:
    """Pretty-print a celery ``crontab`` (or other schedule) for the
    list view. ``str(crontab)`` is verbose; we summarise the fields
    that AutoApply actually uses."""
    try:
        # crontab exposes ._orig_* attributes for the unprocessed strings.
        minute = getattr(schedule, "_orig_minute", str(getattr(schedule, "minute", "*")))
        hour = getattr(schedule, "_orig_hour", str(getattr(schedule, "hour", "*")))
        dow = getattr(schedule, "_orig_day_of_week", "*")
        dom = getattr(schedule, "_orig_day_of_month", "*")
        return f"cron({minute} {hour} {dom} * {dow})"
    except Exception:  # noqa: BLE001
        return repr(schedule)

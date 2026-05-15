"""Phase 14.7: smoke tests for the new CLI commands.

We use Click's ``CliRunner`` so no broker or worker process is needed.
The worker/beat commands have a ``--check`` flag we use to verify the
resolved Celery invocation without actually starting anything.
"""

from __future__ import annotations

from click.testing import CliRunner

from src.cli.cmd_schedule import schedule_cmd
from src.cli.cmd_tasks import tasks_cmd
from src.cli.cmd_worker import beat_cmd, worker_cmd


def test_worker_check_prints_invocation_with_default_queues() -> None:
    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["--check"])
    assert result.exit_code == 0, result.output
    assert "celery -A src.tasks worker" in result.output
    assert "search,materials,application,maintenance" in result.output
    assert "-c 2" in result.output


def test_worker_check_respects_queue_subset() -> None:
    result = CliRunner().invoke(
        worker_cmd, ["--queues", "search,materials", "--concurrency", "8", "--check"]
    )
    assert result.exit_code == 0
    assert "search,materials" in result.output
    assert "-c 8" in result.output


def test_worker_rejects_unknown_queue() -> None:
    result = CliRunner().invoke(worker_cmd, ["--queues", "ghost", "--check"])
    assert result.exit_code != 0
    assert "unknown queue" in result.output.lower()


def test_beat_check_uses_redbeat_scheduler() -> None:
    result = CliRunner().invoke(beat_cmd, ["--check"])
    assert result.exit_code == 0
    assert "redbeat.RedBeatScheduler" in result.output


def test_tasks_kinds_lists_every_known_name() -> None:
    from src.tasks.tasks import KNOWN_TASK_NAMES

    result = CliRunner().invoke(tasks_cmd, ["kinds"])
    assert result.exit_code == 0
    for name in KNOWN_TASK_NAMES:
        assert name in result.output


def test_tasks_list_handles_empty_state() -> None:
    """No tasks in the audit table (filter that won't match) should
    return a friendly message, not blow up."""
    result = CliRunner().invoke(
        tasks_cmd, ["list", "--kind", "this.task.does.not.exist"]
    )
    assert result.exit_code == 0


def test_schedule_list_renders_all_six_entries() -> None:
    result = CliRunner().invoke(schedule_cmd, ["list"])
    assert result.exit_code == 0
    for name in (
        "daily_search",
        "jd_health_check",
        "application_status_sync",
        "linkedin_cookie_refresh",
        "cache_eviction",
        "gate_expire_sweep",
    ):
        assert name in result.output


def test_schedule_list_json_outputs_structured_payload() -> None:
    import json

    result = CliRunner().invoke(schedule_cmd, ["list", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert isinstance(parsed, list) and len(parsed) >= 6
    assert {"name", "task", "queue", "schedule"} <= set(parsed[0].keys())


def test_schedule_run_now_rejects_unknown_entry() -> None:
    result = CliRunner().invoke(schedule_cmd, ["run-now", "ghost-entry"])
    assert result.exit_code != 0
    assert "no such schedule entry" in result.output.lower()


def test_main_cli_registers_new_commands() -> None:
    from src.cli.main import cli

    names = {c.name for c in cli.commands.values()}
    assert {"worker", "beat", "tasks", "schedule"} <= names

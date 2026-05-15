"""``autoapply worker`` and ``autoapply beat`` (Phase 14.7).

Thin wrappers over ``celery -A src.tasks worker`` / ``celery -A src.tasks beat``.
They exist so operators do not need to know the Celery invocation
incantation and so we can layer AutoApply-specific defaults (queues,
prefetch, concurrency) without losing the underlying knobs.
"""

from __future__ import annotations

import logging

import click

from src.tasks import celery_app  # noqa: F401 -- side-effect: register signal handlers + beat
from src.tasks.app import QUEUES

logger = logging.getLogger(__name__)


def _validate_queues(ctx: click.Context, param: click.Parameter, value: str) -> list[str]:
    if not value:
        return list(QUEUES)
    raw = [q.strip() for q in value.split(",") if q.strip()]
    unknown = sorted(set(raw) - set(QUEUES))
    if unknown:
        raise click.BadParameter(f"unknown queue(s): {unknown}; known: {list(QUEUES)}")
    return raw


@click.command("worker")
@click.option(
    "--queues",
    "-Q",
    default=",".join(QUEUES),
    callback=_validate_queues,
    help="Comma-separated queue names to consume. Default: all four.",
)
@click.option(
    "--concurrency",
    "-c",
    default=2,
    type=click.IntRange(min=1, max=64),
    help="Worker concurrency (process pool size). Long tasks prefer low values.",
)
@click.option(
    "--loglevel",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error"]),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print the resolved invocation and exit instead of starting the worker.",
)
def worker_cmd(queues: list[str], concurrency: int, loglevel: str, check: bool) -> None:
    """Start a Celery worker consuming AutoApply task queues."""
    argv = [
        "worker",
        "-Q",
        ",".join(queues),
        "-c",
        str(concurrency),
        "-l",
        loglevel,
    ]
    if check:
        click.echo(f"celery -A src.tasks {' '.join(argv)}")
        return
    from src.tasks import celery_app as app

    app.worker_main(argv=argv)


@click.command("beat")
@click.option(
    "--loglevel",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error"]),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print the resolved invocation and exit instead of starting Beat.",
)
def beat_cmd(loglevel: str, check: bool) -> None:
    """Start Celery Beat (cron triggers; uses redbeat for multi-instance safety)."""
    if check:
        click.echo("celery -A src.tasks beat -S redbeat.RedBeatScheduler -l " + loglevel)
        return
    from src.tasks import celery_app as app

    app.start(
        argv=[
            "celery",
            "beat",
            "-S",
            "redbeat.RedBeatScheduler",
            "-l",
            loglevel,
        ]
    )

"""AutoApply CLI entry point.

Provides the top-level command group and shared options.

Usage:
    autoapply init          — First-time setup (DB, profile, config)
    autoapply search        — Find matching jobs
    autoapply apply         — Run application pipeline
    autoapply status        — View application tracking & analytics
"""

from __future__ import annotations

import logging

import click


def _setup_logging(verbose: bool) -> None:
    """Configure logging for CLI usage."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """AutoApply - AI-powered job application automation."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


# Import and register sub-commands
from src.cli.cmd_apply import apply_cmd  # noqa: E402
from src.cli.cmd_eval import eval_cmd  # noqa: E402
from src.cli.cmd_init import init_cmd  # noqa: E402
from src.cli.cmd_search import search_cmd  # noqa: E402
from src.cli.cmd_status import status_cmd  # noqa: E402
from src.cli.cmd_web import web_cmd  # noqa: E402

cli.add_command(init_cmd, "init")
cli.add_command(search_cmd, "search")
cli.add_command(apply_cmd, "apply")
cli.add_command(status_cmd, "status")
cli.add_command(web_cmd, "web")
cli.add_command(eval_cmd, "eval")


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()

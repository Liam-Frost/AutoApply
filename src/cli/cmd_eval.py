"""`autoapply eval` -- run agent eval suites and report scores."""

from __future__ import annotations

import json
import sys

import click

from src.agent.eval.runner import list_suites, run_suite


@click.command("eval")
@click.option("--suite", "suite_name", default=None, help="Suite to run.")
@click.option(
    "--list",
    "list_only",
    is_flag=True,
    help="List built-in suites and exit.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the full report as JSON instead of a summary.",
)
@click.option(
    "--min-pass-rate",
    type=float,
    default=None,
    help="Exit non-zero if pass rate falls below this value (0..1).",
)
def eval_cmd(
    suite_name: str | None,
    list_only: bool,
    as_json: bool,
    min_pass_rate: float | None,
) -> None:
    """Run agent regression evaluations."""
    suites = list_suites()
    if list_only or not suite_name:
        click.echo("Available suites:")
        for name in suites:
            click.echo(f"  {name}")
        if not suite_name and not list_only:
            click.echo("\nPass --suite NAME to run one.")
        return

    if suite_name not in suites:
        click.echo(f"Unknown suite '{suite_name}'. Available: {suites}.", err=True)
        sys.exit(2)

    report = run_suite(suite_name)

    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        click.echo(
            f"Suite: {report.suite}  "
            f"{report.passed_count}/{report.total} passed  "
            f"({report.pass_rate * 100:.1f}%)"
        )
        for case in report.cases:
            mark = "PASS" if case.passed else "FAIL"
            click.echo(f"  [{mark}] {case.case_id}  ({case.elapsed_ms} ms)")
            if case.error:
                click.echo(f"        error: {case.error}")
            for exp in case.expectations:
                if not exp.passed:
                    click.echo(f"        - {exp.type}: {exp.detail}")

    if min_pass_rate is not None and report.pass_rate < min_pass_rate:
        click.echo(
            f"Pass rate {report.pass_rate:.2%} below threshold "
            f"{min_pass_rate:.2%}.",
            err=True,
        )
        sys.exit(1)

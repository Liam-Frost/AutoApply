"""``autoapply status`` -- view application tracking dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from src.application.tracking import (
    export_applications_csv_data,
)
from src.application.tracking import (
    load_status_data as load_status_data_usecase,
)
from src.cli.output import emit_json

logger = logging.getLogger("autoapply.cli.status")


@click.command("status")
@click.option("--export-csv", type=click.Path(path_type=Path), help="Export applications to CSV.")
@click.option("--company", help="Filter by company name.")
@click.option("--status", "app_status", help="Filter by application status.")
@click.option("--outcome", help="Filter by outcome (pending/rejected/oa/interview/offer).")
@click.option("--limit", default=20, help="Number of recent applications to show.")
@click.option("--json", "as_json", is_flag=True, help="Output structured JSON for agents.")
def status_cmd(
    export_csv: Path | None,
    company: str | None,
    app_status: str | None,
    outcome: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """View application tracking dashboard and analytics."""
    if export_csv:
        result = export_applications_csv_data(output_path=export_csv)
        if as_json:
            emit_json({"command": "status", "mode": "export_csv", **result})
        elif result["ok"]:
            click.secho(f"Exported to {export_csv}", fg="green")
        else:
            click.secho(f"Database connection failed: {result['error']}", fg="red")
            click.echo("Run `autoapply init` first to set up the database.")

        if not result["ok"]:
            raise SystemExit(1)
        return

    result = load_status_data_usecase(
        company=company,
        app_status=app_status,
        outcome=outcome,
        limit=limit,
    )

    if as_json:
        emit_json({"command": "status", "mode": "report", **result})
    elif result["ok"]:
        _render_status_report(result)
    elif result["error_code"] == "schema_out_of_date":
        click.secho("Database schema is out of date for the current code.", fg="red")
        click.echo("Run `uv run alembic upgrade head` or `uv run autoapply init` and try again.")
    else:
        click.secho(f"Database connection failed: {result['error']}", fg="red")
        click.echo("Run `autoapply init` first to set up the database.")

    if not result["ok"]:
        raise SystemExit(1)


def _render_status_report(result: dict) -> None:
    summary = result["pipeline_summary"]
    outcomes = result["outcomes"]
    platforms = result["platforms"]
    companies = result["companies"]

    click.echo("=" * 60)
    click.echo("  AutoApply -- Application Status Report")
    click.echo("=" * 60)
    click.echo()

    click.echo("  Pipeline Overview")
    click.echo("  " + "-" * 40)
    click.echo(f"    Total discovered:   {summary['total_discovered']}")
    click.echo(f"    Applied (submitted): {summary['total_applied']}")
    click.echo(f"    Failed:             {summary['total_failed']}")
    click.echo(f"    Awaiting review:    {summary['total_review']}")
    if summary["avg_match_score"] > 0:
        click.echo(f"    Avg match score:    {summary['avg_match_score']:.0%}")
    if summary["avg_fields_filled_pct"] > 0:
        click.echo(f"    Avg form fill rate: {summary['avg_fields_filled_pct']:.0%}")
    click.echo()

    if outcomes["total"] > 0:
        click.echo("  Outcomes (submitted applications)")
        click.echo("  " + "-" * 40)
        click.echo(f"    Submitted:  {outcomes['total']}")
        click.echo(f"    Pending:    {outcomes['pending']}")
        click.echo(f"    Rejected:   {outcomes['rejected']}")
        click.echo(f"    OA:         {outcomes['oa']}")
        click.echo(f"    Interview:  {outcomes['interview']}")
        click.echo(f"    Offer:      {outcomes['offer']}")
        click.echo(f"    Response rate:  {outcomes['rates']['response_rate']:.0%}")
        click.echo(f"    Positive rate:  {outcomes['rates']['positive_rate']:.0%}")
        click.echo()

    if platforms:
        click.echo("  By Platform")
        click.echo("  " + "-" * 40)
        for ats, status_counts in sorted(platforms.items()):
            total = sum(status_counts.values())
            submitted = status_counts.get("SUBMITTED", 0)
            failed = status_counts.get("FAILED", 0)
            click.echo(f"    {ats:15s}  total={total}  submitted={submitted}  failed={failed}")
        click.echo()

    if companies:
        click.echo("  Top Companies")
        click.echo("  " + "-" * 40)
        for item in companies[:10]:
            outcome_str = ""
            if item["outcomes"]:
                parts = [f"{key}={value}" for key, value in item["outcomes"].items()]
                outcome_str = f"  ({', '.join(parts)})"
            score_str = (
                f"  score={item['avg_match_score']:.0%}" if item["avg_match_score"] > 0 else ""
            )
            click.echo(
                f"    {item['company']:20s}  apps={item['applications']}  "
                f"submitted={item['submitted']}{score_str}{outcome_str}"
            )
        click.echo()

    recent = result["recent_applications"]
    if recent:
        click.echo("  Recent Applications")
        click.echo("  " + "-" * 40)
        for item in recent:
            status_color = _status_color(item["status"])
            click.secho(f"    {item['status']:20s}", fg=status_color, nl=False)
            click.echo(f"  {item['job']['company']} - {item['job']['title']}")
            if item.get("outcome") and item["outcome"] != "pending":
                click.echo(f"    {'':20s}  outcome: {item['outcome']}")
            if item.get("match_score"):
                click.echo(f"    {'':20s}  score: {item['match_score']:.0%}")
        click.echo()
    else:
        click.echo("  No applications found.")
        click.echo()


def _status_color(status: str) -> str:
    colors = {
        "SUBMITTED": "green",
        "REVIEW_REQUIRED": "cyan",
        "FAILED": "red",
        "NEEDS_RETRY": "yellow",
    }
    return colors.get(status, "white")

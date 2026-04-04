"""``autoapply status`` -- view application tracking dashboard.

Displays pipeline stats, outcome breakdown, and recent applications.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

logger = logging.getLogger("autoapply.cli.status")


@click.command("status")
@click.option("--export-csv", type=click.Path(path_type=Path), help="Export applications to CSV.")
@click.option("--company", help="Filter by company name.")
@click.option("--status", "app_status", help="Filter by application status.")
@click.option("--outcome", help="Filter by outcome (pending/rejected/oa/interview/offer).")
@click.option("--limit", default=20, help="Number of recent applications to show.")
def status_cmd(
    export_csv: Path | None,
    company: str | None,
    app_status: str | None,
    outcome: str | None,
    limit: int,
) -> None:
    """View application tracking dashboard and analytics."""
    from src.core.config import load_config
    from src.core.database import get_session_factory

    try:
        config = load_config()
        session_factory = get_session_factory(config)
    except Exception as e:
        click.secho(f"Database connection failed: {e}", fg="red")
        click.echo("Run `autoapply init` first to set up the database.")
        raise SystemExit(1)

    with session_factory() as session:
        # CSV export
        if export_csv:
            from src.tracker.export import export_applications_csv

            export_applications_csv(session, output_path=export_csv)
            click.secho(f"Exported to {export_csv}", fg="green")
            return

        # Full report
        from src.tracker.analytics import (
            compute_company_stats,
            compute_outcome_stats,
            compute_pipeline_stats,
            compute_platform_stats,
        )
        from src.tracker.database import get_applications_with_jobs
        from src.tracker.export import format_status_report

        pipeline = compute_pipeline_stats(session)
        outcomes = compute_outcome_stats(session)
        companies = compute_company_stats(session)
        platforms = compute_platform_stats(session)

        report = format_status_report(pipeline, outcomes, companies, platforms)
        click.echo(report)

        # Recent applications list (single joined query)
        recent = get_applications_with_jobs(
            session,
            status=app_status,
            outcome=outcome,
            company=company,
            limit=limit,
        )

        if recent:
            click.echo("  Recent Applications")
            click.echo("  " + "-" * 40)
            for app, job in recent:
                status_color = _status_color(app.status)
                click.secho(f"    {app.status:20s}", fg=status_color, nl=False)
                click.echo(f"  {job.company} - {job.title}")
                if app.outcome:
                    click.echo(f"    {'':20s}  outcome: {app.outcome}")
                if app.match_score:
                    click.echo(f"    {'':20s}  score: {app.match_score:.0%}")
            click.echo()
        else:
            click.echo("  No applications found.")
            click.echo()


def _status_color(status: str) -> str:
    """Map status to click color."""
    colors = {
        "SUBMITTED": "green",
        "REVIEW_REQUIRED": "cyan",
        "FAILED": "red",
        "NEEDS_RETRY": "yellow",
    }
    return colors.get(status, "white")

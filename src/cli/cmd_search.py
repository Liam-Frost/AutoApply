"""``autoapply search`` -- find matching jobs."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click

from src.application.jobs import search_jobs as search_jobs_usecase
from src.cli.output import build_json_payload, emit_json
from src.core.config import PROJECT_ROOT

logger = logging.getLogger("autoapply.cli.search")


@click.command("search")
@click.option("--profile", default="", help="Optional filter profile name from filters.yaml.")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, path_type=Path),
    default=PROJECT_ROOT / "config",
    help="Config directory (contains companies.yaml, filters.yaml).",
)
@click.option("--no-parse", is_flag=True, help="Skip JD parsing for requirements.")
@click.option("--use-llm", is_flag=True, help="Use LLM for JD parsing (slower, more accurate).")
@click.option(
    "--source",
    type=click.Choice(["ats", "linkedin", "all"]),
    default="ats",
    help="Job source: 'ats' (Greenhouse/Lever), 'linkedin', or 'all'.",
)
@click.option("--ats", type=click.Choice(["greenhouse", "lever"]), help="Only scrape this ATS.")
@click.option("--company", help="Only scrape this company slug.")
@click.option("--score", is_flag=True, help="Score and rank results against your profile.")
@click.option("--keyword", help="LinkedIn search keywords (e.g. 'software engineer intern').")
@click.option(
    "--location", "search_location", help="LinkedIn location filter (e.g. 'United States')."
)
@click.option(
    "--time-filter",
    type=click.Choice(["24h", "week", "month"]),
    default="week",
    help="LinkedIn time posted filter.",
)
@click.option("--max-pages", default=20, help="Max LinkedIn result pages to scrape.")
@click.option("--no-enrich", is_flag=True, help="Skip LinkedIn detail page enrichment.")
@click.option("--headless/--no-headless", default=False, help="Run LinkedIn browser headless.")
@click.option("--json", "as_json", is_flag=True, help="Output structured JSON for agents.")
def search_cmd(
    profile: str,
    config_dir: Path,
    no_parse: bool,
    use_llm: bool,
    source: str,
    ats: str | None,
    company: str | None,
    score: bool,
    keyword: str | None,
    search_location: str | None,
    time_filter: str,
    max_pages: int,
    no_enrich: bool,
    headless: bool,
    as_json: bool,
) -> None:
    """Search for matching jobs from ATS boards and/or LinkedIn."""
    result = asyncio.run(
        search_jobs_usecase(
            profile=profile,
            config_dir=config_dir,
            no_parse=no_parse,
            use_llm=use_llm,
            source=source,
            ats=ats,
            company=company,
            score=score,
            keyword=keyword,
            search_location=search_location,
            time_filter=time_filter,
            max_pages=max_pages,
            no_enrich=no_enrich,
            headless=headless,
            require_keyword_for_linkedin=True,
            warn_on_missing_profile=score,
            allow_public_linkedin_fallback=True,
        )
    )

    if as_json:
        emit_json(
            build_json_payload(command="search", data={"ok": not bool(result["errors"]), **result})
        )
    else:
        _render_search_result(
            result, source=source, use_llm=use_llm, no_parse=no_parse, score=score
        )

    if source == "linkedin" and not keyword:
        raise SystemExit(1)


def _render_search_result(
    result: dict,
    *,
    source: str,
    use_llm: bool,
    no_parse: bool,
    score: bool,
) -> None:
    counts = result["counts"]

    if source in ("ats", "all"):
        if use_llm and not no_parse:
            click.echo(
                "ATS boards: LLM-assisted JD parsing is enabled. "
                "This search may take longer while local LLM CLIs process descriptions."
            )
        click.echo(f"ATS boards: {counts['ats']} jobs found")

    if source in ("linkedin", "all") and result["search_params"]["keyword"]:
        click.echo(
            f"LinkedIn: {counts['linkedin']} jobs found "
            f"({counts['linkedin_external_ats']} with external apply links)"
        )

    for error in result["errors"]:
        click.secho(error, fg="yellow")

    jobs = result["jobs"]
    if not jobs:
        click.secho("No jobs found.", fg="yellow")
        return

    if score:
        _print_ranked_results(jobs)
    else:
        _print_results(jobs)


def _print_ranked_results(jobs: list[dict]) -> None:
    ranked_jobs = [job for job in jobs if not job.get("disqualified")]

    click.echo(f"\n{'=' * 80}")
    click.secho(
        f" Top {min(len(ranked_jobs), 20)} matches (of {len(ranked_jobs)} qualified)",
        fg="cyan",
        bold=True,
    )
    click.echo(f"{'=' * 80}\n")

    for index, job in enumerate(ranked_jobs[:20], 1):
        match_score = job.get("match_score") or 0.0
        if match_score >= 0.7:
            color = "green"
        elif match_score >= 0.4:
            color = "yellow"
        else:
            color = "red"

        source_tag = f" [{job['source']}]" if job["source"] == "linkedin" else ""
        click.secho(f"  [{index:3d}] {match_score:.0%}  ", fg=color, nl=False)
        click.echo(f"{job['company']} - {job['title']}{source_tag}")

        parts = []
        if job.get("location"):
            parts.append(job["location"])
        if job.get("employment_type") and job["employment_type"] != "unknown":
            parts.append(job["employment_type"])
        if parts:
            click.echo(f"        {' | '.join(parts)}")
        if job.get("application_url"):
            click.echo(f"        {job['application_url']}")
        click.echo()


def _print_results(jobs: list[dict]) -> None:
    click.echo(f"\n{'=' * 80}")
    click.echo(f" Found {len(jobs)} matching jobs")
    click.echo(f"{'=' * 80}\n")

    for index, job in enumerate(jobs, 1):
        click.echo(f"  [{index:3d}] {job['company']} - {job['title']}")
        parts = []
        if job.get("location"):
            parts.append(job["location"])
        if job.get("employment_type") and job["employment_type"] != "unknown":
            parts.append(job["employment_type"])
        if parts:
            click.echo(f"        {' | '.join(parts)}")
        if job.get("application_url"):
            click.echo(f"        {job['application_url']}")
        click.echo()

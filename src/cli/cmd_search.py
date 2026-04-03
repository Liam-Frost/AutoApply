"""``autoapply search`` -- find matching jobs.

Wraps the existing intake/search module with the Click CLI interface.
Supports both ATS board scraping and LinkedIn search.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from src.core.config import PROJECT_ROOT

logger = logging.getLogger("autoapply.cli.search")


@click.command("search")
@click.option("--profile", default="default", help="Filter profile name from filters.yaml.")
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
# LinkedIn-specific options
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
@click.option("--max-pages", default=5, help="Max LinkedIn result pages to scrape.")
@click.option("--no-enrich", is_flag=True, help="Skip LinkedIn detail page enrichment.")
@click.option("--headless/--no-headless", default=False, help="Run LinkedIn browser headless.")
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
) -> None:
    """Search for matching jobs from ATS boards and/or LinkedIn."""
    from src.intake.search import _print_results, search_jobs

    all_jobs = []

    # ATS board search
    if source in ("ats", "all"):
        companies = None
        if ats and company:
            companies = {ats: [company]}
        elif company:
            companies = {"greenhouse": [company], "lever": [company]}
        elif ats:
            from src.intake.batch import load_company_list

            all_companies = load_company_list(config_dir / "companies.yaml")
            companies = {ats: all_companies.get(ats, [])}

        ats_jobs = search_jobs(
            profile=profile,
            config_dir=config_dir,
            companies=companies,
            parse_jds=not no_parse,
            use_llm=use_llm,
        )
        click.echo(f"ATS boards: {len(ats_jobs)} jobs found")
        all_jobs.extend(ats_jobs)

    # LinkedIn search
    if source in ("linkedin", "all"):
        if not keyword:
            click.secho(
                "LinkedIn search requires --keyword. "
                "Example: autoapply search --source linkedin --keyword 'swe intern'",
                fg="red",
            )
            if source == "linkedin":
                raise SystemExit(1)
        else:
            from src.intake.search import search_linkedin_sync

            click.echo(f"Searching LinkedIn for '{keyword}'...")
            linkedin_jobs = search_linkedin_sync(
                keywords=keyword,
                location=search_location or "",
                time_filter=time_filter,
                max_pages=max_pages,
                enrich_details=not no_enrich,
                headless=headless,
                filter_profile=profile if source == "all" else None,
                config_dir=config_dir,
            )

            # Show ATS redirect stats
            ats_redirected = sum(1 for j in linkedin_jobs if j.ats_type in ("greenhouse", "lever"))
            click.echo(
                f"LinkedIn: {len(linkedin_jobs)} jobs found "
                f"({ats_redirected} with external ATS links)"
            )
            all_jobs.extend(linkedin_jobs)

    if not all_jobs:
        click.secho("No jobs found.", fg="yellow")
        return

    if score:
        _score_and_print(all_jobs, config_dir)
    else:
        _print_results(all_jobs)


def _score_and_print(jobs, config_dir: Path) -> None:
    """Score jobs against the applicant profile and print ranked results."""
    from src.matching.scorer import build_scoring_context, score_jobs
    from src.memory.profile import load_profile_yaml

    profile_path = PROJECT_ROOT / "data" / "profile" / "profile.yaml"
    if not profile_path.exists():
        click.secho(
            "No profile found -- run `autoapply init` first to enable scoring.",
            fg="yellow",
        )
        from src.intake.search import _print_results

        _print_results(jobs)
        return

    profile_data = load_profile_yaml(profile_path)
    scoring_ctx = build_scoring_context(profile_data)

    click.echo(f"\nScoring {len(jobs)} jobs against your profile...")
    ranked = score_jobs(jobs, scoring_ctx)
    job_by_id = {str(job.id): job for job in jobs}
    ranked_jobs = [
        (job_by_id[score.job_id], score.final_score)
        for score in ranked
        if not score.disqualified and score.job_id in job_by_id
    ]

    click.echo(f"\n{'=' * 80}")
    click.secho(
        f" Top {min(len(ranked_jobs), 20)} matches (of {len(ranked_jobs)} qualified)",
        fg="cyan",
        bold=True,
    )
    click.echo(f"{'=' * 80}\n")

    for i, (job, match_score) in enumerate(ranked_jobs[:20], 1):
        if match_score >= 0.7:
            color = "green"
        elif match_score >= 0.4:
            color = "yellow"
        else:
            color = "red"

        source_tag = f" [{job.source}]" if job.source == "linkedin" else ""
        click.secho(f"  [{i:3d}] {match_score:.0%}  ", fg=color, nl=False)
        click.echo(f"{job.company} - {job.title}{source_tag}")

        parts = []
        if job.location:
            parts.append(job.location)
        if job.employment_type != "unknown":
            parts.append(job.employment_type)
        if parts:
            click.echo(f"        {' | '.join(parts)}")
        if job.application_url:
            click.echo(f"        {job.application_url}")
        click.echo()

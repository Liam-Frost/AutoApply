"""``autoapply search`` — find matching jobs.

Wraps the existing intake/search module with the Click CLI interface.
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
@click.option("--ats", type=click.Choice(["greenhouse", "lever"]), help="Only scrape this ATS.")
@click.option("--company", help="Only scrape this company slug.")
@click.option("--score", is_flag=True, help="Score and rank results against your profile.")
def search_cmd(
    profile: str,
    config_dir: Path,
    no_parse: bool,
    use_llm: bool,
    ats: str | None,
    company: str | None,
    score: bool,
) -> None:
    """Search for matching jobs across configured ATS boards."""
    from src.intake.search import search_jobs, _print_results

    # Build company override
    companies = None
    if ats and company:
        companies = {ats: [company]}
    elif company:
        companies = {"greenhouse": [company], "lever": [company]}
    elif ats:
        from src.intake.batch import load_company_list
        all_companies = load_company_list(config_dir / "companies.yaml")
        companies = {ats: all_companies.get(ats, [])}

    jobs = search_jobs(
        profile=profile,
        config_dir=config_dir,
        companies=companies,
        parse_jds=not no_parse,
        use_llm=use_llm,
    )

    if score and jobs:
        _score_and_print(jobs, config_dir)
    else:
        _print_results(jobs)


def _score_and_print(jobs, config_dir: Path) -> None:
    """Score jobs against the applicant profile and print ranked results."""
    from src.memory.profile import load_profile_yaml
    from src.matching.scorer import score_jobs

    profile_path = PROJECT_ROOT / "data" / "profile" / "profile.yaml"
    if not profile_path.exists():
        click.secho("No profile found -- run `autoapply init` first to enable scoring.", fg="yellow")
        from src.intake.search import _print_results
        _print_results(jobs)
        return

    profile_data = load_profile_yaml(profile_path)

    click.echo(f"\nScoring {len(jobs)} jobs against your profile...")
    ranked = score_jobs(jobs, profile_data)

    click.echo(f"\n{'='*80}")
    click.secho(f" Top {min(len(ranked), 20)} matches (of {len(ranked)} total)", fg="cyan", bold=True)
    click.echo(f"{'='*80}\n")

    for i, (job, match_score) in enumerate(ranked[:20], 1):
        # Color by score
        if match_score >= 0.7:
            color = "green"
        elif match_score >= 0.4:
            color = "yellow"
        else:
            color = "red"

        click.secho(f"  [{i:3d}] {match_score:.0%}  ", fg=color, nl=False)
        click.echo(f"{job.company} - {job.title}")

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

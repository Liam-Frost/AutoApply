"""``autoapply apply`` -- run the application pipeline.

Orchestrates the full flow: search -> score -> generate materials -> fill forms.
Can operate in single-job mode or batch mode.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import click

from src.core.config import PROJECT_ROOT
from src.core.state_machine import AppStatus

logger = logging.getLogger("autoapply.cli.apply")


@click.command("apply")
@click.option("--url", help="Apply to a single job by URL.")
@click.option("--job-id", help="Apply to a job by its database UUID.")
@click.option(
    "--batch",
    is_flag=True,
    help="Batch mode: search, score, and apply to top matches.",
)
@click.option("--top-n", default=5, help="Number of top-scoring jobs to apply to in batch mode.")
@click.option(
    "--auto-submit",
    is_flag=True,
    help="Auto-submit applications (default: pause for review).",
)
@click.option("--headless/--no-headless", default=True, help="Run browser in headless mode.")
@click.option("--profile", default="default", help="Filter profile for batch mode.")
@click.option("--dry-run", is_flag=True, help="Generate materials only, do not open browser.")
def apply_cmd(
    url: str | None,
    job_id: str | None,
    batch: bool,
    top_n: int,
    auto_submit: bool,
    headless: bool,
    profile: str,
    dry_run: bool,
) -> None:
    """Run the application pipeline on one or more jobs."""
    if not url and not job_id and not batch:
        click.echo("Specify --url, --job-id, or --batch. See --help for details.")
        raise SystemExit(1)

    if url:
        asyncio.run(_apply_single_url(url, auto_submit, headless, dry_run))
    elif job_id:
        # Validate UUID format
        try:
            uuid.UUID(job_id)
        except ValueError:
            click.secho(f"Invalid job ID format: {job_id}", fg="red")
            raise SystemExit(1)
        asyncio.run(_apply_single_job_id(job_id, auto_submit, headless, dry_run))
    elif batch:
        asyncio.run(_apply_batch(profile, top_n, auto_submit, headless, dry_run))


async def _apply_single_url(
    url: str,
    auto_submit: bool,
    headless: bool,
    dry_run: bool,
) -> None:
    """Apply to a single job by URL."""
    click.echo(f"Applying to: {url}")

    # Detect ATS type from URL
    ats_type = _detect_ats_from_url(url)
    if not ats_type:
        click.secho("Could not detect ATS type from URL.", fg="red")
        click.echo("Supported: greenhouse (boards.greenhouse.io), lever (jobs.lever.co)")
        raise SystemExit(1)

    click.echo(f"Detected ATS: {ats_type}")

    # Load profile
    profile_data = _load_profile()
    if not profile_data:
        raise SystemExit(1)

    # Generate materials
    resume_path, cl_path, qa_responses = await _generate_materials(
        profile_data=profile_data,
        job_url=url,
        ats_type=ats_type,
    )

    if dry_run:
        click.secho("Dry run complete -- materials generated, not applying.", fg="cyan")
        return

    # Execute application
    result = await _execute_application(
        url=url,
        ats_type=ats_type,
        profile_data=profile_data,
        resume_path=resume_path,
        cover_letter_path=cl_path,
        qa_responses=qa_responses,
        auto_submit=auto_submit,
        headless=headless,
    )

    if result and result.status == AppStatus.SUBMITTED:
        click.secho("    Application submitted!", fg="green")
    elif result and result.status == AppStatus.REVIEW_REQUIRED:
        click.secho("    Paused for review (not auto-submitted).", fg="cyan")
    elif result and result.status == AppStatus.FAILED:
        click.secho(f"    Application failed: {result.error}", fg="red")


async def _apply_single_job_id(
    job_id: str,
    auto_submit: bool,
    headless: bool,
    dry_run: bool,
) -> None:
    """Apply to a job from the database by ID."""
    from src.core.config import load_config
    from src.core.database import get_session_factory
    from src.core.models import Job

    config = load_config()
    SessionFactory = get_session_factory(config)

    with SessionFactory() as session:
        job = session.get(Job, uuid.UUID(job_id))
        if not job:
            click.secho(f"Job {job_id} not found in database.", fg="red")
            raise SystemExit(1)

        if not job.application_url:
            click.secho(f"Job {job.title} at {job.company} has no application URL.", fg="red")
            raise SystemExit(1)

        click.echo(f"Applying to: {job.company} - {job.title}")
        click.echo(f"URL: {job.application_url}")

    await _apply_single_url(
        url=job.application_url,
        auto_submit=auto_submit,
        headless=headless,
        dry_run=dry_run,
    )


async def _apply_batch(
    filter_profile: str,
    top_n: int,
    auto_submit: bool,
    headless: bool,
    dry_run: bool,
) -> None:
    """Batch mode: search, score, and apply to top matches."""
    from src.intake.search import search_jobs
    from src.matching.scorer import score_jobs
    from src.utils.rate_limiter import RateLimiter, RateLimiterConfig

    click.echo(f"Batch mode: searching with profile '{filter_profile}'...")

    # Search and score
    jobs = search_jobs(profile=filter_profile, parse_jds=True)
    if not jobs:
        click.secho("No matching jobs found.", fg="yellow")
        return

    profile_data = _load_profile()
    if not profile_data:
        raise SystemExit(1)

    ranked = score_jobs(jobs, profile_data)
    top_jobs = ranked[:top_n]

    click.echo(f"Found {len(ranked)} matches, applying to top {len(top_jobs)}:")
    for i, (job, score) in enumerate(top_jobs, 1):
        click.echo(f"  [{i}] {score:.0%}  {job.company} - {job.title}")

    if not click.confirm("\nProceed?", default=True):
        return

    # Apply with rate limiting
    limiter = RateLimiter(RateLimiterConfig(min_delay=5, max_delay=15))
    results = {"submitted": 0, "review": 0, "failed": 0, "skipped": 0}

    for job, score in top_jobs:
        if not job.application_url:
            click.secho(f"  Skipping {job.company} - no URL", fg="yellow")
            results["skipped"] += 1
            continue

        if not await limiter.can_apply():
            click.secho("  Hourly application limit reached. Stopping.", fg="yellow")
            break

        click.echo(f"\n  Applying: {job.company} - {job.title}...")

        try:
            ats_type = _detect_ats_from_url(job.application_url)
            if not ats_type:
                click.secho("    Unknown ATS, skipping", fg="yellow")
                results["skipped"] += 1
                continue

            resume_path, cl_path, qa_responses = await _generate_materials(
                profile_data=profile_data,
                job_url=job.application_url,
                ats_type=ats_type,
            )

            if dry_run:
                results["skipped"] += 1
                click.secho("    Dry run -- skipped", fg="cyan")
                continue

            result = await _execute_application(
                url=job.application_url,
                ats_type=ats_type,
                profile_data=profile_data,
                resume_path=resume_path,
                cover_letter_path=cl_path,
                qa_responses=qa_responses,
                auto_submit=auto_submit,
                headless=headless,
            )

            if result and result.status == AppStatus.SUBMITTED:
                await limiter.record_application()
                results["submitted"] += 1
                click.secho("    Submitted", fg="green")
            elif result and result.status == AppStatus.REVIEW_REQUIRED:
                results["review"] += 1
                click.secho("    Paused for review", fg="cyan")
            else:
                results["failed"] += 1
                click.secho("    Failed", fg="red")

        except Exception as e:
            click.secho(f"    Failed: {e}", fg="red")
            results["failed"] += 1
            await limiter.error_cooldown()

    click.echo(
        f"\nBatch complete: {results['submitted']} submitted, "
        f"{results['review']} review, "
        f"{results['failed']} failed, {results['skipped']} skipped"
    )


async def _generate_materials(
    profile_data: dict,
    job_url: str,
    ats_type: str,
) -> tuple[Path | None, Path | None, dict[str, str] | None]:
    """Generate resume, cover letter, and QA responses for a job.

    Returns (resume_path, cover_letter_path, qa_responses).
    Selects the most recently modified resume/cover letter from output dir.
    Full per-job generation will be added when the generation layer is wired in.
    """
    output_dir = PROJECT_ROOT / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Select most recent resume and cover letter by modification time
    resume_candidates = sorted(
        list(output_dir.glob("resume_*.pdf")) + list(output_dir.glob("resume_*.docx")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    resume_path = resume_candidates[0] if resume_candidates else None

    cl_candidates = sorted(
        list(output_dir.glob("cover_*.pdf")) + list(output_dir.glob("cover_*.docx")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    cl_path = cl_candidates[0] if cl_candidates else None

    if resume_path:
        click.echo(f"    Resume: {resume_path.name}")
    else:
        click.secho("    No resume found in data/output/", fg="yellow")

    if cl_path:
        click.echo(f"    Cover letter: {cl_path.name}")

    return resume_path, cl_path, None


async def _execute_application(
    url: str,
    ats_type: str,
    profile_data: dict,
    resume_path: Path | None,
    cover_letter_path: Path | None,
    qa_responses: dict[str, str] | None,
    auto_submit: bool,
    headless: bool,
):
    """Execute the browser-based application workflow.

    Returns the ApplicationResult from the adapter.
    """
    from src.execution.browser import BrowserManager
    from src.execution.ats.greenhouse import GreenhouseAdapter
    from src.execution.ats.lever import LeverAdapter
    from src.core.state_machine import ApplicationState

    adapter_map = {
        "greenhouse": GreenhouseAdapter,
        "lever": LeverAdapter,
    }
    adapter_cls = adapter_map.get(ats_type)
    if not adapter_cls:
        raise ValueError(f"No adapter for ATS type: {ats_type}")

    # Create state machine
    job_id = str(uuid.uuid4())
    state = ApplicationState(job_id)
    state.transition(AppStatus.QUALIFIED)
    state.transition(AppStatus.MATERIALS_READY)

    async with BrowserManager(headless=headless) as browser:
        adapter = adapter_cls(browser=browser)
        page = await browser.new_page()

        result = await adapter.apply(
            page=page,
            application_url=url,
            state=state,
            profile_data=profile_data,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            qa_responses=qa_responses,
            auto_submit=auto_submit,
        )

        # Log screenshots
        for ss in result.screenshots:
            click.echo(f"    Screenshot: {ss}")

        if result.status == AppStatus.REVIEW_REQUIRED and not headless:
            click.echo("    Browser is open -- review and submit manually if satisfied.")
            click.pause("    Press Enter when done...")

        return result


def _detect_ats_from_url(url: str) -> str | None:
    """Detect ATS type from application URL."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower:
        return "greenhouse"
    elif "lever.co" in url_lower:
        return "lever"
    return None


def _load_profile() -> dict | None:
    """Load applicant profile from YAML."""
    profile_path = PROJECT_ROOT / "data" / "profile" / "profile.yaml"
    if not profile_path.exists():
        click.secho("No profile found. Run `autoapply init` first.", fg="red")
        return None

    from src.memory.profile import load_profile_yaml
    return load_profile_yaml(profile_path)

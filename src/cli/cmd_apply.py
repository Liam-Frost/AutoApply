"""``autoapply apply`` -- run the application pipeline.

Orchestrates the full flow: search -> score -> generate materials -> fill forms.
Can operate in single-job mode or batch mode.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from urllib.parse import urlparse

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

    job = _load_job_for_application(url, ats_type)
    click.echo(f"Company: {job.company}")
    click.echo(f"Role: {job.title}")

    # Load profile
    profile_data = _load_profile()
    if not profile_data:
        raise SystemExit(1)

    result = await _run_application_for_job(
        job=job,
        profile_data=profile_data,
        auto_submit=auto_submit,
        headless=headless,
        dry_run=dry_run,
    )

    if dry_run or not result:
        return

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
    session_factory = get_session_factory(config)

    with session_factory() as session:
        job = session.get(Job, uuid.UUID(job_id))
        if not job:
            click.secho(f"Job {job_id} not found in database.", fg="red")
            raise SystemExit(1)

        if not job.application_url:
            click.secho(f"Job {job.title} at {job.company} has no application URL.", fg="red")
            raise SystemExit(1)

        click.echo(f"Applying to: {job.company} - {job.title}")
        click.echo(f"URL: {job.application_url}")

        raw_job = _job_to_raw_job(job)

    profile_data = _load_profile()
    if not profile_data:
        raise SystemExit(1)

    result = await _run_application_for_job(
        job=raw_job,
        profile_data=profile_data,
        auto_submit=auto_submit,
        headless=headless,
        dry_run=dry_run,
    )

    if dry_run or not result:
        return

    if result.status == AppStatus.SUBMITTED:
        click.secho("    Application submitted!", fg="green")
    elif result.status == AppStatus.REVIEW_REQUIRED:
        click.secho("    Paused for review (not auto-submitted).", fg="cyan")
    elif result.status == AppStatus.FAILED:
        click.secho(f"    Application failed: {result.error}", fg="red")


async def _apply_batch(
    filter_profile: str,
    top_n: int,
    auto_submit: bool,
    headless: bool,
    dry_run: bool,
) -> None:
    """Batch mode: search, score, and apply to top matches."""
    from src.intake.search import search_jobs
    from src.matching.scorer import build_scoring_context, score_jobs
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

    scoring_ctx = build_scoring_context(profile_data)
    ranked = score_jobs(jobs, scoring_ctx)
    job_by_id = {str(job.id): job for job in jobs}
    top_jobs = [
        (job_by_id[score.job_id], score.final_score)
        for score in ranked
        if not score.disqualified and score.job_id in job_by_id
    ][:top_n]

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

            result = await _run_application_for_job(
                job=job,
                profile_data=profile_data,
                auto_submit=auto_submit,
                headless=headless,
                dry_run=dry_run,
                match_score=score,
            )

            if dry_run:
                results["skipped"] += 1
                click.secho("    Dry run -- skipped", fg="cyan")
                continue

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
    job,
) -> tuple[Path | None, Path | None, dict[str, str] | None]:
    """Generate resume, cover letter, and QA responses for a job.

    Returns (resume_path, cover_letter_path, qa_responses).
    """
    from src.generation.cover_letter import generate_cover_letter
    from src.generation.qa_responder import answer_questions
    from src.generation.resume_builder import generate_resume

    output_dir = PROJECT_ROOT / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    resume_files = generate_resume(job=job, profile_data=profile_data, output_dir=output_dir)
    resume_path = resume_files.get("pdf") or resume_files.get("docx")

    cover_files = generate_cover_letter(job=job, profile_data=profile_data, output_dir=output_dir)
    cl_path = cover_files.get("txt")

    qa_entries = [
        entry
        for entry in profile_data.get("qa_bank", [])
        if isinstance(entry, dict) and entry.get("question_pattern")
    ]
    qa_responses = None
    if qa_entries:
        answers = answer_questions(
            questions=[entry["question_pattern"] for entry in qa_entries],
            job=job,
            profile_data=profile_data,
            qa_entries=qa_entries,
            use_llm=False,
        )
        qa_responses = {
            response.question: response.answer for response in answers if response.answer
        } or None

    if resume_path:
        click.echo(f"    Resume: {resume_path.name}")
    else:
        click.secho("    Resume generation failed", fg="red")

    if cl_path:
        click.echo(f"    Cover letter: {cl_path.name}")

    if qa_responses:
        click.echo(f"    QA templates loaded: {len(qa_responses)}")

    return resume_path, cl_path, qa_responses


async def _run_application_for_job(
    job,
    profile_data: dict,
    auto_submit: bool,
    headless: bool,
    dry_run: bool,
    match_score: float | None = None,
):
    """Generate materials, optionally track, and execute one application."""
    resume_path, cl_path, qa_responses = await _generate_materials(
        profile_data=profile_data, job=job
    )

    if not resume_path:
        click.secho("    Cannot continue without a generated resume.", fg="red")
        return None

    if dry_run:
        click.secho("Dry run complete -- materials generated, not applying.", fg="cyan")
        return None

    app_id = _create_tracking_application(
        job=job,
        match_score=match_score,
        resume_path=resume_path,
        cover_letter_path=cl_path,
    )

    from src.core.state_machine import ApplicationState

    state = ApplicationState(str(app_id or job.id))
    result = await _execute_application(
        url=job.application_url or "",
        ats_type=job.ats_type,
        profile_data=profile_data,
        resume_path=resume_path,
        cover_letter_path=cl_path,
        qa_responses=qa_responses,
        auto_submit=auto_submit,
        headless=headless,
        state=state,
    )

    if app_id:
        _sync_tracking_application(app_id, state, result, qa_responses)

    return result


async def _execute_application(
    url: str,
    ats_type: str,
    profile_data: dict,
    resume_path: Path | None,
    cover_letter_path: Path | None,
    qa_responses: dict[str, str] | None,
    auto_submit: bool,
    headless: bool,
    state=None,
):
    """Execute the browser-based application workflow.

    Returns the ApplicationResult from the adapter.
    """
    from src.core.state_machine import ApplicationState
    from src.execution.ats.greenhouse import GreenhouseAdapter
    from src.execution.ats.lever import LeverAdapter
    from src.execution.browser import BrowserManager

    adapter_map = {
        "greenhouse": GreenhouseAdapter,
        "lever": LeverAdapter,
    }
    adapter_cls = adapter_map.get(ats_type)
    if not adapter_cls:
        raise ValueError(f"No adapter for ATS type: {ats_type}")

    if state is None:
        state = ApplicationState(str(uuid.uuid4()))

    if state.status == AppStatus.DISCOVERED:
        state.transition(AppStatus.QUALIFIED)
    if state.status == AppStatus.QUALIFIED:
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
    elif "linkedin.com" in url_lower:
        # LinkedIn jobs should be redirected to external ATS first
        click.secho(
            "This is a LinkedIn URL. Use `autoapply search --source linkedin` "
            "to find the external ATS link first.",
            fg="yellow",
        )
        return None
    return None


def _load_profile() -> dict | None:
    """Load applicant profile from YAML."""
    profile_path = PROJECT_ROOT / "data" / "profile" / "profile.yaml"
    if not profile_path.exists():
        click.secho("No profile found. Run `autoapply init` first.", fg="red")
        return None

    from src.memory.profile import load_profile_yaml

    return load_profile_yaml(profile_path)


def _load_job_for_application(url: str, ats_type: str):
    """Load job context from DB or ATS API, falling back to URL-derived metadata."""
    db_job = _find_db_job_by_url(url)
    if db_job is not None:
        return _job_to_raw_job(db_job)

    fetched_job = _fetch_job_from_ats(url, ats_type)
    if fetched_job is not None:
        return fetched_job

    return _synthesize_job_from_url(url, ats_type)


def _find_db_job_by_url(url: str):
    """Try to find an existing Job record by application URL."""
    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.core.models import Job

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            return session.query(Job).filter(Job.application_url == url).first()
    except Exception as exc:
        logger.debug("DB lookup skipped for %s: %s", url, exc)
        return None


def _fetch_job_from_ats(url: str, ats_type: str):
    """Fetch a single ATS job posting using the public board APIs."""
    locator = _parse_ats_job_locator(url, ats_type)
    if locator is None:
        return None

    company_slug, job_id = locator

    try:
        if ats_type == "greenhouse":
            from src.intake.greenhouse import GreenhouseScraper

            with GreenhouseScraper() as scraper:
                return scraper.fetch_job(company_slug, job_id)
        if ats_type == "lever":
            from src.intake.lever import LeverScraper

            with LeverScraper() as scraper:
                return scraper.fetch_job(company_slug, job_id)
    except Exception as exc:
        logger.warning("Failed to fetch %s job details for %s: %s", ats_type, url, exc)

    return None


def _parse_ats_job_locator(url: str, ats_type: str) -> tuple[str, str] | None:
    """Extract company slug and ATS-native job ID from an application URL."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]

    if ats_type == "greenhouse":
        if len(parts) >= 3 and parts[1] == "jobs":
            return parts[0], parts[2]
        if "jobs" in parts:
            idx = parts.index("jobs")
            if idx > 0 and idx + 1 < len(parts):
                return parts[idx - 1], parts[idx + 1]

    if ats_type == "lever" and len(parts) >= 2:
        return parts[0], parts[1]

    return None


def _synthesize_job_from_url(url: str, ats_type: str):
    """Create a minimal job context when ATS lookup is unavailable."""
    from src.intake.schema import RawJob

    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    company = parts[0].replace("-", " ").replace("_", " ").title() if parts else parsed.netloc
    source_id = parts[-1] if parts else parsed.netloc

    return RawJob(
        source=ats_type,
        source_id=source_id,
        company=company or "Unknown Company",
        title="Unknown Role",
        application_url=url,
        ats_type=ats_type,
        description=None,
    )


def _job_to_raw_job(job):
    """Convert a persisted Job ORM object to the intake schema."""
    from src.intake.schema import JobRequirements, RawJob

    return RawJob(
        id=job.id,
        source=job.source or "unknown",
        source_id=job.source_id or str(job.id),
        company=job.company,
        title=job.title,
        location=job.location,
        employment_type=job.employment_type or "unknown",
        seniority=job.seniority or "unknown",
        description=job.description,
        requirements=JobRequirements.model_validate(job.requirements or {}),
        application_url=job.application_url,
        ats_type=job.ats_type or job.source or "unknown",
        raw_data=job.raw_data or {},
        discovered_at=job.discovered_at,
        expires_at=job.expires_at,
    )


def _create_tracking_application(
    job,
    match_score: float | None,
    resume_path: Path,
    cover_letter_path: Path | None,
) -> uuid.UUID | None:
    """Create or reuse a tracked Application record before execution."""
    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.tracker.database import create_application

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            db_job = _get_or_create_job_record(session, job)
            application = create_application(
                session,
                db_job.id,
                match_score=match_score,
                resume_version=str(resume_path),
                cover_letter_version=str(cover_letter_path) if cover_letter_path else None,
            )
            session.commit()
            return application.id
    except Exception as exc:
        logger.warning("Tracking create skipped for %s at %s: %s", job.title, job.company, exc)
        return None


def _sync_tracking_application(
    app_id: uuid.UUID, state, result, qa_responses: dict[str, str] | None
) -> None:
    """Persist execution results back into the Application record."""
    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.tracker.database import sync_state_to_db

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            sync_state_to_db(
                session,
                app_id,
                state,
                {
                    "fields_filled": result.fields_filled,
                    "fields_total": result.fields_total,
                    "files_uploaded": result.files_uploaded,
                    "qa_responses": qa_responses,
                    "screenshot_paths": [str(path) for path in result.screenshots],
                },
            )
            session.commit()
    except Exception as exc:
        logger.warning("Tracking sync skipped for application %s: %s", app_id, exc)


def _get_or_create_job_record(session, job):
    """Ensure a persisted Job record exists for tracking and reporting."""
    from src.core.models import Job

    existing = (
        session.query(Job)
        .filter(
            Job.source == job.source,
            Job.company == job.company,
            Job.source_id == job.source_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    if job.application_url:
        existing = session.query(Job).filter(Job.application_url == job.application_url).first()
        if existing is not None:
            return existing

    db_job = Job(
        id=job.id,
        source=job.source,
        source_id=job.source_id,
        company=job.company,
        title=job.title,
        location=job.location,
        employment_type=job.employment_type,
        seniority=job.seniority,
        description=job.description,
        requirements=job.requirements.model_dump(),
        visa_sponsorship=job.requirements.visa_sponsorship,
        ats_type=job.ats_type,
        application_url=job.application_url,
        raw_data=job.raw_data,
        discovered_at=job.discovered_at,
        expires_at=job.expires_at,
    )
    session.add(db_job)
    session.flush()
    return db_job

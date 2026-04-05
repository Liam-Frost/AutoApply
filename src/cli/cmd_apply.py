"""``autoapply apply`` -- run the application pipeline."""

from __future__ import annotations

import asyncio
import logging

import click

from src.application import jobs as jobs_application
from src.application.jobs import (
    apply_batch_jobs as apply_batch_jobs_usecase,
)
from src.application.jobs import (
    apply_to_job_id as apply_to_job_id_usecase,
)
from src.application.jobs import (
    apply_to_url as apply_to_url_usecase,
)
from src.cli.output import build_json_payload, emit_json
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
@click.option("--json", "as_json", is_flag=True, help="Output structured JSON for agents.")
def apply_cmd(
    url: str | None,
    job_id: str | None,
    batch: bool,
    top_n: int,
    auto_submit: bool,
    headless: bool,
    profile: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Run the application pipeline on one or more jobs."""
    if not url and not job_id and not batch:
        payload = {
            "ok": False,
            "error": "Specify --url, --job-id, or --batch. See --help for details.",
            "error_code": "missing_target",
        }
        if as_json:
            emit_json(build_json_payload(command="apply", data=payload))
        else:
            click.echo(payload["error"])
        raise SystemExit(1)

    if url:
        result = asyncio.run(
            apply_to_url_usecase(
                url=url,
                auto_submit=auto_submit,
                headless=headless,
                dry_run=dry_run,
            )
        )
        _emit_apply_result(result, as_json=as_json)
        if not result["ok"]:
            raise SystemExit(1)
        return

    if job_id:
        result = asyncio.run(
            apply_to_job_id_usecase(
                job_id=job_id,
                auto_submit=auto_submit,
                headless=headless,
                dry_run=dry_run,
            )
        )
        _emit_apply_result(result, as_json=as_json)
        if not result["ok"]:
            raise SystemExit(1)
        return

    selected_jobs, errors, total_matches = jobs_application._select_batch_jobs(profile, top_n)
    preview = {
        "profile": profile,
        "top_n": top_n,
        "available_matches": total_matches,
        "selected_jobs": [
            jobs_application.serialize_job(job, match_score=match_score)
            for job, match_score in selected_jobs
        ],
        "errors": errors,
    }

    if not selected_jobs:
        payload = {
            "mode": "batch",
            "ok": False,
            **preview,
            "summary": {
                "attempted": 0,
                "submitted": 0,
                "review": 0,
                "failed": 0,
                "skipped": 0,
                "dry_run": 0,
                "stopped_early": False,
                "stop_reason": None,
            },
        }
        if as_json:
            emit_json(build_json_payload(command="apply", data=payload))
        else:
            _render_batch_preview(preview)
        if preview["errors"] and any("Profile" in item for item in preview["errors"]):
            raise SystemExit(1)
        return

    if not as_json:
        _render_batch_preview(preview)
        if not click.confirm("\nProceed?", default=True):
            return

    result = asyncio.run(
        apply_batch_jobs_usecase(
            selected_jobs=selected_jobs,
            profile=profile,
            top_n=top_n,
            auto_submit=auto_submit,
            headless=headless,
            dry_run=dry_run,
        )
    )
    _emit_apply_result(result, as_json=as_json)


def _emit_apply_result(result: dict, *, as_json: bool) -> None:
    if as_json:
        emit_json(build_json_payload(command="apply", data=result))
        return

    if result["mode"] == "batch":
        _render_batch_result(result)
    else:
        _render_single_apply_result(result)


def _render_single_apply_result(result: dict) -> None:
    input_payload = result["input"]
    if result["mode"] == "url":
        click.echo(f"Applying to: {input_payload['url']}")
    elif result["mode"] == "job_id":
        click.echo(f"Applying to job ID: {input_payload['job_id']}")

    job = result.get("job")
    if job:
        click.echo(f"Company: {job['company']}")
        click.echo(f"Role: {job['title']}")
        if job.get("application_url"):
            click.echo(f"URL: {job['application_url']}")

    if result.get("error"):
        click.secho(result["error"], fg="red")
        return

    artifacts = result["artifacts"]
    if artifacts["resume_path"]:
        click.echo(f"Resume: {artifacts['resume_path']}")
    if artifacts["cover_letter_path"]:
        click.echo(f"Cover letter: {artifacts['cover_letter_path']}")
    if artifacts["qa_responses"]:
        click.echo(f"QA templates loaded: {len(artifacts['qa_responses'])}")

    status = result["status"]
    if status == "DRY_RUN":
        click.secho("Dry run complete -- materials generated, not applying.", fg="cyan")
    elif status == AppStatus.SUBMITTED:
        click.secho("Application submitted!", fg="green")
    elif status == AppStatus.REVIEW_REQUIRED:
        click.secho("Paused for review (not auto-submitted).", fg="cyan")
    elif status == AppStatus.FAILED:
        click.secho(f"Application failed: {result['result']['error']}", fg="red")


def _render_batch_preview(preview: dict) -> None:
    for error in preview["errors"]:
        click.secho(error, fg="yellow")

    selected_jobs = preview["selected_jobs"]
    if not selected_jobs:
        return

    click.echo(
        f"Found {preview['available_matches']} matches, applying to top {len(selected_jobs)}:"
    )
    for index, job in enumerate(selected_jobs, 1):
        click.echo(
            f"  [{index}] {job.get('match_score', 0.0):.0%}  {job['company']} - {job['title']}"
        )


def _render_batch_result(result: dict) -> None:
    for item in result["items"]:
        status = item["status"] or "UNKNOWN"
        job = item.get("job")
        job_label = (
            f"{job['company']} - {job['title']}"
            if job
            else item["input"].get("profile", "unknown job")
        )
        if status == AppStatus.SUBMITTED:
            color = "green"
        elif status == AppStatus.REVIEW_REQUIRED:
            color = "cyan"
        elif status in {"DRY_RUN", "SKIPPED"}:
            color = "yellow"
        else:
            color = "red"

        click.secho(f"{status:16s}", fg=color, nl=False)
        click.echo(f"  {job_label}")
        if item.get("error"):
            click.echo(f"                {item['error']}")

    summary = result["summary"]
    click.echo(
        f"\nBatch complete: {summary['submitted']} submitted, "
        f"{summary['review']} review, "
        f"{summary['failed']} failed, "
        f"{summary['skipped']} skipped, "
        f"{summary['dry_run']} dry-run"
    )
    if summary["stopped_early"]:
        click.secho("Stopped early due to rate limit.", fg="yellow")


def _detect_ats_from_url(url: str) -> str | None:
    return jobs_application._detect_ats_from_url(url)


def _load_profile() -> dict | None:
    return jobs_application._load_profile()


def _load_job_for_application(url: str, ats_type: str):
    return jobs_application._load_job_for_application(url, ats_type)


async def _generate_materials(profile_data: dict, job):
    return await jobs_application._generate_materials(profile_data, job)


def _parse_ats_job_locator(url: str, ats_type: str) -> tuple[str, str] | None:
    return jobs_application._parse_ats_job_locator(url, ats_type)

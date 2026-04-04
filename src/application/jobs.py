"""Job search and application use cases shared by CLI and Web."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from urllib.parse import urlparse

from src.core.config import PROJECT_ROOT
from src.core.state_machine import ApplicationState, AppStatus

logger = logging.getLogger("autoapply.application.jobs")

PROFILE_FILE = PROJECT_ROOT / "data" / "profile" / "profile.yaml"


async def search_jobs(
    *,
    profile: str = "default",
    config_dir: Path = PROJECT_ROOT / "config",
    no_parse: bool = False,
    use_llm: bool = False,
    source: str = "ats",
    ats: str | None = None,
    company: str | None = None,
    score: bool = False,
    keyword: str | None = None,
    search_location: str | None = None,
    time_filter: str = "week",
    max_pages: int = 5,
    no_enrich: bool = False,
    headless: bool = False,
    require_keyword_for_linkedin: bool = False,
    warn_on_missing_profile: bool = False,
) -> dict:
    jobs = []
    errors: list[str] = []
    counts = {"ats": 0, "linkedin": 0, "linkedin_external_ats": 0, "total": 0}

    if source in ("ats", "all"):
        try:
            from src.intake.search import search_jobs as search_ats_jobs

            ats_jobs = search_ats_jobs(
                profile=profile,
                config_dir=config_dir,
                companies=_build_companies_filter(config_dir, ats, company),
                parse_jds=not no_parse,
                use_llm=use_llm,
            )
            counts["ats"] = len(ats_jobs)
            jobs.extend(ats_jobs)
        except Exception as exc:
            errors.append(f"ATS: {exc}")

    if source in ("linkedin", "all"):
        if not keyword:
            if require_keyword_for_linkedin:
                errors.append("LinkedIn search requires --keyword.")
        else:
            try:
                from src.intake.search import search_linkedin

                linkedin_jobs = await search_linkedin(
                    keywords=keyword,
                    location=search_location or "",
                    time_filter=time_filter,
                    max_pages=max_pages,
                    enrich_details=not no_enrich,
                    headless=headless,
                    filter_profile=profile,
                    config_dir=config_dir,
                )
                counts["linkedin"] = len(linkedin_jobs)
                counts["linkedin_external_ats"] = sum(
                    1 for job in linkedin_jobs if job.ats_type in ("greenhouse", "lever")
                )
                jobs.extend(linkedin_jobs)
            except Exception as exc:
                errors.append(f"LinkedIn: {exc}")

    scored = False
    if score and jobs:
        scored, scoring_errors = _score_jobs(jobs, warn_on_missing_profile=warn_on_missing_profile)
        errors.extend(scoring_errors)

    counts["total"] = len(jobs)

    return {
        "search_params": {
            "profile": profile,
            "config_dir": str(config_dir),
            "no_parse": no_parse,
            "use_llm": use_llm,
            "source": source,
            "ats": ats,
            "company": company,
            "score": score,
            "keyword": keyword or "",
            "location": search_location or "",
            "time_filter": time_filter,
            "max_pages": max_pages,
            "no_enrich": no_enrich,
            "headless": headless,
        },
        "jobs": [serialize_job(job) for job in jobs],
        "errors": errors,
        "error": "; ".join(errors) or None,
        "counts": counts,
        "scored": scored,
    }


def preview_batch_jobs(*, profile: str = "default", top_n: int = 5) -> dict:
    selected_jobs, errors, total_matches = _select_batch_jobs(profile, top_n)
    return {
        "profile": profile,
        "top_n": top_n,
        "available_matches": total_matches,
        "selected_jobs": [
            serialize_job(job, match_score=match_score) for job, match_score in selected_jobs
        ],
        "errors": errors,
    }


async def apply_to_url(
    *,
    url: str,
    auto_submit: bool = False,
    headless: bool = True,
    dry_run: bool = False,
) -> dict:
    payload = {
        "mode": "url",
        "input": {"url": url},
    }

    ats_type = _detect_ats_from_url(url)
    if not ats_type:
        return {
            **payload,
            "ok": False,
            "status": None,
            "job": None,
            "tracking_id": None,
            "result": None,
            "artifacts": _empty_artifacts(),
            "error": _unsupported_ats_message(url),
            "error_code": "unsupported_ats",
            "dry_run": dry_run,
        }

    try:
        job = _load_job_for_application(url, ats_type)
    except Exception as exc:
        return {
            **payload,
            "ok": False,
            "status": None,
            "job": None,
            "tracking_id": None,
            "result": None,
            "artifacts": _empty_artifacts(),
            "error": f"Failed to load job context: {exc}",
            "error_code": "job_load_failed",
            "dry_run": dry_run,
        }

    profile_data = _load_profile()
    if not profile_data:
        return {
            **payload,
            "ok": False,
            "status": None,
            "job": serialize_job(job),
            "tracking_id": None,
            "result": None,
            "artifacts": _empty_artifacts(),
            "error": "Profile not configured.",
            "error_code": "profile_missing",
            "dry_run": dry_run,
        }

    return await _run_application_for_job(
        job=job,
        profile_data=profile_data,
        auto_submit=auto_submit,
        headless=headless,
        dry_run=dry_run,
        mode="url",
        input_payload=payload["input"],
    )


async def apply_to_job_id(
    *,
    job_id: str,
    auto_submit: bool = False,
    headless: bool = True,
    dry_run: bool = False,
) -> dict:
    payload = {
        "mode": "job_id",
        "input": {"job_id": job_id},
    }

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return {
            **payload,
            "ok": False,
            "status": None,
            "job": None,
            "tracking_id": None,
            "result": None,
            "artifacts": _empty_artifacts(),
            "error": f"Invalid job ID format: {job_id}",
            "error_code": "invalid_job_id",
            "dry_run": dry_run,
        }

    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.core.models import Job

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            db_job = session.get(Job, job_uuid)
            if db_job is None:
                return {
                    **payload,
                    "ok": False,
                    "status": None,
                    "job": None,
                    "tracking_id": None,
                    "result": None,
                    "artifacts": _empty_artifacts(),
                    "error": f"Job {job_id} not found in database.",
                    "error_code": "job_not_found",
                    "dry_run": dry_run,
                }

            if not db_job.application_url:
                return {
                    **payload,
                    "ok": False,
                    "status": None,
                    "job": serialize_job(_job_to_raw_job(db_job)),
                    "tracking_id": None,
                    "result": None,
                    "artifacts": _empty_artifacts(),
                    "error": f"Job {db_job.title} at {db_job.company} has no application URL.",
                    "error_code": "missing_application_url",
                    "dry_run": dry_run,
                }

            job = _job_to_raw_job(db_job)
    except Exception as exc:
        return {
            **payload,
            "ok": False,
            "status": None,
            "job": None,
            "tracking_id": None,
            "result": None,
            "artifacts": _empty_artifacts(),
            "error": f"Failed to load job from database: {exc}",
            "error_code": "job_load_failed",
            "dry_run": dry_run,
        }

    profile_data = _load_profile()
    if not profile_data:
        return {
            **payload,
            "ok": False,
            "status": None,
            "job": serialize_job(job),
            "tracking_id": None,
            "result": None,
            "artifacts": _empty_artifacts(),
            "error": "Profile not configured.",
            "error_code": "profile_missing",
            "dry_run": dry_run,
        }

    return await _run_application_for_job(
        job=job,
        profile_data=profile_data,
        auto_submit=auto_submit,
        headless=headless,
        dry_run=dry_run,
        mode="job_id",
        input_payload=payload["input"],
    )


async def apply_batch_jobs(
    *,
    selected_jobs: list[tuple],
    profile: str,
    top_n: int,
    auto_submit: bool = False,
    headless: bool = True,
    dry_run: bool = False,
) -> dict:
    profile_data = _load_profile()
    if not profile_data:
        return {
            "mode": "batch",
            "profile": profile,
            "top_n": top_n,
            "ok": False,
            "errors": ["Profile not configured."],
            "items": [],
            "summary": _batch_summary(),
            "dry_run": dry_run,
        }

    from src.utils.rate_limiter import RateLimiter, RateLimiterConfig

    limiter = RateLimiter(RateLimiterConfig(min_delay=5, max_delay=15))
    items = []
    summary = _batch_summary()

    for job, match_score in selected_jobs:
        if not job.application_url:
            items.append(
                {
                    "mode": "batch",
                    "input": {"profile": profile},
                    "ok": False,
                    "status": "SKIPPED",
                    "job": serialize_job(job, match_score=match_score),
                    "tracking_id": None,
                    "result": None,
                    "artifacts": _empty_artifacts(),
                    "error": "Job has no application URL.",
                    "error_code": "missing_application_url",
                    "dry_run": dry_run,
                }
            )
            summary["skipped"] += 1
            continue

        if not await limiter.can_apply():
            summary["stopped_early"] = True
            summary["stop_reason"] = "rate_limit_reached"
            break

        ats_type = _detect_ats_from_url(job.application_url)
        if not ats_type:
            items.append(
                {
                    "mode": "batch",
                    "input": {"profile": profile},
                    "ok": False,
                    "status": "SKIPPED",
                    "job": serialize_job(job, match_score=match_score),
                    "tracking_id": None,
                    "result": None,
                    "artifacts": _empty_artifacts(),
                    "error": _unsupported_ats_message(job.application_url),
                    "error_code": "unsupported_ats",
                    "dry_run": dry_run,
                }
            )
            summary["skipped"] += 1
            continue

        item = await _run_application_for_job(
            job=job,
            profile_data=profile_data,
            auto_submit=auto_submit,
            headless=headless,
            dry_run=dry_run,
            match_score=match_score,
            mode="batch",
            input_payload={"profile": profile},
        )
        items.append(item)

        status = item["status"]
        if status == AppStatus.SUBMITTED:
            await limiter.record_application()
            summary["submitted"] += 1
        elif status == AppStatus.REVIEW_REQUIRED:
            summary["review"] += 1
        elif status == "DRY_RUN":
            summary["dry_run"] += 1
        elif status == "SKIPPED":
            summary["skipped"] += 1
        else:
            summary["failed"] += 1
            await limiter.error_cooldown()

    summary["attempted"] = len(items)

    return {
        "mode": "batch",
        "profile": profile,
        "top_n": top_n,
        "ok": True,
        "errors": [],
        "items": items,
        "summary": summary,
        "dry_run": dry_run,
    }


def serialize_job(job, match_score: float | None = None) -> dict:
    score = job.raw_data.get("match_score") if match_score is None else match_score
    return {
        "id": str(job.id),
        "source": job.source,
        "source_id": job.source_id,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "description": job.description,
        "application_url": job.application_url,
        "ats_type": job.ats_type,
        "match_score": score,
        "disqualified": bool(job.raw_data.get("disqualified")),
        "raw_data": job.raw_data,
        "discovered_at": _isoformat(job.discovered_at),
    }


def _batch_summary() -> dict:
    return {
        "attempted": 0,
        "submitted": 0,
        "review": 0,
        "failed": 0,
        "skipped": 0,
        "dry_run": 0,
        "stopped_early": False,
        "stop_reason": None,
    }


def _build_companies_filter(
    config_dir: Path,
    ats: str | None,
    company: str | None,
) -> dict[str, list[str]] | None:
    if ats and company:
        return {ats: [company]}
    if company:
        return {"greenhouse": [company], "lever": [company]}
    if ats:
        from src.intake.batch import load_company_list

        all_companies = load_company_list(config_dir / "companies.yaml")
        return {ats: all_companies.get(ats, [])}
    return None


def _score_jobs(jobs, *, warn_on_missing_profile: bool) -> tuple[bool, list[str]]:
    if not PROFILE_FILE.exists():
        if warn_on_missing_profile:
            return False, ["No profile found -- run `autoapply init` first to enable scoring."]
        return False, []

    from src.matching.scorer import build_scoring_context
    from src.matching.scorer import score_jobs as score_ranked_jobs
    from src.memory.profile import load_profile_yaml

    profile_data = load_profile_yaml(PROFILE_FILE)
    scoring_ctx = build_scoring_context(profile_data)
    ranked = score_ranked_jobs(jobs, scoring_ctx)
    score_by_id = {score.job_id: score for score in ranked}

    for job in jobs:
        score = score_by_id.get(str(job.id))
        if score is not None:
            job.raw_data["match_score"] = score.final_score
            job.raw_data["disqualified"] = score.disqualified

    jobs.sort(key=lambda item: item.raw_data.get("match_score", 0.0), reverse=True)
    return True, []


def _select_batch_jobs(filter_profile: str, top_n: int) -> tuple[list[tuple], list[str], int]:
    from src.intake.search import search_jobs as search_ats_jobs
    from src.matching.scorer import build_scoring_context
    from src.matching.scorer import score_jobs as score_ranked_jobs

    jobs = search_ats_jobs(profile=filter_profile, parse_jds=True)
    if not jobs:
        return [], ["No matching jobs found."], 0

    profile_data = _load_profile()
    if not profile_data:
        return [], ["Profile not configured."], 0

    scoring_ctx = build_scoring_context(profile_data)
    ranked = score_ranked_jobs(jobs, scoring_ctx)
    job_by_id = {str(job.id): job for job in jobs}
    selected = []

    for score in ranked:
        job = job_by_id.get(score.job_id)
        if job is None:
            continue
        job.raw_data["match_score"] = score.final_score
        job.raw_data["disqualified"] = score.disqualified
        if score.disqualified:
            continue
        selected.append((job, score.final_score))
        if len(selected) >= top_n:
            break

    total_matches = sum(1 for score in ranked if not score.disqualified)
    return selected, [], total_matches


def _empty_artifacts() -> dict:
    return {
        "resume_path": None,
        "cover_letter_path": None,
        "qa_responses": None,
    }


def _unsupported_ats_message(url: str) -> str:
    if "linkedin.com" in url.lower():
        return (
            "This is a LinkedIn URL. Use `autoapply search --source linkedin` "
            "to find the external ATS link first."
        )
    return "Could not detect ATS type from URL. Supported: greenhouse, lever."


def _serialize_execution_result(result) -> dict:
    if result is None:
        return {
            "status": None,
            "error": None,
            "fields_filled": 0,
            "fields_total": 0,
            "files_uploaded": [],
            "qa_answered": 0,
            "screenshots": [],
        }

    return {
        "status": str(result.status),
        "error": result.error or None,
        "fields_filled": result.fields_filled,
        "fields_total": result.fields_total,
        "files_uploaded": result.files_uploaded,
        "qa_answered": result.qa_answered,
        "screenshots": [str(path) for path in result.screenshots],
    }


async def _run_application_for_job(
    *,
    job,
    profile_data: dict,
    auto_submit: bool,
    headless: bool,
    dry_run: bool,
    mode: str,
    input_payload: dict,
    match_score: float | None = None,
) -> dict:
    resume_path, cover_letter_path, qa_responses = await _generate_materials(profile_data, job)

    payload = {
        "mode": mode,
        "input": input_payload,
        "job": serialize_job(job, match_score=match_score),
        "tracking_id": None,
        "artifacts": {
            "resume_path": str(resume_path) if resume_path else None,
            "cover_letter_path": str(cover_letter_path) if cover_letter_path else None,
            "qa_responses": qa_responses,
        },
        "dry_run": dry_run,
        "result": None,
        "status": None,
        "ok": False,
        "error": None,
        "error_code": None,
    }

    if not resume_path:
        payload["error"] = "Cannot continue without a generated resume."
        payload["error_code"] = "resume_generation_failed"
        payload["result"] = _serialize_execution_result(None)
        return payload

    if dry_run:
        payload["status"] = "DRY_RUN"
        payload["ok"] = True
        payload["result"] = {
            "status": "DRY_RUN",
            "error": None,
            "fields_filled": 0,
            "fields_total": 0,
            "files_uploaded": [],
            "qa_answered": 0,
            "screenshots": [],
        }
        return payload

    app_id = _create_tracking_application(
        job=job,
        match_score=match_score,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
    )
    if app_id is not None:
        payload["tracking_id"] = str(app_id)

    state = ApplicationState(str(app_id or job.id))
    result = await _execute_application(
        url=job.application_url or "",
        ats_type=job.ats_type,
        profile_data=profile_data,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        qa_responses=qa_responses,
        auto_submit=auto_submit,
        headless=headless,
        state=state,
    )

    if app_id is not None:
        _sync_tracking_application(app_id, state, result, qa_responses)

    payload["result"] = _serialize_execution_result(result)
    payload["status"] = payload["result"]["status"]
    payload["ok"] = payload["status"] in {AppStatus.SUBMITTED, AppStatus.REVIEW_REQUIRED}
    if not payload["ok"]:
        payload["error"] = payload["result"]["error"] or "Application failed."
        payload["error_code"] = "application_failed"

    return payload


async def _generate_materials(
    profile_data: dict, job
) -> tuple[Path | None, Path | None, dict | None]:
    from src.generation.cover_letter import generate_cover_letter
    from src.generation.qa_responder import answer_questions
    from src.generation.resume_builder import generate_resume

    output_dir = PROJECT_ROOT / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    resume_files = generate_resume(job=job, profile_data=profile_data, output_dir=output_dir)
    resume_path = resume_files.get("pdf") or resume_files.get("docx")

    cover_files = generate_cover_letter(job=job, profile_data=profile_data, output_dir=output_dir)
    cover_letter_path = cover_files.get("txt")

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
        }
        if not qa_responses:
            qa_responses = None

    return resume_path, cover_letter_path, qa_responses


async def _execute_application(
    *,
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
        return result


def _detect_ats_from_url(url: str) -> str | None:
    url_lower = url.lower()
    if "greenhouse.io" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower:
        return "lever"
    return None


def _load_profile() -> dict | None:
    if not PROFILE_FILE.exists():
        return None

    from src.memory.profile import load_profile_yaml

    return load_profile_yaml(PROFILE_FILE)


def _load_job_for_application(url: str, ats_type: str):
    db_job = _find_db_job_by_url(url)
    if db_job is not None:
        return _job_to_raw_job(db_job)

    fetched_job = _fetch_job_from_ats(url, ats_type)
    if fetched_job is not None:
        return fetched_job

    return _synthesize_job_from_url(url, ats_type)


def _find_db_job_by_url(url: str):
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
    *,
    job,
    match_score: float | None,
    resume_path: Path,
    cover_letter_path: Path | None,
) -> uuid.UUID | None:
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


def _sync_tracking_application(app_id: uuid.UUID, state, result, qa_responses: dict | None) -> None:
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


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None

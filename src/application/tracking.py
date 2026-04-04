"""Tracking and dashboard use cases shared by CLI and Web."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import ProgrammingError

from src.core.config import load_config

logger = logging.getLogger("autoapply.application.tracking")

VALID_OUTCOMES = {"pending", "rejected", "oa", "interview", "offer"}


def load_dashboard_data() -> dict:
    try:
        from src.core.database import get_session_factory
        from src.tracker.analytics import (
            compute_company_stats,
            compute_outcome_stats,
            compute_pipeline_stats,
        )
        from src.tracker.database import get_application_counts

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            pipeline_summary = compute_pipeline_stats(session)
            pipeline = get_application_counts(session)
            outcome_summary = compute_outcome_stats(session)
            companies = compute_company_stats(session)

        return {
            "pipeline": pipeline,
            "summary": _serialize_pipeline_summary(pipeline_summary),
            "outcomes": _serialize_outcome_stats(outcome_summary),
            "companies": [_serialize_company_stats(company) for company in companies],
            "db_connected": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "pipeline": {},
            "summary": _empty_pipeline_summary(),
            "outcomes": _empty_outcome_stats(),
            "companies": [],
            "db_connected": False,
            "error": str(exc),
        }


def load_applications_data(
    *,
    status: str = "",
    outcome: str = "",
    company: str = "",
    limit: int = 50,
) -> dict:
    applications = []
    pipeline_stats = {}
    outcome_stats = _empty_outcome_stats()
    error = None

    try:
        from src.core.database import get_session_factory
        from src.tracker.database import get_applications_with_jobs

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            filtered_applications = get_applications_with_jobs(
                session,
                status=status or None,
                outcome=outcome or None,
                company=company or None,
                limit=None,
            )
            applications = filtered_applications[:limit]
            summaries = _summarize_applications(filtered_applications)
            pipeline_stats = summaries["pipeline_counts"]
            outcome_stats = summaries["outcomes"]
    except Exception as exc:
        error = str(exc)

    return {
        "applications": [_serialize_application(app, job) for app, job in applications],
        "pipeline": pipeline_stats,
        "outcomes": outcome_stats,
        "error": error,
        "filters": {"status": status, "outcome": outcome, "company": company, "limit": limit},
    }


def update_application_outcome(*, application_id: UUID, outcome: str) -> dict:
    if outcome not in VALID_OUTCOMES:
        return {
            "ok": False,
            "error": "Invalid outcome",
            "error_code": "invalid_outcome",
        }

    try:
        from src.core.database import get_session_factory
        from src.tracker.database import update_outcome

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            app = update_outcome(session, application_id, outcome)
            session.commit()
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "application_not_found",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to update outcome: {exc}",
            "error_code": "update_failed",
        }

    return {
        "ok": True,
        "status": "updated",
        "message": f"Updated to {outcome}",
        "application_id": str(app.id),
        "outcome": app.outcome,
        "updated_at": _isoformat(app.outcome_updated_at),
    }


def load_status_data(
    *,
    company: str | None = None,
    app_status: str | None = None,
    outcome: str | None = None,
    limit: int = 20,
) -> dict:
    try:
        from src.core.database import get_session_factory

        session_factory = get_session_factory(load_config())
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "database_connection_failed",
        }

    with session_factory() as session:
        from src.tracker.database import get_applications_with_jobs

        try:
            filtered_applications = get_applications_with_jobs(
                session,
                status=app_status,
                outcome=outcome,
                company=company,
                limit=None,
            )
            summaries = _summarize_applications(filtered_applications)
        except ProgrammingError as exc:
            logger.debug("Status analytics failed due to schema mismatch: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "error_code": "schema_out_of_date",
            }

        recent = filtered_applications[:limit]

    return {
        "ok": True,
        "filters": {
            "company": company,
            "status": app_status,
            "outcome": outcome,
            "limit": limit,
        },
        "pipeline_counts": summaries["pipeline_counts"],
        "pipeline_summary": summaries["pipeline_summary"],
        "outcomes": summaries["outcomes"],
        "companies": summaries["companies"],
        "platforms": summaries["platforms"],
        "recent_applications": [_serialize_application(app, job) for app, job in recent],
    }


def export_applications_csv_data(*, output_path: Path) -> dict:
    try:
        from src.core.database import get_session_factory
        from src.tracker.export import export_applications_csv

        session_factory = get_session_factory(load_config())
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "database_connection_failed",
        }

    with session_factory() as session:
        csv_content = export_applications_csv(session, output_path=output_path)

    row_count = max(len(csv_content.splitlines()) - 1, 0)
    return {
        "ok": True,
        "exported_to": str(output_path),
        "row_count": row_count,
    }


def _serialize_pipeline_summary(summary) -> dict:
    return {
        "total_discovered": summary.total_discovered,
        "total_applied": summary.total_applied,
        "total_failed": summary.total_failed,
        "total_review": summary.total_review,
        "avg_match_score": summary.avg_match_score,
        "avg_fields_filled_pct": summary.avg_fields_filled_pct,
    }


def _serialize_outcome_stats(summary) -> dict:
    return {
        "total": summary.total_submitted,
        "pending": summary.pending,
        "rejected": summary.rejected,
        "oa": summary.oa,
        "interview": summary.interview,
        "offer": summary.offer,
        "rates": {
            "response_rate": summary.response_rate,
            "positive_rate": summary.positive_rate,
        },
    }


def _serialize_company_stats(company) -> dict:
    return {
        "company": company.company,
        "applications": company.applications,
        "submitted": company.submitted,
        "outcomes": company.outcomes,
        "avg_match_score": company.avg_match_score,
    }


def _serialize_application(app, job) -> dict:
    return {
        "id": str(app.id),
        "job_id": str(app.job_id),
        "status": app.status,
        "match_score": app.match_score,
        "outcome": app.outcome or "pending",
        "created_at": _isoformat(app.created_at),
        "updated_at": _isoformat(app.updated_at),
        "submitted_at": _isoformat(app.submitted_at),
        "job": {
            "id": str(job.id),
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "application_url": job.application_url,
            "ats_type": job.ats_type,
        },
    }


def _summarize_applications(records: list[tuple]) -> dict:
    pipeline_counts: dict[str, int] = {}
    company_map: dict[str, list[tuple]] = {}
    platform_map: dict[str, dict[str, int]] = {}

    match_scores = []
    fill_rates = []
    total_applied = 0
    total_failed = 0
    total_review = 0
    outcome_counts = {"pending": 0, "rejected": 0, "oa": 0, "interview": 0, "offer": 0}

    for app, job in records:
        pipeline_counts[app.status] = pipeline_counts.get(app.status, 0) + 1
        company_map.setdefault(job.company, []).append((app, job))

        ats_type = job.ats_type or "unknown"
        platform_counts = platform_map.setdefault(ats_type, {})
        platform_counts[app.status] = platform_counts.get(app.status, 0) + 1

        if app.status == "SUBMITTED":
            total_applied += 1
            normalized_outcome = app.outcome or "pending"
            outcome_counts[normalized_outcome] = outcome_counts.get(normalized_outcome, 0) + 1
        elif app.status == "FAILED":
            total_failed += 1
        elif app.status == "REVIEW_REQUIRED":
            total_review += 1

        if app.match_score is not None:
            match_scores.append(app.match_score)

        if app.fields_total:
            fill_rates.append((app.fields_filled or 0) / app.fields_total)

    companies = []
    for company_name, items in company_map.items():
        submitted = sum(1 for app, _ in items if app.status == "SUBMITTED")
        scores = [app.match_score for app, _ in items if app.match_score is not None]
        company_outcomes = {}
        for app, _ in items:
            normalized_outcome = app.outcome or "pending"
            company_outcomes[normalized_outcome] = company_outcomes.get(normalized_outcome, 0) + 1

        companies.append(
            {
                "company": company_name,
                "applications": len(items),
                "submitted": submitted,
                "outcomes": company_outcomes,
                "avg_match_score": sum(scores) / len(scores) if scores else 0.0,
            }
        )

    companies.sort(key=lambda item: item["applications"], reverse=True)
    total_submitted = (
        outcome_counts["pending"]
        + outcome_counts["rejected"]
        + outcome_counts["oa"]
        + outcome_counts["interview"]
        + outcome_counts["offer"]
    )

    return {
        "pipeline_counts": pipeline_counts,
        "pipeline_summary": {
            "total_discovered": len(records),
            "total_applied": total_applied,
            "total_failed": total_failed,
            "total_review": total_review,
            "avg_match_score": sum(match_scores) / len(match_scores) if match_scores else 0.0,
            "avg_fields_filled_pct": sum(fill_rates) / len(fill_rates) if fill_rates else 0.0,
        },
        "outcomes": {
            "total": total_submitted,
            "pending": outcome_counts["pending"],
            "rejected": outcome_counts["rejected"],
            "oa": outcome_counts["oa"],
            "interview": outcome_counts["interview"],
            "offer": outcome_counts["offer"],
            "rates": {
                "response_rate": (
                    (total_submitted - outcome_counts["pending"]) / total_submitted
                    if total_submitted
                    else 0.0
                ),
                "positive_rate": (
                    (outcome_counts["oa"] + outcome_counts["interview"] + outcome_counts["offer"])
                    / total_submitted
                    if total_submitted
                    else 0.0
                ),
            },
        },
        "companies": companies,
        "platforms": platform_map,
    }


def _empty_pipeline_summary() -> dict:
    return {
        "total_discovered": 0,
        "total_applied": 0,
        "total_failed": 0,
        "total_review": 0,
        "avg_match_score": 0.0,
        "avg_fields_filled_pct": 0.0,
    }


def _empty_outcome_stats() -> dict:
    return {
        "total": 0,
        "pending": 0,
        "rejected": 0,
        "oa": 0,
        "interview": 0,
        "offer": 0,
        "rates": {"response_rate": 0.0, "positive_rate": 0.0},
    }


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None

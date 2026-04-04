"""Application analytics and statistics.

Computes metrics from application records: hit rates, platform quality,
conversion funnels, and timeline analysis.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.models import Application, Job
from src.core.state_machine import AppStatus

logger = logging.getLogger("autoapply.tracker.analytics")


@dataclass
class PipelineStats:
    """Overall pipeline statistics."""

    total_discovered: int = 0
    total_applied: int = 0  # SUBMITTED or later
    total_failed: int = 0
    total_review: int = 0  # REVIEW_REQUIRED (paused)
    avg_match_score: float = 0.0
    avg_fields_filled_pct: float = 0.0


@dataclass
class OutcomeStats:
    """Outcome breakdown for submitted applications."""

    total_submitted: int = 0
    pending: int = 0
    rejected: int = 0
    oa: int = 0  # online assessment
    interview: int = 0
    offer: int = 0

    @property
    def response_rate(self) -> float:
        """Percentage of submitted apps that got any response."""
        if self.total_submitted == 0:
            return 0.0
        responded = self.oa + self.interview + self.offer + self.rejected
        return responded / self.total_submitted

    @property
    def positive_rate(self) -> float:
        """Percentage of submitted apps that got OA/interview/offer."""
        if self.total_submitted == 0:
            return 0.0
        positive = self.oa + self.interview + self.offer
        return positive / self.total_submitted


@dataclass
class CompanyStats:
    """Stats for a single company."""

    company: str = ""
    applications: int = 0
    submitted: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    avg_match_score: float = 0.0


def compute_pipeline_stats(session: Session) -> PipelineStats:
    """Compute overall pipeline statistics."""
    stats = PipelineStats()

    # Count by status
    status_counts = _count_by_column(session, Application.status)
    stats.total_discovered = sum(status_counts.values())
    stats.total_applied = status_counts.get(AppStatus.SUBMITTED, 0)
    stats.total_failed = status_counts.get(AppStatus.FAILED, 0)
    stats.total_review = status_counts.get(AppStatus.REVIEW_REQUIRED, 0)

    # Average match score
    row = session.execute(
        select(func.avg(Application.match_score)).where(Application.match_score.isnot(None))
    ).scalar()
    stats.avg_match_score = float(row) if row else 0.0

    # Average fill rate
    row = session.execute(
        select(
            func.avg(Application.fields_filled * 1.0 / func.nullif(Application.fields_total, 0))
        ).where(Application.fields_total.isnot(None), Application.fields_total > 0)
    ).scalar()
    stats.avg_fields_filled_pct = float(row) if row else 0.0

    return stats


def compute_outcome_stats(session: Session) -> OutcomeStats:
    """Compute outcome breakdown for submitted applications."""
    stats = OutcomeStats()

    submitted = (
        session.execute(select(Application).where(Application.status == AppStatus.SUBMITTED))
        .scalars()
        .all()
    )

    stats.total_submitted = len(submitted)
    for app in submitted:
        outcome = app.outcome or "pending"
        if outcome == "pending":
            stats.pending += 1
        elif outcome == "rejected":
            stats.rejected += 1
        elif outcome == "oa":
            stats.oa += 1
        elif outcome == "interview":
            stats.interview += 1
        elif outcome == "offer":
            stats.offer += 1

    return stats


def compute_company_stats(session: Session, limit: int = 20) -> list[CompanyStats]:
    """Compute per-company statistics, sorted by application count."""
    stmt = (
        select(Job.company, func.count(Application.id).label("app_count"))
        .join(Application, Application.job_id == Job.id)
        .group_by(Job.company)
        .order_by(func.count(Application.id).desc())
        .limit(limit)
    )
    rows = session.execute(stmt).all()

    results = []
    for company_name, app_count in rows:
        cs = CompanyStats(company=company_name, applications=app_count)

        # Get details for this company
        apps = (
            session.execute(
                select(Application)
                .join(Job, Application.job_id == Job.id)
                .where(Job.company == company_name)
            )
            .scalars()
            .all()
        )

        scores = [a.match_score for a in apps if a.match_score is not None]
        cs.avg_match_score = sum(scores) / len(scores) if scores else 0.0
        cs.submitted = sum(1 for a in apps if a.status == AppStatus.SUBMITTED)

        for a in apps:
            if a.outcome:
                cs.outcomes[a.outcome] = cs.outcomes.get(a.outcome, 0) + 1

        results.append(cs)

    return results


def compute_platform_stats(session: Session) -> dict[str, dict[str, int]]:
    """Compute per-ATS-platform statistics."""
    stmt = (
        select(Job.ats_type, Application.status, func.count())
        .join(Application, Application.job_id == Job.id)
        .group_by(Job.ats_type, Application.status)
    )
    rows = session.execute(stmt).all()

    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ats, status, count in rows:
        result[ats or "unknown"][status] = count

    return dict(result)


def compute_daily_activity(
    session: Session,
    days: int = 30,
) -> list[tuple[str, int, int]]:
    """Compute daily application activity (created, submitted) over N days.

    Returns list of (date_str, created_count, submitted_count).
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Created per day
    created_stmt = (
        select(
            func.date(Application.created_at).label("day"),
            func.count().label("cnt"),
        )
        .where(Application.created_at >= cutoff)
        .group_by(func.date(Application.created_at))
    )
    created_rows = {str(row[0]): row[1] for row in session.execute(created_stmt).all()}

    # Submitted per day
    submitted_stmt = (
        select(
            func.date(Application.submitted_at).label("day"),
            func.count().label("cnt"),
        )
        .where(Application.submitted_at >= cutoff, Application.submitted_at.isnot(None))
        .group_by(func.date(Application.submitted_at))
    )
    submitted_rows = {str(row[0]): row[1] for row in session.execute(submitted_stmt).all()}

    # Merge into daily series
    all_dates = sorted(set(list(created_rows.keys()) + list(submitted_rows.keys())))
    return [(d, created_rows.get(d, 0), submitted_rows.get(d, 0)) for d in all_dates]


def _count_by_column(session: Session, column) -> dict[str, int]:
    """Helper to count rows grouped by a column."""
    stmt = select(column, func.count()).group_by(column)
    rows = session.execute(stmt).all()
    return {val: count for val, count in rows}

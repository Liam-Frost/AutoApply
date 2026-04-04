"""Export application data and reports.

Supports CSV export of application records and text-based summary reports.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.models import Application, Job

logger = logging.getLogger("autoapply.tracker.export")


def export_applications_csv(
    session: Session,
    output_path: Path | None = None,
    include_errors: bool = False,
) -> str:
    """Export all applications as CSV.

    Args:
        session: DB session.
        output_path: Optional file path. If None, returns CSV as string.

    Returns:
        CSV content as string.
    """
    stmt = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .order_by(Application.created_at.desc())
    )
    rows = session.execute(stmt).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    header = [
        "app_id",
        "company",
        "title",
        "location",
        "ats_type",
        "status",
        "match_score",
        "outcome",
        "fields_filled",
        "fields_total",
        "resume_version",
        "cover_letter_version",
        "created_at",
        "submitted_at",
        "outcome_updated_at",
    ]
    if include_errors:
        header.append("error")
    writer.writerow(header)

    for app, job in rows:
        row_data = [
            str(app.id),
            job.company,
            job.title,
            job.location or "",
            job.ats_type or "",
            app.status,
            f"{app.match_score:.2f}" if app.match_score else "",
            app.outcome or "",
            app.fields_filled or "",
            app.fields_total or "",
            app.resume_version or "",
            app.cover_letter_version or "",
            str(app.created_at) if app.created_at else "",
            str(app.submitted_at) if app.submitted_at else "",
            str(app.outcome_updated_at) if app.outcome_updated_at else "",
        ]
        if include_errors:
            row_data.append(app.error_log or "")
        writer.writerow(row_data)

    csv_content = output.getvalue()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(csv_content, encoding="utf-8")
        logger.info("Exported %d applications to %s", len(rows), output_path)

    return csv_content


def format_status_report(
    pipeline_stats,
    outcome_stats,
    company_stats: list,
    platform_stats: dict,
) -> str:
    """Format a text-based status report for CLI display.

    Args:
        pipeline_stats: PipelineStats dataclass.
        outcome_stats: OutcomeStats dataclass.
        company_stats: List of CompanyStats.
        platform_stats: Dict of {ats: {status: count}}.

    Returns:
        Formatted text report.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  AutoApply -- Application Status Report")
    lines.append("=" * 60)
    lines.append("")

    # Pipeline overview
    lines.append("  Pipeline Overview")
    lines.append("  " + "-" * 40)
    lines.append(f"    Total discovered:   {pipeline_stats.total_discovered}")
    lines.append(f"    Applied (submitted): {pipeline_stats.total_applied}")
    lines.append(f"    Failed:             {pipeline_stats.total_failed}")
    lines.append(f"    Awaiting review:    {pipeline_stats.total_review}")
    if pipeline_stats.avg_match_score > 0:
        lines.append(f"    Avg match score:    {pipeline_stats.avg_match_score:.0%}")
    if pipeline_stats.avg_fields_filled_pct > 0:
        lines.append(f"    Avg form fill rate: {pipeline_stats.avg_fields_filled_pct:.0%}")
    lines.append("")

    # Outcomes
    if outcome_stats.total_submitted > 0:
        lines.append("  Outcomes (submitted applications)")
        lines.append("  " + "-" * 40)
        lines.append(f"    Submitted:  {outcome_stats.total_submitted}")
        lines.append(f"    Pending:    {outcome_stats.pending}")
        lines.append(f"    Rejected:   {outcome_stats.rejected}")
        lines.append(f"    OA:         {outcome_stats.oa}")
        lines.append(f"    Interview:  {outcome_stats.interview}")
        lines.append(f"    Offer:      {outcome_stats.offer}")
        lines.append(f"    Response rate:  {outcome_stats.response_rate:.0%}")
        lines.append(f"    Positive rate:  {outcome_stats.positive_rate:.0%}")
        lines.append("")

    # Platform breakdown
    if platform_stats:
        lines.append("  By Platform")
        lines.append("  " + "-" * 40)
        for ats, status_counts in sorted(platform_stats.items()):
            total = sum(status_counts.values())
            submitted = status_counts.get("SUBMITTED", 0)
            failed = status_counts.get("FAILED", 0)
            lines.append(f"    {ats:15s}  total={total}  submitted={submitted}  failed={failed}")
        lines.append("")

    # Top companies
    if company_stats:
        lines.append("  Top Companies")
        lines.append("  " + "-" * 40)
        for cs in company_stats[:10]:
            outcome_str = ""
            if cs.outcomes:
                parts = [f"{k}={v}" for k, v in cs.outcomes.items()]
                outcome_str = f"  ({', '.join(parts)})"
            score_str = f"  score={cs.avg_match_score:.0%}" if cs.avg_match_score > 0 else ""
            lines.append(
                f"    {cs.company:20s}  apps={cs.applications}  "
                f"submitted={cs.submitted}{score_str}{outcome_str}"
            )
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)

"""Phase 17.6: morning digest.

Produces the 'Last night: 12 new jobs, 7 passed filter, 3 in review
queue, est. cost $0.21' payload the dashboard banner consumes. The
digest is a *read-only* aggregation over:

* Nightly run reports persisted by the orchestrator under
  ``data/nightly_runs/<run_id>.json`` (rolled here so the digest
  doesn't need a new DB table -- mirrors the ``agent_traces`` layout
  from Phase 8).
* The review_queue table -- per-status counts since the last
  digest window.

The 08:00 Beat tick re-renders the digest by calling
:func:`compute_digest` and emitting a structured payload that:

* the dashboard banner reads via ``GET /api/digest`` (Phase 17.6
  route landing here), and
* the future desktop-notification hook (out of scope for this phase,
  but the digest payload is intentionally serialisable so a future
  hook just reads the same JSON).

The window defaults to the last 24h ending at ``now``; the route can
override for back-dated digests / 'show me last week' affordances.

Persistence layout for nightly run reports::

    data/
      nightly_runs/
        20260516T230000Z-<run_id>.json   <- one file per run

Files are JSON dumps of :class:`NightlyRunReport.to_dict()`. The
filename's leading ISO timestamp is the report's ``started_at`` so
the digest can do a directory-scan + name-filter without parsing
every file.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.models import ReviewQueueEntry
from src.orchestration.nightly_run import NightlyRunReport

logger = logging.getLogger(__name__)

NIGHTLY_RUNS_DIRNAME = "nightly_runs"

# Filename: 20260516T230000Z-<run_id>.json
_NIGHTLY_FILENAME_RE = re.compile(
    r"^(\d{8}T\d{6}Z)-([0-9a-fA-F-]+)\.json$"
)


def nightly_runs_dir(root: Path | None = None) -> Path:
    """Resolve the directory where nightly run reports live.

    Mirrors :func:`src.orchestration.nightly_run.nightly_pause_sentinel_path` --
    callers can override ``root`` for tests; production uses
    :data:`src.core.config.PROJECT_ROOT`.
    """
    from src.core.config import PROJECT_ROOT  # noqa: PLC0415 - avoid cycle

    base = root if root is not None else PROJECT_ROOT
    return base / "data" / NIGHTLY_RUNS_DIRNAME


def _isoformat_filename(dt: datetime) -> str:
    """Filename-safe ISO 8601 -- 20260516T230000Z."""
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def persist_nightly_report(
    report: NightlyRunReport,
    *,
    root: Path | None = None,
) -> Path:
    """Write the report to ``data/nightly_runs/<ts>-<run_id>.json``.

    Idempotent on the filename: a re-fire of the same ``run_id`` with
    the same ``started_at`` overwrites the previous file (safe because
    NightlyRunReport is immutable per run -- only re-fires of the same
    run_id can land here, and Phase 17.1 generates a fresh uuid4
    per call).

    Returns the absolute path so the orchestrator can stash it in the
    audit row's ``trace_id`` column if desired.
    """
    target_dir = nightly_runs_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        ts = datetime.fromisoformat(report.started_at)
    except (ValueError, TypeError):
        ts = datetime.now(UTC)
    path = target_dir / f"{_isoformat_filename(ts)}-{report.run_id}.json"
    path.write_text(json.dumps(report.to_dict(), default=str), encoding="utf-8")
    return path


def _parse_filename_ts(name: str) -> datetime | None:
    match = _NIGHTLY_FILENAME_RE.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def load_reports_in_window(
    *,
    since: datetime,
    until: datetime,
    root: Path | None = None,
) -> list[NightlyRunReport]:
    """Load every report whose ``started_at`` is in ``[since, until)``.

    Filename-prefix filtering keeps this cheap even with thousands of
    reports -- we only ``open()`` files whose name puts them in the
    window.

    Files that fail to parse are skipped with a logged warning;
    they don't break the digest (a corrupt file shouldn't blank out
    the banner).
    """
    target_dir = nightly_runs_dir(root)
    if not target_dir.exists():
        return []
    reports: list[NightlyRunReport] = []
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_file():
            continue
        ts = _parse_filename_ts(entry.name)
        if ts is None:
            continue
        if not (since <= ts < until):
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("digest: could not parse %s", entry, exc_info=True)
            continue
        try:
            reports.append(NightlyRunReport(**data))
        except TypeError:
            # Schema drift -- log and continue. Future-proofing for
            # when NightlyRunReport gains fields.
            logger.warning(
                "digest: report %s has unexpected fields; skipping", entry
            )
            continue
    return reports


# --------------------------------------------------------------------------- #
# Digest payload                                                              #
# --------------------------------------------------------------------------- #


@dataclass
class DigestPayload:
    """The banner consumes this JSON shape.

    Counts are *windowed* (default last 24h). ``review_queue_status``
    is the live snapshot at digest time (current state of the queue
    for this tenant), not windowed -- the operator wants to know what's
    on the board right now, not what was on the board at 08:00.
    """

    tenant_id: str
    window_start: str  # ISO 8601 UTC
    window_end: str
    generated_at: str
    runs: int = 0
    total_jobs_seen: int = 0
    qualified: int = 0
    disqualified: int = 0
    borderline: int = 0
    selected: int = 0
    materials_enqueued: int = 0
    errors: int = 0
    paused_runs: int = 0
    estimated_cost_usd: float = 0.0
    review_queue_status: dict[str, int] = field(default_factory=dict)
    headline: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_headline(payload: DigestPayload) -> str:
    """Compose the human-readable single-line headline the dashboard
    banner shows ('Last night: 12 new jobs, 7 passed filter, 3 in
    review queue, est. cost $0.21')."""
    pending = payload.review_queue_status.get("pending", 0)
    cost = payload.estimated_cost_usd
    if payload.runs == 0:
        return "No nightly runs in the last 24h."
    parts = [
        f"Last 24h: {payload.total_jobs_seen} new jobs",
        f"{payload.qualified} passed filter",
        f"{pending} in review queue",
    ]
    if cost > 0:
        parts.append(f"est. cost ${cost:.2f}")
    return ", ".join(parts) + "."


def compute_digest(
    session: Session,
    *,
    tenant_id: str,
    window_hours: int = 24,
    now: datetime | None = None,
    root: Path | None = None,
) -> DigestPayload:
    """Aggregate the last ``window_hours`` of nightly_run reports +
    the current review queue state for ``tenant_id``."""
    now = now or datetime.now(UTC)
    window_start = now - timedelta(hours=window_hours)

    reports = load_reports_in_window(
        since=window_start, until=now, root=root
    )
    # Filter to the requested tenant -- reports may include other
    # tenants when the same disk is shared (multi-tenant future).
    reports = [r for r in reports if r.tenant_id == tenant_id]

    runs = len(reports)
    total_jobs_seen = sum(r.total_jobs_seen for r in reports)
    qualified = sum(r.qualified for r in reports)
    disqualified = sum(r.disqualified for r in reports)
    borderline = sum(r.borderline for r in reports)
    selected = sum(r.selected for r in reports)
    materials_enqueued = sum(len(r.materials_task_ids) for r in reports)
    errors = sum(1 for r in reports if r.status == "error")
    paused_runs = sum(1 for r in reports if r.status == "paused")
    estimated_cost_usd = sum(r.estimated_cost_usd or 0.0 for r in reports)

    # Review queue snapshot -- live, not windowed.
    rows = session.execute(
        select(ReviewQueueEntry.status, func.count(ReviewQueueEntry.id))
        .where(ReviewQueueEntry.tenant_id == tenant_id)
        .group_by(ReviewQueueEntry.status)
    ).all()
    queue_counts = {status: int(n) for status, n in rows}

    payload = DigestPayload(
        tenant_id=tenant_id,
        window_start=window_start.isoformat(),
        window_end=now.isoformat(),
        generated_at=now.isoformat(),
        runs=runs,
        total_jobs_seen=total_jobs_seen,
        qualified=qualified,
        disqualified=disqualified,
        borderline=borderline,
        selected=selected,
        materials_enqueued=materials_enqueued,
        errors=errors,
        paused_runs=paused_runs,
        estimated_cost_usd=round(estimated_cost_usd, 4),
        review_queue_status=queue_counts,
    )
    payload.headline = _build_headline(payload)
    return payload


__all__ = [
    "DigestPayload",
    "NIGHTLY_RUNS_DIRNAME",
    "compute_digest",
    "load_reports_in_window",
    "nightly_runs_dir",
    "persist_nightly_report",
]

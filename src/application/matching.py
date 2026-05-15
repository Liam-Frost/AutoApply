"""Application-layer use cases for Phase 16.3 explainability.

Wraps :mod:`src.matching.scorer` for the FastAPI route + the CLI. Keeps
the route handler thin and gives the frontend popover a stable contract.

Contract::

    explain_job(payload) -> {
        "ok": bool,
        "score_breakdown": ScoreBreakdown.to_dict() | None,
        "warnings": list[str],
    }

``score_breakdown`` is None only when ``ok=False`` (e.g. no active
profile, or the payload could not be parsed into a ``RawJob``).
"""

from __future__ import annotations

import logging
from typing import Any

from src.application.profile import load_profile_data
from src.intake.schema import RawJob

logger = logging.getLogger(__name__)


def _get_active_profile_dict() -> dict[str, Any] | None:
    """Load the active profile YAML as a dict, or ``None`` when missing.

    Wraps :func:`src.application.profile.load_profile_data` which returns
    the bundle for the currently active profile.
    """
    try:
        bundle = load_profile_data(None)
    except Exception:  # noqa: BLE001 -- swallow file/parse errors; route reports them
        logger.exception("Failed to load active profile for scoring explain")
        return None
    if not bundle:
        return None
    data = bundle.get("profile") if isinstance(bundle, dict) else None
    if not isinstance(data, dict):
        return None
    return data


def _coerce_to_raw_job(payload: dict[str, Any]) -> RawJob | None:
    """Best-effort RawJob construction from a frontend job dict.

    The frontend ships back ``serialize_job`` output, which has flat
    fields. RawJob accepts most of these directly via Pydantic; the
    nested ``requirements`` may live under ``raw_data.requirements``
    when the JD was parsed.
    """
    candidate = dict(payload)

    # Frontend ``serialize_job`` flattens these into top-level scalars
    # that don't exist on RawJob; pop them so Pydantic doesn't choke.
    for k in (
        "match_score",
        "disqualified",
        "experience_level",
        "employment_category",
        "education_level",
        "experience_years_min",
        "experience_years_max",
        "pay_min",
        "pay_max",
        "location_type",
        "discovered_at",
    ):
        candidate.pop(k, None)

    # ``requirements`` typically rides inside raw_data when present.
    raw_data = candidate.get("raw_data") or {}
    if "requirements" not in candidate and isinstance(raw_data, dict):
        reqs = raw_data.get("requirements")
        if reqs:
            candidate["requirements"] = reqs

    try:
        return RawJob(**candidate)
    except Exception:  # noqa: BLE001 -- caller surfaces as a warning
        logger.exception("Could not coerce payload into RawJob for explain")
        return None


def explain_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Re-score a job and return its structured breakdown.

    Used by the Phase 16.3 "Why was this filtered?" popover so the UI
    can render rule reasons + evidence excerpts on demand for any job,
    not just jobs that came through the active search pipeline (which
    already get ``raw_data['score_breakdown']`` attached during
    ``_score_jobs``).
    """
    warnings: list[str] = []

    profile_data = _get_active_profile_dict()
    if profile_data is None:
        return {
            "ok": False,
            "score_breakdown": None,
            "warnings": ["No active profile -- run `autoapply init` first."],
        }

    job = _coerce_to_raw_job(payload)
    if job is None:
        return {
            "ok": False,
            "score_breakdown": None,
            "warnings": [
                "Job payload could not be parsed; expected serialize_job() shape."
            ],
        }

    # Lazy imports keep the route module light.
    from src.matching.scorer import build_scoring_context, score_job

    ctx = build_scoring_context(profile_data)
    snapshot_id = None
    if isinstance(payload.get("raw_data"), dict):
        snapshot_id = payload["raw_data"].get("job_snapshot_id")
    breakdown = score_job(job, ctx, job_snapshot_id=snapshot_id)

    return {
        "ok": True,
        "score_breakdown": breakdown.to_dict(),
        "warnings": warnings,
    }

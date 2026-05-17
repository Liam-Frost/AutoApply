"""File-backed user automation task configuration."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import yaml
from celery.schedules import crontab

from src.core.config import PROJECT_ROOT

AUTOMATION_PLANS_PATH = PROJECT_ROOT / "config" / "automation_plans.yaml"
VALID_PLAN_ID_RE = re.compile(r"[^a-z0-9_-]+")


def sanitize_plan_id(value: str) -> str:
    cleaned = VALID_PLAN_ID_RE.sub("-", (value or "").strip().lower()).strip("-")
    return cleaned or "automation-task"


def load_automation_plans_data() -> dict[str, Any]:
    return {"ok": True, "plans": _read_plans()}


def save_automation_plan_data(*, plan_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    target_id = sanitize_plan_id(plan_id)
    plans = _read_plans()
    existing = next((p for p in plans if p.get("id") == target_id), None)
    now = _now_iso()
    normalized = _normalize_plan({**(existing or {}), **plan, "id": target_id})
    normalized["created_at"] = existing.get("created_at") if existing else now
    normalized["updated_at"] = now

    if existing:
        plans = [normalized if p.get("id") == target_id else p for p in plans]
    else:
        plans.append(normalized)

    _write_plans(plans)
    return {
        "ok": True,
        "status": "saved" if existing else "created",
        "message": f"Automation task '{target_id}' saved.",
        "plans": plans,
        "plan": normalized,
    }


def delete_automation_plan_data(plan_id: str) -> dict[str, Any]:
    target_id = sanitize_plan_id(plan_id)
    plans = _read_plans()
    next_plans = [p for p in plans if p.get("id") != target_id]
    if len(next_plans) == len(plans):
        return {
            "ok": False,
            "error": f"Automation task '{target_id}' not found.",
            "error_code": "automation_plan_not_found",
        }
    _write_plans(next_plans)
    return {
        "ok": True,
        "status": "deleted",
        "message": f"Automation task '{target_id}' deleted.",
        "plans": next_plans,
    }


def get_automation_plan(plan_id: str) -> dict[str, Any] | None:
    target_id = sanitize_plan_id(plan_id)
    return next((p for p in _read_plans() if p.get("id") == target_id), None)


def automation_plan_schedule_entries() -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for plan in _read_plans():
        if not plan.get("enabled", True):
            continue
        entries[f"automation:{plan['id']}"] = schedule_entry_for_plan(plan)
    return entries


def schedule_entry_for_plan(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_plan(plan)
    return {
        "task": "orchestration.plan_run",
        "schedule": _crontab_for_plan(normalized),
        "options": {"queue": "search"},
        "kwargs": _task_kwargs(normalized),
    }


def _read_plans() -> list[dict[str, Any]]:
    if not AUTOMATION_PLANS_PATH.exists():
        return []
    with open(AUTOMATION_PLANS_PATH, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    raw_plans = data.get("plans", []) if isinstance(data, dict) else []
    if not isinstance(raw_plans, list):
        return []
    return [_normalize_plan(p) for p in raw_plans if isinstance(p, dict)]


def _write_plans(plans: list[dict[str, Any]]) -> None:
    AUTOMATION_PLANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"plans": sorted(plans, key=lambda p: p.get("id", ""))}
    with open(AUTOMATION_PLANS_PATH, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def _normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    cadence = str(plan.get("cadence") or "daily")
    if cadence not in {"interval", "daily", "weekly", "monthly"}:
        cadence = "daily"
    interval_unit = str(plan.get("interval_unit") or "hours")
    if interval_unit not in {"minutes", "hours"}:
        interval_unit = "hours"
    apply_mode = str(plan.get("apply_mode") or "review_queue")
    if apply_mode not in {"review_queue", "auto_apply"}:
        apply_mode = "review_queue"

    plan_id = sanitize_plan_id(str(plan.get("id") or plan.get("name") or "automation-task"))
    name = str(plan.get("name") or plan_id.replace("-", " ")).strip()
    search_profile_id = str(plan.get("search_profile_id") or "").strip()

    return {
        "id": plan_id,
        "name": name or plan_id,
        "enabled": bool(plan.get("enabled", True)),
        "search_profile_id": search_profile_id,
        "profile_id": str(plan.get("profile_id") or "default").strip() or "default",
        "cadence": cadence,
        "interval_every": _bounded_int(plan.get("interval_every"), 1, 24, 1),
        "interval_unit": interval_unit,
        "hour": _bounded_int(plan.get("hour"), 0, 23, 23),
        "minute": _bounded_int(plan.get("minute"), 0, 59, 0),
        "day_of_week": _bounded_int(plan.get("day_of_week"), 0, 6, 1),
        "day_of_month": _bounded_int(plan.get("day_of_month"), 1, 31, 1),
        "scrape_enabled": bool(plan.get("scrape_enabled", True)),
        "apply_mode": apply_mode,
        "skip_previously_applied": bool(plan.get("skip_previously_applied", True)),
        "top_n": _bounded_int(plan.get("top_n"), 1, 100, 10),
        "dry_run": bool(plan.get("dry_run", False)),
        # Phase 17.8: per-plan material strategy overrides. Both
        # documents share the same shape; empty values mean "inherit
        # from Settings → Default material strategy".
        "resume_strategy": _normalize_strategy(plan.get("resume_strategy")),
        "resume_template_id": _clean_optional_id(plan.get("resume_template_id")),
        "resume_source_document_id": _clean_optional_uuid(plan.get("resume_source_document_id")),
        "cover_letter_strategy": _normalize_strategy(plan.get("cover_letter_strategy")),
        "cover_letter_template_id": _clean_optional_id(plan.get("cover_letter_template_id")),
        "cover_letter_source_document_id": _clean_optional_uuid(
            plan.get("cover_letter_source_document_id")
        ),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
    }


def _normalize_strategy(value: Any) -> str:
    """Empty / unknown values mean "inherit Settings default"."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if text in {"regenerate", "patch_existing"}:
        return text
    return ""


def _clean_optional_id(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return text


def _clean_optional_uuid(value: Any) -> str:
    from uuid import UUID

    if value in (None, ""):
        return ""
    text = str(value).strip()
    try:
        UUID(text)
    except (TypeError, ValueError):
        return ""
    return text


def _crontab_for_plan(plan: dict[str, Any]) -> crontab:
    cadence = plan["cadence"]
    if cadence == "interval":
        every = plan["interval_every"]
        if plan["interval_unit"] == "minutes":
            return crontab(minute=f"*/{every}")
        return crontab(hour=f"*/{every}", minute=plan["minute"])
    if cadence == "weekly":
        return crontab(hour=plan["hour"], minute=plan["minute"], day_of_week=plan["day_of_week"])
    if cadence == "monthly":
        return crontab(hour=plan["hour"], minute=plan["minute"], day_of_month=plan["day_of_month"])
    return crontab(hour=plan["hour"], minute=plan["minute"])


def _task_kwargs(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": plan["profile_id"],
        "search_profile_id": plan["search_profile_id"] or None,
        "top_n": plan["top_n"],
        "dry_run": plan["dry_run"],
        "auto_submit": plan["apply_mode"] == "auto_apply",
        "skip_previously_applied": plan["skip_previously_applied"],
        "scrape_enabled": plan["scrape_enabled"],
        # Phase 17.8: per-plan material strategy overrides flow through
        # to orchestration.plan_run as kwargs. Empty strings mean
        # "inherit from Settings → Default material strategy" — the
        # plan_run task hands them straight to
        # ``resolve_material_choice`` which already treats them that way.
        "resume_strategy": plan.get("resume_strategy") or None,
        "resume_template_id": plan.get("resume_template_id") or None,
        "resume_source_document_id": plan.get("resume_source_document_id") or None,
        "cover_letter_strategy": plan.get("cover_letter_strategy") or None,
        "cover_letter_template_id": plan.get("cover_letter_template_id") or None,
        "cover_letter_source_document_id": plan.get("cover_letter_source_document_id") or None,
    }


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, n))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "automation_plan_schedule_entries",
    "delete_automation_plan_data",
    "get_automation_plan",
    "load_automation_plans_data",
    "save_automation_plan_data",
    "schedule_entry_for_plan",
]

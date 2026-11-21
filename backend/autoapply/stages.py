"""One user-facing stage per job, derived from the job row and its application.

Internally a job has a discovery status (new / scored / queued / skipped / offline) and, once a draft
exists, an application status (lifecycle.py; agent/work.py moves it while an application is worked). The jobs table shows a
single stage instead, so "not applied" never hides behind an internal word like "queued".
"""

from __future__ import annotations

from .say import say as T

from datetime import datetime
from typing import Any

# key -> (label, group, tone)
STAGES: dict[str, tuple[str, str, str]] = {
    "not_applied": (T("server.stages.notApplied"), "todo", ""),
    "drafting": (T("server.stages.generatingDraft"), "active", "info"),
    "needs_input": (T("server.stages.draftNeedsInfo"), "active", "warn"),
    "draft_ready": (T("server.stages.draftAwaitingReview"), "active", "warn"),
    "applying": (T("server.stages.applying"), "active", "info"),
    "needs_you": (T("server.stages.needsYou"), "active", "warn"),
    "failed": (T("server.stages.applicationFailed"), "active", "bad"),
    "submitted": (T("server.stages.applicationSent"), "applied", "info"),
    "confirmed": (T("server.stages.applicationConfirmed"), "applied", "ok"),
    "assessment": (T("server.stages.writtenTestOaVa"), "progress", "ok"),
    "interview": (T("server.stages.interview"), "progress", "ok"),
    "offer": (T("server.stages.offerReceived"), "progress", "ok"),
    "rejected": (T("server.stages.rejected"), "rejected", "bad"),
    "skipped": (T("server.stages.dontApply"), "skipped", ""),
    "expired": (T("server.stages.deadlinePassed"), "closed", ""),
    "offline": (T("server.stages.takenDown"), "closed", ""),
}
GROUPS = [("todo", T("server.stages.notApplied")), ("active", T("server.stages.inProgress")), ("applied", T("server.stages.applied")), ("progress", T("server.stages.hasUpdates")), ("rejected", T("server.stages.rejected")), ("skipped", T("server.stages.dontApply")), ("closed", T("server.stages.takenDownClosed")), ("all", T("server.stages.all"))]

_APP = {
    "recon": "drafting", "revising": "drafting",
    "needs_input": "needs_input", "draft_ready": "draft_ready",
    "approved": "applying", "executing": "applying", "drifted": "applying",
    "ready_to_submit": "needs_you", "submit_unknown": "needs_you", "needs_human": "needs_you",
    "failed": "failed", "submitted": "submitted", "confirmed": "confirmed",
    "assessment": "assessment", "interview": "interview", "offer": "offer", "rejected": "rejected",
    "withdrawn": "skipped",
}


def _past(deadline: str) -> bool:
    if not deadline:
        return False
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(deadline.strip()[:16] if fmt.endswith("%M") else deadline.strip()[:10], fmt)
            if fmt == "%Y-%m-%d":
                d = d.replace(hour=23, minute=59)
            return d < datetime.now()
        except ValueError:
            continue
    return False


def stage(job_status: str, online: bool, deadline: str, app_status: str | None) -> str:
    """The stage shown in the jobs table. An application that was actually sent keeps its stage even
    after the posting goes offline; a posting that was never applied to becomes offline / expired."""
    s = _APP.get(app_status or "")
    if s in ("submitted", "confirmed", "assessment", "interview", "offer", "rejected", "applying", "needs_you"):
        return s
    if s == "skipped" or job_status == "skipped":
        return "skipped"
    if not online or job_status == "offline":
        return "offline"
    if s in ("drafting", "needs_input", "draft_ready", "failed"):
        return s
    return "expired" if _past(deadline) else "not_applied"


def describe(key: str) -> dict[str, Any]:
    label, group, tone = STAGES[key]
    return {"stage": key, "stage_label": label, "stage_group": group, "stage_tone": tone}

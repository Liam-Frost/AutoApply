"""One user-facing stage per job, derived from the job row and its application.

Internally a job has a discovery status (new / scored / queued / skipped / offline) and, once a draft
exists, an application status (the state machine in drafts.py and executor.py). The jobs table shows a
single stage instead, so "not applied" never hides behind an internal word like "queued".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# key -> (label, group, tone)
STAGES: dict[str, tuple[str, str, str]] = {
    "not_applied": ("未投递", "todo", ""),
    "drafting": ("草案生成中", "active", "info"),
    "needs_input": ("草案待补充", "active", "warn"),
    "draft_ready": ("草案待审", "active", "warn"),
    "applying": ("投递中", "active", "info"),
    "needs_you": ("等你处理", "active", "warn"),
    "failed": ("投递失败", "active", "bad"),
    "submitted": ("投递成功", "applied", "info"),
    "confirmed": ("已确认投递", "applied", "ok"),
    "assessment": ("笔试 / OA / VA", "progress", "ok"),
    "interview": ("面试", "progress", "ok"),
    "offer": ("收到 Offer", "progress", "ok"),
    "rejected": ("已被拒", "rejected", "bad"),
    "skipped": ("不投递", "skipped", ""),
    "expired": ("已截止", "closed", ""),
    "offline": ("已下线", "closed", ""),
}
GROUPS = [("todo", "未投递"), ("active", "进行中"), ("applied", "已投递"), ("progress", "有进展"), ("rejected", "已被拒"), ("skipped", "不投递"), ("closed", "已下线 / 已截止"), ("all", "全部")]

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

"""One-off import of the legacy tracking table (jobs.tsv, 14 tab-separated columns).

Columns: ID 岗位 公司 方向 评分 学期 月数 薪资 工作类型 截止时间 投递渠道 登记状态 投递情况 岗位说明
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import db
from .models import Application, Job

STATUS_MAP = {
    # legacy 登记状态 -> (job.status, application.status | None)
    "未登记": ("scored", None),
    "新增意向": ("scored", None),
    "原有意向": ("scored", None),
    "待确认": ("scored", None),
    "已投递": ("queued", "submitted"),
    "已被拒": ("queued", "rejected"),
    "不投递": ("skipped", None),
    "已下线": ("offline", None),
}

_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _submitted_at(detail: str) -> datetime | None:
    m = _DATE.search(detail)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def import_tsv(path: str | Path) -> dict[str, int]:
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").split("\n") if ln.strip()]
    rows = [ln.split("\t") for ln in lines[1:]]
    added = updated = apps = 0
    with db.session() as s:
        for r in rows:
            if len(r) != 14:
                raise ValueError(f"expected 14 columns, got {len(r)}: {r[:2]}")
            sid, title, company, direction, score, term, months, salary, work, deadline, channel, st, detail, desc = r
            source = "pdportal" if sid.isdigit() else "manual"
            job = s.query(Job).filter_by(source=source, source_id=sid).first()
            jstatus, astatus = STATUS_MAP.get(st, ("scored", None))
            is_new = job is None
            if is_new:
                job = Job(source=source, source_id=sid)
                s.add(job)
                added += 1
            else:
                updated += 1
            job.title, job.company, job.direction = title, company, direction
            try:
                job.score = float(score)
            except ValueError:
                job.score = None
            job.term, job.months, job.salary, job.work_type = term, months, salary, work
            job.deadline, job.channel = deadline, channel
            job.status, job.online = jstatus, 0 if st == "已下线" else 1
            job.summary = desc
            if st == "不投递":
                job.exclusion = detail.removeprefix("不投：")
            job.note = detail
            s.flush()
            if astatus and job.application is None:
                s.add(
                    Application(
                        job_id=job.id,
                        status=astatus,
                        channel=channel,
                        submitted_at=_submitted_at(detail),
                        detail=detail,
                        evidence={"imported": True},
                    )
                )
                apps += 1
    return {"added": added, "updated": updated, "applications": apps, "rows": len(rows)}

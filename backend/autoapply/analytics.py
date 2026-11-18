"""Numbers for the analysis page: three views over one time window.

* ``applications`` - what came of the applications that were sent;
* ``automation``   - what the program's tasks (workflow executions) did, and where they failed - also per recruiting
                     system (``_systems``): how reading its forms and filling them went, what it took, who had to step in;
* ``ai``           - what the model calls used and what they cost, by model, by feature and per result.

Rules that hold everywhere:

* A window is given in local dates. Every figure of a view uses the same date for the same thing: applications by the
  day they were sent (a cohort), replies by the day they arrived, tasks by the day they started, model requests by the
  day they were made. Nothing mixes two of these without saying so.
* "Not known" is never zero. A cost that cannot be told (no usage reported, no price for the model, a record from
  before requests were kept) is ``None`` and is counted separately.
* Money is millionths of a dollar as integers; ratios are computed here, not in the page.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from . import db, humanize, llm, metering, stages
from .models import SENT, Application, ApplicationEvent, Draft, Job, LLMRequest, MailEvent, Run, Task

MIN_SAMPLE = 5          # a share over fewer applications than this is not shown as a percentage
POSITIVE = ("assessment", "interview", "offer")
DECISION_MAIL = ("rejection", "assessment", "interview", "offer")
REPLIED = ("confirmed", *POSITIVE, "rejected")


# --- the time window ----------------------------------------------------------------------------


def _local(dt: datetime | None) -> datetime | None:
    """A stored time (UTC, no zone) as local wall-clock time."""
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None) if dt else None


def _utc(local: datetime | None) -> datetime | None:
    return local.astimezone().astimezone(timezone.utc).replace(tzinfo=None) if local else None


@dataclass
class Window:
    lo: datetime | None          # UTC, inclusive (None = from the beginning)
    hi: datetime | None          # UTC, exclusive (None = until now)
    prev_lo: datetime | None     # the period of the same length just before, for comparison (None = there is none)
    prev_hi: datetime | None
    start: str                   # local dates, as shown
    end: str

    def has(self, dt: datetime | None) -> bool:
        return dt is not None and (self.lo is None or dt >= self.lo) and (self.hi is None or dt < self.hi)

    def had(self, dt: datetime | None) -> bool:
        return self.prev_lo is not None and dt is not None and self.prev_lo <= dt < self.prev_hi

    def describe(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "compared": self.prev_lo is not None}


def window(days: int = 0, start: str = "", end: str = "") -> Window:
    """``days`` = the last N days up to now; or local dates ``start`` / ``end`` (inclusive, YYYY-MM-DD); neither = everything."""
    now_l = datetime.now()

    def day(s: str) -> datetime | None:
        try:
            return datetime.strptime(s, "%Y-%m-%d") if s else None
        except ValueError:
            return None

    lo_l, hi_l = day(start), day(end)
    if lo_l is None and hi_l is None and days > 0:
        lo_l = now_l - timedelta(days=days)
    if hi_l is not None:
        hi_l += timedelta(days=1)
    prev_lo = prev_hi = None
    if lo_l is not None:
        span = (hi_l or now_l) - lo_l
        if span > timedelta(0):
            prev_lo, prev_hi = _utc(lo_l - span), _utc(lo_l)
    return Window(_utc(lo_l), _utc(hi_l), prev_lo, prev_hi, lo_l.strftime("%Y-%m-%d") if lo_l else "", (hi_l - timedelta(days=1)).strftime("%Y-%m-%d") if hi_l else "")


def _naive(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _fence(xs: list[float]) -> float | None:
    """Tukey's upper fence (Q3 + 1.5 x IQR): the usual, explainable line for "far above the rest". Needs a few values."""
    if len(xs) < 8:
        return None
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[2] + 1.5 * (q[2] - q[0])


# --- applications -------------------------------------------------------------------------------


def _heard_from(s: Any) -> tuple[dict[int, list[tuple[str, datetime | None]]], dict[int, set[str]]]:
    """The mails about each application (category, when) and the stages each application has been at."""
    mails: dict[int, list[tuple[str, datetime | None]]] = defaultdict(list)
    for m in s.query(MailEvent.application_id, MailEvent.category, MailEvent.received_at).filter(MailEvent.application_id.isnot(None)):
        mails[m[0]].append((m[1], _naive(m[2])))
    been: dict[int, set[str]] = defaultdict(set)
    for e in s.query(ApplicationEvent.application_id, ApplicationEvent.new):
        been[e[0]].add(e[1])
    return mails, been


def came_of(status: str, mine: list[tuple[str, datetime | None]], been: set[str]) -> dict[str, bool]:
    """The three things said about an application that was sent, wherever they are said (the overview, the analytics):

    - ``heard`` - 收到回执: anything came back, an automatic acknowledgement included;
    - ``decided`` - 有实质结果: it went on to an assessment or an interview, or was declined (an acknowledgement is not that);
    - ``progressed`` - 进入笔试/面试: it has been at an assessment, an interview or an offer - also when it was declined afterwards.

    "Has been": the status now, a status it had before, or a mail that says so."""
    progressed = status in POSITIVE or bool(been & set(POSITIVE)) or any(c in POSITIVE for c, _ in mine)
    decided = progressed or status == "rejected"
    return {"progressed": progressed, "decided": decided, "heard": decided or status in REPLIED or any(c != "other" for c, _ in mine)}


def sent_summary() -> dict[str, int]:
    """Everything that has gone out, and how much of it each page speaks about. "Sent" is the same number everywhere;
    a page that shows a part of it says which part: the overview's chart of stages leaves out the applications whose
    posting is archived, the analytics count by the day of sending and so leave out those without one (found through
    a mail, seen on the employer's site, marked by hand)."""
    with db.session() as s:
        mails, been = _heard_from(s)
        out = {"sent": 0, "dated": 0, "archived": 0, "heard": 0, "decided": 0, "progressed": 0}
        for a in s.query(Application).filter(Application.status.in_(SENT)):
            got = came_of(a.status, mails.get(a.id, []), been[a.id])
            out["sent"] += 1
            out["dated"] += 1 if a.submitted_at is not None else 0
            out["archived"] += 1 if a.job is not None and a.job.archived_at is not None else 0
            for k in ("heard", "decided", "progressed"):
                out[k] += 1 if got[k] else 0
    out["undated"] = out["sent"] - out["dated"]
    return out


def applications(w: Window) -> dict[str, Any]:
    """What came of the applications sent in the window (a cohort by the day of sending). Archived jobs are included:
    this is about what happened, not about what is still open."""
    coverage = sent_summary()
    with db.session() as s:
        mails, been = _heard_from(s)
        apps, prev_n = [], 0
        for a in s.query(Application).filter(Application.submitted_at.isnot(None)):
            sub_at = _naive(a.submitted_at)
            if w.had(sub_at):
                prev_n += 1
            if not w.has(sub_at):
                continue
            j = a.job
            mine = mails.get(a.id, [])
            decisions = sorted(t for c, t in mine if c in DECISION_MAIL + ("info_request",) and t is not None and t >= sub_at)   # an automatic receipt is not an answer
            got = came_of(a.status, mine, been[a.id])
            progressed, decided, heard = got["progressed"], got["decided"], got["heard"]
            apps.append({
                "status": a.status, "score": j.score, "direction": (j.direction or "未标注").split("/")[0].strip() or "未标注",
                "channel": "UBC PD Portal" if (j.ats == "pdportal" or j.channel == "PD Portal") else (humanize.ats_name(j.ats) if j.ats and j.ats != "generic" else "雇主官网"),
                "auto": bool(a.auto_approved), "wait": (decisions[0] - sub_at).days if decisions else None,
                "lead": (sub_at - _naive(j.first_seen)).days if j.first_seen else None, "month": _local(sub_at).strftime("%Y-%m"),
                "progressed": progressed, "decided": decided, "heard": heard, "offer": a.status == "offer" or "offer" in been[a.id]})
        # replies by the day they arrived (not by the day the application was sent)
        reply_months: dict[str, int] = defaultdict(int)
        for aid, lst in mails.items():
            for c, t in lst:
                if c in DECISION_MAIL and w.has(t):
                    reply_months[_local(t).strftime("%Y-%m")] += 1
        missed = []
        for j in s.query(Job).filter(Job.duplicate_of.is_(None), Job.score >= 7.5):
            st = stages.stage(j.status, bool(j.online), j.deadline or "", j.application.status if j.application else None)
            if st in ("expired", "offline") and w.has(_naive(j.first_seen)):
                missed.append({"id": j.id, "company": j.company, "title": j.title, "score": j.score, "deadline": (j.deadline or "")[:10], "stage": st,
                               "why": "没有申请链接" if not j.apply_url else "已截止，没有投" if st == "expired" else "已下线，没有投"})
        missed.sort(key=lambda r: (-(r["score"] or 0), r["deadline"] or "9999"))

    def rate(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {"n": len(rows), "replied": sum(1 for r in rows if r["heard"]), "decided": sum(1 for r in rows if r["decided"]),
                "positive": sum(1 for r in rows if r["status"] in POSITIVE), "progressed": sum(1 for r in rows if r["progressed"]),
                "rejected": sum(1 for r in rows if r["status"] == "rejected"), "offer": sum(1 for r in rows if r["offer"])}

    def by(key: Callable[[dict[str, Any]], str], order: list[str] | None = None) -> list[dict[str, Any]]:
        g: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in apps:
            g[key(r)].append(r)
        return [{"label": k, **rate(g[k]), "thin": len(g[k]) < MIN_SAMPLE} for k in (order or sorted(g, key=lambda k: -len(g[k]))) if k in g]

    def band(r: dict[str, Any]) -> str:
        sc = r["score"]
        return "没评分" if sc is None else "9–10" if sc >= 9 else "8–8.5" if sc >= 8 else "7–7.5" if sc >= 7 else "6–6.5" if sc >= 6 else "6 以下"

    total = rate(apps)
    waits = sorted(r["wait"] for r in apps if r["wait"] is not None)
    leads = sorted(r["lead"] for r in apps if r["lead"] is not None and r["lead"] >= 0)
    # Where each application stands now. Exactly one of these per application, so the parts add up to the whole.
    state = lambda r: ("offer" if r["status"] == "offer" else "interview" if r["status"] == "interview" else "assessment" if r["status"] == "assessment"  # noqa: E731
                       else "rejected" if r["status"] == "rejected" else "other" if r["status"] not in ("submitted", "confirmed") else "receipt" if r["heard"] else "silent")
    states = defaultdict(int)
    for r in apps:
        states[state(r)] += 1
    months = sorted({r["month"] for r in apps} | set(reply_months))
    per_month = {m["label"]: m for m in by(lambda r: r["month"])}
    return {
        "window": w.describe(), "total": total, "previous": {"n": prev_n} if w.prev_lo is not None else None, "min_sample": MIN_SAMPLE,
        "coverage": coverage,
        # Each step is a part of the one before (sent > heard anything > a decision > got further > offer), so it can be drawn as a funnel.
        "funnel": [{"key": "sent", "label": "投出", "value": total["n"]}, {"key": "heard", "label": "收到回执（确认信或任何回复）", "value": total["replied"]},
                   {"key": "decided", "label": "有实质结果（进展或被拒）", "value": total["decided"]},
                   {"key": "progressed", "label": "进入笔试 / 面试", "value": total["progressed"]}, {"key": "offer", "label": "拿到 Offer", "value": total["offer"]}],
        "states": [{"key": k, "label": lab, "value": states.get(k, 0)} for k, lab in
                   (("silent", "没有任何回音"), ("receipt", "只收到自动确认"), ("assessment", "笔试 / 测评中"), ("interview", "面试中"), ("offer", "Offer"), ("rejected", "被拒"), ("other", "其他（撤回等）"))],
        "rejected_after_progress": sum(1 for r in apps if r["status"] == "rejected" and r["progressed"]),
        "median_wait_days": waits[len(waits) // 2] if waits else None, "waited": len(waits), "median_lead_days": leads[len(leads) // 2] if leads else None,
        "by_score": by(band, ["9–10", "8–8.5", "7–7.5", "6–6.5", "6 以下", "没评分"]), "by_channel": by(lambda r: r["channel"]), "by_direction": by(lambda r: r["direction"])[:8],
        "by_month": [{"label": m, **(per_month.get(m) or {**rate([]), "thin": True}), "replies": reply_months.get(m, 0)} for m in months],
        "auto": {"auto": sum(1 for r in apps if r["auto"]), "manual": sum(1 for r in apps if not r["auto"])},
        "missed": missed[:12], "missed_total": len(missed),
    }


# --- tasks: what a workflow execution came to ----------------------------------------------------

OUTCOMES = {"success": "完成", "handed": "填好，等你提交", "unknown": "点了提交，结果待确认", "waiting": "等你处理", "rerun": "改为可见窗口重跑", "failed": "失败", "interrupted": "被中断",
            "cancelled": "已取消", "skipped": "没有要做的", "running": "进行中"}
UNFINISHED = ("handed", "unknown", "waiting", "rerun", "running")       # not a failure: the next move is yours, or it is still going
# (not counted either way: the task was called off, or found that there was nothing for it to do)
NOT_COUNTED = ("cancelled", "skipped")
STAGES = {"read_form": "读取申请表", "ensure_session": "登录网站", "open": "打开申请表", "sign_in": "登录网站", "reopen": "打开申请表", "walk": "逐步填写", "fill_step": "填写",
          "fill_page": "填写", "form_reports": "表单校验", "repair": "AI 接手", "repair_skipped": "AI 接手", "read_back": "和草案核对", "unverified": "和草案核对",
          "next": "翻页", "advance": "翻页", "cannot_advance": "翻页", "stuck": "翻页", "not_asked": "和确认页核对", "review_step": "确认页", "handed_over": "交给你提交",
          "submit": "提交", "scouted": "读完后面的步骤", "read_step": "读这一步问了什么", "read_review": "读确认页", "review_unfolded": "展开确认页上的答案", "email_code": "邮箱验证码", "submitted_in_window": "你已提交", "window_closed": "窗口被关闭"}


def stage_label(key: str) -> str:
    return STAGES.get(key) or metering.FEATURES.get(key) or key


def outcome(kind: str, status: str, result: dict[str, Any] | None, error: str) -> str:
    """What a task came to. "Done" is not always success: a filling task is done when it has handed the form over."""
    if status in ("queued", "running"):
        return "running"
    if status == "waiting_human":
        return "waiting"
    if status == "cancelled":
        return "cancelled"
    if status == "failed":
        return "interrupted" if "interrupted" in (error or "") else "failed"
    if kind == "execute":
        # A filling task counts as a success when THIS run got the application submitted - not when the task ended
        # without an error. A task that found the application already sent (a retry, a task that was still queued)
        # answers with where the application stands and submitted nothing: it was counted among the successes. And
        # "Submit was pressed, nothing says it was received" is neither that nor "handed over to you".
        st, note = str((result or {}).get("status") or ""), str((result or {}).get("note") or "")
        if st == "skipped" or note in ("already submitted", "waiting for the outcome of a submission"):
            return "skipped"
        return {"submitted": "success", "ready_to_submit": "handed", "submit_unknown": "unknown", "needs_human": "waiting", "approved": "rerun"}.get(st, "failed" if st in ("failed", "drifted") else "success")
    if kind == "scout" and str((result or {}).get("status") or "") in ("failed", "needs_human"):      # the walk itself did not work
        return "failed"
    return "success"


# Why a task failed, as a short name. The mapping reads the raw error text and is the same for every run, so the same
# failure always lands in the same group; the sentence shown elsewhere and the raw text are kept beside it.
CATEGORIES: list[tuple[str, str, str]] = [
    ("interrupted", "运行被中断", r"interrupted|superseded|server stopped|Target page, context or browser has been closed|TargetClosed"),
    ("ai_limit", "AI 额度用完", r"usage limit|limit reached|quota|额度|欠费|insufficient|billing"),
    ("ai_unavailable", "AI 服务不可用", r"LLMUnavailable|LLMError|login is not usable|no model|API key|AI 服务|AI 模型"),
    ("posting_closed", "岗位已关闭", r"posting not found|已关闭|已经关闭|no longer|下线|\b404\b|closed or wrong id"),
    ("site_down", "网站打不开", r"网站暂时打不开|打不开|not answering|HTTP 5\d\d|ERR_|Page\.goto: Timeout|could not open the posting|SiteDown"),
    ("login", "需要登录或验证", r"login required|needs login|sign.?in|captcha|verification|登录|验证码"),
    ("cannot_advance", "表单进不了下一页", r"could not advance|没法进入下一步|does not go on"),
    ("fields", "有字段没填上", r"could not set every field|field\(s\) could not be filled|没能自动填上|option not found"),
    ("mismatch", "填的和草案不一致", r"differ from the approved draft|不一致|verify failed|mismatch"),
    ("form_changed", "申请表有变化", r"form changed|drift"),
    ("no_confirmation", "提交后没看到确认", r"no confirmation after submit"),
    ("materials", "材料没准备好", r"cover-letter|cover letter|résumé|resume|求职信|简历"),
    ("program", "程序自身出错", r"Error:|Exception|Traceback|driver bug|while parsing"),
]


def failure(kind: str, status: str, result: dict[str, Any] | None, error: str) -> dict[str, str]:
    """{key, label, message, raw} for a failed task: a short category, the sentence the program shows, the text as recorded."""
    import re

    raw = (error or str((result or {}).get("error") or "")).strip()
    if not raw:
        return {"key": "none", "label": "没有记录原因", "message": "", "raw": ""}
    key, label = next(((k, lab) for k, lab, pat in CATEGORIES if re.search(pat, raw, re.I)), ("other", "其他原因"))
    return {"key": key, "label": label, "message": humanize.explain(raw)["message"] or raw[:120], "raw": raw[:600]}


def _task_rows(s: Any, w: Window) -> list[dict[str, Any]]:
    rows = []
    for t in s.query(Task):
        at = _naive(t.started_at or t.created_at)
        if not w.has(at):
            continue
        oc = outcome(t.kind, t.status, t.result, t.error)
        dur = (_naive(t.finished_at) - _naive(t.started_at)).total_seconds() if t.started_at and t.finished_at else None
        st = [x.get("stage") for x in (t.stages or []) if isinstance(x, dict)]
        rows.append({"id": t.id, "kind": t.kind, "ref": t.ref or "", "at": at, "outcome": oc, "duration": dur, "attempts": t.attempts or 0, "stage": st[-1] if st else "",
                     "has_stages": t.stages is not None, **({"why": failure(t.kind, t.status, t.result, t.error)} if oc in ("failed", "interrupted") else {"why": None}),
                     "reason": failure(t.kind, t.status, t.result, t.error)["message"] if oc in ("failed", "interrupted") else "",
                     "result": t.result or {}, "auto_retry": bool((t.payload or {}).get("_limit_retries") or (t.payload or {}).get("_down_retries"))})
    # a filling task from before stages were kept: the last step of its run says how far it got
    old = [r["id"] for r in rows if r["kind"] == "execute" and not r["stage"]]
    if old:
        for run in s.query(Run.task_id, Run.steps).filter(Run.kind == "execute", Run.task_id.in_(old)):
            ops = [x.get("op") for x in (run[1] or []) if isinstance(x, dict)]
            for r in rows:
                if r["id"] == run[0] and ops:
                    r["stage"] = ops[-1]
    return rows


def _ai_by_task(s: Any, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    ids = list(ids)
    out: dict[int, dict[str, Any]] = defaultdict(lambda: {"requests": 0, "tokens": 0, "cost": 0, "priced": 0, "unknown": 0, "legacy": False})
    if not ids:
        return out
    q = s.query(LLMRequest.task_id, LLMRequest.input_tokens, LLMRequest.cache_read_tokens, LLMRequest.cache_write_tokens, LLMRequest.output_tokens,
                LLMRequest.cost_micros, LLMRequest.source, LLMRequest.turns).filter(LLMRequest.task_id.isnot(None))
    want = set(ids)
    for tid, a, b, c, d, cost, src, turns in q:
        if tid not in want:
            continue
        o = out[tid]
        o["requests"] += (turns or 1) if src == "legacy" else 1
        o["tokens"] += sum(int(x or 0) for x in (a, b, c, d))
        if cost is None:
            o["unknown"] += 1
        else:
            o["cost"] += cost
            o["priced"] += 1
        o["legacy"] = o["legacy"] or src == "legacy"
    return out


def _bucket_fn(w: Window, firsts: list[datetime], bucket: str = "") -> tuple[str, Callable[[datetime], tuple[str, str]]]:
    """How to group days for a trend: by day for a short window, by week for a medium one, else by month."""
    lo = w.lo or (min(firsts) if firsts else None)
    hi = w.hi or datetime.now(timezone.utc).replace(tzinfo=None)
    days = (hi - lo).days if lo else 0
    size = bucket if bucket in ("day", "week", "month") else "day" if days <= 45 else "week" if days <= 200 else "month"

    def key(dt: datetime) -> tuple[str, str]:
        d = _local(dt)
        if size == "day":
            return d.strftime("%Y-%m-%d"), d.strftime("%m/%d")
        if size == "week":
            mon = d - timedelta(days=d.weekday())
            return mon.strftime("%Y-%m-%d"), mon.strftime("%m/%d")
        return d.strftime("%Y-%m"), d.strftime("%y/%m")

    return size, key


def _run_row(r: dict[str, Any], ai: dict[int, dict[str, Any]], subject: str) -> dict[str, Any]:
    """One run as the page lists it."""
    a = ai.get(r["id"])
    return {"id": r["id"], "kind": r["kind"], "label": metering.workflow_label(r["kind"]), "subject": subject, "at": r["at"].isoformat(), "outcome": r["outcome"],
            "outcome_label": OUTCOMES[r["outcome"]], "duration_s": r["duration"], "attempts": r["attempts"], "reason": r["reason"], "reason_label": (r["why"] or {}).get("label", ""),
            "stage": stage_label(r["stage"]) if r["stage"] else "",
            "requests": a["requests"] if a else 0, "tokens": a["tokens"] if a else 0, "cost": (a["cost"] if a["priced"] else None) if a else None,
            "cost_partial": bool(a["unknown"]) if a else False, "ref": r["ref"]}


def runs(w: Window, *, kind: str = "", outcome: str = "", offset: int = 0, limit: int = 15) -> dict[str, Any]:
    """The runs of the window, newest first, a page at a time (the list behind "show all" on the automation view)."""
    group = {"success": ("success",), "unfinished": UNFINISHED, "failed": ("failed", "interrupted")}.get(outcome)
    limit = max(1, min(int(limit or 15), 100))
    with db.session() as s:
        rows = [r for r in _task_rows(s, w) if (not kind or r["kind"] == kind) and (group is None or r["outcome"] in group)]
        rows.sort(key=lambda r: (r["at"], r["id"]), reverse=True)
        page = rows[max(0, int(offset or 0)):][:limit]
        ai = _ai_by_task(s, [r["id"] for r in page])
        out = [_run_row(r, ai, humanize.subject(r["ref"])) for r in page]
    return {"total": len(rows), "offset": max(0, int(offset or 0)), "limit": limit, "rows": out}


def system_label(ats: str) -> str:
    return "UBC PD Portal" if ats == "pdportal" else humanize.ats_name(ats) if ats and ats != "generic" else "其他网站（没有专门的驱动）"


def _systems(s: Any, rows: list[dict[str, Any]], ai: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per recruiting system, from the tasks of the window: how reading its forms went, how filling them went, how
    often a run stopped for the applicant, and what the model was asked for it.

    Every site's form is read by the agent and the system's driver is a tool for it (the decision is written down in
    REFACTOR_PLAN). Whether that serves a system well is a question of these figures, system by system - not of one
    figure for all of them. The definitions are the ones the rest of this view uses:

    - a task belongs to the system of the posting it is about (its "job:", "application:" or "draft:");
    - success rate = succeeded / ran to an end of its own (succeeded + failed + interrupted). A fill that ends with the
      form handed over, or with Submit pressed and no confirmation, is not in it either way - it is shown beside it;
    - the time of a fill is the run's working time (timing.working_ms): the applicant's own time is not in it;
    - a stop for the applicant is a step of the run that waited for them (timing.stops_for_applicant), counted from
      the steps of every run - the column on the run was never written before, so it is not read;
    - the model's use is everything asked on behalf of the system's postings in the window - reading, answering,
      revising, filling, the failed tasks too - and a cost only where one is known.
    """
    from . import timing

    jobs = {i: ats or "generic" for i, ats in s.query(Job.id, Job.ats)}
    apps = dict(s.query(Application.id, Application.job_id).all())
    drafts = dict(s.query(Draft.id, Draft.application_id).all())

    def posting(ref: str) -> int | None:
        kind, _, rest = (ref or "").partition(":")
        num = rest.split(":")[0]
        if not num.isdigit():
            return None
        n = int(num)
        return n if kind == "job" else apps.get(n) if kind == "application" else apps.get(drafts.get(n)) if kind == "draft" else None

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        job = posting(r["ref"])
        if job in jobs:
            groups[jobs[job]].append({**r, "job": job})
    fills = {r["id"] for rs in groups.values() for r in rs if r["kind"] == "execute"}
    runs: dict[int, list[dict[str, int]]] = defaultdict(list)
    if fills:
        for task_id, spans, steps in s.query(Run.task_id, Run.spans, Run.steps).filter(Run.kind == "execute", Run.task_id.isnot(None)):
            if task_id in fills:
                runs[task_id].append({"working_ms": timing.working_ms(spans or []) if spans else None, "stops": timing.stops_for_applicant(steps), "takeovers": timing.takeovers(steps)})

    def part(xs: list[dict[str, Any]]) -> dict[str, Any]:
        c = {k: sum(1 for r in xs if r["outcome"] == k) for k in OUTCOMES}
        settled = c["success"] + c["failed"] + c["interrupted"]
        ran = sorted(r["duration"] for r in xs if r["duration"] is not None and r["outcome"] in ("success", "failed"))
        return {"total": len(xs) - sum(c[k] for k in NOT_COUNTED), "success": c["success"], "failed": c["failed"] + c["interrupted"], "settled": settled,
                "success_rate": round(c["success"] / settled, 4) if settled else None, "median_s": _median(ran),
                "handed": c["handed"], "unknown": c["unknown"], "waiting": c["waiting"] + c["rerun"], "running": c["running"]}

    out = []
    for key, rs in groups.items():
        fill = [r for r in rs if r["kind"] == "execute"]
        mine = [x for r in fill for x in runs.get(r["id"], [])]
        worked = [x["working_ms"] for x in mine if x["working_ms"] is not None]
        got = [ai[r["id"]] for r in rs if r["id"] in ai]
        postings = len({r["job"] for r in rs})
        tokens = sum(g["tokens"] for g in got)
        out.append({
            "ats": key, "label": system_label(key), "postings": postings,
            "read": part([r for r in rs if r["kind"] == "recon"]),
            "fill": {**part(fill), "working_ms": int(_median(worked)) if worked else None},
            "human": {"runs": len(mine), "stops": sum(x["stops"] for x in mine), "runs_stopped": sum(1 for x in mine if x["stops"]),
                      "stops_per_run": round(sum(x["stops"] for x in mine) / len(mine), 2) if mine else None,
                      "takeovers_per_run": round(sum(x["takeovers"] for x in mine) / len(mine), 2) if mine else None},
            "ai": {"requests": sum(g["requests"] for g in got), "tokens": tokens, "tokens_per_posting": round(tokens / postings) if postings and tokens else None,
                   "cost": sum(g["cost"] for g in got) if any(g["priced"] for g in got) else None, "cost_unknown_requests": sum(g["unknown"] for g in got)},
        })
    return sorted(out, key=lambda r: -(r["read"]["total"] + r["fill"]["total"]))


def automation(w: Window, *, kind: str = "") -> dict[str, Any]:
    """What the program's tasks did in the window (by the day a task started)."""
    with db.session() as s:
        rows = _task_rows(s, w)
        prev_n = sum(1 for t in s.query(Task.started_at, Task.created_at) if w.had(_naive(t[0] or t[1]))) if w.prev_lo is not None else None
        ai = _ai_by_task(s, [r["id"] for r in rows])
        systems = _systems(s, rows, ai)
        kinds = sorted({r["kind"] for r in rows}, key=lambda k: -sum(1 for r in rows if r["kind"] == k))
        shown = [r for r in rows if not kind or r["kind"] == kind]
        recent = sorted(shown, key=lambda r: (r["at"], r["id"]), reverse=True)[:8]
        subjects = {r["id"]: humanize.subject(r["ref"]) for r in recent}

    def counts(rs: list[dict[str, Any]]) -> dict[str, Any]:
        c = {k: sum(1 for r in rs if r["outcome"] == k) for k in OUTCOMES}
        settled = c["success"] + c["failed"] + c["interrupted"]            # tasks that ran to an end of their own
        return {"total": len(rs), **c, "unfinished": sum(c[k] for k in UNFINISHED), "success_rate": round(c["success"] / settled, 4) if settled else None, "settled": settled}

    def cost_of(rs: list[dict[str, Any]]) -> dict[str, Any]:
        got = [ai[r["id"]] for r in rs if r["id"] in ai]
        # a cost is the sum of what is known; when some requests have none, the sum is a lower bound and says so
        return {"requests": sum(g["requests"] for g in got), "tokens": sum(g["tokens"] for g in got), "cost": sum(g["cost"] for g in got) if any(g["priced"] for g in got) else None,
                "cost_unknown_requests": sum(g["unknown"] for g in got)}

    by_kind = []
    for k in kinds:
        rs = [r for r in rows if r["kind"] == k]
        c, a = counts(rs), cost_of(rs)
        ran = sorted(r["duration"] for r in rs if r["duration"] is not None and r["outcome"] in ("success", "failed"))
        by_kind.append({"kind": k, "label": metering.workflow_label(k), **c, "median_s": _median(ran), "p90_s": ran[int(len(ran) * 0.9)] if len(ran) >= 10 else None,
                        "retried": sum(1 for r in rs if r["attempts"] > 1), **a,
                        # everything spent on this kind of task, the failed runs included, over the ones that succeeded
                        # (a lower bound when some of its requests have no cost: the page shows it as "at least")
                        "cost_per_success": round(a["cost"] / c["success"]) if a["cost"] is not None and c["success"] else None,
                        "waits_for_you": k == "execute"})
    bad = [r for r in shown if r["outcome"] in ("failed", "interrupted")]
    # Every failure is in exactly one category; inside it, the sentences the program shows are counted one by one and an
    # example of the raw text is kept, so nothing of the old list is lost - it is one level down.
    reasons: dict[str, dict[str, Any]] = {}
    for r in bad:
        w_ = r["why"]
        e = reasons.setdefault(w_["key"], {"key": w_["key"], "reason": w_["label"], "n": 0, "kinds": set(), "messages": {}})
        e["n"] += 1
        e["kinds"].add(metering.workflow_label(r["kind"]))
        m = e["messages"].setdefault(w_["message"] or w_["label"], {"message": w_["message"] or w_["label"], "n": 0, "raw": w_["raw"]})
        m["n"] += 1
    by_stage: dict[str, dict[str, Any]] = {}
    for r in bad:
        e = by_stage.setdefault(r["stage"], {"key": r["stage"], "stage": stage_label(r["stage"]) if r["stage"] else "没有记录到哪一步", "n": 0, "recorded": bool(r["stage"])})
        e["n"] += 1
    # the same thing run again: how often, and how many of those were the program's own retries
    per_obj: dict[tuple[str, str], int] = defaultdict(int)
    for r in shown:
        if any(ch.isdigit() for ch in r["ref"]):
            per_obj[(r["kind"], r["ref"])] += 1
    size, key = _bucket_fn(w, [r["at"] for r in shown])
    trend: dict[str, dict[str, Any]] = {}
    for r in sorted(shown, key=lambda r: r["at"]):
        k, lab = key(r["at"])
        b = trend.setdefault(k, {"key": k, "label": lab, "success": 0, "unfinished": 0, "failed": 0})
        b["success" if r["outcome"] == "success" else "failed" if r["outcome"] in ("failed", "interrupted") else "unfinished"] += 1 if r["outcome"] not in NOT_COUNTED else 0
    total, a_all = counts(shown), cost_of(shown)
    return {
        "window": w.describe(), "total": total, "previous": {"total": prev_n} if prev_n is not None and not kind else None, "ai": a_all,
        "kinds": [{"kind": k, "label": metering.workflow_label(k)} for k in kinds], "by_kind": by_kind, "bucket": size, "trend": list(trend.values()),
        "reasons": sorted(({**v, "kinds": sorted(v["kinds"]), "messages": sorted(v["messages"].values(), key=lambda m: -m["n"])} for v in reasons.values()), key=lambda v: -v["n"]),
        "stages": sorted(by_stage.values(), key=lambda v: (not v["recorded"], -v["n"])), "stages_recorded": any(r["has_stages"] for r in bad) if bad else None,
        "repeats": {"objects": sum(1 for v in per_obj.values() if v > 1), "extra_runs": sum(v - 1 for v in per_obj.values() if v > 1),
                    "auto_retries": sum(1 for r in shown if r["auto_retry"]), "restarted": sum(1 for r in shown if r["attempts"] > 1)},
        "outcomes": OUTCOMES,
        "recent": [_run_row(r, ai, subjects.get(r["id"], "")) for r in recent], "recent_total": len(shown),
        "systems": systems,      # (all kinds of task, whatever ``kind`` narrows the rest to: a system is read and filled)
    }


# --- AI use and cost ----------------------------------------------------------------------------

BILLING = {"metered": "按量计费", "subscription": "订阅内（不另收费）", "local": "本机模型（免费）", "unknown": "没有记录"}
TOKEN_KINDS = (("input", "输入"), ("cache_read", "缓存读取"), ("cache_write", "缓存写入"), ("output", "输出"))


# --- where the time of the runs went (timing.py), and what was learned from it (learned.py) ---


def _sites() -> list[dict[str, Any]]:
    """The sites something was learned about (how they are worked): for the analysis page."""
    from . import sites

    return [r for r in sites.listing() if r["notes"] or r["steps"] or r["revisions"]]


def timing_overview(w: Window, *, ats: str = "", limit: int = 2000) -> dict[str, Any]:
    """Runs that filled a form, in the window: how long they took without the applicant's own time, by what the
    time was spent on, per system over time, and the runs themselves."""
    from . import humanize, learned, timing
    from .models import Run

    with db.session() as s:
        rows = [r for r in s.query(Run).filter(Run.kind == "execute", Run.spans.isnot(None)).order_by(Run.id.desc()).limit(2000) if w.has(_naive(r.created_at)) and (not ats or r.ats == ats)]
        runs = [{"id": r.id, "at": r.created_at.isoformat(), "ats": r.ats, "site": r.site or "", "ok": bool(r.ok), "subject": humanize.subject(r.ref), "learned": list(r.learned or []),
                 "working_ms": timing.working_ms(r.spans or []), "totals": timing.totals(r.spans or []), "takeovers": timing.takeovers(r.steps), "stops": timing.stops_for_applicant(r.steps)} for r in rows]
    systems: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        systems.setdefault(r["ats"], []).append(r)
    by_system = []
    for name, rs in sorted(systems.items(), key=lambda kv: -len(kv[1])):
        weeks: dict[str, list[dict[str, Any]]] = {}
        for r in rs:
            local = _local(datetime.fromisoformat(r["at"]))
            start = (local - timedelta(days=local.weekday())).date().isoformat()
            weeks.setdefault(start, []).append(r)
        trend = [{"week": k, "runs": len(v), "median_ms": int(_median([x["working_ms"] for x in v]) or 0), "ok": sum(1 for x in v if x["ok"]),
                  **{kind: int(_median([x["totals"][kind] for x in v]) or 0) for kind in ("site", "driver", "ai", "tool")}} for k, v in sorted(weeks.items())]
        by_system.append({"ats": name, "runs": len(rs), "ok": sum(1 for x in rs if x["ok"]), "median_ms": int(_median([x["working_ms"] for x in rs]) or 0),
                          "takeovers": round(sum(x["takeovers"] for x in rs) / len(rs), 1), "trend": trend})
    revs = [{**{k: v.get(k) for k in ("id", "kind", "target", "title", "why", "expected", "status", "why_status", "created", "from_run", "version", "strikes", "baseline")},
             "trials": len(v.get("trials") or []), "good": sum(1 for t in v.get("trials") or [] if t.get("ok") and t.get("used")),
             "median_ms": int(_median([t["ms"] for t in v.get("trials") or [] if t.get("ok") and t.get("used")]) or 0)} for v in reversed(learned.revisions())]
    return {"window": w.describe(), "runs": runs[:limit], "count": len(runs), "systems": by_system, "learned": revs,
            "mode": db.get_setting("learned.mode") or "auto", "enabled": bool(db.get_setting("learned.enabled")), "share": db.get_setting("learned.share") or "ask", "sites": _sites()}


def timing_run(run_id: int) -> dict[str, Any]:
    """One run: its spans in order, what stands out in it, and what was learned that was in force."""
    from . import humanize, improve, learned
    from .models import Run

    with db.session() as s:
        r = s.get(Run, run_id)
        if r is None or r.spans is None:
            raise KeyError(run_id)
        out = {"id": r.id, "at": r.created_at.isoformat(), "ats": r.ats, "site": r.site or "", "ok": bool(r.ok), "subject": humanize.subject(r.ref), "spans": list(r.spans or []),
               "learned": [{"id": i, "title": (learned.get(i) or {}).get("title", ""), "status": (learned.get(i) or {}).get("status", "")} for i in (r.learned or [])]}
    return {**out, "review": improve.review(run_id)}


def _provider_label(p: str) -> str:
    return llm.label(p) if p else "改造前的记录"


def _requests(s: Any, lo: datetime | None, hi: datetime | None, provider: str, model: str, feature: str) -> list[Any]:
    q = s.query(LLMRequest)
    if lo is not None:
        q = q.filter(LLMRequest.started_at >= lo)
    if hi is not None:
        q = q.filter(LLMRequest.started_at < hi)
    if provider:
        q = q.filter(LLMRequest.provider == provider)
    if model:
        q = q.filter(LLMRequest.model == model)
    if feature:
        q = q.filter(LLMRequest.feature == feature)
    return q.order_by(LLMRequest.id).all()


def _tok(r: Any) -> int:
    return sum(int(x or 0) for x in (r.input_tokens, r.cache_read_tokens, r.cache_write_tokens, r.output_tokens))


def _sum_up(rows: list[Any]) -> dict[str, Any]:
    """Totals of a set of requests. Legacy rows (a per-task total from before requests were kept) are counted apart."""
    live = [r for r in rows if r.source == "live"]
    legacy = [r for r in rows if r.source == "legacy"]
    priced = [r for r in live if r.cost_micros is not None]
    by_billing: dict[str, int] = defaultdict(int)
    for r in priced:
        by_billing[r.billing] += r.cost_micros
    tokens = {k: sum(int(getattr(r, f"{k}_tokens") or 0) for r in live if r.detail == "full") for k, _ in TOKEN_KINDS}
    tokens["unsplit"] = sum(int(r.input_tokens or 0) for r in live if r.detail == "no_cache_split")       # prompt tokens whose cached part is not told apart
    tokens["output"] += sum(int(r.output_tokens or 0) for r in live if r.detail == "no_cache_split")
    return {
        "requests": len(live), "turns": sum(r.turns or 1 for r in live), "calls": len({r.call_id for r in live}),
        "tokens": tokens, "tokens_total": sum(tokens.values()),
        "cost": sum(r.cost_micros for r in priced) if priced else None, "by_billing": dict(by_billing),
        "priced_requests": len(priced), "unpriced_requests": sum(1 for r in live if r.cost_micros is None and r.detail != "none"),
        "no_usage_requests": sum(1 for r in live if r.detail == "none"),
        "reported_cost_requests": sum(1 for r in priced if r.cost_source == "provider"),
        "failed_requests": sum(1 for r in live if r.status != "ok"),
        "legacy": {"tasks": len(legacy), "calls": sum(r.turns or 1 for r in legacy), "input": sum(int(r.input_tokens or 0) for r in legacy),
                   "output": sum(int(r.output_tokens or 0) for r in legacy)} if legacy else None,
    }


def ai(w: Window, *, group: str = "model", bucket: str = "", provider: str = "", model: str = "", feature: str = "") -> dict[str, Any]:
    """What the model calls made in the window used and cost."""
    with db.session() as s:
        everything = _requests(s, w.lo, w.hi, "", "", "")
        rows = [r for r in everything if (not provider or r.provider == provider) and (not model or r.model == model) and (not feature or r.feature == feature)]
        prev = _sum_up(_requests(s, w.prev_lo, w.prev_hi, provider, model, feature)) if w.prev_lo is not None else None
        tasks = {t["id"]: t for t in _task_rows(s, Window(None, None, None, None, "", ""))}
    live = [r for r in rows if r.source == "live"]
    total = _sum_up(rows)
    cost_total = total["cost"] or 0

    # --- trend -----------------------------------------------------------------------------------
    gkey = {"model": lambda r: r.model or "", "feature": lambda r: r.feature or "", "provider": lambda r: r.provider or ""}.get(group) or (lambda r: r.model or "")
    glabel = (lambda k: k or "没有记录模型") if group not in ("feature", "provider") else metering.feature_label if group == "feature" else _provider_label
    weight: dict[str, int] = defaultdict(int)
    for r in live:
        weight[gkey(r)] += (r.cost_micros or 0) if cost_total else _tok(r)
    top = [k for k, _ in sorted(weight.items(), key=lambda kv: -kv[1])[:6]]
    size, bkey = _bucket_fn(w, [r.started_at for r in live], bucket)
    buckets: dict[str, dict[str, Any]] = {}
    for r in live:
        k, lab = bkey(r.started_at)
        b = buckets.setdefault(k, {"key": k, "label": lab, "cost": 0, "requests": 0, "tokens": 0, "unpriced": 0, "values": defaultdict(int), "token_values": defaultdict(int)})
        g = gkey(r) if gkey(r) in top else "__other"
        b["requests"] += 1
        b["tokens"] += _tok(r)
        b["token_values"][g] += _tok(r)
        if r.cost_micros is None:
            b["unpriced"] += 1
        else:
            b["cost"] += r.cost_micros
            b["values"][g] += r.cost_micros
    series = [{"key": k, "label": glabel(k)} for k in top] + ([{"key": "__other", "label": "其他"}] if len(weight) > len(top) else [])

    # --- token structure: how many, and what share of the cost each kind carries --------------------
    kind_cost: dict[str, int] = defaultdict(int)
    split_rows = 0
    for r in live:
        if r.cost_micros is None or r.detail != "full":
            continue
        parts = metering.class_costs(metering.Tokens(r.input_tokens, r.cache_read_tokens, r.cache_write_tokens, r.output_tokens), metering.price_for(r.provider, r.model))
        if not parts or not sum(parts.values()):
            continue
        scale = r.cost_micros / sum(parts.values())        # a cost the service reported is divided in the proportions of the price list
        for k, v in parts.items():
            kind_cost[k] += round(v * scale)
        split_rows += 1

    # --- by model, provider, feature --------------------------------------------------------------
    def table(key: Callable[[Any], Any], more: Callable[[Any, list[Any]], dict[str, Any]]) -> list[dict[str, Any]]:
        g: dict[Any, list[Any]] = defaultdict(list)
        for r in live:
            g[key(r)].append(r)
        out = []
        for k, rs in g.items():
            priced = [r for r in rs if r.cost_micros is not None]
            cost = sum(r.cost_micros for r in priced) if priced else None
            calls = defaultdict(list)
            for r in rs:
                calls[r.call_id].append(r)
            ok_calls = sum(1 for c in calls.values() if max(c, key=lambda r: (r.attempt, r.id)).status == "ok")     # a call is judged by its last attempt
            out.append({**more(k, rs), "requests": len(rs), "turns": sum(r.turns or 1 for r in rs), "calls": len(calls), "ok_calls": ok_calls,
                        "ok_rate": round(ok_calls / len(calls), 4) if calls else None, "tokens": sum(_tok(r) for r in rs), "cost": cost,
                        "unpriced_requests": sum(1 for r in rs if r.cost_micros is None and r.detail != "none"), "no_usage_requests": sum(1 for r in rs if r.detail == "none"),
                        "avg_cost": round(cost / len(priced)) if priced else None, "avg_cost_per_call": round(cost / len({r.call_id for r in priced})) if priced else None,
                        "share": round(cost / cost_total, 4) if cost is not None and cost_total else None,
                        "median_ms": _median([r.latency_ms for r in rs if r.latency_ms is not None])})
        return sorted(out, key=lambda r: (-(r["cost"] or 0), -r["tokens"]))

    def price_of(p: str, m: str) -> dict[str, Any] | None:
        pr = metering.price_for(p, m)
        return {k: (float(pr[k]) if k in ("input", "output", "cache_read", "cache_write") else pr[k]) for k in ("input", "output", "cache_read", "cache_write", "source", "version")} if pr else None

    by_model = table(lambda r: (r.provider, r.model), lambda k, rs: {"provider": k[0], "provider_label": _provider_label(k[0]), "model": k[1], "billing": rs[0].billing,
                                                                    "billing_label": BILLING.get(rs[0].billing, rs[0].billing), "price": price_of(k[0], k[1]),
                                                                    "reported": sum(1 for r in rs if r.cost_source == "provider")})
    by_provider = table(lambda r: r.provider, lambda k, rs: {"provider": k, "provider_label": _provider_label(k), "billing": rs[0].billing, "billing_label": BILLING.get(rs[0].billing, rs[0].billing)})
    by_feature = table(lambda r: r.feature, lambda k, rs: {"feature": k, "label": metering.feature_label(k)})

    # --- cost per result: everything spent on a kind of task (failed runs and retries included) over what it achieved ---------
    cost_by_task: dict[int, dict[str, Any]] = defaultdict(lambda: {"cost": 0, "unknown": 0, "requests": 0, "tokens": 0})
    for r in live:
        if r.task_id:
            c = cost_by_task[r.task_id]
            c["requests"] += 1
            c["tokens"] += _tok(r)
            if r.cost_micros is None:
                c["unknown"] += 1
            else:
                c["cost"] += r.cost_micros
    in_window = [t for t in tasks.values() if w.has(t["at"])]

    def unit(kind: str, label: str, unit_name: str, per_label: str, achieved: Callable[[dict[str, Any]], int]) -> dict[str, Any] | None:
        ts = [t for t in in_window if t["kind"] == kind]
        spent = [cost_by_task[t["id"]] for t in ts if t["id"] in cost_by_task]
        done = sum(achieved(t) for t in ts)
        if not spent:
            return None
        cost, unknown = sum(c["cost"] for c in spent), sum(c["unknown"] for c in spent)
        return {"kind": kind, "label": label, "unit": unit_name, "per_label": per_label, "results": done, "runs": len(ts), "failed_runs": sum(1 for t in ts if t["outcome"] in ("failed", "interrupted")),
                "requests": sum(c["requests"] for c in spent), "cost": cost if any(c["cost"] for c in spent) or not unknown else None, "partial": bool(unknown),
                "per_result": round(cost / done) if done and (cost or not unknown) else None}       # with ``partial``: at least this much

    ok = lambda t: 1 if t["outcome"] == "success" else 0  # noqa: E731
    units = [u for u in (
        unit("score", "给岗位评分", "评完分的岗位", "每个评完分的岗位", lambda t: int(t["result"].get("scored") or (1 if t["outcome"] == "success" and "score" in t["result"] else 0))),
        unit("recon", "读取申请表、生成草案", "生成的草案", "每份生成的草案", ok),
        unit("execute", "填写申请表", "填好的申请表（已提交或交给你提交）", "每份填好的申请表", lambda t: 1 if t["outcome"] in ("success", "handed") else 0),
        unit("revise", "按意见修改草案", "完成的修改", "每次完成的修改", ok), unit("tailor", "按岗位调整简历", "调整好的简历", "每份调整好的简历", ok),
        unit("mail", "查收邮件", "处理的新邮件", "每封处理的新邮件", lambda t: int(t["result"].get("new_mail") or 0)),
    ) if u]

    # --- what failures and repeats cost -----------------------------------------------------------
    def spent(rs: Iterable[Any]) -> dict[str, Any]:
        rs = list(rs)
        return {"requests": len(rs), "cost": sum(r.cost_micros for r in rs if r.cost_micros is not None) if any(r.cost_micros is not None for r in rs) else None,
                "unknown": sum(1 for r in rs if r.cost_micros is None)}

    failed_tasks = {t["id"] for t in tasks.values() if t["outcome"] in ("failed", "interrupted")}
    seen: dict[tuple[str, str], int] = {}
    repeat_tasks = set()
    for t in sorted(tasks.values(), key=lambda t: t["id"]):
        if any(ch.isdigit() for ch in t["ref"]):
            k = (t["kind"], t["ref"])
            if k in seen:
                repeat_tasks.add(t["id"])
            seen[k] = t["id"]
    fail_by_feature = table(lambda r: r.feature if r.task_id in failed_tasks else None, lambda k, rs: {"feature": k, "label": metering.feature_label(k) if k is not None else ""})
    waste = {"failed_requests": spent(r for r in live if r.status != "ok"), "backup_attempts": spent(r for r in live if r.attempt > 0),
             "failed_tasks": spent(r for r in live if r.task_id in failed_tasks), "repeated_tasks": spent(r for r in live if r.task_id in repeat_tasks),
             "by_feature": [{"feature": f["feature"], "label": f["label"], "requests": f["requests"], "cost": f["cost"]} for f in fail_by_feature if f["feature"] is not None and f["cost"]][:6]}

    # --- unusually expensive: far above the others of the same kind (Tukey's fence), not above a made-up number ---------------
    per_kind: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for tid, c in cost_by_task.items():
        if not c["unknown"] and c["cost"] and tid in tasks:
            per_kind[tasks[tid]["kind"]].append((c["cost"], tid))
    costly = []
    for k, lst in per_kind.items():
        vals = [c for c, _ in lst]
        fence, med = _fence(vals), _median(vals)
        for c, tid in lst:
            costly.append({"task_id": tid, "kind": k, "label": metering.workflow_label(k), "cost": c, "median": round(med) if med else None,
                           "times_median": round(c / med, 1) if med else None, "outlier": fence is not None and c > fence, "requests": cost_by_task[tid]["requests"],
                           "tokens": cost_by_task[tid]["tokens"], "outcome": tasks[tid]["outcome"], "outcome_label": OUTCOMES[tasks[tid]["outcome"]], "at": tasks[tid]["at"].isoformat(),
                           "ref": tasks[tid]["ref"]})
    costly.sort(key=lambda r: -r["cost"])
    costly = costly[:30]
    per_feature: dict[str, list[Any]] = defaultdict(list)
    for r in live:
        if r.detail != "none":
            per_feature[r.feature].append(r)
    heavy = []
    for f, rs in per_feature.items():
        fence = _fence([_tok(r) for r in rs])
        med = _median([_tok(r) for r in rs])
        heavy += [{"id": r.id, "feature": f, "label": metering.feature_label(f), "model": r.model, "tokens": _tok(r), "median": round(med) if med else None, "cost": r.cost_micros,
                   "turns": r.turns, "at": r.started_at.isoformat(), "task_id": r.task_id} for r in rs if fence is not None and _tok(r) > fence]
    heavy.sort(key=lambda r: -r["tokens"])
    for row in costly:
        row["subject"] = humanize.subject(row["ref"])

    opts = lambda key, lab: sorted(({"key": k, "label": lab(k)} for k in {key(r) for r in everything if r.source == "live"} if k), key=lambda o: o["label"])  # noqa: E731
    return {
        "window": w.describe(), "total": total, "previous": prev, "group": group if group in ("model", "feature", "provider") else "model", "bucket": size,
        "series": series, "trend": [{**b, "values": dict(b["values"]), "token_values": dict(b["token_values"])} for _, b in sorted(buckets.items())],
        "token_kinds": [{"key": k, "label": lab, "tokens": total["tokens"][k], "cost": kind_cost.get(k) if split_rows else None} for k, lab in TOKEN_KINDS],
        "token_cost_requests": split_rows, "billing_labels": BILLING,
        "by_model": by_model, "by_provider": by_provider, "by_feature": by_feature, "units": units, "waste": waste, "costly": costly, "heavy": heavy[:30],
        "filters": {"providers": opts(lambda r: r.provider, _provider_label), "models": opts(lambda r: r.model, lambda k: k), "features": opts(lambda r: r.feature, metering.feature_label),
                    "provider": provider, "model": model, "feature": feature},
        "pricing": {"version": metering.price_table()["version"], "user": metering.user_prices(),
                    "missing": sorted({(r["provider_label"] + " · " + r["model"]) for r in by_model if r["price"] is None and r["model"] and not r["reported"]})},
    }


def requests_of(task_id: int | None = None, request_ids: list[int] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """The model requests of one task (or the given ones): the drill-down from a total to what it is made of."""
    with db.session() as s:
        q = s.query(LLMRequest)
        if task_id is not None:
            q = q.filter(LLMRequest.task_id == task_id)
        if request_ids:
            q = q.filter(LLMRequest.id.in_(request_ids))
        return [{"id": r.id, "at": r.started_at.isoformat(), "provider": r.provider, "provider_label": _provider_label(r.provider), "model": r.model, "feature": r.feature,
                 "label": metering.feature_label(r.feature), "kind": r.kind, "status": r.status, "error": r.error, "attempt": r.attempt, "turns": r.turns, "latency_ms": r.latency_ms,
                 "input": r.input_tokens, "cache_read": r.cache_read_tokens, "cache_write": r.cache_write_tokens, "output": r.output_tokens, "detail": r.detail,
                 "cost": r.cost_micros, "cost_source": r.cost_source, "billing": r.billing, "legacy": r.source == "legacy"} for r in q.order_by(LLMRequest.id).limit(limit)]

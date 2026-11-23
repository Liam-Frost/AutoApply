"""Numbers for the analysis page: three views over one time window.

* ``applications`` - what came of the applications that were sent;
* ``automation``   - what the program's tasks (workflow executions) did, and where they failed - and, by application
                     rather than by run (``_applications``): how many were prepared, how many without the applicant,
                     how many of those to be sent went out with their evidence, what one application takes;
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

from .say import say as T

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


def _through_time(w: Window, sent: list[tuple[datetime, bool]], replies: list[datetime], bucket: str) -> dict[str, Any]:
    """Applications sent, and replies that arrived, along the window: by day, week or month - by the length of the
    window unless ``bucket`` says which. Every step of the stretch is there, also those in which nothing was sent: a
    week without an application is part of the picture."""
    size, key = _bucket_fn(w, [t for t, _ in sent] + replies, bucket)
    one_day = w.lo is not None and w.hi is not None and w.hi - w.lo <= timedelta(days=1)
    if one_day:      # a single day is looked at by the hour - and only a single day is
        size = "hour"

        def key(dt: datetime) -> tuple[str, str]:  # noqa: F811
            d = _local(dt)
            return d.strftime("%Y-%m-%d %H:00"), d.strftime("%H:00")
    rows: dict[str, dict[str, Any]] = {}

    def at(t: datetime) -> dict[str, Any]:
        k, label = key(t)
        return rows.setdefault(k, {"key": k, "label": label, "n": 0, "decided": 0, "replies": 0})

    for t, decided in sent:
        r = at(t)
        r["n"] += 1
        r["decided"] += int(decided)
    for t in replies:
        at(t)["replies"] += 1
    times = [t for t, _ in sent] + replies
    lo = w.lo or (min(times) if times else None)
    hi = min(w.hi or datetime.now(timezone.utc).replace(tzinfo=None), datetime.now(timezone.utc).replace(tzinfo=None))
    step = lo
    while step is not None and step <= hi and len(rows) < 800:      # the steps in which nothing happened
        at(step)
        step += timedelta(hours=1) if size == "hour" else timedelta(days=1 if size == "day" else 7 if size == "week" else 28)
    if lo is not None:
        at(hi)
    return {"bucket": size, "rows": [rows[k] for k in sorted(rows)]}


def applications(w: Window, bucket: str = "") -> dict[str, Any]:
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
                "status": a.status, "score": j.score, "direction": (j.direction or "").split("/")[0].strip() or T("server.analytics.unlabeled"),
                "channel": "UBC PD Portal" if (j.ats == "pdportal" or j.channel == "PD Portal") else (humanize.ats_name(j.ats) if j.ats and j.ats != "generic" else T("server.analytics.employerWebsite")),
                "auto": bool(a.auto_approved), "wait": (decisions[0] - sub_at).days if decisions else None,
                "lead": (sub_at - _naive(j.first_seen)).days if j.first_seen else None, "month": _local(sub_at).strftime("%Y-%m"), "at": sub_at,
                "progressed": progressed, "decided": decided, "heard": heard, "offer": a.status == "offer" or "offer" in been[a.id]})
        # replies by the day they arrived (not by the day the application was sent)
        reply_months: dict[str, int] = defaultdict(int)
        reply_times: list[datetime] = []
        for aid, lst in mails.items():
            for c, t in lst:
                if c in DECISION_MAIL and w.has(t):
                    reply_months[_local(t).strftime("%Y-%m")] += 1
                    reply_times.append(t)
        missed = []
        for j in s.query(Job).filter(Job.duplicate_of.is_(None), Job.score >= 7.5):
            a_ = j.application
            # closed without an application sent - also one that was begun and stopped short of sending
            st = "offline" if not j.online or j.status == "offline" else "expired" if stages._past(j.deadline or "") else ""
            gone_out = a_ is not None and (a_.status in SENT or a_.status == "submit_unknown")
            if st and not gone_out and j.status != "skipped" and w.has(_naive(j.first_seen)):
                missed.append({"id": j.id, "company": j.company, "title": j.title, "score": j.score, "deadline": (j.deadline or "")[:10], "stage": st,
                               "why": T("server.analytics.noApplicationLink") if not j.apply_url else T("server.analytics.closedNotApplied") if st == "expired" else T("server.analytics.takenDownNotApplied"),
                               "reason": _missed_reason(j, a_)})
        missed.sort(key=lambda r: (-(r["score"] or 0), r["deadline"] or "9999"))
        first = _first_records(s, w)
        backlog = _backlog(s, w)

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
        return T("server.analytics.notScored") if sc is None else "9–10" if sc >= 9 else "8–8.5" if sc >= 8 else "7–7.5" if sc >= 7 else "6–6.5" if sc >= 6 else T("server.analytics.below")

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
        "funnel": [{"key": "sent", "label": T("server.analytics.sent"), "value": total["n"]}, {"key": "heard", "label": T("server.analytics.acknowledgedAConfirmationOr"), "value": total["replied"]},
                   {"key": "decided", "label": T("server.analytics.cameToSomethingWent"), "value": total["decided"]},
                   {"key": "progressed", "label": T("server.analytics.reachedAnAssessmentInterview"), "value": total["progressed"]}, {"key": "offer", "label": T("server.analytics.offer"), "value": total["offer"]}],
        "states": [{"key": k, "label": lab, "value": states.get(k, 0)} for k, lab in
                   (("silent", T("server.analytics.noReplyAtAll")), ("receipt", T("server.analytics.automaticReceiptOnly")), ("assessment", T("server.analytics.assessment")), ("interview", T("server.analytics.interviewing")), ("offer", "Offer"), ("rejected", T("server.analytics.rejected")), ("other", T("server.analytics.otherWithdrawnEtc")))],
        "rejected_after_progress": sum(1 for r in apps if r["status"] == "rejected" and r["progressed"]),
        "median_wait_days": waits[len(waits) // 2] if waits else None, "waited": len(waits), "median_lead_days": leads[len(leads) // 2] if leads else None,
        "by_score": by(band, ["9–10", "8–8.5", "7–7.5", "6–6.5", T("server.analytics.below"), T("server.analytics.notScored")]), "by_channel": by(lambda r: r["channel"]), "by_direction": by(lambda r: r["direction"])[:8],
        "by_time": _through_time(w, [(r["at"], bool(r["decided"])) for r in apps], reply_times, bucket),
        "by_month": [{"label": m, **(per_month.get(m) or {**rate([]), "thin": True}), "replies": reply_months.get(m, 0)} for m in months],
        "auto": {"auto": sum(1 for r in apps if r["auto"]), "manual": sum(1 for r in apps if not r["auto"])},
        "missed": missed[:12], "missed_total": len(missed),
        "missed_reasons": [{"key": k, "n": sum(1 for r in missed if r["reason"] == k)} for k in MISSED if any(r["reason"] == k for r in missed)],
        "first_record": first, "backlog": backlog,
    }


# Why a posting good enough to apply for went past its deadline (or offline) without an application sent (the page
# says each in words: analytics.missed.reason.<key>).
MISSED = ("no_link", "not_started", "waited_for_you", "failed", "under_way", "withdrawn")


def _missed_reason(j: Job, a: Application | None) -> str:
    if not j.apply_url and a is None:
        return "no_link"
    if a is None:
        return "not_started"
    if a.status in ("needs_input", "draft_ready", "needs_human", "returned"):
        return "waited_for_you"
    if a.status == "failed":
        return "failed"
    if a.status == "withdrawn":
        return "withdrawn"
    return "under_way"


def _first_records(s: Any, w: Window) -> dict[str, Any]:
    """How long a posting waited for its first record ready to be sent: from when it was found, and from when its
    application was begun. For the applications whose first record was made in the window."""
    found, begun = [], []
    for a in s.query(Application):
        d = min(a.drafts, key=lambda d: d.id) if a.drafts else None
        if d is None or not w.has(_naive(d.created_at)):
            continue
        if a.job.first_seen:
            found.append((d.created_at - a.job.first_seen).total_seconds() / 3600)
        begun.append((d.created_at - a.created_at).total_seconds() / 3600)
    found, begun = sorted(x for x in found if x >= 0), sorted(x for x in begun if x >= 0)
    return {"n": len(begun), "from_found_hours": _median(found), "from_begun_hours": _median(begun), "slow": sum(1 for x in found if x > 72)}


def _backlog(s: Any, w: Window) -> dict[str, Any]:
    """What waits for the applicant: how long the cards dealt with in the window had waited, by kind; and the oldest
    of the ones still open."""
    from .models import Todo

    now_ = datetime.now(timezone.utc).replace(tzinfo=None)
    by_kind: dict[str, list[float]] = defaultdict(list)
    for t in s.query(Todo).filter(Todo.status != "open", Todo.done_at.isnot(None)):
        if w.has(_naive(t.done_at)):
            by_kind[t.kind].append((t.done_at - t.created_at).total_seconds() / 3600)
    open_ = [t for t in s.query(Todo).filter_by(status="open")]
    oldest = sorted(open_, key=lambda t: t.created_at)[:5]
    every = sorted(x for xs in by_kind.values() for x in xs)
    # by what the applicant reads: two kinds of card with one name ("sign in": at a site, in a window) are one row
    named: dict[str, tuple[Any, str, list[float]]] = {}
    for k, v in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        label = TODO_KINDS.get(k) or T("server.analytics.otherCards")
        named.setdefault(str(label), (label, k, []))[2].extend(v)      # (`kind`: the one of them with the most cards)
    return {"handled": len(every), "median_hours": _median(every),
            "by_kind": sorted(({"kind": k, "label": label, "n": len(v), "median_hours": _median(sorted(v))} for label, k, v in named.values()), key=lambda r: -r["n"]),
            "open": len(open_), "oldest": [{"id": t.id, "title": t.title, "kind": TODO_KINDS.get(t.kind) or T("server.analytics.otherCards"), "hours": (now_ - t.created_at).total_seconds() / 3600} for t in oldest]}


TODO_KINDS = {"answer": T("server.analytics.answerQuestions"), "review": T("server.analytics.approveARecord"), "confirm": T("server.analytics.confirm"), "code": T("server.analytics.code"), "resume": T("server.analytics.continueAnApplication"), "submit": T("server.analytics.submitYourself"), "failed": T("server.analytics.didNotGetThrough"),
              "config": T("server.analytics.settings"), "mail_unmatched": T("server.analytics.whichApplicationAMail"), "followup": T("server.analytics.interviewAssessment"), "gone": T("server.analytics.postingTakenDown"), "login": T("server.analytics.signIn"), "facts_changed": T("server.analytics.profileChanged"),
              "mail_out": T("server.analytics.readAMailBefore"), "takeover": T("server.analytics.signIn"), "blocked": T("server.analytics.siteTheProgramCannot"), "captcha": T("server.analytics.humanCheck"),
              # cards of the program before 2.0, still in the record: a site's form had changed and its reading was repaired
              "driver": T("server.analytics.siteFormChanged"), "driver_patch": T("server.analytics.siteFormChanged"),
              "note": T("server.analytics.ownEvent")}


# --- tasks: what a workflow execution came to ----------------------------------------------------

OUTCOMES = {"success": T("server.analytics.done"), "handed": T("server.analytics.readyWaitingForYou"), "unknown": T("server.analytics.submitWasPressedThe"), "waiting": T("server.analytics.needsYou"), "rerun": T("server.analytics.goesOn"), "failed": T("server.analytics.failed"), "interrupted": T("server.analytics.interrupted"),
            "cancelled": T("server.analytics.cancelled"), "skipped": T("server.analytics.nothingToDo"), "running": T("server.analytics.inProgress")}
UNFINISHED = ("handed", "unknown", "waiting", "rerun", "running")       # not a failure: the next move is yours, or it is still going
# (not counted either way: the task was called off, or found that there was nothing for it to do)
NOT_COUNTED = ("cancelled", "skipped")
STAGES = {"read_form": T("server.analytics.readApplicationForm"), "ensure_session": T("server.analytics.signInToThe"), "open": T("server.analytics.openingTheForm"), "sign_in": T("server.analytics.signInToThe"), "reopen": T("server.analytics.openingTheForm"), "walk": T("server.analytics.fillingStepByStep"), "fill_step": T("server.analytics.enter"),
          "fill_page": T("server.analytics.enter"), "form_reports": T("server.analytics.formCheck"), "repair": T("server.analytics.aiTakeOver"), "repair_skipped": T("server.analytics.aiTakeOver"), "read_back": T("server.analytics.checkingAgainstTheDraft"), "unverified": T("server.analytics.checkingAgainstTheDraft"),
          "next": T("server.analytics.nextPage"), "advance": T("server.analytics.nextPage"), "cannot_advance": T("server.analytics.nextPage"), "stuck": T("server.analytics.nextPage"), "not_asked": T("server.analytics.checkingAgainstTheReview"), "review_step": T("server.analytics.confirmationPage"), "handed_over": T("server.analytics.handedToYouTo"),
          "submit": T("server.analytics.submit"), "scouted": T("server.analytics.readTheLaterSteps"), "read_step": T("server.analytics.readingWhatTheStep"), "read_review": T("server.analytics.readingTheReviewPage"), "review_unfolded": T("server.analytics.unfoldingTheAnswersOn"), "email_code": T("server.analytics.eMailedCode"), "submitted_in_window": T("server.analytics.youSubmitted"), "window_closed": T("server.analytics.windowClosed")}


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
    if kind == "apply":
        # One run of the agent on an application. A success is an application that went out in this run; a record that
        # waits for the applicant (their approval, their answers, their press of the last button) is theirs to move;
        # a run that used its share of the budget and is taken up again is neither.
        st = str((result or {}).get("status") or "")
        if (result or {}).get("already_applied") or (result or {}).get("skipped"):
            return "skipped"
        if st == "stopped":
            return "cancelled"
        return {"submitted": "success", "not_sent": "success", "ready": "handed", "needs_input": "handed", "submit_unknown": "unknown", "goes_on": "rerun",
                "cannot": "failed", "gone": "skipped", "stuck": "failed", "budget_used": "failed"}.get(st, "success")
    if kind == "execute":      # (the kinds of earlier versions, for the history)
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
    ("interrupted", T("server.analytics.runInterrupted"), r"interrupted|superseded|server stopped|Target page, context or browser has been closed|TargetClosed"),
    ("ai_limit", T("server.analytics.aiAllowanceUsedUp"), r"usage limit|limit reached|quota|额度|欠费|insufficient|billing"),
    ("ai_unavailable", T("server.analytics.aiServiceUnavailable"), r"LLMUnavailable|LLMError|login is not usable|no model|API key|AI 服务|AI 模型"),
    ("posting_closed", T("server.analytics.postingClosed"), r"posting not found|已关闭|已经关闭|no longer|下线|\b404\b|closed or wrong id"),
    ("site_down", T("server.analytics.siteUnreachable"), r"网站暂时打不开|打不开|not answering|HTTP 5\d\d|ERR_|Page\.goto: Timeout|could not open the posting|SiteDown"),
    ("login", T("server.analytics.signInOrVerification"), r"login required|needs login|sign.?in|captcha|verification|登录|验证码"),
    ("cannot_advance", T("server.analytics.formWillNotGo"), r"could not advance|没法进入下一步|does not go on"),
    ("fields", T("server.analytics.fieldsLeftUnfilled"), r"could not set every field|field\(s\) could not be filled|没能自动填上|option not found"),
    ("mismatch", T("server.analytics.formDiffersFromThe"), r"differ from the approved draft|不一致|verify failed|mismatch"),
    ("form_changed", T("server.analytics.applicationFormHasChanged"), r"form changed|drift"),
    ("no_confirmation", T("server.analytics.noConfirmationAfterSubmitting"), r"no confirmation after submit"),
    ("materials", T("server.analytics.materialsNotReady"), r"cover-letter|cover letter|résumé|resume|求职信|简历"),
    ("program", T("server.analytics.errorInTheProgram"), r"Error:|Exception|Traceback|driver bug|while parsing"),
]


def failure(kind: str, status: str, result: dict[str, Any] | None, error: str) -> dict[str, str]:
    """{key, label, message, raw} for a failed task: a short category, the sentence the program shows, the text as recorded."""
    import re

    raw = (error or str((result or {}).get("error") or "")).strip()
    if not raw:
        return {"key": "none", "label": T("server.analytics.noReasonRecorded"), "message": "", "raw": ""}
    key, label = next(((k, lab) for k, lab, pat in CATEGORIES if re.search(pat, raw, re.I)), ("other", T("server.analytics.otherReasons")))
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


def _applications(s: Any, rows: list[dict[str, Any]], ai: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """How the agent does, counted by application and not by run - an application takes as many runs as it takes.
    From the applications a run worked in the window:

    - prepared: the application was brought to where one press sends it (a record with nothing open), or sent. Of
      those that came to an end either way: an application that still waits for an answer or a sign-in, or is still
      being worked, is in neither count;
    - without you: of the prepared ones, those that got there with no question to the applicant, no stop on their
      word and nothing the agent could not do (a sign-in only they can make is not counted against it);
    - sent: of the applications that were to be sent - approved by the applicant, or sent by the agent itself under
      "send when nothing is open" - those that are out with the confirmation kept as evidence. One that is still on
      its way is not counted;
    - for one application: the time and the model's tokens of all its runs together, the median over the prepared ones.
    """
    from . import lifecycle
    from .models import SENT, UNKNOWN

    apps_of_job = {job_id: (app_id, status, bool(auto), dict(ev or {})) for app_id, job_id, status, auto, ev in
                   s.query(Application.id, Application.job_id, Application.status, Application.auto_approved, Application.evidence)}
    job_of_app = {v[0]: k for k, v in apps_of_job.items()}
    drafts = {d_id: (app_id, review) for d_id, app_id, review in s.query(Draft.id, Draft.application_id, Draft.review_status)}

    def posting(ref: str) -> int | None:
        kind, _, rest = (ref or "").partition(":")
        num = rest.split(":")[0]
        if not num.isdigit():
            return None
        n = int(num)
        return n if kind == "job" else job_of_app.get(n) if kind == "application" else job_of_app.get(drafts.get(n, (None, ""))[0]) if kind == "draft" else None

    runs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r["at"], r["id"])):
        job = posting(r["ref"]) if r["kind"] in lifecycle.WORK and r["kind"] != "tailor" else None
        # (a run the applicant stopped is no success and no failure of a run - and it is part of what its application took)
        if job in apps_of_job and (r["outcome"] not in NOT_COUNTED or str((r["result"] or {}).get("status") or "") == "stopped"):
            runs[job].append(r)
    approved = {app_id for app_id, review in drafts.values() if review == "approved"}
    prepared, failed, alone, to_send, sent, took, used = 0, 0, 0, 0, 0, [], []
    for job, rs in runs.items():
        app_id, status, auto, ev = apps_of_job[job]
        said = [str((r["result"] or {}).get("status") or "") for r in rs]
        got_there = any(x in ("ready", "submitted") for x in said) or status in SENT
        if got_there:
            prepared += 1
            alone += not any(x in ("needs_input", "cannot", "stuck", "budget_used", "stopped") for x in said)
            took.append(sum(r["duration"] or 0 for r in rs))
            tokens = sum(ai[r["id"]]["tokens"] for r in rs if r["id"] in ai)
            if tokens:
                used.append(float(tokens))
        elif rs[-1]["outcome"] in ("failed", "interrupted"):
            failed += 1
        if app_id in approved or auto or status in SENT:
            if status in SENT:
                to_send += 1
                sent += bool(str(ev.get("text") or "").strip() or ev.get("mail_id") or ev.get("mail_ids"))
            elif status in ("failed", UNKNOWN):
                to_send += 1

    def share(n: int, of: int) -> dict[str, Any]:
        return {"n": n, "of": of, "rate": round(n / of, 4) if of else None}

    return {"worked": len(runs), "prepared": share(prepared, prepared + failed), "alone": share(alone, prepared), "sent": share(sent, to_send),
            "median_s": _median(sorted(took)), "median_tokens": _median(sorted(used))}


# How each run of an application ended, as its journal says it (agent/run.py writes the journal).
RUN_ENDS = {"submitted": T("server.analytics.submitted"), "ready": T("server.analytics.readyWaitingForYour"), "mailed": T("server.analytics.applicationEMailWritten"), "needs_you": T("server.analytics.stoppedForYou"), "cannot": T("server.analytics.couldNotBeDone"), "gone": T("server.analytics.thePostingHasBeen"),
            "other_browser": T("server.analytics.movedToTheOther"), "cut_off": T("server.analytics.stoppedWithoutAReport"), "model": T("server.analytics.modelUnavailableDidNot")}


def _journal_runs(folder: Path) -> list[dict[str, Any]]:
    """The runs of one application, from its journal: when each began and ended, how many tool calls it made, how it
    ended. A run that made no call because the model could not be reached is one of them ("model")."""
    import json

    f = folder / "journal.jsonl"
    if not f.exists():
        return []
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            at = datetime.fromisoformat(str(e.get("at")))
        except (ValueError, TypeError):
            continue
        k = e.get("kind")
        if k == "run":
            cur = {"start": at, "end": at, "steps": 0, "end_kind": "", "mode": str(e.get("mode") or "")}
            out.append(cur)
            continue
        if cur is None:
            continue
        cur["end"] = at
        if k == "tool":
            cur["steps"] += 1
        elif k == "report" and e.get("outcome"):
            cur["end_kind"] = str(e["outcome"])
        elif k == "mailed":
            cur["end_kind"] = "mailed"
        elif k == "browser" and not cur["end_kind"]:
            cur["end_kind"] = "other_browser"
        elif k == "ended" and not cur["end_kind"] and not cur["steps"] and str(e.get("why") or "").startswith(("LLMUnavailable", "LLMError")):
            cur["end_kind"] = "model"
    for r in out:
        r["end_kind"] = r["end_kind"] if r["end_kind"] in RUN_ENDS else "cut_off"
        r["seconds"] = max(0.0, (r["end"] - r["start"]).total_seconds())
    return out


def agent_runs(w: Window) -> dict[str, Any]:
    """How applications get done, from their journals: for the applications with a run that began in the window -
    how many runs one takes, how the runs ended, how much of the work was going over an application again (every run
    after its first that did anything starts over: the browser, the way to the form, the check of what was filled),
    and by recruiting system, the calls and minutes it took to get one to the point of sending."""
    from .agent import brief, work

    with db.session() as s:
        apps = [(a.id, a.job.apply_url if a.job is not None else "") for a in s.query(Application)]
    per_app, ends, systems = [], defaultdict(int), defaultdict(lambda: {"apps": 0, "done": 0, "steps": [], "seconds": []})
    first_steps = later_steps = idle = 0
    for app_id, url in apps:
        runs_ = _journal_runs(work.folder_of(app_id))
        if not any(w.has(_utc(r["start"])) for r in runs_):
            continue
        worked = [r for r in runs_ if r["steps"]]
        idle += len(runs_) - len(worked)
        for r in runs_:
            if w.has(_utc(r["start"])):
                ends[r["end_kind"]] += 1
        if not worked:
            continue
        per_app.append(len(worked))
        first_steps += worked[0]["steps"]
        later_steps += sum(r["steps"] for r in worked[1:])
        name = brief.playbook_for(url or "")[0]
        sysd = systems[name or "other"]
        sysd["apps"] += 1
        upto = next((i for i, r in enumerate(worked) if r["end_kind"] in ("ready", "submitted", "mailed")), None)
        if upto is not None:
            sysd["done"] += 1
            sysd["steps"].append(sum(r["steps"] for r in worked[: upto + 1]))
            sysd["seconds"].append(sum(r["seconds"] for r in worked[: upto + 1]))
    total = first_steps + later_steps
    by_system = [{"key": k, "label": humanize.ats_name(k) if k != "other" else T("server.analytics.otherEmployerSites"), "apps": v["apps"], "done": v["done"],
                  "median_steps": _median(v["steps"]), "median_seconds": _median(v["seconds"])}
                 for k, v in sorted(systems.items(), key=lambda kv: -kv[1]["apps"])]
    return {"applications": len(per_app), "runs": sum(per_app), "idle_runs": idle,
            "runs_per_application": {"median": _median(per_app), "mean": round(sum(per_app) / len(per_app), 1) if per_app else None, "max": max(per_app) if per_app else None},
            "again": {"steps": later_steps, "of": total, "rate": round(later_steps / total, 4) if total else None},
            "ends": [{"key": k, "label": RUN_ENDS[k], "n": ends[k]} for k in RUN_ENDS if ends.get(k)],
            "by_system": by_system}


def _question_key(text: str) -> str:
    """A question as it is compared with others: lower case, without the marks and filler a form adds around it."""
    t = re.sub(r"\((optional|required)\)|\*", " ", str(text).lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(w_ for w_ in t.split() if w_ not in ("please", "the", "a", "an", "your", "you"))


def asked_again(w: Window) -> dict[str, Any]:
    """The questions that had to be put to the applicant - or that they corrected - in more than one application: each
    is one the profile could answer by itself. Counted once per application (its versions are one application), for
    applications begun in the window."""
    from . import knowledge

    groups: dict[str, dict[str, Any]] = {}
    with db.session() as s:
        for a in s.query(Application):
            if not w.has(_naive(a.created_at)):
                continue
            seen: set[str] = set()
            for d in sorted(a.drafts, key=lambda d: d.id, reverse=True):        # the newest version's answer first
                for row in d.answers or []:
                    put = row.get("about") is not None or str(row.get("id", "")).startswith("q")      # a question the agent asked
                    mine = row.get("basis") == "edited by user"                                       # an entry the applicant gave or corrected
                    key = _question_key(row.get("label") or "")
                    if not (put or mine) or not key or key in seen or row.get("dropped"):
                        continue
                    seen.add(key)
                    g = groups.setdefault(key, {"question": str(row.get("label") or "")[:200], "times": 0, "answer": None, "applications": []})
                    g["times"] += 1
                    if g["answer"] in (None, "", []) and row.get("value") not in (None, "", []):
                        g["answer"] = row.get("value")
                    g["applications"].append({"id": a.id, "company": a.job.company, "title": a.job.title})
    profile = knowledge.read("profile").lower()
    rows = sorted((g for g in groups.values() if g["times"] >= 2), key=lambda g: (-g["times"], g["question"]))
    for g in rows:
        g["in_profile"] = f'form question "{g["question"].strip()[:200].lower()}"' in profile
        g["applications"] = g["applications"][:6]
        g["answer"] = g["answer"] if isinstance(g["answer"], (str, int, float)) or g["answer"] is None else ", ".join(map(str, g["answer"]))
    return {"rows": rows[:20], "total": len(rows), "asked": sum(g["times"] for g in groups.values())}


def _settled_after(s: Any, w: Window) -> dict[str, Any]:
    """How long a submission whose outcome was not known stayed that way, until a confirmation said it went out or the
    applicant said it did not; and the ones not known still."""
    spans, open_ = [], []
    by_app: dict[int, list[Any]] = defaultdict(list)
    for e in s.query(ApplicationEvent).order_by(ApplicationEvent.application_id, ApplicationEvent.at, ApplicationEvent.id):
        by_app[e.application_id].append(e)
    now_ = datetime.now(timezone.utc).replace(tzinfo=None)
    for app_id, evs in by_app.items():
        began = None
        for e in evs:
            if e.new == "submit_unknown" and began is None:
                began = e.at
            elif began is not None and e.new != "submit_unknown":
                if w.has(_naive(e.at)):
                    spans.append({"hours": (e.at - began).total_seconds() / 3600, "went_out": e.new in ("submitted", "confirmed", "assessment", "interview", "offer", "rejected"), "by": e.source})
                began = None
        if began is not None:
            a = s.get(Application, app_id)
            if a is not None and a.status == "submit_unknown":
                open_.append({"id": app_id, "company": a.job.company, "title": a.job.title, "hours": (now_ - began).total_seconds() / 3600})
    hours = sorted(x["hours"] for x in spans)
    return {"settled": len(spans), "went_out": sum(1 for x in spans if x["went_out"]), "by_mail": sum(1 for x in spans if x["by"] == "mail"),
            "median_hours": _median(hours), "open": sorted(open_, key=lambda x: -x["hours"])[:5], "open_total": len(open_)}


def automation(w: Window, *, kind: str = "") -> dict[str, Any]:
    """What the program's tasks did in the window (by the day a task started)."""
    with db.session() as s:
        rows = _task_rows(s, w)
        prev_n = sum(1 for t in s.query(Task.started_at, Task.created_at) if w.had(_naive(t[0] or t[1]))) if w.prev_lo is not None else None
        ai = _ai_by_task(s, [r["id"] for r in rows])
        applications = _applications(s, rows, ai)
        unknown = _settled_after(s, w)
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
                        "waits_for_you": k in ("apply", "execute")})
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
        e = by_stage.setdefault(r["stage"], {"key": r["stage"], "stage": stage_label(r["stage"]) if r["stage"] else T("server.analytics.stepNotRecorded"), "n": 0, "recorded": bool(r["stage"])})
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
        "applications": applications,      # (by application, whatever ``kind`` narrows the rest to)
        "agent_runs": agent_runs(w),
        "asked_again": asked_again(w),
        "unknown_settled": unknown,
    }


# --- AI use and cost ----------------------------------------------------------------------------

BILLING = {"metered": T("server.analytics.payAsYouGo"), "subscription": T("server.analytics.withinTheSubscriptionNo"), "local": T("server.analytics.localModelFree"), "unknown": T("server.analytics.notRecorded")}
TOKEN_KINDS = (("input", T("server.analytics.input")), ("cache_read", T("server.analytics.cacheRead")), ("cache_write", T("server.analytics.cacheWrite")), ("output", T("server.analytics.output")))


def _provider_label(p: str) -> str:
    return llm.label(p) if p else T("server.analytics.recordsFromBefore")


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
    glabel = (lambda k: k or T("server.analytics.modelNotRecorded")) if group not in ("feature", "provider") else metering.feature_label if group == "feature" else _provider_label
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
    series = [{"key": k, "label": glabel(k)} for k in top] + ([{"key": "__other", "label": T("server.analytics.other")}] if len(weight) > len(top) else [])

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
        unit("score", T("server.analytics.scoreJobs"), T("server.analytics.postingsScored"), T("server.analytics.perPostingScored"), lambda t: int(t["result"].get("scored") or (1 if t["outcome"] == "success" and "score" in t["result"] else 0))),
        unit("apply", T("server.analytics.workingAnApplication"), T("server.analytics.finishedApplicationsSubmittedOr"), T("server.analytics.perFinishedApplication"), lambda t: 1 if t["outcome"] in ("success", "handed") else 0),
        unit("recon", T("server.analytics.readingTheFormAnd"), T("server.analytics.draftsCreated"), T("server.analytics.perDraftCreated"), ok),
        unit("execute", T("server.analytics.fillingInTheForm"), T("server.analytics.formsFilledSubmittedOr"), T("server.analytics.perFormFilled"), lambda t: 1 if t["outcome"] in ("success", "handed") else 0),
        unit("tailor", T("server.analytics.tailorRSumTo"), T("server.analytics.rSumSTailored"), T("server.analytics.perRSumTailored"), ok),
        unit("mail", T("server.analytics.checkMail"), T("server.analytics.newEMailsHandled"), T("server.analytics.perNewEMail"), lambda t: int(t["result"].get("new_mail") or 0)),
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

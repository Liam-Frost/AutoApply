"""The application agent in the program: a task of the queue, and what its run leaves in the database.

``run.py`` is one run of the agent on a page. This is what is around it in the program: which posting, in which
mode (the applicant's submit policy and whether they have approved a record), and what the run's outcome becomes -
a record to look at, questions for the applicant, a card that asks them to sign in, an application marked as sent
with its evidence, one whose outcome is not known.

The record is kept in the drafts table, in the shape the review page already shows: one row per question of the form
with what was entered and where it comes from. A draft made by the agent has no form structure behind it; its
``schema`` says only that (``extra.agent``).

    ready        -> a pending draft; the application waits for the applicant's approval ("draft_ready")
    questions    -> the same draft with the questions open ("needs_input") and one card
    sign-in      -> a card that opens the sign-in window; the task waits for it
    submitted    -> the application is sent, with the confirmation as evidence
    cannot       -> a card that says why
    no report    -> see ``_without_report``: the allowance of the model, this application's budget, the same place
                    again, or - when the run had said it was about to send - an outcome that is not known
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import config, db, lifecycle, messages, notify
from ..models import SENT, UNKNOWN, Application, Draft, Job, now
from . import brief, run

log = logging.getLogger("autoapply.agent")

SURE = {"yes": "high", "fairly": "medium", "no": "low"}
MODE_OF_POLICY = {"manual": "hand_over", "approve_then_submit": "prepare", "auto_approve": "auto"}
SAME_PLACE = 3          # runs in a row that ended at the same place without a report, before the applicant is asked


def enabled() -> bool:
    """Is the application agent what works applications? (``legacy``: the pipeline it replaces, kept to compare with
    until it is removed.)"""
    return str(db.get_setting("agent.pipeline") or "agent") != "legacy"


def folder_of(application_id: int) -> Path:
    return config.DATA / "agent" / f"app_{application_id}"


def journal(application_id: int, limit: int = 200) -> list[dict[str, Any]]:
    """What the agent did on this application, for the applicant to read: each run, the lines it wrote down itself,
    what it asked, how it ended - and how many actions each run took (the actions themselves stay in the file)."""
    p = folder_of(application_id) / "journal.jsonl"
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    calls = 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        kind = e.get("kind")
        if kind == "tool":
            calls += 1
            continue
        if kind == "run":
            calls = 0
            out.append({"at": e.get("at"), "kind": "run", "text": str(e.get("mode") or "")})
        elif kind == "log":
            out.append({"at": e.get("at"), "kind": "log", "text": str(e.get("text") or "")})
        elif kind == "ask":
            out.append({"at": e.get("at"), "kind": "ask", "text": str(e.get("question") or "")})
        elif kind == "note":
            out.append({"at": e.get("at"), "kind": "note", "text": str(e.get("text") or "")})
        elif kind == "sending":
            out.append({"at": e.get("at"), "kind": "sending", "text": str(e.get("button") or "")})
        elif kind == "needs_applicant":
            out.append({"at": e.get("at"), "kind": "waits", "text": str(e.get("why") or "")})
        elif kind == "report":
            out.append({"at": e.get("at"), "kind": "report", "text": str(e.get("summary") or ""), "outcome": e.get("outcome"), "calls": calls})
        elif kind == "ended":
            out.append({"at": e.get("at"), "kind": "ended", "text": str(e.get("why") or ""), "calls": calls})
    return out[-limit:]


def spent(application_id: int) -> dict[str, Any]:
    """What this application has used of its budget, over all its runs."""
    used, total = _spent_so_far(folder_of(application_id)), _budget()
    grants = max(1, int(used.get("granted") or 1))
    return {"steps": int(used["steps"]), "minutes": round(used["seconds"] / 60, 1), "runs": int(used.get("runs") or 0),
            "of_steps": int(total["steps"] * grants), "of_minutes": round(total["seconds"] * grants / 60)}


# --- what a run is given ---------------------------------------------------------------------------------------------
def mode_for(app_status: str, draft: Draft | None) -> str:
    if app_status == UNKNOWN:
        return "verify"
    if draft is not None and draft.review_status == "approved":
        return "send"
    return MODE_OF_POLICY.get(str(db.get_setting("policy.default") or ""), "prepare")


def record_of(draft: Draft | None) -> dict[str, Any] | None:
    """A draft as the record the agent reads: what each question holds, and where that comes from."""
    if draft is None:
        return None
    rows = [a for a in draft.answers or [] if a.get("value") not in ("", None, [])]
    return {"answers": [{"question": a.get("label", ""), "entered": a.get("value"), "from": a.get("basis", "")} for a in rows if a.get("type") != "file"],
            "files": [{"field": m.get("slot") or m.get("label") or "", "file": m.get("name") or ""} for m in draft.materials or []],
            "notes": list(draft.notes or [])[:12]}


def answers_of(draft: Draft | None) -> dict[str, str]:
    """What the applicant themselves said in the record: the questions they answered, the values they changed."""
    if draft is None:
        return {}
    said = {str(a.get("label", "")): _shown(a.get("value")) for a in draft.answers or [] if a.get("basis") == "edited by user" and a.get("value") not in ("", None, [])}
    for n, c in enumerate(draft.comments or [], 1):      # what they wrote about the record as a whole
        if str(c.comment or "").strip():
            said[f"(the applicant's note {n} on this application)"] = str(c.comment)[:1500]
    return said


def _shown(v: Any) -> str:
    return "; ".join(map(str, v)) if isinstance(v, list) else str(v)


# --- one application, once ---------------------------------------------------------------------------------------------
def work(job_id: int, *, task_id: int | None = None) -> dict[str, Any]:
    """Run the agent on the application for this posting, and settle what came of it. Returns the task's result."""
    from .. import browser

    with db.session() as s:
        job = s.get(Job, job_id)
        if job is None or not job.apply_url:
            return {"skipped": "the posting is gone or has no address to apply at"}
        app = job.application
        if app is None:
            app = Application(job_id=job.id, status="recon", channel=job.channel)
            s.add(app)
            s.flush()
        if app.status in SENT and app.status != UNKNOWN:
            return {"already_applied": True}
        draft = app.drafts[-1] if app.drafts else None
        mode = mode_for(app.status, draft)
        record, answers = record_of(draft), answers_of(draft)
        if mode != "verify":
            lifecycle.move(app, "executing" if mode == "send" else "recon", source="run")
        app_id, title, channel = app.id, f"{job.company} · {job.title}", job.channel or ""
        posting = brief.Posting(company=job.company, title=job.title, url=job.apply_url, text=job.jd_text or job.summary or "", deadline=job.deadline or "",
                                extra=" · ".join(x for x in (f"Term: {job.term} {job.months}".strip() if (job.term or job.months) else "", f"Place: {job.location or job.work_type}" if (job.location or job.work_type) else "",
                                                             f"Documents asked for: {job.docs_required}" if job.docs_required else "") if x))
    folder, site = folder_of(app_id), brief.site_key(posting.url)
    from .. import tasks

    if tasks.running_by_hand():      # the applicant asked for it: what counted "the same place again" starts anew
        (folder / "places.json").unlink(missing_ok=True)
    left = _left(folder)
    if left["steps"] < 20 or left["seconds"] < 120:
        return _budget_used(app_id, title, folder)
    applicant = brief.applicant_on_file(channel)
    _own_letter(applicant, job_id)
    began = now()
    with browser.open_page(site, headless=mode != "hand_over", url=posting.url) as page:
        result = run.apply(page, posting, applicant, folder, mode=mode, answers=answers or None, job_id=job_id, record=record, budget=left)
    _spent(folder, result)
    return settle(app_id, job_id, title, site, mode, result, folder, began=began)


def _own_letter(applicant: brief.Applicant, job_id: int) -> None:
    """A letter already written for this posting is among the files."""
    from .. import materials

    got = materials.existing_cover_letter(job_id)
    if got is not None:
        applicant.files[got["name"]], applicant.file_notes[got["name"]] = got["path"], "cover letter written for this posting"


# --- the budget of one application, over all its runs ----------------------------------------------------------------------
def _budget() -> dict[str, float]:
    from .. import agentbudget

    b = agentbudget.for_kind("apply")
    return {"steps": float(b.steps), "seconds": float(b.seconds)}


def _spent_so_far(folder: Path) -> dict[str, float]:
    try:
        return json.loads((folder / "spent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"steps": 0, "seconds": 0, "runs": 0, "granted": 1}


def _left(folder: Path) -> dict[str, float]:
    total, spent = _budget(), _spent_so_far(folder)
    grants = max(1, int(spent.get("granted") or 1))
    return {"steps": total["steps"] * grants - spent["steps"], "seconds": total["seconds"] * grants - spent["seconds"]}


def _spent(folder: Path, result: run.Result) -> None:
    spent = _spent_so_far(folder)
    spent.update(steps=spent["steps"] + result.steps, seconds=spent["seconds"] + result.seconds, runs=int(spent.get("runs") or 0) + 1)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spent.json").write_text(json.dumps(spent), encoding="utf-8")


def grant(application_id: int) -> None:
    """The applicant gives this application another budget."""
    folder = folder_of(application_id)
    spent = _spent_so_far(folder)
    spent["granted"] = int(spent.get("granted") or 1) + 1
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spent.json").write_text(json.dumps(spent), encoding="utf-8")
    notify.close_todos("failed", f"application:{application_id}")


def _budget_used(app_id: int, title: str, folder: Path) -> dict[str, Any]:
    spent = _spent_so_far(folder)
    with db.session() as s:
        app = s.get(Application, app_id)
        lifecycle.move(app, "failed", source="run")
        app.last_event = "这份申请的预算用完了，等你决定是否继续"
    said = [e["text"] for e in journal(app_id) if e["kind"] == "log"][-1:] or ["（没有）"]      # the agent's own last line
    notify.add_todo("failed", f"{title}：这份申请的预算用完了", ref=f"application:{app_id}", payload={"application_id": app_id, "budget": True},
                    body=f"已经用了 {int(spent['steps'])} 步、约 {int(spent['seconds'] // 60)} 分钟，分 {int(spent.get('runs') or 0)} 次运行，还没有做完。Agent 最后记下的是：{said[0][:300]}\n要继续的话，再给它一份预算。")
    return {"status": "budget_used", **spent}


# --- what a run's outcome becomes ----------------------------------------------------------------------------------------
def rows_of(record: dict[str, Any], files: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """(answers, unresolved, materials) in the shape the review page shows."""
    def row(n: int, label: str, value: Any, basis: str, confidence: str, source: str, **more: Any) -> dict[str, Any]:
        return {"id": f"{'q' if source == 'unresolved' else 'a'}{n}", "label": label, "type": more.pop("type", "text"), "options": more.pop("options", []), "required": source == "unresolved",
                "page": 0, "value": value, "basis": basis, "confidence": confidence, "source": source, "sensitive": "", "sensitive_confirmed": False, **more}

    answers = [row(n, str(a.get("question", ""))[:400], a.get("entered", ""), str(a.get("from", ""))[:400], SURE.get(str(a.get("sure") or "yes"), "high"), "agent")
               for n, a in enumerate(record.get("answers") or [], 1) if str(a.get("question", "")).strip()]
    open_ = [row(n, q["question"][:400], "", q.get("why", "")[:400], "low", "unresolved", options=list(q.get("options") or []), type="select" if q.get("options") else "text",
                 about=q.get("about", "applicant")) for n, q in enumerate(record.get("asked") or [], 1)]
    mats = [{"slot": str(f.get("field", ""))[:200], "label": str(f.get("field", ""))[:200], "name": str(f.get("file", "")), "path": files.get(str(f.get("file", "")), ""), "kind": "file"}
            for f in record.get("files") or []]
    return answers + open_, open_, mats


def keep_record(app_id: int, record: dict[str, Any], files: dict[str, str], url: str) -> int:
    """The agent's record as a new pending draft of this application (the one before it is superseded)."""
    answers, open_, mats = rows_of(record, files)
    notes = [str(record.get("summary", ""))[:3000]] + [f"Still open: {x}"[:600] for x in record.get("open") or []]
    with db.session() as s:
        app = s.get(Application, app_id)
        version = 1
        for old in app.drafts:
            version = max(version, old.version + 1)
            if old.review_status == "pending":
                old.review_status = "superseded"
        d = Draft(application_id=app_id, version=version, review_status="pending", answers=answers, unresolved=open_, materials=mats, notes=[n for n in notes if n.strip()], plan=[],
                  schema={"ats": "agent", "tenant": urlparse(url).netloc.lower(), "url": url, "source": "agent", "pages": [], "questions": [], "extra": {"agent": True}})
        s.add(d)
        s.flush()
        return d.id


def settle(app_id: int, job_id: int, title: str, site: str, mode: str, result: run.Result, folder: Path, *, began: Any = None) -> dict[str, Any]:
    from ..ats.base import NeedsHuman

    rec, files = result.record or {}, {}
    try:
        files = brief.applicant_on_file().files
    except Exception:  # noqa: BLE001
        pass
    if result.outcome == "submitted":
        conf = rec.get("confirmation") or {}
        with db.session() as s:
            app = s.get(Application, app_id)
            lifecycle.move(app, "submitted", source="run", evidence={"url": conf.get("url", ""), "text": str(conf.get("words", ""))[:600], "ties_to_posting": str(conf.get("ties_to_posting", ""))[:300],
                                                                    "read_by": "agent", "folder": str(folder)})
            app.last_event = ""
            was_auto = mode == "auto"
            app.auto_approved = int(was_auto)
        _sent(app_id, title, conf, was_auto)
        return {"status": "submitted", "steps": result.steps, "seconds": result.seconds}
    if _was_sending(folder, began):
        # the run said it was about to send, and did not say what came of it: the application may be out
        lifecycle.outcome_unknown(app_id, title, "Agent 已经要点提交了，运行在给出结果之前中断；这份申请可能已经发出。程序会先去网站和邮箱核实，不会再点一次。")
        from .. import tasks

        tasks.enqueue_later("recon", ref=f"job:{job_id}", payload={"job_id": job_id, "verify": True}, minutes=3, priority=30)
        return {"status": UNKNOWN, "steps": result.steps}
    if mode == "verify":
        return _verified(app_id, job_id, title, result)
    if result.outcome == "ready" or (result.outcome == "needs_you" and rec.get("asked")):
        draft_id = keep_record(app_id, rec, files, rec.get("url") or "")
        open_n = len(rec.get("asked") or [])
        with db.session() as s:
            app = s.get(Application, app_id)
            lifecycle.move(app, "needs_input" if open_n else "draft_ready", source="run")
            app.last_event = ""
        notify.close_todos("answer", f"draft:{draft_id}")
        if open_n:
            qs = "\n".join("· " + str(q["question"])[:120] for q in (rec.get("asked") or [])[:6])
            notify.add_todo("answer", title, body=f"{open_n} 个问题需要你回答：\n{qs}", ref=f"draft:{draft_id}", payload={"draft_id": draft_id})
        else:
            n_ans = sum(1 for a in rec.get("answers") or [] if a.get("entered") not in ("", None, []))
            notify.send("todo", messages.draft_ready(title, draft_id, answers=n_ans, files=[str(f.get("file", "")) for f in rec.get("files") or []], why_not_auto=[]), ref=f"draft:{draft_id}")
        return {"draft_id": draft_id, "status": "needs_input" if open_n else "ready", "steps": result.steps, "seconds": result.seconds}
    if result.outcome == "needs_you":
        why = str(rec.get("summary") or "这个网站需要你登录或验证一次")[:600]
        url = _last_url(folder)
        with db.session() as s:
            lifecycle.move(s.get(Application, app_id), "needs_human", source="run")
        notify.add_todo("takeover", title, body=why, ref=f"account:{site}", payload={"tenant_key": site, "url": url, "job_url": url, "can_register": False})
        raise NeedsHuman(why, kind="login", url=url, waits_for=f"account:{site}")
    if result.outcome == "cannot":
        why = str(rec.get("summary") or "")[:800]
        with db.session() as s:
            app = s.get(Application, app_id)
            lifecycle.move(app, "failed", source="run")
            app.last_event = why[:300]
        notify.add_todo("failed", f"{title}：没有做成", body=why, ref=f"application:{app_id}", payload={"application_id": app_id, "job_id": job_id})
        notify.send("task_result", messages.failed(title, error=why), ref=f"application:{app_id}")
        return {"status": "cannot", "steps": result.steps}
    return _without_report(app_id, job_id, title, result, folder)


def _sent(app_id: int, title: str, conf: dict[str, Any], was_auto: bool) -> None:
    from .. import tasks

    for kind in ("failed", "submit", "answer"):
        notify.close_todos(kind, f"application:{app_id}")
    for m in db.get_setting("mail.confirm_check_minutes") or []:      # the confirmation e-mail turns "submitted" into "confirmed"
        tasks.enqueue_later("mail", ref=f"confirm:{app_id}", minutes=float(m), priority=40)
    notify.send("task_result", messages.submitted(title, evidence=str(conf.get("words") or ""), auto=was_auto, note=""), ref=f"application:{app_id}")


def _was_sending(folder: Path, began: Any) -> bool:
    """Did this run write that it was about to send the application - and nothing about how it ended?"""
    p = folder / "journal.jsonl"
    if not p.exists():
        return False
    sending = False
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("kind") == "run":
            sending = False
        elif e.get("kind") == "sending":
            sending = True
        elif e.get("kind") == "report":
            sending = False
    return sending


def _last_url(folder: Path) -> str:
    try:
        for ln in reversed((folder / "journal.jsonl").read_text(encoding="utf-8").splitlines()):
            e = json.loads(ln)
            if e.get("kind") == "needs_applicant" and e.get("url"):
                return str(e["url"])
    except (OSError, ValueError):
        pass
    return ""


def _verified(app_id: int, job_id: int, title: str, result: run.Result) -> dict[str, Any]:
    """A run that only looked whether the application had gone out."""
    if result.outcome == "ready":      # it is not out: the site shows it as not sent. It may be worked again.
        with db.session() as s:
            app = s.get(Application, app_id)
            lifecycle.move(app, "approved" if any(d.review_status == "approved" for d in app.drafts) else "draft_ready", source="run", not_sent=True, note="网站上显示这份申请没有发出")
        notify.close_todos("failed", f"application:{app_id}")
        from .. import tasks

        tasks.enqueue("recon", ref=f"job:{job_id}", payload={"job_id": job_id}, priority=30)
        return {"status": "not_sent", "steps": result.steps}
    return {"status": UNKNOWN, "note": str((result.record or {}).get("summary") or result.stopped)[:400]}


def _without_report(app_id: int, job_id: int, title: str, result: run.Result, folder: Path) -> dict[str, Any]:
    """The run ended and the agent did not say how. Three different things, three different answers:
    the model's allowance ran out (raised: the queue tries again when it is back); this run's share of the budget ran
    out (the next run goes on from the journal, while the application has budget left); it stopped at the same place
    several times (the applicant is asked)."""
    from .. import llm, tasks

    if result.stopped.startswith("LLMUnavailable"):
        raise llm.LLMUnavailable(result.stopped.split(": ", 1)[-1])
    place = _place(folder)
    same = _same_place(folder, place)
    with db.session() as s:
        app = s.get(Application, app_id)
        if same >= SAME_PLACE:
            lifecycle.move(app, "failed", source="run")
            app.last_event = "连续几次停在同一个地方"
    if same >= SAME_PLACE:
        notify.add_todo("failed", f"{title}：连续 {same} 次停在同一个地方", ref=f"application:{app_id}", payload={"application_id": app_id, "job_id": job_id},
                        body=f"停在：{place[:200]}\n{run.journal_text(folder)[-900:]}")
        return {"status": "stuck", "at": place[:200], "steps": result.steps}
    tasks.enqueue_later("recon", ref=f"job:{job_id}", payload={"job_id": job_id}, minutes=1, priority=60)
    return {"status": "goes_on", "stopped": result.stopped, "steps": result.steps}


def _place(folder: Path) -> str:
    """Where the last run was when it ended: the address its last tool call saw."""
    try:
        for ln in reversed((folder / "journal.jsonl").read_text(encoding="utf-8").splitlines()):
            e = json.loads(ln)
            out = str(e.get("output") or "")
            if e.get("kind") == "tool" and " at http" in out:
                return out.split(" at ", 1)[1].split()[0].rstrip(".")
    except (OSError, ValueError):
        pass
    return ""


def _same_place(folder: Path, place: str) -> int:
    """How many runs in a row have now ended at ``place`` without a report."""
    p = folder / "places.json"
    try:
        seen = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = []
    seen = [*seen, place][-8:]
    p.write_text(json.dumps(seen), encoding="utf-8")
    n = 0
    for x in reversed(seen):
        if x != place or not place:
            break
        n += 1
    return n

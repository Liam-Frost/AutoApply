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
MODE_OF_POLICY = {"hand_over": "hand_over", "approve": "prepare", "auto": "auto"}
SAME_PLACE = 3          # runs in a row that ended at the same place without a report, before the applicant is asked


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


def stop(application_id: int) -> None:
    """The applicant says: stop. The run that is working this application ends before its next action; nothing is
    started again for it until they say so."""
    folder = folder_of(application_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / run.STOP).write_text("stop", encoding="utf-8")


def spent(application_id: int) -> dict[str, Any]:
    """What this application has used of its budget, over all its runs."""
    used, total = _spent_so_far(folder_of(application_id)), _budget()
    grants = max(1, int(used.get("granted") or 1))
    return {"steps": int(used["steps"]), "minutes": round(used["seconds"] / 60, 1), "runs": int(used.get("runs") or 0),
            "of_steps": int(total["steps"] * grants), "of_minutes": round(total["seconds"] * grants / 60)}


# --- what a run is given ---------------------------------------------------------------------------------------------
def policy(company: str = "") -> str:
    """How applications are sent, as the applicant has set it: auto | approve | hand_over. An employer they named as
    one whose applications they send themselves is theirs whatever the general setting says."""
    p = str(db.get_setting("submit.policy") or "auto")
    if any(c and c.strip().lower() in (company or "").lower() for c in (db.get_setting("policy.manual_companies") or [])):
        return "hand_over"
    return p if p in MODE_OF_POLICY else "approve"


def policy_from_before() -> str | None:
    """For an installation from before there was one setting: what its settings came to. None for a new one.
    (Sending without being asked is not something an update switches on: an installation that asked for an approval
    of every draft still does.)"""
    from ..models import Setting

    with db.session() as s:
        if s.get(Setting, "submit.policy") is not None:
            return None
        old = {k: (json.loads(r.value) if (r := s.get(Setting, k)) is not None else None) for k in ("policy.default", "auto_approve.enabled", "onboarding.done")}
        used = old["onboarding.done"] or s.query(Application).count() > 0
    if old["policy.default"] == "manual":
        return "hand_over"
    if old["auto_approve.enabled"]:
        return "auto"
    return "approve" if (used or old["policy.default"]) else None


def mode_for(app_status: str, draft: Draft | None, company: str = "") -> str:
    if app_status == UNKNOWN:
        return "verify"
    if draft is not None and draft.review_status == "approved":
        return "send"
    return MODE_OF_POLICY[policy(company)]


def record_of(draft: Draft | None) -> dict[str, Any] | None:
    """A draft as the record the agent reads: what each question holds, and where that comes from."""
    if draft is None:
        return None
    rows = [a for a in draft.answers or [] if a.get("value") not in ("", None, [])]
    return {"answers": [{"question": a.get("label", ""), "entered": a.get("value"), "from": a.get("basis", "")} for a in rows if a.get("type") != "file"],
            "files": [{"field": m.get("slot") or m.get("label") or "", "file": m.get("name") or ""} for m in draft.materials or []],
            "notes": list(draft.notes or [])[:12]}


def answers_of(draft: Draft | None) -> dict[str, str]:
    """What the applicant themselves said in the record: the questions they answered, the values they changed, the
    questions they said are not to be answered."""
    from ..drafts import NOT_TO_ANSWER

    if draft is None:
        return {}
    said = {str(a.get("label", "")): _shown(a.get("value")) for a in draft.answers or [] if a.get("basis") == "edited by user" and a.get("value") not in ("", None, [])}
    said.update({str(a.get("label", "")): NOT_TO_ANSWER for a in draft.answers or [] if a.get("dropped")})
    for n, c in enumerate(draft.comments or [], 1):      # what they wrote about the record as a whole
        if str(c.comment or "").strip():
            said[f"(the applicant's note {n} on this application)"] = str(c.comment)[:1500]
    return said


def _shown(v: Any) -> str:
    return "; ".join(map(str, v)) if isinstance(v, list) else str(v)


# --- one application, once ---------------------------------------------------------------------------------------------
def work(job_id: int, *, task_id: int | None = None, instructions: str = "") -> dict[str, Any]:
    """Run the agent on the application for this posting, and settle what came of it. Returns the task's result.
    ``instructions``: what the applicant said when they asked for this application; kept for every run of it."""
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
        from .. import tasks as _tasks

        if app.status == "withdrawn" and not _tasks.running_by_hand():
            # They decided not to apply. An application they ask for themselves takes it up again; the program does
            # not - not a task that was still in the queue when they decided.
            return {"skipped": "the applicant is not applying for this one"}
        draft = app.drafts[-1] if app.drafts else None
        mode = mode_for(app.status, draft, job.company)
        record, answers = record_of(draft), {}
        for earlier in app.drafts:      # what the applicant said on any version of the record stands, the latest word last
            answers.update(answers_of(earlier))
        base = ((draft.schema or {}).get("extra") or {}).get("resume") == "base" if draft is not None else False
        if mode != "verify":
            lifecycle.move(app, "executing" if mode == "send" else "recon", source="run")
        app_id, title, channel = app.id, f"{job.company} · {job.title}", job.channel or ""
        posting = brief.Posting(company=job.company, title=job.title, url=job.apply_url, text=job.jd_text or job.summary or "", deadline=job.deadline or "",
                                extra=" · ".join(x for x in (f"Term: {job.term} {job.months}".strip() if (job.term or job.months) else "", f"Place: {job.location or job.work_type}" if (job.location or job.work_type) else "",
                                                             f"Documents asked for: {job.docs_required}" if job.docs_required else "",
                                                             f"Found on {job.source} as posting {job.source_id}" if job.source_id and (job.channel or job.ats) else "",
                                                             f"How it is applied for: {job.channel}" if job.channel else "") if x))
    folder, site = folder_of(app_id), brief.site_key(posting.url)
    from .. import tasks

    for n, said in enumerate(_instructions(folder, instructions), 1):
        answers[f"(what the applicant said when they asked for this application, {n})"] = said

    if tasks.running_by_hand():      # the applicant asked for it: what counted "the same place again" starts anew
        (folder / "places.json").unlink(missing_ok=True)
    left = _left(folder)
    if left["steps"] < 20 or left["seconds"] < 120:
        return _budget_used(app_id, title, folder)
    applicant = brief.applicant_on_file(channel)
    _own_letter(applicant, job_id)
    if mode != "verify":
        told, new = _own_resume(applicant, job_id, base)
        if told:
            answers["(the résumé for this application)"] = told
        if new and mode == "auto" and db.get_setting("tailor.review"):
            mode = "prepare"        # a résumé written just now is looked at by the applicant before it goes out
    began = now()
    def handed() -> None:       # the window is the applicant's: they are told, on a card and on their phone
        notify.add_todo("submit", f"{title}：请检查并点提交", ref=f"application:{app_id}", payload={"application_id": app_id, "job_id": job_id},
                        body="Agent 已经把申请表填到最后一步，浏览器窗口已经打开。请在窗口里看一遍，然后自己点提交；提交后直接关掉窗口。")

    with browser.open_page(site, headless=mode != "hand_over", url=posting.url) as page:
        result = run.apply(page, posting, applicant, folder, mode=mode, answers=answers or None, job_id=job_id, record=record, budget=left, on_hand=handed)
    notify.close_todos("submit", f"application:{app_id}")      # the window is closed: the card that pointed at it has nothing left to point at
    _spent(folder, result)
    return settle(app_id, job_id, title, site, mode, result, folder, began=began)


def _instructions(folder: Path, new: str = "") -> list[str]:
    p = folder / "instructions.json"
    try:
        said = list(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        said = []
    new = " ".join(str(new or "").split())[:2000]
    if new and new not in said:
        said.append(new)
        folder.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(said, ensure_ascii=False), encoding="utf-8")
    return said


def _own_resume(applicant: brief.Applicant, job_id: int, base: bool) -> tuple[str, bool]:
    """The résumé written for this posting (tailor.py: one that exists, or one written now when the applicant's
    settings ask for it) is among the files, and the run is told to use it. Returns (what the run is told, it was
    written just now). ``base``: the applicant chose the résumé as uploaded for this application."""
    from .. import llm, tailor

    if base:
        return "The applicant chose the résumé as uploaded for this application, not one rewritten for the posting.", False
    with db.session() as s:
        job = s.get(Job, job_id)
        s.expunge(job)
    try:
        doc, new = tailor.for_job(job)
    except llm.LLMUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 - the application goes ahead with the résumé as uploaded
        log.warning("no résumé was written for job %s: %s", job_id, e)
        return "", False
    if doc is None:
        return "", False
    applicant.files[doc["name"]], applicant.file_notes[doc["name"]] = doc["path"], "résumé rewritten for this posting"
    return (f"A résumé was rewritten for this posting: the file {doc['name']!r}. Upload it wherever the form takes a résumé, in place of the general one "
            "(also where an earlier run uploaded the general one)."), new


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
    notes = [str(record.get("summary", ""))[:3000]] + [str(x)[:600] for x in record.get("open") or []]      # the agent's own words: how it ended, and what it left open
    with db.session() as s:
        from ..models import Document

        for m in mats:      # the file as a document of the library, where it is one: the record's page links to it
            doc = s.query(Document).filter_by(path=m["path"]).order_by(Document.id.desc()).first() if m.get("path") else None
            if doc is not None:
                m["document_id"] = doc.id
        app = s.get(Application, app_id)
        version, kept = 1, {}
        for old in app.drafts:
            version = max(version, old.version + 1)
            if ((old.schema or {}).get("extra") or {}).get("resume"):      # which résumé the applicant chose stays chosen
                kept = {"resume": old.schema["extra"]["resume"]}
            if old.review_status == "pending":
                old.review_status = "superseded"
        d = Draft(application_id=app_id, version=version, review_status="pending", answers=answers, unresolved=open_, materials=mats, notes=[n for n in notes if n.strip()], plan=[],
                  schema={"ats": "agent", "tenant": urlparse(url).netloc.lower(), "url": url, "source": "agent", "pages": [], "questions": [], "extra": {"agent": True, **kept}})
        s.add(d)
        s.flush()
        return d.id


def settle(app_id: int, job_id: int, title: str, site: str, mode: str, result: run.Result, folder: Path, *, began: Any = None) -> dict[str, Any]:
    from ..errors import NeedsHuman

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

        tasks.enqueue_later("apply", ref=f"job:{job_id}", payload={"job_id": job_id}, minutes=3, priority=30)
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
            notify.send("todo", messages.draft_ready(title, draft_id, answers=n_ans, files=[str(f.get("file", "")) for f in rec.get("files") or []]), ref=f"draft:{draft_id}")
        return {"draft_id": draft_id, "status": "needs_input" if open_n else "ready", "steps": result.steps, "seconds": result.seconds}
    if result.outcome == "needs_you":
        why = str(rec.get("summary") or "这个网站需要你登录或验证一次")[:600]
        url = _last_url(folder)
        with db.session() as s:
            lifecycle.move(s.get(Application, app_id), "needs_human", source="run")
        from .. import auth

        # (the card names whose sign-in is missing: the site's, or - when the run stopped on a sign-in provider's own page - the provider's)
        waits = auth.ask_to_sign_in(site, title, why, url=url, job_url=url)
        raise NeedsHuman(why, kind="login", url=url, waits_for=waits)
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

        tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id, "after": "it was found not to be sent"}, priority=30)      # (a task of its own: this one only looked)
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
    if result.stopped == "stopped":      # the applicant's word: it is not taken up again by itself
        with db.session() as s:
            app = s.get(Application, app_id)
            lifecycle.move(app, "failed", source="user")
            app.last_event = "你叫停了 Agent"
        notify.add_todo("failed", f"{title}：已按你的要求停下", ref=f"application:{app_id}", payload={"application_id": app_id, "job_id": job_id}, push=False,
                        body="Agent 在下一步操作之前停了，没有再继续。网站上已经保存的内容还在。想让它接着做，点“让 Agent 再试一次”。")
        return {"status": "stopped", "steps": result.steps}
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
    tasks.enqueue_later("apply", ref=f"job:{job_id}", payload={"job_id": job_id}, minutes=1, priority=60)
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


# --- an installation from before there was one task for an application ------------------------------------------------------
def tasks_from_before() -> int:
    """Tasks that wait in the queue under the kinds the older pipeline had (read the form, fill it, revise the draft,
    ask again, read the later steps) become the one task there is now, for the same posting. A note the applicant
    wrote on a draft and that was still waiting to be applied is kept with the draft. Returns how many were changed."""
    from ..models import DraftComment, Task

    n = 0
    with db.session() as s:
        seen: set[int] = set()
        for t in s.query(Task).filter(Task.kind.in_(("recon", "execute", "revise", "reanswer", "scout")), Task.status.in_(("queued", "waiting_human", "held"))).order_by(Task.id):
            payload = dict(t.payload or {})
            job_id = payload.get("job_id")
            draft = s.get(Draft, int(payload["draft_id"])) if payload.get("draft_id") else None
            if job_id is None and draft is not None:
                job_id = draft.application.job_id
            if job_id is None and t.ref.startswith("application:") and t.ref.split(":")[1].isdigit():
                app = s.get(Application, int(t.ref.split(":")[1]))
                job_id = app.job_id if app is not None else None
            if t.kind == "revise" and draft is not None and str(payload.get("comment") or "").strip():
                s.add(DraftComment(draft_id=draft.id, comment=str(payload["comment"])[:4000], result=""))
            if job_id is None or (int(job_id) in seen and t.status == "queued"):
                t.status, t.error = "cancelled", "这个任务属于旧的流程，已经由新的申请任务代替"
            else:
                seen.add(int(job_id))
                keep = {k: v for k, v in payload.items() if k in ("instructions", "waits_for", "by_hand", "browser_backend") or k.startswith("_")}
                t.kind, t.ref, t.payload = "apply", f"job:{int(job_id)}", {**keep, "job_id": int(job_id)}
            n += 1
    return n

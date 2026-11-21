"""The assistant behind the bots: what the applicant says to the Telegram or Discord bot that is not a command and not
a reply to a card ("what is waiting for me", "don't apply to the Acme one", "my notice period is two weeks").

It is a small agent with the program's own operations as its tools - the same functions the pages call - and a short
memory of the conversation. It can look things up, start, retry or stop an application, mark a posting as one the
applicant is not applying for, pause and resume, scan, put a card off, and enter the answers the applicant gives it to
the questions an application waits on. What it cannot do is not a rule it is asked to keep, it is a tool it does not
have: approving a record, sending an e-mail, changing the profile, anything with a password.

One action, the applicant asked for it in so many words: done. More than one in a reply ("all of them"): the reply
carries a button, and nothing happens until it is pressed.
"""
from __future__ import annotations

import json
import logging
import secrets as _random
from datetime import datetime, timedelta
from typing import Any

from . import db, i18n, llm

log = logging.getLogger("autoapply.chat")

HISTORY = "bot.chat_history"      # the last exchanges ({who, text, at}); forgotten after two quiet hours
PENDING = "bot.pending"           # actions waiting for the applicant's press: {token: {what, ids, until, said}}
KEEP = 8
ACTIONS = ("apply", "retry", "stop", "not_applying", "pause", "resume", "scan", "snooze", "done")

SYSTEM = """You are the assistant of AutoApply, a program that applies to jobs for one person (the applicant). They are
talking to you in a chat app (Telegram or Discord) on their phone. Answer briefly - a few lines, no tables, no
markdown headings - in the language they write in.

Use the tools to find out how things stand before you answer: never guess an application's state. When they ask you
to do something, do it with the tools and say what was done. When something they ask is not one of your tools -
approving a record, sending an e-mail, changing their profile, signing in anywhere, anything with a password - say so
in one line and tell them where in the program it is done (the to-do page, the application's page, the profile, the
settings). Never ask for a password or a code; a code a site sent them goes on the card that asks for it.

An application waits on a question only they can answer (the open questions of its record, on the cards): when they
tell you the answer, enter it with `answer`, as they said it - choose the option that matches when the question has
options. Never make an answer up, and never enter one they did not give.

Several actions at once ("all of them", "every Acme posting"): call `act` with all the ids together. The program then
puts a button under your reply and does it when they press it: say that it is waiting for their press."""


def _t(text: str) -> str:
    return i18n.tr(text)


# --- what the tools see ------------------------------------------------------------------------------------------------
def _questions(s: Any, draft_id: int) -> list[dict[str, Any]]:
    from .models import Draft

    d = s.get(Draft, draft_id) if draft_id else None
    if d is None:
        return []
    return [{"question_id": a.get("id"), "question": a.get("label"), "options": (a.get("options") or [])[:20], "suggested": a.get("suggested")}
            for a in d.answers or [] if a.get("source") == "unresolved" and a.get("value") in ("", None, [])]


def look(query: str = "") -> list[dict[str, Any]]:
    """Postings and their applications whose company or title has these words (all of them, when no words)."""
    from .models import Job

    words = [w for w in query.lower().split() if w]
    out = []
    with db.session() as s:
        q = s.query(Job).filter(Job.archived_at.is_(None)).order_by(Job.id.desc())
        for j in q.limit(3000):
            hay = f"{j.company} {j.title}".lower()
            if words and not all(w in hay for w in words):
                continue
            a = j.application
            out.append({"job_id": j.id, "company": j.company, "title": j.title, "posting": j.status, "deadline": j.deadline or None,
                        "application_id": a.id if a else None, "application": a.status if a else None,
                        "last": (a.last_event or "")[:240] if a else None})
            if len(out) >= 12:
                break
    return out


def cards() -> list[dict[str, Any]]:
    """What is waiting for the applicant (the to-do page), with the questions a card asks."""
    from . import reminders
    from .models import Todo

    out = []
    with db.session() as s:
        for t in s.query(Todo).filter_by(status="open").order_by(Todo.id.desc()).limit(40):
            if reminders.snoozed(t):
                continue
            p = t.payload or {}
            row: dict[str, Any] = {"todo_id": t.id, "kind": t.kind, "title": t.title, "body": (t.body or "")[:300],
                                   "application_id": p.get("application_id"), "job_id": p.get("job_id")}
            if t.kind == "answer" and p.get("draft_id") and not p.get("review"):
                row["draft_id"], row["questions"] = int(p["draft_id"]), _questions(s, int(p["draft_id"]))
            out.append(row)
    return out


def application(application_id: int) -> dict[str, Any]:
    from .models import Application

    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None:
            return {"error": "no such application"}
        d = max(a.drafts, key=lambda x: x.id) if a.drafts else None
        return {"application_id": a.id, "job_id": a.job_id, "company": a.job.company, "title": a.job.title, "status": a.status,
                "last": (a.last_event or "")[:600], "updated": a.updated_at.isoformat(timespec="minutes") if getattr(a, "updated_at", None) else None,
                "record": {"draft_id": d.id, "review": d.review_status, "open_questions": _questions(s, d.id)} if d else None,
                "page": f"/applications/{a.id}"}


# --- doing ---------------------------------------------------------------------------------------------------------------
def perform(what: str, ids: list[int]) -> str:
    """Carry out one of ACTIONS on these ids (postings, applications or cards, by the action). Returns what was done."""
    from . import reminders, tasks
    from .api import main as api
    from .models import Application, Todo

    if what == "pause":
        db.set_setting("schedule.paused", True)
        return "paused"
    if what == "resume":
        db.set_setting("schedule.paused", False)
        return "resumed"
    if what == "scan":
        asked = tasks.by_hand.set(True)
        try:
            tasks.enqueue("discover", ref="manual", priority=20, dedupe=True)
        finally:
            tasks.by_hand.reset(asked)
        return "a scan for new postings was started"
    if what in ("apply", "not_applying"):
        got = api.bulk_jobs({"action": "draft" if what == "apply" else "skip", "ids": ids})
        return f"{what}: {got.get('done', 0)} done, {got.get('skipped', 0)} could not be (already sent, offline, or no link to apply)"
    if what in ("retry", "stop"):
        done = []
        for aid in ids:
            with db.session() as s:
                a = s.get(Application, aid)
                job_id = a.job_id if a else 0
            if not job_id:
                continue
            if what == "retry":
                asked = tasks.by_hand.set(True)
                try:
                    api.make_draft(job_id, {})
                finally:
                    tasks.by_hand.reset(asked)
            else:
                from .agent import work as _work

                _work.stop(aid)
            done.append(aid)
        return f"{what}: applications {done}"
    if what in ("snooze", "done"):
        done = []
        for tid in ids:
            with db.session() as s:
                t = s.get(Todo, tid)
                kind = t.kind if t is not None and t.status == "open" else ""
            if not kind:
                continue
            if what == "snooze":
                reminders.snooze(tid, (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0))
            elif kind in ("confirm", "resume", "followup", "gone"):
                api.todo_done(tid, {})
            else:
                continue      # a card that needs more than "done" (a code, a question, a mail): its own page
            done.append(tid)
        return f"{what}: cards {done}"
    raise ValueError(f"unknown action {what}")


def confirm(token: str) -> str:
    """The applicant pressed the button under a reply: what it proposed is done now (once)."""
    pending = dict(db.get_setting(PENDING) or {})
    p = pending.pop(token, None)
    db.set_setting(PENDING, {k: v for k, v in pending.items() if v.get("until", "") > datetime.now().isoformat()})
    if not p or p.get("until", "") < datetime.now().isoformat():
        from .actions import Done

        raise Done(_t("这个按钮已经过期了；再说一遍要做什么。"))
    perform(p["what"], list(p.get("ids") or []))
    return _t("已照办")


def _propose(what: str, ids: list[int], said: str) -> dict[str, str]:
    token = _random.token_urlsafe(6)
    pending = {k: v for k, v in (db.get_setting(PENDING) or {}).items() if v.get("until", "") > datetime.now().isoformat()}
    pending[token] = {"what": what, "ids": ids, "said": said, "until": (datetime.now() + timedelta(hours=2)).isoformat()}
    db.set_setting(PENDING, pending)
    return {"label": _t(f"确认：{said[:50]}"), "data": f"c:{token}"}


# --- the conversation ----------------------------------------------------------------------------------------------------
def _history() -> list[dict[str, str]]:
    h = list(db.get_setting(HISTORY) or [])
    if h and h[-1].get("at", "") < (datetime.now() - timedelta(hours=2)).isoformat():
        return []
    return h[-KEEP:]


def _remember(who: str, text: str) -> None:
    h = _history() + [{"who": who, "text": text[:1500], "at": datetime.now().isoformat(timespec="seconds")}]
    db.set_setting(HISTORY, h[-KEEP:])


def reply(text: str) -> tuple[str, list[dict[str, str]]]:
    """Answer what the applicant said. Returns the reply and the buttons under it (a confirmation, when it proposes)."""
    from . import bots, drafts

    buttons: list[dict[str, str]] = []
    acted = {"n": 0}

    def t_status() -> str:
        return bots.status()

    def t_cards() -> str:
        return json.dumps(cards(), ensure_ascii=False, default=str)

    def t_look(query: str = "") -> str:
        return json.dumps(look(query), ensure_ascii=False, default=str)

    def t_application(application_id: int) -> str:
        return json.dumps(application(int(application_id)), ensure_ascii=False, default=str)

    def t_act(action: str, ids: list[int] | None = None, summary: str = "") -> str:
        if action not in ACTIONS:
            return f"unknown action; one of {', '.join(ACTIONS)}"
        ids = [int(i) for i in ids or []][:200]
        if len(ids) > 1 or acted["n"] >= 1:
            buttons.append(_propose(action, ids, summary or f"{action} × {len(ids) or 1}"))
            return "not done yet: a button was put under your reply, and it is done when the applicant presses it. Tell them so."
        acted["n"] += 1
        try:
            return perform(action, ids)
        except Exception as e:  # noqa: BLE001 - said back to the model, which tells the applicant
            return f"could not: {getattr(e, 'detail', None) or e}"

    def t_answer(draft_id: int, question_id: str, value: str) -> str:
        with db.session() as s:
            qs = {q["question_id"]: q for q in _questions(s, int(draft_id))}
        q = qs.get(question_id)
        if q is None:
            return "that question is not open (answered already, or not on this record)"
        v = value.strip()
        if q["options"]:
            hit = [o for o in q["options"] if str(o).strip().lower() == v.lower()]
            if not hit:
                return "the answer must be one of: " + " / ".join(map(str, q["options"]))
            v = hit[0]
        if not v:
            return "empty answer"
        drafts.edit_answer(int(draft_id), question_id, v)
        return f"entered: {q['question']} = {v}"

    S, I = {"type": "string"}, {"type": "integer"}
    tools = [
        llm.Tool("status", "What the program is doing now: paused or running, the applications being worked, how much is queued and waiting.", llm.obj({}), t_status),
        llm.Tool("cards", "What is waiting for the applicant (the to-do page), with the open questions of each card that asks some.", llm.obj({}), t_cards),
        llm.Tool("look", "Postings and their applications whose company or title contains all these words (empty: the newest).", llm.obj({"query": S}), t_look),
        llm.Tool("application", "One application: its state, what happened last, its record and the questions open on it.", llm.obj({"application_id": I}, ["application_id"]), t_application),
        llm.Tool("act", "Do something: apply (job_ids: let the agent apply), retry (application_ids: work it again now), stop (application_ids: stop the "
                 "run working it), not_applying (job_ids), pause, resume, scan (look for new postings), snooze (todo_ids: remind tomorrow), done "
                 "(todo_ids: a card that only needs 'done'). Give a short summary in the applicant's language for the confirmation button.",
                 llm.obj({"action": {"type": "string", "enum": list(ACTIONS)}, "ids": {"type": "array", "items": I}, "summary": S}, ["action"]), t_act),
        llm.Tool("answer", "Enter the applicant's answer to an open question of an application's record (draft_id and question_id from cards or "
                 "application). Only what they said.", llm.obj({"draft_id": I, "question_id": S, "value": S}, ["draft_id", "question_id", "value"]), t_answer),
    ]
    past = "\n".join(f"{'Applicant' if h['who'] == 'me' else 'You'}: {h['text']}" for h in _history())
    goal = (f"The conversation so far:\n{past}\n\n" if past else "") + f"The applicant now says:\n{text}\n\nToday is {datetime.now():%Y-%m-%d %H:%M}."
    res = llm.agent(goal, tools, system=SYSTEM, kind="chat")
    said = (res.final_text or "").strip() or _t("我没能给出回答，换个说法再试一次？")
    _remember("me", text)
    _remember("bot", said)
    return said, buttons

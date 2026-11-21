"""What can be done from a notification: the buttons under a card, and what a reply to it means.

The same actions as the buttons on the program's pages, reached through the same functions (api/main.py): a press in
Telegram or Discord does exactly what the press on the page does, so the two cannot drift apart. What an action may do
is the page's rule too - a card that has been dealt with says so instead of acting again, and nothing here can send
an e-mail, type a password or change the profile.

An action is a short string a chat service can carry back (Telegram allows 64 bytes): ``t:<todo>:<what>[:<n>]`` for a
card on the to-do page, ``d:<draft>:<what>`` for a record waiting for approval.
"""
from __future__ import annotations

from .say import say as T

import logging
from datetime import datetime, timedelta
from typing import Any

from . import db, i18n
from .messages import Card
from .models import Draft, Job, Todo

log = logging.getLogger("autoapply.actions")


def _t(text: str) -> str:
    return i18n.tr(text)


# --- the buttons of a card ---------------------------------------------------------------------------------------------
def for_todo(todo_id: int) -> list[dict[str, str]]:
    """The buttons of a card on the to-do page, by its kind: only what is done in one press and needs nothing more to be
    seen. Cards about a sign-in, a mail to be read and sent, or a changed profile have none: they lead to the page."""
    with db.session() as s:
        t = s.get(Todo, todo_id)
        if t is None or t.status != "open":
            return []
        kind, p = t.kind, dict(t.payload or {})
        if kind == "confirm":
            return [{"label": _t(T("server.actions.doneGoOn")), "data": f"t:{todo_id}:done"}]
        if kind == "resume":
            return [{"label": _t(T("server.actions.imHereNowGo")), "data": f"t:{todo_id}:done"}]
        if kind == "code":
            return [{"label": _t(T("server.actions.enterTheCode")), "data": f"t:{todo_id}:code", "input": "code"}]
        if kind == "failed" and p.get("job_id"):
            return [{"label": _t(T("server.actions.tryAgain")), "data": f"t:{todo_id}:retry"}, {"label": _t(T("server.actions.skipIt")), "data": f"t:{todo_id}:skip"}]
        if kind == "gone":
            return [{"label": _t(T("server.actions.gotIt")), "data": f"t:{todo_id}:ack"}]
        if kind == "followup":
            return [{"label": _t(T("server.actions.done")), "data": f"t:{todo_id}:done"}, {"label": _t(T("server.actions.remindMeTomorrow")), "data": f"t:{todo_id}:snooze"}]
        if kind == "answer" and p.get("draft_id") and not p.get("review"):
            q = _open_question(s, int(p["draft_id"]))
            if q is None:
                return []
            out = [{"label": str(o)[:60], "data": f"t:{todo_id}:opt:{i}"} for i, o in enumerate((q.get("options") or [])[:8])]
            if q.get("suggested"):
                out.insert(0, {"label": _t(T("server.actions.asSuggested", p0=str(q['suggested'])[:40])), "data": f"t:{todo_id}:sug"})
            return out
    return []


SHOWN = 12      # what a card on a phone can list; a record with more to look at than that is approved on its page


def _unsure(d: Draft) -> list[str]:
    return [f"{a.get('label')}：{a.get('value')}" for a in (d.answers or []) if a.get("confidence") in ("low", "medium") and a.get("source") != "unresolved"]


def _changed(s: Any, d: Draft) -> list[str]:
    """What is different from the version of this record before it (one the applicant saw, asked to change, or that
    the agent made again): every answer added or changed."""
    before = (s.query(Draft).filter(Draft.application_id == d.application_id, Draft.id < d.id).order_by(Draft.id.desc()).first())
    if before is None:
        return []
    was = {str(a.get("label")): a.get("value") for a in before.answers or []}
    return [f"{a.get('label')}：{was.get(str(a.get('label')), '—') or '—'} → {a.get('value')}" for a in d.answers or []
            if a.get("source") != "unresolved" and was.get(str(a.get("label"))) != a.get("value")]


def for_record(draft_id: int) -> list[dict[str, str]]:
    """A record waiting for approval: "approve and send" - when nothing in it is open, and everything the applicant has
    to have seen before approving it fits on the card (the answers the agent was not sure of, what changed since the
    version before). Otherwise the card has only its link."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d is None or d.review_status != "pending" or d.unresolved:
            return []
        if len(_unsure(d)) > SHOWN or len(_changed(s, d)) > SHOWN:
            return []
    return [{"label": _t(T("server.actions.approveAndSend")), "data": f"d:{draft_id}:approve"}]


def decorate(card: Card, ref: str, todo_id: int | None) -> list[dict[str, str]]:
    """The buttons for a card that is being sent, and what the card has to show for them to be pressed from a phone:
    under "approve and send", every answer the agent was not sure of, what changed since the version before, and every
    file that goes with it. A card about something that has a place of its own (an interview's meeting) leads there."""
    go = [{"label": _t(T("server.actions.open")), "url": card.open_url}] if card.open_url else []
    return go + _decorate(card, ref, todo_id)


def _decorate(card: Card, ref: str, todo_id: int | None) -> list[dict[str, str]]:
    if todo_id:
        acts = for_todo(todo_id)
        with db.session() as s:
            t = s.get(Todo, todo_id)
            if t is not None and t.kind == "answer" and acts:
                q = _open_question(s, int((t.payload or {}).get("draft_id") or 0))
                if q is not None:
                    card.fields = [*card.fields, (_t(T("server.actions.theQuestion")), str(q.get("label") or "")[:300])]
        return acts
    if ref.startswith("update:"):      # a new version: "update when idle" (a restart right now is pressed on the page)
        from . import updates

        _, ver, what = (ref.split(":") + ["", ""])[:3]
        if what in ("available", "ready") and updates.kind() == "managed":
            return [{"label": _t(T("server.actions.updateWhenIdle")), "data": f"u:{ver}:idle"}]
        return []
    if ref.startswith("draft:") and ref[6:].isdigit():
        acts = for_record(int(ref[6:]))
        if acts:
            with db.session() as s:
                d = s.get(Draft, int(ref[6:]))
                unsure, changed = _unsure(d), _changed(s, d)
                files = [str(m.get("name") or "") for m in (d.materials or []) if m.get("name")]
            if unsure:
                card.items_title, card.items = _t(T("server.actions.answersTheAgentWas")), [x[:160] for x in unsure]
            if changed:
                card.detail = "\n".join([*([card.detail] if card.detail else []), _t(T("server.actions.differentFromTheVersion")), *(f"• {x[:160]}" for x in changed)])
            # (the files as the record has them; the card's own line about what was uploaded gives way to it)
            card.fields = [*(f for f in card.fields if f[0] != _t("上传了")), (_t(T("server.actions.files")), "、".join(files) or _t(T("server.actions.none")))]
        return acts
    return []


def _open_question(s: Any, draft_id: int) -> dict[str, Any] | None:
    d = s.get(Draft, draft_id) if draft_id else None
    if d is None:
        return None
    open_ = [a for a in (d.answers or []) if a.get("source") == "unresolved" and a.get("value") in ("", None, [])]
    return open_[0] if open_ else None


# --- doing it ------------------------------------------------------------------------------------------------------------
class Done(Exception):
    """The card was dealt with already, or the action does not apply any more: the message says so."""


def run(data: str, value: str = "", *, via: str = "") -> str:
    """Carry out an action. Returns a short sentence for the chat ("已继续"). Raises Done when there is nothing to do."""
    from fastapi import HTTPException

    from .api import main as api

    parts = data.split(":")
    log.info("action %s from %s", data, via or "?")
    try:
        if parts[0] == "c" and len(parts) == 2:      # the button under an answer of the assistant's: what it proposed
            from . import chat

            return chat.confirm(parts[1])
        if parts[0] == "u" and len(parts) == 3 and parts[2] == "idle":
            from . import updates

            try:
                return _t(updates.when_idle(parts[1]))
            except ValueError as e:
                raise Done(_t(T("server.actions.thisButtonNoLonger"))) from e
        if parts[0] == "d" and len(parts) == 3 and parts[2] == "approve":
            from . import drafts

            try:
                drafts.approve(int(parts[1]))
            except ValueError as e:
                raise Done(_t(T("server.actions.thisRecordIsNo"))) from e
            return _t(T("server.actions.approvedSendingNow"))
        if parts[0] != "t" or len(parts) < 3:
            raise Done(_t(T("server.actions.thisButtonNoLonger")))
        todo_id, what = int(parts[1]), parts[2]
        with db.session() as s:
            t = s.get(Todo, todo_id)
            if t is None or t.status != "open":
                raise Done(_t(T("server.actions.thisHasBeenDealt")))
            kind, p = t.kind, dict(t.payload or {})
        if what == "done":
            api.todo_done(todo_id, {})
            return _t(T("server.actions.resumed")) if kind in ("confirm", "resume") else _t(T("server.actions.done"))
        if what == "code":
            if not value.strip():
                raise Done(_t(T("server.actions.replyToThisMessage")))
            given = api.todo_code(todo_id, {"code": value})
            return _t(T("server.actions.givenToTheAgent")) if given.get("given") else _t(T("server.actions.theAgentIsNo"))
        if what == "retry":
            api.make_draft(int(p["job_id"]), {})
            api.todo_done(todo_id, {"status": "dismissed", "resume": False})
            return _t(T("server.actions.theAgentHasStarted"))
        if what == "skip":
            from . import lifecycle

            with db.session() as s:
                job = s.get(Job, int(p["job_id"]))
                if job is not None:
                    lifecycle.not_applying(job, source="user")
            api.todo_done(todo_id, {"status": "dismissed", "resume": False})
            return _t(T("server.actions.markedAsNotApplying"))
        if what == "ack":
            api.todo_done(todo_id, {"status": "dismissed", "resume": False})
            return _t(T("server.actions.allRight"))
        if what == "snooze":
            from . import reminders

            until = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            reminders.snooze(todo_id, until)
            return _t(T("server.actions.okIWillRemind"))
        if what in ("opt", "sug", "answer"):
            return answer(int(p["draft_id"]), value if what == "answer" else "", option=int(parts[3]) if what == "opt" and len(parts) > 3 else None, suggested=what == "sug")
    except HTTPException as e:
        raise Done(str(e.detail)) from e
    raise Done(_t(T("server.actions.thisButtonNoLonger")))


def answer(draft_id: int, text: str, *, option: int | None = None, suggested: bool = False) -> str:
    """Answer the first open question of a record (as on the record's page). Returns what was entered, said back."""
    from . import drafts

    with db.session() as s:
        q = _open_question(s, draft_id)
        if q is None:
            raise Done(_t(T("server.actions.thisApplicationHasNo")))
        qid, label, options, sug = q["id"], str(q.get("label") or ""), list(q.get("options") or []), q.get("suggested")
    value = options[option] if option is not None and 0 <= option < len(options) else sug if suggested else text.strip()
    if value in ("", None):
        raise Done(_t(T("server.actions.noAnswerReceived")))
    if options and value not in options:
        hit = [o for o in options if str(o).strip().lower() == str(value).strip().lower()]
        if not hit:
            raise Done(_t(T("server.actions.thisQuestionTakesOne", p0=' / '.join(map(str, options[:10])))))
        value = hit[0]
    drafts.edit_answer(draft_id, qid, value)
    return _t(T("server.actions.noted", p0=label[:80], p1=value))


def speak(application_id: int, text: str) -> str:
    """A reply to a card about an application is a word to its agent (the box on the application's page)."""
    from .api import main as api

    got = api.say_to_the_agent(application_id, {"text": text})
    return _t(T("server.actions.toldTheAgentWorking")) if got.get("heard") == "now" else _t(T("server.actions.notedTheAgentWill"))


def about(ref: str) -> tuple[str, int]:
    """What a card is about, from its ref: ("code"|"answer"|"application"|"", id)."""
    head, _, rest = ref.partition(":")
    if head == "application" and rest.endswith(":code") and rest.split(":")[0].isdigit():
        return "code", int(rest.split(":")[0])
    if head == "draft" and rest.isdigit():
        return "answer", int(rest)
    if head == "application" and rest.split(":")[0].isdigit():
        return "application", int(rest.split(":")[0])
    return "", 0


def reply(ref: str, todo_id: int | None, text: str) -> str:
    """A reply to a notification: the code it waits for, the answer to the question it asks, or a word to the agent of
    its application."""
    what, n = about(ref)
    if what == "code" and todo_id:
        return run(f"t:{todo_id}:code", text)
    if what == "answer":
        with db.session() as s:
            asks = _open_question(s, n) is not None
            d = s.get(Draft, n)
            app_id = d.application_id if d is not None else 0
        if asks or not app_id:
            return answer(n, text)
        return speak(app_id, text)      # a record that asks nothing (one waiting for approval): a word to its agent
    if what == "application":
        return speak(n, text)
    with db.session() as s:      # a card about a posting: a word to its application, if it has one
        t = s.get(Todo, todo_id) if todo_id else None
        app_id = int((t.payload or {}).get("application_id") or 0) if t is not None else 0
        if not app_id and t is not None and (t.payload or {}).get("job_id"):
            j = s.get(Job, int(t.payload["job_id"]))
            app_id = j.application.id if j is not None and j.application is not None else 0
    if app_id:
        return speak(app_id, text)
    raise Done(_t(T("server.actions.thisNotificationIsNot")))

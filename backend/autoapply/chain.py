"""Every application that is not finished has something that moves it: work in the queue, or a card with the applicant.

That is the whole rule. Each part of the program kept its own half of it - the run moved the status, the queue held
the task, the page held the card - and every way of ending that one of them did not foresee left an application
standing where nothing would ever touch it again: "being prepared" behind a task that had failed, "waiting for you"
behind a card that had been closed, "failed" with nothing to press. Nothing was wrong in any one place.

So the rule is checked as a whole, here, from what is on record - after every task that works an application, when
the program starts, and every few minutes - and whatever does not hold is put right in the one way that loses
nothing: the applicant gets a card that says where it stands and what they can do. ``look`` only says what does not
hold; ``mend`` puts it right and says what it did.
"""
from __future__ import annotations

from .say import say as T

import logging
from datetime import timedelta
from typing import Any

from . import db, lifecycle, notify
from .models import SENT, UNKNOWN, Application, Outgoing, Task, Todo, now

log = logging.getLogger("autoapply.chain")

LIVE = ("queued", "running", "waiting_human", "held")       # a task that will still do something, or waits for someone
WORKED = ("recon", "revising", "executing")                 # "the program is on it": true only while a task is
OVER = (*SENT, "withdrawn")                                 # nothing more is done for these
ABOUT_A_RUN = ("code", "confirm")                           # cards a working run waits on: nothing without the run
OF_AN_APPLICATION = ("answer", "failed", "resume", "submit", "mail_out", "gone", *ABOUT_A_RUN)


def _cards(s: Any) -> list[Todo]:
    return list(s.query(Todo).filter_by(status="open"))


def _of(app: Application, cards: list[Todo], draft_ids: set[int]) -> list[Todo]:
    """The open cards that are about this application."""
    mine = []
    for t in cards:
        p = t.payload or {}
        if p.get("application_id") == app.id or t.ref == f"application:{app.id}" or t.ref.startswith(f"application:{app.id}:") \
                or (t.ref.startswith("draft:") and t.ref[6:].isdigit() and int(t.ref[6:]) in draft_ids) or p.get("job_id") == app.job_id:
            mine.append(t)
    return mine


def look(settled: int | None = None) -> list[dict[str, Any]]:
    """What does not hold right now: one entry for each application (or card, or mail) with nothing to move it.
    ``settled``: the posting whose task has just ended - its application is not "in the middle of being changed"."""
    out: list[dict[str, Any]] = []
    with db.session() as s:
        cards = _cards(s)
        open_refs = {t.ref for t in cards}
        tasks: dict[str, list[Task]] = {}
        for t in s.query(Task).filter(Task.kind == "apply", Task.status.in_(LIVE)):
            tasks.setdefault(t.ref, []).append(t)
        # (a cover letter being written for an application is work on it: the application goes on when it is there)
        letters = {int((t.payload or {}).get("job_id") or 0) for t in s.query(Task).filter(Task.kind == "cover_letter", Task.status.in_(("queued", "running")))}
        fresh = now() - timedelta(seconds=30)      # (in the middle of being changed by whoever is on it: looked at next time)
        for app in s.query(Application).filter(Application.status.notin_(OVER)):
            live = tasks.get(f"job:{app.job_id}", [])
            going = [t for t in live if t.status in ("queued", "running")]
            waiting = [t for t in live if t.status == "waiting_human"]
            held = [t for t in live if t.status == "held"]
            mine = _of(app, cards, {d.id for d in app.drafts})
            latest = app.drafts[-1] if app.drafts else None
            say = lambda what, **more: out.append({"what": what, "application_id": app.id, "job_id": app.job_id, "status": app.status, **more})  # noqa: E731
            for t in waiting:      # a task waits for a card that is not there
                ref = str((t.payload or {}).get("waits_for") or "")
                if ref and ref not in open_refs and not ref.startswith("profile"):
                    say("waits_for_nothing", task_id=t.id, waits_for=ref, reason=t.error or "")
            if going or held or app.job_id in letters:
                continue      # (work is queued or running; or the applicant put it aside, which the queue's page shows)
            if app.job_id != settled and app.updated_at is not None and app.updated_at.replace(tzinfo=None) > fresh.replace(tzinfo=None):
                continue
            if app.status in WORKED:
                if not waiting:
                    say("worked_by_nothing")
            elif app.status == "approved":
                if not waiting:
                    say("approved_and_not_queued")
            elif app.status == UNKNOWN:
                if not mine:
                    say("unknown_and_not_looked_into")
            elif app.status == "needs_input":
                if latest is None or not latest.unresolved:
                    say("asks_nothing")
                elif f"draft:{latest.id}" not in open_refs:
                    say("question_without_card", draft_id=latest.id)
            elif app.status == "draft_ready":
                if latest is None or latest.review_status not in ("pending", "approved"):
                    say("ready_without_record")
            elif app.status in ("needs_human", "failed"):
                if not waiting and not mine:
                    say("nothing_to_press")
        for t in cards:      # a card about a run that is not running; a card about an application that is over
            p = t.payload or {}
            app = s.get(Application, int(p["application_id"])) if str(p.get("application_id") or "").isdigit() else None
            if t.kind in ABOUT_A_RUN and not any(x.status == "running" for x in tasks.get(f"job:{p.get('job_id')}", [])):
                out.append({"what": "card_without_run", "todo_id": t.id})
            elif app is not None and app.status in OVER and t.kind in OF_AN_APPLICATION and t.kind != "gone":
                out.append({"what": "card_of_a_finished_application", "todo_id": t.id})
        late = now() - timedelta(minutes=5)
        for o in s.query(Outgoing).filter_by(status="sending"):
            if o.created_at is None or o.created_at.replace(tzinfo=None) < late.replace(tzinfo=None):
                out.append({"what": "mail_not_known_sent", "outgoing_id": o.id})
    return out


def mend(settled: int | None = None) -> list[dict[str, Any]]:
    """Put right what ``look`` finds. Each repair leaves the application with a task in the queue or a card with the
    applicant, and says on the card what happened. Returns what was done."""
    from . import humanize, tasks

    done: list[dict[str, Any]] = []
    for f in look(settled):
        what = f["what"]
        try:
            if what in ("card_without_run", "card_of_a_finished_application"):
                with db.session() as s:
                    t = s.get(Todo, f["todo_id"])
                    if t is not None and t.status == "open":
                        t.status, t.done_at = "dismissed", now()
            elif what == "mail_not_known_sent":
                with db.session() as s:
                    o = s.get(Outgoing, f["outgoing_id"])
                    if o is not None and o.status == "sending":
                        o.status, o.error = "failed", T("server.chain.theProgramWasInterrupted")
            elif what == "approved_and_not_queued":
                tasks.enqueue("apply", ref=f"job:{f['job_id']}", payload={"job_id": f["job_id"]}, priority=30)
            elif what == "unknown_and_not_looked_into":
                tasks.enqueue_later("apply", ref=f"job:{f['job_id']}", payload={"job_id": f["job_id"]}, minutes=1, priority=30)
            else:
                with db.session() as s:
                    app = s.get(Application, f["application_id"])
                    if app is None:
                        continue
                    title = f"{app.job.company} · {app.job.title}" if app.job is not None else ""
                    last = s.query(Task).filter(Task.kind == "apply", Task.ref == f"job:{app.job_id}").order_by(Task.id.desc()).first()
                    why = ""
                    if what == "waits_for_nothing":
                        why = str(f.get("reason") or "")
                    elif last is not None and last.status == "failed" and last.error:
                        # (in words, and as it was: the words alone are sometimes "this step did not finish")
                        why = str(humanize.explain(last.error).get("message") or "").strip() + "（" + last.error.splitlines()[0][:200] + "）"
                    why = (why or app.last_event or "")[:600]
                    if what == "worked_by_nothing" and last is not None and last.status == "failed" and not int((last.payload or {}).get("_chain_retries", 0)):
                        # Its task ended in an error - the program's, not a verdict of the agent's on the application
                        # (that is a task that ended well, with "cannot"). It is taken up once more by itself before
                        # the applicant is asked to press anything.
                        tasks.enqueue("apply", ref=f"job:{app.job_id}", payload={"job_id": app.job_id, "_chain_retries": 1}, priority=last.priority)
                        done.append({**f, "did": "queued again"})
                        continue
                    if what == "question_without_card":
                        n = len(app.drafts[-1].unresolved or [])
                        notify.add_todo("answer", title, body=T("server.chain.questionSForYou", p0=n), ref=f"draft:{f['draft_id']}", payload={"draft_id": f["draft_id"]}, push=False)
                    elif what == "asks_nothing":
                        latest = app.drafts[-1] if app.drafts else None
                        lifecycle.move(app, "draft_ready" if latest is not None and latest.review_status == "pending" else "failed", source="recover")
                    elif what == "waits_for_nothing":
                        # The need is still there (the run stopped for it), the card is not: said again, on a card that
                        # takes the application up when the applicant is ready.
                        ref = f"application:{app.id}:resume"
                        t = s.get(Task, f["task_id"])
                        t.payload = {**(t.payload or {}), "waits_for": ref}
                        notify.add_todo("resume", title, body=why or T("server.chain.thisApplicationStoppedAt"), ref=ref, payload={"application_id": app.id, "job_id": app.job_id, "need": "confirm"}, push=False)
                    else:      # worked_by_nothing, ready_without_record, nothing_to_press: it did not get done, and nothing will try again by itself
                        if app.status != "failed":
                            lifecycle.move(app, "failed", source="recover")
                        app.last_event = (why or T("server.chain.thisApplicationStoppedHalf"))[:300]
                        notify.add_todo("failed", T("server.chain.couldNotBeDone", p0=title), body=why or T("server.chain.thisApplicationStoppedHalf2"), ref=f"application:{app.id}",
                                        payload={"application_id": app.id, "job_id": app.job_id}, push=False)
            done.append(f)
        except Exception:  # noqa: BLE001 - one application that cannot be put right does not stop the others
            log.exception("could not mend %s", f)
    try:      # (and the other way round: work that is queued for something nothing waits for any more)
        from . import mail

        mail.drop_needless_looks()
    except Exception:  # noqa: BLE001
        log.exception("could not drop looks for confirmations that are not needed")
    if done:
        log.info("the chain was mended in %d place(s): %s", len(done), ", ".join(sorted({d['what'] for d in done})))
    return done

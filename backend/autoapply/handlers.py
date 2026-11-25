"""Task handlers: the glue between the queue and the modules."""

from __future__ import annotations

from .say import say as T

from typing import Any

from . import db, discover, knowledge, lifecycle, mail, messages, notify, profile_init, scoring, tasks
from .errors import NeedsHuman
from .models import Application, Task
from .tasks import asked_again, enqueue, handler


@handler("discover")
def _discover(t: Task) -> dict[str, Any]:
    return discover.run()


@handler("profile_init")
def _profile_init(t: Task) -> dict[str, Any]:
    try:
        return profile_init.run(str(t.payload.get("notes") or ""))
    except Exception:
        profile_init.failed()
        raise


@handler("score")
def _score(t: Task) -> dict[str, Any]:
    if scoring.nobody_to_score_for():       # (said on a card; scoring is queued again when the profile is there)
        return {"waits_for_profile": True}
    if t.payload.get("job_id"):
        out = scoring.score_job(int(t.payload["job_id"]))
        return out or {"skipped": "no description"}
    out = scoring.score_pending()
    if out.get("remaining"):  # the per-run cap keeps one task short; the rest follows at once - or, after the model ran out, in a while
        tasks.enqueue_later("score", ref="unscored", minutes=30 if out.get("stopped") else 1, priority=150)
    return out


@handler("directions")
def _directions(t: Task) -> dict[str, Any]:
    """Postings labelled before the fixed list of fields (or by a table brought in): sorted into it by the model."""
    from . import directions

    out = directions.sort_unsorted()
    if out["left"] and out["sorted"]:      # (on to the rest; a round that sorted nothing is not repeated at once)
        tasks.enqueue_later("directions", ref="unsorted", minutes=1, priority=180)
    return out


@handler("apply")
def _apply(t: Task) -> dict[str, Any]:
    """One application, worked by the agent from the posting to the confirmation - or as far as this run gets
    (agent/work.py). Whatever started it - a posting that scored well, the applicant's "apply", their answer to a
    question, their approval, their note on the record - it is the same task: the agent reads where the application
    stands and goes on from there."""
    from .agent import work

    if knowledge.blank():
        # Nothing is known about the applicant: every question of the form would come back unanswered, after minutes
        # at the employer's site. The task waits for the profile - which may be on its way (written from the résumé
        # just uploaded) - and goes on by itself when it is there (profile_init.arrived).
        raise NeedsHuman(T("server.handlers.yourProfileIsStill"), kind="profile", waits_for=profile_init.wanted())
    return work.work(int(t.payload["job_id"]), task_id=t.id, instructions=str(t.payload.get("instructions") or ""))


@handler("mail_reply")
def _mail_reply(t: Task) -> dict[str, Any]:
    """Write the reply to an employer's mail that asks the applicant something (outbox.draft_reply)."""
    from . import outbox

    return outbox.draft_reply(int(t.payload["todo_id"]))


@handler("cover_letter")
def _cover_letter(t: Task) -> dict[str, Any]:
    from . import materials
    from .models import Job

    job_id = int(t.payload["job_id"])
    doc = materials.existing_cover_letter(job_id)
    key = t.payload["request_key"]
    if not doc or doc.get("request_key") != key:
        with db.session() as session:
            job = session.get(Job, job_id)
            session.expunge(job)
        doc = materials.make_cover_letter(job, instructions=t.payload.get("instructions", ""), request_key=key)
    return {"document_id": doc["id"]}


@handler("tailor")
def _tailor(t: Task) -> dict[str, Any]:
    """Write (or rewrite) the tailored résumé for one job."""
    from . import tailor
    from .models import Job

    job_id = int(t.payload["job_id"])
    with db.session() as s:
        job = s.get(Job, job_id)
        s.expunge(job)
    doc = tailor.make(job, instructions=t.payload.get("instructions", ""))
    info = doc["tailor"]
    notify.send("task_result", messages.tailored(f"{job.company} · {job.title}", focus=info["focus"], problems=info["problems"]), ref=f"job:{job_id}")
    # (one that passed is among the files of the agent's next run on this application, and the run is told to use it: agent/work.py)
    return {"document_id": doc["id"], "changes": len(info["changes"]), "current": bool(doc["current"]), "problems": info["problems"]}


@handler("mail")
def _mail(t: Task) -> dict[str, Any]:
    if t.ref.startswith("confirm:") and t.ref[8:].isdigit():      # a look for one application's confirmation: only while it is waited for
        from .models import SENT, UNKNOWN, Application

        with db.session() as s:
            app = s.get(Application, int(t.ref[8:]))
            if app is None or app.status not in ("submitted", UNKNOWN):
                return {"skipped": "the application is confirmed already"}
    try:
        out = mail.track(days=int(t.payload.get("days", 3)), quick=bool(t.payload.get("quick")))
        if out.get("skipped"):
            return out
        fixed = mail.reconcile()      # a confirmation read while the application was taken for unsent
        return {**out, "status_updates": out["status_updates"] + fixed} if fixed else out
    except mail.MailNotConfigured as e:
        return {"skipped": str(e)}
    except Exception as e:
        if not mail.no_answer(e):
            raise
        from . import net

        how = net.describe()["in_effect"] or "a direct connection"
        raise mail.GmailUnreachable(f"cannot reach Gmail through {how}: {type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}") from e


@handler("site_status")
def _site_status(t: Task) -> dict[str, Any]:
    """An e-mail that names no posting: read the employer's own list of the applicant's applications to tell which it is."""
    from . import sitestatus

    return sitestatus.resolve(str(t.payload["message_id"]))


def resume_waiting(*handled: str) -> int:
    """The applicant has dealt with something: put the tasks that waited for it back in the queue.

    ``handled``: what was dealt with, as the cards are filed ("account:idp:google", "job:718"). A task is resumed when
    that is what it waited for - or when it is not known what it waited for (tasks from before this was recorded).
    Signing in to Google no longer sends the tasks that wait for the university portal off to fail again.
    Without ``handled``, every waiting task is resumed (the applicant says: try them all again)."""
    from .models import Job

    n = 0
    with db.session() as s:
        again: set[int] = set()
        every = not handled
        for t in s.query(Task).filter_by(status="waiting_human"):
            waits = str((t.payload or {}).get("waits_for") or "")
            if not every and waits and waits not in handled:
                continue
            t.status, t.error = "queued", ""
            asked_again(t)      # (the applicant dealt with what it waited for: it is theirs from here)
            n += 1
            kind, _, num = t.ref.partition(":")
            if kind == "application" and num.split(":")[0].isdigit():
                again.add(int(num.split(":")[0]))
            elif kind == "job" and num.isdigit():
                j = s.get(Job, int(num))
                if j is not None and j.application is not None:
                    again.add(j.application.id)
        for a in s.query(Application).filter_by(status="needs_human"):
            if every or a.id in again:
                lifecycle.move(a, "approved" if any(d.review_status == "approved" for d in a.drafts) else "recon", source="resume")
    if n:
        from . import tasks

        tasks._wake.set()
    return n


__all__ = ["enqueue", "resume_waiting"]

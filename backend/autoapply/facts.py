"""The applicant changed something about themselves: what is prepared and not sent yet may still say the old thing.

An application's record says, for every answer, what it rests on ("profile: Earliest start", "the résumé"). When the
profile is saved, the lines that changed or went are compared with the records of the applications that are not sent
yet: an answer that names a changed line, or that holds the old value, is affected. Those applications stop where they
are - a record that was approved goes back to waiting for approval, its queued work is put aside - and one card says
what changed and which answers rest on it. The applicant decides, for each: prepare it again with the new fact, or send
it as it is.

The comparison leans to saying too much: an affected answer that is missed is the old fact sent to an employer; one
that is shown and is not affected costs a press.
"""
from __future__ import annotations

from .say import say as T

import difflib
import logging
import re
from typing import Any

from . import db, lifecycle, notify
from .models import SENT, UNKNOWN, Application, Task, Todo, now

log = logging.getLogger("autoapply.facts")

KIND = "facts_changed"
BULLET = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#+\s*)")


def _fact(line: str) -> tuple[str, str]:
    """(what, value) of a profile line: "- Earliest start: 2027-01-06" -> ("earliest start", "2027-01-06")."""
    text = BULLET.sub("", line).strip()
    key, sep, value = text.partition(":")
    if not sep:
        key, sep, value = text.partition("：")
    return (key.strip().lower(), value.strip()) if sep else ("", text)


def changes(old: str, new: str) -> list[dict[str, str]]:
    """The lines of the profile that changed or went: [{"key", "old", "new"}] (``new`` empty for a line taken out).
    Lines that were only added change nothing already prepared."""
    out: list[dict[str, str]] = []
    a, b = old.splitlines(), new.splitlines()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag not in ("replace", "delete"):
            continue
        gone = [ln for ln in a[i1:i2] if ln.strip() and not ln.lstrip().startswith("#")]
        came = [ln for ln in b[j1:j2] if ln.strip() and not ln.lstrip().startswith("#")]
        by_key = {_fact(ln)[0]: ln for ln in came if _fact(ln)[0]}
        for k, ln in enumerate(gone):
            key, value = _fact(ln)
            to = by_key.get(key) if key else (came[k] if k < len(came) else "")
            if to is not None and to.strip() == ln.strip():
                continue
            out.append({"key": key, "old": value, "new": _fact(to)[1] if to else "", "old_line": ln.strip(), "new_line": (to or "").strip()})
    return out


def _touches(answer: dict[str, Any], change: dict[str, str]) -> bool:
    basis = str(answer.get("basis") or "").lower()
    value = str(answer.get("value") or "").lower() if not isinstance(answer.get("value"), list) else " ".join(map(str, answer["value"])).lower()
    key, old, new = change["key"], change["old"].lower(), change["new"].lower()
    if key and len(key) >= 3 and key in basis:
        return True
    if old and len(old) >= 3 and old in basis:
        return True
    # the relaxed reading: the old value is in what was entered (and the new one is not yet)
    return bool(old) and len(old) >= 4 and old in value and not (new and new in value)


def affected(found: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(not sent, sent): applications whose latest record has an answer resting on a changed line, with those answers."""
    open_, sent = [], []
    with db.session() as s:
        for app in s.query(Application).filter(Application.status != "withdrawn"):
            records = [d for d in app.drafts if d.review_status in ("pending", "approved")] or ([app.drafts[-1]] if app.drafts and app.status in SENT else [])
            if not records:
                continue
            d = records[-1]
            hits = []
            for a in d.answers or []:
                why = [c for c in found if _touches(a, c)]
                if why:
                    hits.append({"label": str(a.get("label", ""))[:200], "value": str(a.get("value", ""))[:200], "basis": str(a.get("basis", ""))[:200],
                                 "changes": [c["key"] or c["old_line"][:60] for c in why]})
            if not hits:
                continue
            row = {"application_id": app.id, "job_id": app.job_id, "draft_id": d.id, "title": f"{app.job.company} · {app.job.title}" if app.job else "",
                   "status": app.status, "was_approved": d.review_status == "approved", "answers": hits}
            (sent if app.status in SENT or app.status == UNKNOWN else open_).append(row)
    return open_, sent


def _say(change: list[dict[str, str]]) -> str:
    lines = "；".join(T("server.facts.became", p0=c['old_line'], p1=c['new_line']) if c["new_line"] else T("server.facts.removed", p0=c['old_line']) for c in change[:8])
    return (T("server.facts.iHaveJustChanged", p0=lines))


def profile_saved(old: str, new: str) -> int | None:
    """Called when the profile is saved. Stops the applications that would send an old fact and makes the card.
    Returns the card's id, or None when nothing prepared rests on what changed."""
    found = changes(old, new)
    if not found:
        return None
    open_, sent = affected(found)
    if not open_:
        return None
    from .agent import work

    held: dict[int, list[int]] = {}
    for row in open_:
        if work.being_worked(row["job_id"]):
            work.say(row["application_id"], _say(found))      # working now: it hears it with its next action
            row["told_while_working"] = True
            continue
        with db.session() as s:
            app = s.get(Application, row["application_id"])
            d = next((x for x in app.drafts if x.id == row["draft_id"]), None)
            if d is not None and d.review_status == "approved":
                d.review_status, d.approved_at = "pending", None
            if app.status in ("approved", "recon", "revising", "executing") and d is not None:
                lifecycle.move(app, "needs_input" if d.unresolved else "draft_ready", source="user")
            ids = []
            for t in s.query(Task).filter(Task.kind == "apply", Task.ref == f"job:{row['job_id']}", Task.status == "queued"):
                t.status = "held"
                ids.append(t.id)
            held[row["application_id"]] = ids
    titles = "\n".join(T("server.facts.answers", p0=r['title'], p1=len(r['answers'])) for r in open_[:8])
    body = T("server.facts.youChangedLineS", p0=len(found), p1=len(open_), p2=titles)
    tid = notify.add_todo(KIND, T("server.facts.yourProfileChangedSome"), body=body, ref=f"facts:{now().strftime('%Y%m%d%H%M%S')}",
                          payload={"changes": found, "applications": open_, "sent": sent, "held": {str(k): v for k, v in held.items()}})
    log.info("profile change: %d application(s) stopped, %d sent ones use the old value", len(open_), len(sent))
    return tid


def decide(todo_id: int, action: str, application_ids: list[int]) -> dict[str, int]:
    """The applicant's choice for some of the applications on the card: "redo" - prepare again with the new fact (the
    run is told what changed and changes only that); "keep" - send it as it is (an approval it had is given back).
    The card closes when every application on it has been decided."""
    from . import tasks
    from .agent import work

    with db.session() as s:
        t = s.get(Todo, todo_id)
        if t is None or t.kind != KIND or t.status != "open":
            raise ValueError(T("server.facts.thisCardHasAlready"))
        p = dict(t.payload or {})
    rows = {r["application_id"]: r for r in p.get("applications") or []}
    done = set(p.get("decided") or [])
    n = 0
    for app_id in application_ids:
        row = rows.get(int(app_id))
        if row is None or row["application_id"] in done:
            continue
        held = (p.get("held") or {}).get(str(row["application_id"])) or []
        with db.session() as s:
            for task_id in held:
                x = s.get(Task, task_id)
                if x is not None and x.status == "held":
                    x.status = "cancelled"
        if action == "redo":
            work.say(row["application_id"], _say(p.get("changes") or []))
            asked = tasks.by_hand.set(True)
            try:
                tasks.enqueue("apply", ref=f"job:{row['job_id']}", payload={"job_id": row["job_id"], "facts_changed": now().isoformat()}, priority=20)
            finally:
                tasks.by_hand.reset(asked)
        elif action == "keep":
            if row.get("was_approved"):
                from . import drafts

                try:
                    drafts.approve(row["draft_id"])      # (queues the run that sends it, as an approval does)
                except ValueError:
                    pass
            elif held:
                tasks.enqueue("apply", ref=f"job:{row['job_id']}", payload={"job_id": row["job_id"]}, priority=30)
        else:
            raise ValueError("action is redo or keep")
        done.add(row["application_id"])
        n += 1
    with db.session() as s:
        t = s.get(Todo, todo_id)
        t.payload = {**p, "decided": sorted(done)}
        if all(r["application_id"] in done for r in rows.values()):
            t.status, t.done_at = "done", now()
    return {"decided": n, "left": len(rows) - len(done)}

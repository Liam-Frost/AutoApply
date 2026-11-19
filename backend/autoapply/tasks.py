"""In-process task queue (one SQLite table) and scheduler. No Celery, no Redis.

A single worker thread pulls queued tasks by priority. Browser work is
serialised by design: one task at a time.
"""

from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from datetime import timezone
import traceback
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler

from . import db, llm, metering, notify
from .errors import NeedsHuman, unreachable
from .models import Run, Task, now

log = logging.getLogger("autoapply.tasks")

_handlers: dict[str, Callable[[Task], dict[str, Any]]] = {}
_wake = threading.Event()
_stop = threading.Event()
_worker: threading.Thread | None = None
_sched: BackgroundScheduler | None = None


def handler(kind: str):
    def deco(fn: Callable[[Task], dict[str, Any]]):
        _handlers[kind] = fn
        return fn

    return deco


def deadline_priority(deadline: str) -> int:
    """Earlier deadlines run first. Priority = hours until the deadline (min 0)."""
    try:
        dt = datetime.strptime(deadline[:16], "%Y-%m-%d %H:%M")
        return max(0, int((dt - datetime.now()).total_seconds() // 3600))
    except (ValueError, TypeError):
        return 500


# Is this being done because the applicant asked for it just now (a request to the program's own page), or by the
# program itself (the clock, one task leading to the next, a retry)? Set by the API for every request that changes
# something; read here when a task is queued. It decides what "pause" stops: what the program does by itself.
by_hand: ContextVar[bool] = ContextVar("by_hand", default=False)


def _asked(payload: dict[str, Any] | None) -> dict[str, Any]:
    """What a request asks for: its payload without the queue's own notes (``_delay``, the retry counts, who asked) and
    without what is empty ("no instructions" is the same request as none given)."""
    return {k: v for k, v in (payload or {}).items() if not k.startswith("_") and v not in (None, "", [], {})}


def asked_again(t: Task) -> None:
    """An existing task goes back into the queue because the applicant said so - a card marked done, "retry", "take it
    up", "do it first": it is theirs from here, as if they had just asked for it. (``enqueue`` marks the tasks it makes;
    a row that is already there was left as the program's, so a sign-in that was held back for the quiet hours was
    held back again the moment the applicant said "go ahead", and was not taken at all while paused.)"""
    if by_hand.get() and not (t.payload or {}).get("_by_hand"):
        t.payload = {**(t.payload or {}), "_by_hand": True}


def enqueue(kind: str, *, ref: str = "", payload: dict[str, Any] | None = None, priority: int = 100, dedupe: bool = True) -> int:
    """Queue work. The same work (kind and ref) that is already in the queue is not queued a second time - and what is
    asked for now is what gets done:

    - it waits (also: for a later time, a retry in half an hour): that task takes what this request says - the comment
      that was just written, not the one from before - and is taken forward if it was put off;
    - it is being done this moment, and this request says something else: a task of its own, after that one. The one
      that is running cannot be told anything any more, and answering "queued" for a request that nothing will carry
      out is not an answer."""
    if by_hand.get():
        payload = {**(payload or {}), "_by_hand": True}
    with db.session() as s:
        if dedupe and ref:
            ex = s.query(Task).filter(Task.kind == kind, Task.ref == ref, Task.status.in_(("queued", "running"))).order_by(Task.due_at.isnot(None), Task.id).first()
            if ex is None:
                # The same work was put aside by the applicant ("not now"). Asked for by the program - the timer that
                # reads on, the scan - it stays put aside: a second task would do what was set aside while the first
                # still says "held". Asked for by the applicant, it is taken up.
                held = s.query(Task).filter(Task.kind == kind, Task.ref == ref, Task.status == "held").order_by(Task.id).first()
                if held is not None:
                    if by_hand.get():
                        held.status, held.payload = "queued", {**(held.payload or {}), **(payload or {})}
                        _wake.set()
                    return held.id
            if ex and ex.status == "queued":
                if _asked(payload) != _asked(ex.payload):
                    ex.payload = {**(ex.payload or {}), **(payload or {})}
                if by_hand.get() and not (ex.payload or {}).get("_by_hand"):
                    ex.payload = {**(ex.payload or {}), "_by_hand": True}       # the applicant asks for it now: it is theirs from here
                if ex.due_at is not None:
                    # the same work is waiting for a later time and is wanted now: it is taken forward, not queued a
                    # second time - and not left to wait while the caller thinks it runs
                    ex.due_at, ex.priority = None, min(ex.priority, priority)
                    _wake.set()
                return ex.id
            if ex and _asked(payload) == _asked(ex.payload):
                return ex.id
        t = Task(kind=kind, ref=ref, payload=payload or {}, priority=priority)
        s.add(t)
        s.flush()
        tid = t.id
    _wake.set()
    return tid


# Three kinds of worker. One kind works applications - each a browser, a site, an account: as many at a time as the
# applicant has set (agent.parallel; three unless they say otherwise), never two on the same application and never
# two on the same site (an account and its sign-in are one). One does what needs none of that and can take long:
# scanning the sources, scoring, reading mail. A scan of twenty minutes used to hold every application up; now they
# do not wait for each other. The third is the desk: writing the applicant asked for at a page and is waiting to see -
# their profile, from the résumé they just uploaded. The last two: one task at a time.
BACKGROUND = ("discover", "score", "mail")
DESK = ("profile_init",)
LANES = ("forms", "background", "desk")
MOST = 6       # the most applications that can be worked at once, whatever is set
_claiming = threading.Lock()      # (several workers look at the same queue: one takes a task at a time)


def parallel() -> int:
    """How many applications are worked at the same time (the setting agent.parallel)."""
    try:
        return max(1, min(int(db.get_setting("agent.parallel") or 3), MOST))
    except (TypeError, ValueError):
        return 3


def _site(s: Any, t: Task) -> str:
    """The site an application's task works on ('' for a task that is not an application's)."""
    from . import sites
    from .models import Job

    if t.kind != "apply" or not t.ref.startswith("job:") or not t.ref[4:].isdigit():
        return ""
    job = s.get(Job, int(t.ref[4:]))
    # (the key its account and its saved sign-in are kept under: two addresses that turned out to sign in on the same one are one site here)
    return sites.account(sites.key_of(job.apply_url)) if job is not None and job.apply_url else ""


def lane_of(kind: str) -> str:
    return "background" if kind in BACKGROUND else "desk" if kind in DESK else "forms"


def _claim(lane: str = "", *, only_by_hand: bool = False) -> Task | None:
    with _claiming, db.session() as s:
        q = s.query(Task).filter_by(status="queued")
        if lane == "background":
            q = q.filter(Task.kind.in_(BACKGROUND))
        elif lane == "desk":
            q = q.filter(Task.kind.in_(DESK))
        elif lane == "forms":
            q = q.filter(Task.kind.notin_(BACKGROUND + DESK))
        # a task that is for later (a retry, a look for the confirmation mail in half an hour) is not taken before its time
        due = q.filter((Task.due_at.is_(None)) | (Task.due_at <= now())).order_by(Task.priority, Task.id)
        # paused: only what the applicant asked for by hand (they pressed the button; the pause is for what runs by itself)
        if lane == "forms":
            # not the application another worker is on, and not another application on the site one is on
            busy = s.query(Task).filter(Task.status == "running", Task.kind.notin_(BACKGROUND + DESK)).all()
            refs, on = {b.ref for b in busy}, {_site(s, b) for b in busy} - {""}
            t = next((x for x in due.limit(200) if (not only_by_hand or (x.payload or {}).get("_by_hand")) and x.ref not in refs and (_site(s, x) or None) not in on), None)
        else:
            t = next((x for x in due.limit(200) if (x.payload or {}).get("_by_hand")), None) if only_by_hand else due.first()
        if t is None:
            return None
        t.status, t.started_at, t.attempts = "running", now(), t.attempts + 1
        s.flush()
        s.expunge(t)
        return t


# What the running task was started by. The task's, on every thread that does a part of it (context.py).
_started_by_hand: ContextVar[bool] = ContextVar("task_by_hand", default=False)


def running_by_hand() -> bool:
    """Is the task that is running here one the applicant asked for (so that they are at the program now)? False for
    what the program does by itself - and outside any task."""
    return _started_by_hand.get()


def run_one(t: Task) -> None:
    token = _started_by_hand.set(bool((t.payload or {}).get("_by_hand")))
    try:
        _run_one(t)
    finally:
        _started_by_hand.reset(token)


def _run_one(t: Task) -> None:
    fn = _handlers.get(t.kind)
    usage = llm.reset_usage()
    metering.begin_task(t.id, t.kind, t.ref)     # every model request until the task ends belongs to it
    status, result, error, waits_for = "done", {}, "", ""
    try:
        if fn is None:
            raise KeyError(f"no handler for task kind {t.kind}")
        from .browser_policy import task_backend
        with task_backend(t.payload.get("browser_backend")):
            result = fn(t) or {}
    except NeedsHuman as e:
        status, error = "waiting_human", e.reason
        waits_for = getattr(e, "waits_for", "")
    except llm.LLMUnavailable as e:
        status, error = "failed", str(e)
        if "usage limit" in str(e).lower():
            # The subscription's quota is used up for now. Try again later instead of dropping the work.
            notify.add_todo("config", "AI 服务的额度暂时用完" + ("（备用的也都试过了）" if "所有配置的 AI 服务" in str(e) else ""), ref="config:llm-limit",
                            body=f"{str(e)[:200]}\n需要模型的任务会每 30 分钟自动重试一次，额度恢复后继续；不需要你操作。")
            if t.kind in ("apply", "score") and int(t.payload.get("_limit_retries", 0)) < 12:
                enqueue_later(t.kind, ref=t.ref, payload={**t.payload, "_limit_retries": int(t.payload.get("_limit_retries", 0)) + 1}, minutes=30, priority=t.priority)
        else:
            notify.add_todo("config", "AI 模型不可用", body=str(e), ref="config:llm")
    except Exception as e:  # noqa: BLE001
        if unreachable(e):
            # The employer's site is not answering - an error page, or no answer at all from its address (a connection
            # that timed out is the same thing, wherever in the run it happened). Try again later; nobody needs to do
            # anything. The first time soon: a network that dropped for a moment is back in minutes.
            n = int(t.payload.get("_down_retries", 0))
            again, wait = t.kind == "apply" and n < 6, 5 if n == 0 else 30
            status, error = "failed", f"网站暂时打不开：{str(e).splitlines()[0][:200]}" + (f"；{wait} 分钟后自动重试" if again else "")
            log.warning("task %s (%s): the site did not answer: %s", t.id, t.kind, str(e).splitlines()[0][:200])
            if again:
                enqueue_later(t.kind, ref=t.ref, payload={**t.payload, "_down_retries": n + 1}, minutes=wait, priority=t.priority)
        else:
            status, error = "failed", f"{type(e).__name__}: {e}"
            log.error("task %s (%s) failed: %s\n%s", t.id, t.kind, error, traceback.format_exc())
            if t.kind == "apply":  # an application the applicant waits for: say why it failed
                from . import messages

                notify.send("task_result", messages.task_failed(t.kind, error), ref=t.ref)
    stages = metering.end_task()
    with db.session() as s:
        row = s.get(Task, t.id)
        row.status, row.result, row.error, row.finished_at = status, result, error, now()
        if status == "waiting_human":      # what it waits for: handlers.resume_waiting() puts it back when that is dealt with
            row.payload = {**(row.payload or {}), "waits_for": waits_for}
        row.stages = stages
        if usage.calls:
            s.add(Run(task_id=t.id, kind="llm", ref=t.ref, ok=int(status == "done"), llm_calls=usage.calls,
                      input_tokens=usage.input_tokens, output_tokens=usage.output_tokens))
    if waits_for or result.get("waits_for_profile"):       # (what it waits for may have come while it was finding it missing)
        from . import profile_init

        profile_init.began_to_wait(status, waits_for, result)


def _loop(lane: str = "", nth: int = 0) -> None:
    """``nth``: which of the workers of this lane this is (from 0). One beyond the number set takes nothing."""
    while not _stop.is_set():
        if nth and nth >= parallel():
            _stop.wait(5)
            continue
        if db.get_setting("schedule.draining"):
            # "finish what is being done and start nothing new": nothing is claimed; when the last task has ended, say so once
            _tell_when_drained()
            _stop.wait(2)
            continue
        t = _claim(lane, only_by_hand=bool(db.get_setting("schedule.paused")))
        if t is None:
            _wake.wait(2)       # (two workers share the signal: neither clears it for the other, both look again shortly)
            _wake.clear()
            continue
        run_one(t)


def _tell_when_drained() -> None:
    if db.get_setting("schedule.drain_told"):
        return
    with db.session() as s:
        if s.query(Task).filter_by(status="running").count():
            return
    db.set_setting("schedule.drain_told", True)
    from . import messages

    try:
        notify.send("task_result", messages.drained(), ref="queue")
    except Exception:  # noqa: BLE001 - it is said on the page as well
        log.exception("could not say that the queue has stopped")


def set_draining(on: bool) -> dict[str, Any]:
    """Finish what is being done, start nothing new, and say when it has stopped - for closing or restarting the
    program without cutting a form off halfway. Off: the queue goes on."""
    db.set_setting("schedule.drain_told", False)
    db.set_setting("schedule.draining", bool(on))
    if on:
        _tell_when_drained()        # nothing may be running at all: then it is said at once
    _wake.set()
    return {"draining": bool(on), "stopped": bool(on) and bool(db.get_setting("schedule.drain_told"))}


class NotNow(ValueError):
    """What was asked of a task cannot be done in the state it is in (and why, in the applicant's words)."""


def cancel(task_id: int) -> None:
    """Take a task out of the queue: one that has not started, or that waits for the applicant. A task that is running
    is not cut off - a form half filled, a Submit half pressed; it ends at a point where it can, and "finish and stop"
    (set_draining) is the way to have nothing follow it.

    An application whose work is cancelled is not left saying "queued" or "being read" for ever."""
    from . import lifecycle
    from .models import SENT

    undo = None
    with db.session() as s:
        t = s.get(Task, task_id)
        if t is None:
            raise KeyError(task_id)
        if t.status == "running":
            raise NotNow("这个任务正在执行，不能中途取消。想让它做完就停、后面的不再开始，用“做完手上的就停”。")
        if t.status not in ("queued", "waiting_human", "held"):
            raise NotNow("这个任务已经结束了。")
        t.status, t.error, t.finished_at = "cancelled", "你取消了这个任务", now()
        s.flush()
        a = application_of(s, t.ref) if t.kind in lifecycle.WORK else None
        if a is not None and a.status not in SENT:
            refs = {f"application:{a.id}", f"job:{a.job_id}", *(f"draft:{d.id}" for d in a.drafts)}
            more = s.query(Task).filter(Task.kind.in_(lifecycle.WORK), Task.status.in_(("queued", "running", "waiting_human", "held"))).all()
            if not any(x.ref.split(":manual")[0] in refs for x in more):
                if a.status in ("approved", "executing"):
                    if lifecycle.move(a, "failed", source="user"):
                        a.last_event = "你取消了这次填写；草案还在，可以重新开始"
                elif a.status in ("recon", "revising"):
                    pending = [d for d in a.drafts if d.review_status == "pending"]
                    if pending:
                        lifecycle.move(a, "needs_input" if pending[-1].unresolved else "draft_ready", source="user")
                    elif not a.drafts:
                        undo = a.id          # nothing was drafted: the posting goes back to "not applied"
    if undo is not None:
        from . import drafts

        drafts.undo(undo)


def hold(task_id: int) -> None:
    """Set a queued task aside: it keeps its place in the list and is not started until it is taken up again."""
    with db.session() as s:
        t = s.get(Task, task_id)
        if t is None:
            raise KeyError(task_id)
        if t.status != "queued":
            raise NotNow("只有还在排队的任务可以暂缓。")
        t.status = "held"


def take_up(task_id: int) -> None:
    with db.session() as s:
        t = s.get(Task, task_id)
        if t is None:
            raise KeyError(task_id)
        if t.status != "held":
            raise NotNow("这个任务没有被暂缓。")
        t.status = "queued"
        asked_again(t)
    _wake.set()


def first(task_id: int) -> None:
    """Do this one next: ahead of everything else that is queued, and now rather than at the time it was set for."""
    with db.session() as s:
        t = s.get(Task, task_id)
        if t is None:
            raise KeyError(task_id)
        if t.status not in ("queued", "held"):
            raise NotNow("只有还在排队的任务可以提前。")
        lowest = min([x.priority for x in s.query(Task).filter(Task.status == "queued")] or [0])
        t.status, t.priority, t.due_at = "queued", min(lowest, t.priority) - 1, None
        t.payload = {**(t.payload or {}), "_by_hand": True}
    _wake.set()


def plan() -> dict[str, Any]:
    """What the program is doing, what comes next and in which order, what waits for the applicant, what was set aside,
    and what is set for a later time. The order of "next" is the order it will be taken in. No times of completion:
    how long a form takes is not something the program knows."""
    from . import humanize
    from .models import Todo

    def row(t: Task) -> dict[str, Any]:
        return {"id": t.id, "kind": t.kind, "label": humanize.TASK.get(t.kind, t.kind), "subject": humanize.subject(t.ref), "ref": t.ref,
                "status": t.status, "by_hand": bool((t.payload or {}).get("_by_hand")), "lane": lane_of(t.kind),
                "created_at": t.created_at.isoformat() if t.created_at else None, "started_at": t.started_at.isoformat() if t.started_at else None,
                "due_at": t.due_at.isoformat() if t.due_at else None, "why": humanize.explain(t.error)["message"] if t.error else ""}

    paused, draining = bool(db.get_setting("schedule.paused")), bool(db.get_setting("schedule.draining"))
    with db.session() as s:
        at = now()
        queued = s.query(Task).filter_by(status="queued").order_by(Task.priority, Task.id).all()
        is_due = lambda t: t.due_at is None or (t.due_at if t.due_at.tzinfo else t.due_at.replace(tzinfo=timezone.utc)) <= at  # noqa: E731
        nxt = [row(t) for t in queued if is_due(t)]
        for r in nxt:       # what a pause holds back, said per task
            r["held_by_pause"] = paused and not r["by_hand"]
        waiting = []
        cards = {t.ref: t.title for t in s.query(Todo).filter_by(status="open")}
        for t in s.query(Task).filter_by(status="waiting_human").order_by(Task.id.desc()).limit(50):
            r = row(t)
            r["waits_for"] = cards.get(str((t.payload or {}).get("waits_for") or ""), "")
            waiting.append(r)
        return {"running": [row(t) for t in s.query(Task).filter_by(status="running").order_by(Task.started_at)],
                "next": nxt[:60], "next_total": len(nxt),
                "later": sorted((row(t) for t in queued if not is_due(t)), key=lambda r: r["due_at"])[:60],
                "waiting": waiting, "held": [row(t) for t in s.query(Task).filter_by(status="held").order_by(Task.id)],
                "paused": paused, "draining": draining, "stopped": draining and bool(db.get_setting("schedule.drain_told"))}


def drain(max_tasks: int = 100) -> int:
    """Run queued tasks synchronously (tests and CLI)."""
    n = 0
    while n < max_tasks:
        t = _claim()
        if t is None:
            break
        run_one(t)
        n += 1
    return n


def recover() -> None:
    """Tasks left 'running' by a crash go back to the queue once."""
    with db.session() as s:
        for t in s.query(Task).filter_by(status="running"):
            t.status = "queued" if t.attempts < 2 else "failed"
            if t.status == "failed":
                t.error = "interrupted twice"
        s.flush()
        # An application whose filling was cut off and will not be taken up again is not "being filled": say so, so that
        # it can be started again instead of showing "filling in" for ever.
        from .models import Application

        waiting = {t.ref for t in s.query(Task).filter(Task.kind == "apply", Task.status.in_(("queued", "running")))}
        for a in s.query(Application).filter_by(status="executing"):
            if f"job:{a.job_id}" not in waiting:
                from . import lifecycle

                if lifecycle.move(a, "failed", source="recover"):
                    a.last_event = "填写被中断（程序在填写途中被关闭），可以重新开始"


class NothingToRetry(ValueError):
    """The task is about an application that has gone out: there is nothing to do again."""


def application_of(s: Any, ref: str) -> Any:
    """The application a task works on, from what the task is filed under ("application:12", "draft:40", "job:7")."""
    from .models import Application, Draft, Job

    kind, _, num = (ref or "").partition(":")
    num = num.split(":")[0]
    if not num.isdigit():
        return None
    if kind == "application":
        return s.get(Application, int(num))
    if kind == "draft":
        d = s.get(Draft, int(num))
        return d.application if d is not None else None
    if kind == "job":
        j = s.get(Job, int(num))
        return j.application if j is not None else None
    return None


def may_retry(s: Any, t: Task) -> None:
    """Work on an application's form is not done again for an application that has gone out (a task from before it was
    sent, retried from the list of what has run), nor for one whose submission has an unknown outcome. Raises
    NothingToRetry."""
    from . import lifecycle

    if t.kind in lifecycle.WORK:
        why = lifecycle.closed_to_work(application_of(s, t.ref))
        if why:
            raise NothingToRetry(why)


def retry(task_id: int) -> None:
    with db.session() as s:
        t = s.get(Task, task_id)
        may_retry(s, t)
        t.status, t.error = "queued", ""
        asked_again(t)
    _wake.set()


def start() -> None:
    global _worker, _sched
    from . import handlers  # noqa: F401  (registers task handlers)

    recover()
    # "finish and stop" was for closing the program: it has been started again
    db.set_setting("schedule.draining", False)
    db.set_setting("schedule.drain_told", False)
    try:  # postings left unscored by an interrupted or capped run are picked up again at start-up and by the hourly check
        from . import scoring

        if scoring.unscored_count() and not scoring.nobody_to_score_for(quiet=True):
            enqueue("score", ref="unscored", priority=150)
    except Exception:  # noqa: BLE001
        pass
    _stop.clear()
    _worker = threading.Thread(target=_loop, args=("forms",), name="autoapply-worker", daemon=True)
    _worker.start()
    for nth in range(1, MOST):      # (they are all there; how many take work is the setting, read as they go)
        threading.Thread(target=_loop, args=("forms", nth), name=f"autoapply-worker-{nth + 1}", daemon=True).start()
    threading.Thread(target=_loop, args=("background",), name="autoapply-background", daemon=True).start()
    threading.Thread(target=_loop, args=("desk",), name="autoapply-desk", daemon=True).start()
    _sched = BackgroundScheduler(daemon=True)
    _schedule_jobs()
    _sched.start()


def _mail_new() -> None:
    """Every couple of minutes: was anything added to the inbox? Asked here, without a task - the answer is nearly
    always "no", and a task every two minutes would bury the activity record. Only when something arrived is a task
    queued to read it."""
    from . import mail, mailbox

    try:
        if db.get_setting("schedule.paused") or not mailbox.incremental():
            return
        if mail.anything_new():
            enqueue("mail", ref="new", payload={"quick": True}, priority=50)
    except Exception as e:  # noqa: BLE001 - the network is down, the sign-in has run out: the hourly pass reports that
        log.info("could not ask the mailbox what is new (%s)", type(e).__name__)


PERIODIC = ("discover", "mail", "mail_new", "upkeep", "unscored", "quota")      # what the clock starts by itself


def _schedule_jobs() -> None:
    assert _sched is not None
    for job in _sched.get_jobs():
        if job.id in PERIODIC:      # only what is set up below; nothing else that waits for its time is this function's to drop
            job.remove()
    plan = {
        "discover": ("schedule.discover_minutes", lambda: enqueue("discover", ref="schedule", priority=200)),
        "mail": ("schedule.mail_minutes", lambda: enqueue("mail", ref="schedule", priority=50)),
        # between the passes over the last days: only what arrived since the last look (one small request, usually "nothing")
        "mail_new": ("schedule.mail_new_minutes", _mail_new),
    }
    from datetime import datetime, timedelta

    for name, (key, fn) in plan.items():
        minutes = int(db.get_setting(key) or 0)
        if minutes > 0:
            # Counted from the last time it ran, not from the start of the program: an interval of twelve hours never
            # came round on a program that is restarted or closed more often than that - the scan simply never ran.
            last = last_run(name)
            due = (minutes * 60 - (datetime.now(timezone.utc) - last).total_seconds()) if last else 0
            _sched.add_job(fn, "interval", minutes=minutes, id=name, replace_existing=True, next_run_time=datetime.now() + timedelta(seconds=max(120, due)))

    def upkeep() -> None:
        """What should happen by itself between the big runs: postings that have come to qualify are applied for."""
        try:
            from . import scoring

            scoring.queue_qualifying()
        except Exception:  # noqa: BLE001
            log.exception("upkeep failed")
        try:      # what is due tomorrow and today, cards put off until now, contacts to get back to, notices held for the night
            from . import reminders

            reminders.check()
        except Exception:  # noqa: BLE001
            log.exception("reminders failed")

    _sched.add_job(upkeep, "interval", minutes=10, id="upkeep", replace_existing=True, next_run_time=datetime.now() + timedelta(seconds=90))

    def unscored() -> None:  # safety net: nothing that can be scored stays unscored for long, whatever interrupted the last run
        from . import scoring

        if scoring.unscored_count() and not scoring.nobody_to_score_for(quiet=True):
            enqueue("score", ref="unscored", priority=150)

    _sched.add_job(unscored, "interval", minutes=60, id="unscored", replace_existing=True)

    def quota_check() -> None:  # the allowance of the AI services: warn before it runs out, rest a service that is used up
        try:
            from . import quota

            quota.check_all()
        except Exception:  # noqa: BLE001
            log.exception("quota check failed")

    minutes = int(db.get_setting("llm.quota_check_minutes") or 0)
    if minutes > 0:
        _sched.add_job(quota_check, "interval", minutes=minutes, id="quota", replace_existing=True)


SCHEDULED = {"discover": "schedule.discover_minutes", "mail": "schedule.mail_minutes"}


def last_run(kind: str):  # noqa: ANN201
    """When a scheduled kind of task last ran (by the clock or by hand), as an aware UTC time; None if never."""
    with db.session() as s:
        t = s.query(Task).filter(Task.kind == kind, Task.ref.in_(("schedule", "manual"))).order_by(Task.id.desc()).first()
        at = (t.finished_at or t.created_at) if t else None
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) if at else None


def schedule_status() -> list[dict[str, Any]]:
    """The regular jobs: how often, when last, when next - for the page that shows them."""
    out = []
    for kind, key in SCHEDULED.items():
        minutes = int(db.get_setting(key) or 0)
        job = _sched.get_job(kind) if _sched is not None else None
        last = last_run(kind)
        with db.session() as s:
            t = s.query(Task).filter(Task.kind == kind, Task.ref.in_(("schedule", "manual"))).order_by(Task.id.desc()).first()
            state = t.status if t else ""
        out.append({"kind": kind, "setting": key, "minutes": minutes, "last": last.isoformat() if last else None, "last_status": state,
                    "next": job.next_run_time.isoformat() if job is not None and job.next_run_time else None, "paused": bool(db.get_setting("schedule.paused"))})
    return out


def enqueue_later(kind: str, *, ref: str = "", payload: dict | None = None, minutes: float = 5, priority: int = 100) -> int:
    """Queue a task for later (one-off): it is in the queue from now, and not taken before its time.

    It used to be a timer in the program's memory: saving the settings dropped every one of them, and so did a restart -
    the retry of a site that was down, the look for a confirmation mail half an hour after a submission. A row in the
    queue is still there after either. Asking twice for the same work after the same delay moves the one that waits."""
    from datetime import timedelta

    due = now() + timedelta(minutes=float(minutes))
    with db.session() as s:
        for ex in s.query(Task).filter(Task.kind == kind, Task.ref == ref, Task.status == "queued", Task.due_at.isnot(None)):
            if (ex.payload or {}).get("_delay") == float(minutes):
                ex.due_at, ex.payload, ex.priority = due, {**(payload or {}), "_delay": float(minutes)}, priority
                return ex.id
        t = Task(kind=kind, ref=ref, payload={**(payload or {}), "_delay": float(minutes)}, priority=priority, due_at=due)
        s.add(t)
        s.flush()
        return t.id


def reschedule() -> None:
    if _sched is not None:
        _schedule_jobs()


def stop() -> None:
    _stop.set()
    _wake.set()
    if _sched is not None:
        _sched.shutdown(wait=False)

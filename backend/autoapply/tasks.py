"""In-process task queue (one SQLite table) and scheduler. No Celery, no Redis.

A single worker thread pulls queued tasks by priority. Browser work is
serialised by design: one task at a time.
"""

from __future__ import annotations

import logging
import threading
from datetime import timezone
import traceback
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler

from . import db, llm, metering, notify
from .ats.base import NeedsHuman, unreachable
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


def enqueue(kind: str, *, ref: str = "", payload: dict[str, Any] | None = None, priority: int = 100, dedupe: bool = True) -> int:
    with db.session() as s:
        if dedupe and ref:
            ex = s.query(Task).filter(Task.kind == kind, Task.ref == ref, Task.status.in_(("queued", "running"))).first()
            if ex:
                return ex.id
        t = Task(kind=kind, ref=ref, payload=payload or {}, priority=priority)
        s.add(t)
        s.flush()
        tid = t.id
    _wake.set()
    return tid


# Two workers. One fills and reads forms - a browser, a site, an account at a time. The other does what needs none of
# that and can take long: scanning the sources, scoring, reading mail, the self-check, learning from a run. A scan of
# twenty minutes used to hold every application up; now the two do not wait for each other. Within each, one task at
# a time, as before.
BACKGROUND = ("discover", "score", "mail", "canary", "improve")


def _claim(lane: str = "") -> Task | None:
    with db.session() as s:
        q = s.query(Task).filter_by(status="queued")
        if lane == "background":
            q = q.filter(Task.kind.in_(BACKGROUND))
        elif lane == "forms":
            q = q.filter(Task.kind.notin_(BACKGROUND))
        t = q.order_by(Task.priority, Task.id).first()
        if t is None:
            return None
        t.status, t.started_at, t.attempts = "running", now(), t.attempts + 1
        s.flush()
        s.expunge(t)
        return t


def run_one(t: Task) -> None:
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
            if t.kind in ("recon", "revise", "score") and int(t.payload.get("_limit_retries", 0)) < 12:
                enqueue_later(t.kind, ref=t.ref, payload={**t.payload, "_limit_retries": int(t.payload.get("_limit_retries", 0)) + 1}, minutes=30, priority=t.priority)
        else:
            notify.add_todo("config", "AI 模型不可用", body=str(e), ref="config:llm")
    except Exception as e:  # noqa: BLE001
        if unreachable(e):
            # The employer's site is not answering - an error page, or no answer at all from its address (a connection
            # that timed out is the same thing, wherever in the run it happened). Try again later; nobody needs to do
            # anything. The first time soon: a network that dropped for a moment is back in minutes.
            n = int(t.payload.get("_down_retries", 0))
            again, wait = t.kind == "recon" and n < 6, 5 if n == 0 else 30
            status, error = "failed", f"网站暂时打不开：{str(e).splitlines()[0][:200]}" + (f"；{wait} 分钟后自动重试" if again else "")
            log.warning("task %s (%s): the site did not answer: %s", t.id, t.kind, str(e).splitlines()[0][:200])
            if again:
                enqueue_later(t.kind, ref=t.ref, payload={**t.payload, "_down_retries": n + 1}, minutes=wait, priority=t.priority)
        else:
            status, error = "failed", f"{type(e).__name__}: {e}"
            log.error("task %s (%s) failed: %s\n%s", t.id, t.kind, error, traceback.format_exc())
            if t.kind in ("revise", "recon"):  # started by the user from the UI: say why it failed
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


def _loop(lane: str = "") -> None:
    while not _stop.is_set():
        if db.get_setting("schedule.paused"):
            _stop.wait(2)
            continue
        t = _claim(lane)
        if t is None:
            _wake.wait(2)       # (two workers share the signal: neither clears it for the other, both look again shortly)
            _wake.clear()
            continue
        run_one(t)


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

        waiting = {t.ref for t in s.query(Task).filter(Task.kind == "execute", Task.status.in_(("queued", "running")))}
        for a in s.query(Application).filter_by(status="executing"):
            if f"application:{a.id}" not in waiting:
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
    sent, retried from the list of what has run). Raises NothingToRetry."""
    from . import lifecycle

    if t.kind in lifecycle.WORK:
        a = application_of(s, t.ref)
        if lifecycle.is_sent(a):
            raise NothingToRetry(f"这份申请已经是“{lifecycle.LABEL.get(a.status, a.status)}”，没有可以重做的了")


def retry(task_id: int) -> None:
    with db.session() as s:
        t = s.get(Task, task_id)
        may_retry(s, t)
        t.status, t.error = "queued", ""
    _wake.set()


def start() -> None:
    global _worker, _sched
    from . import handlers  # noqa: F401  (registers task handlers)

    recover()
    try:  # what was learned on another version of the program is checked again before it is used
        from . import learned

        learned.recheck_after_upgrade()
    except Exception:  # noqa: BLE001
        log.exception("could not re-check what was learned")
    try:  # postings left unscored by an interrupted or capped run are picked up again at start-up and by the hourly check
        from . import scoring

        if scoring.unscored_count():
            enqueue("score", ref="unscored", priority=150)
    except Exception:  # noqa: BLE001
        pass
    _stop.clear()
    _worker = threading.Thread(target=_loop, args=("forms",), name="autoapply-worker", daemon=True)
    _worker.start()
    threading.Thread(target=_loop, args=("background",), name="autoapply-background", daemon=True).start()
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


def _schedule_jobs() -> None:
    assert _sched is not None
    for job in _sched.get_jobs():
        job.remove()
    plan = {
        "discover": ("schedule.discover_minutes", lambda: enqueue("discover", ref="schedule", priority=200)),
        "mail": ("schedule.mail_minutes", lambda: enqueue("mail", ref="schedule", priority=50)),
        # between the passes over the last days: only what arrived since the last look (one small request, usually "nothing")
        "mail_new": ("schedule.mail_new_minutes", _mail_new),
        "canary": ("schedule.canary_minutes", lambda: enqueue("canary", ref="schedule", priority=900)),
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
        """What should happen by itself between the big runs: drafts whose form still has unread steps are read on, and
        postings that have come to qualify for a draft get one."""
        try:
            from . import drafts, scoring

            drafts.walk_pending()
            scoring.queue_qualifying()
        except Exception:  # noqa: BLE001
            log.exception("upkeep failed")

    _sched.add_job(upkeep, "interval", minutes=10, id="upkeep", replace_existing=True, next_run_time=datetime.now() + timedelta(seconds=90))

    def unscored() -> None:  # safety net: nothing that can be scored stays unscored for long, whatever interrupted the last run
        from . import scoring

        if scoring.unscored_count():
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


SCHEDULED = {"discover": "schedule.discover_minutes", "mail": "schedule.mail_minutes", "canary": "schedule.canary_minutes"}


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


def enqueue_later(kind: str, *, ref: str = "", payload: dict | None = None, minutes: float = 5, priority: int = 100) -> None:
    """Queue a task after a delay (one-off). Falls back to a timer when the scheduler is not running."""
    from datetime import datetime, timedelta

    fn = lambda: enqueue(kind, ref=ref, payload=payload or {}, priority=priority)  # noqa: E731
    if _sched is not None:
        _sched.add_job(fn, "date", run_date=datetime.now() + timedelta(minutes=minutes), id=f"later:{kind}:{ref}:{minutes}", replace_existing=True)
    else:
        t = threading.Timer(minutes * 60, fn)
        t.daemon = True
        t.start()


def reschedule() -> None:
    if _sched is not None:
        _schedule_jobs()


def stop() -> None:
    _stop.set()
    _wake.set()
    if _sched is not None:
        _sched.shutdown(wait=False)

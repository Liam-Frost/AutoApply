"""In-process task queue (one SQLite table) and scheduler. No Celery, no Redis.

A single worker thread pulls queued tasks by priority. Browser work is
serialised by design (executor.concurrency defaults to 1).
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
from .ats.base import NeedsHuman, SiteDown
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


def _claim() -> Task | None:
    with db.session() as s:
        t = s.query(Task).filter_by(status="queued").order_by(Task.priority, Task.id).first()
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
    status, result, error = "done", {}, ""
    try:
        if fn is None:
            raise KeyError(f"no handler for task kind {t.kind}")
        result = fn(t) or {}
    except NeedsHuman as e:
        status, error = "waiting_human", e.reason
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
    except SiteDown as e:
        # The employer's site is not answering. Try again later; nobody needs to do anything.
        n = int(t.payload.get("_down_retries", 0))
        status, error = "failed", f"网站暂时打不开：{e}" + ("；30 分钟后自动重试" if n < 6 and t.kind == "recon" else "")
        if t.kind == "recon" and n < 6:
            enqueue_later(t.kind, ref=t.ref, payload={**t.payload, "_down_retries": n + 1}, minutes=30, priority=t.priority)
    except Exception as e:  # noqa: BLE001
        status, error = "failed", f"{type(e).__name__}: {e}"
        log.error("task %s (%s) failed: %s\n%s", t.id, t.kind, error, traceback.format_exc())
        if t.kind in ("revise", "recon"):  # started by the user from the UI: say why it failed
            from . import messages

            notify.send("task_result", messages.task_failed(t.kind, error), ref=t.ref)
    stages = metering.end_task()
    with db.session() as s:
        row = s.get(Task, t.id)
        row.status, row.result, row.error, row.finished_at = status, result, error, now()
        row.stages = stages
        if usage.calls:
            s.add(Run(task_id=t.id, kind="llm", ref=t.ref, ok=int(status == "done"), llm_calls=usage.calls,
                      input_tokens=usage.input_tokens, output_tokens=usage.output_tokens))


def _loop() -> None:
    while not _stop.is_set():
        if db.get_setting("schedule.paused"):
            _wake.wait(5)
            _wake.clear()
            continue
        t = _claim()
        if t is None:
            _wake.wait(5)
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
                a.status, a.last_event = "failed", "填写被中断（程序在填写途中被关闭），可以重新开始"


def retry(task_id: int) -> None:
    with db.session() as s:
        t = s.get(Task, task_id)
        t.status, t.error = "queued", ""
    _wake.set()


def start() -> None:
    global _worker, _sched
    from . import handlers  # noqa: F401  (registers task handlers)

    recover()
    try:  # postings left unscored by an interrupted or capped run are picked up again at start-up and by the hourly check
        from . import scoring

        if scoring.unscored_count():
            enqueue("score", ref="unscored", priority=150)
    except Exception:  # noqa: BLE001
        pass
    _stop.clear()
    _worker = threading.Thread(target=_loop, name="autoapply-worker", daemon=True)
    _worker.start()
    _sched = BackgroundScheduler(daemon=True)
    _schedule_jobs()
    _sched.start()


def _schedule_jobs() -> None:
    assert _sched is not None
    for job in _sched.get_jobs():
        job.remove()
    plan = {
        "discover": ("schedule.discover_minutes", lambda: enqueue("discover", ref="schedule", priority=200)),
        "mail": ("schedule.mail_minutes", lambda: enqueue("mail", ref="schedule", priority=50)),
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

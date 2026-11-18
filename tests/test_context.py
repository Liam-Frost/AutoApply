"""What a task is goes with every part of its work, on whichever thread does it (autoapply/context.py)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from autoapply import db


def _at_once(n, work, items):
    """Run ``work`` over ``items`` on ``n`` threads that are all inside it at the same time (a real parallel run: the
    first ``n`` wait for each other before any of them goes on)."""
    gate = threading.Barrier(n, timeout=10)
    first = set(items[:n])

    def one(x):
        if x in first:
            gate.wait()
        return work(x)

    from autoapply import context

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(context.carried(one), items))


def test_what_a_task_is_goes_with_each_piece_of_its_work(app_env, monkeypatch):
    """The helper threads of a task were handed its metering record and nothing else - and all of them the same one.

    (F-11: the browser a task was told to use is a context variable; the pool's wrapper carried a thread-local.)"""
    from contextvars import ContextVar

    from autoapply import browser_policy, llm, metering, tasks
    from autoapply.models import Task

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))
    db.set_setting("browser.nodriver_enabled", True)
    seen = []

    def piece(i):
        with metering.call("text", f"feature {i}"):
            mine = dict(metering._ctx())
            time.sleep(0.05)                                   # the others start their calls meanwhile
            still = dict(metering._ctx())
        llm.usage().count(1, 10, 2)
        return {"i": i, "thread": threading.current_thread().name, "browser": browser_policy.select(None, "https://jobs.example.org", "scan"),
                "by_hand": tasks.running_by_hand(), "call": mine["call_id"], "same": mine == still, "feature": mine["call_feature"], "task": mine.get("task_id")}

    def handler(t):
        seen.extend(_at_once(4, piece, list(range(8))))
        return {}

    monkeypatch.setitem(tasks._handlers, "discover", handler)
    with db.session() as s:
        s.add(Task(kind="discover", ref="t", payload={"browser_backend": "nodriver", "_by_hand": True}))
    assert tasks.drain() == 1
    assert len({r["thread"] for r in seen}) == 4 and threading.current_thread().name not in {r["thread"] for r in seen}
    # the browser the task was told to use, and who started it
    assert {(r["browser"].backend, r["browser"].reason) for r in seen} == {("nodriver", "task override")}
    assert all(r["by_hand"] for r in seen)
    # each piece's call is its own: eight calls, eight ids, none overwritten by a neighbour while it ran
    assert len({r["call"] for r in seen}) == 8 and all(r["same"] for r in seen) and all(r["feature"] == f"feature {r['i']}" for r in seen)
    with db.session() as s:
        t = s.query(Task).one()
        # ...and what is the task's as a whole is one thing: its stages, and its own count of model calls
        assert {x["stage"] for x in t.stages} >= {f"feature {i}" for i in range(8)} and all(r["task"] == t.id for r in seen)
    from autoapply.models import Run

    with db.session() as s:
        r = s.query(Run).filter_by(kind="llm").one()
        assert (r.llm_calls, r.input_tokens, r.output_tokens) == (8, 80, 16)
    # nothing of it is left on the thread that ran the task, and a thread that was not given the task knows nothing of it
    assert not tasks.running_by_hand() and "call_id" not in metering._ctx() and browser_policy.select(None, "https://jobs.example.org", "scan").backend == "playwright"
    with browser_policy.task_backend("nodriver"):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(lambda: browser_policy.select(None, "https://jobs.example.org", "scan").backend).result() == "playwright"


def test_which_browser_is_chosen_on_helper_threads_in_the_same_order_as_anywhere(app_env, monkeypatch):
    """What the task says, then the site's own rule, then the rule for the address, then the usual one - in parallel."""
    from contextvars import ContextVar

    from autoapply import browser_policy

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))
    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [{"tenant": "greenhouse:acme", "backend": "nodriver"}, {"domain": "example.com", "backend": "nodriver"},
                                     {"tenant": "lever:beta", "backend": "playwright"}])
    asked = [("greenhouse:acme", "https://plain.example.org/a"), ("lever:beta", "https://jobs.example.com/b"), (None, "https://jobs.example.com/c"),
             (None, "https://plain.example.org/d")] * 2

    def choose(x):
        time.sleep(0.02)
        got = browser_policy.select(x[0], x[1], "scan")
        return got.backend, got.reason

    usual = [("nodriver", "tenant: greenhouse:acme"), ("playwright", "tenant: lever:beta"), ("nodriver", "domain: example.com"), ("playwright", "default")] * 2
    assert _at_once(4, choose, asked) == usual
    with browser_policy.task_backend("playwright"):
        assert set(_at_once(4, choose, asked)) == {("playwright", "task override")}
    with browser_policy.task_backend("nodriver"):
        assert set(_at_once(4, choose, asked)) == {("nodriver", "task override")}
    assert _at_once(4, choose, asked) == usual                 # and it ends with the task


def test_a_scan_told_to_use_the_ordinary_browser_reads_every_listing_in_it(app_env, monkeypatch):
    """"Retry in the ordinary browser" on a scan: the listings are fetched side by side, each on a helper thread."""
    from contextvars import ContextVar

    from autoapply import browser_policy, employers, handlers, tasks  # noqa: F401 - handlers registers the scan
    from autoapply.models import Job, Task

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))
    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("sources.pdportal", False)
    db.set_setting("sources.parallel", 4)
    db.set_setting("intake.enabled", False)
    listed = [{"id": f"e{n}", "name": f"Employer {n}", "kind": "greenhouse", "ref": {"board": f"b{n}"}, "enabled": True} for n in range(4)]
    monkeypatch.setattr(employers, "listing", lambda: listed)
    monkeypatch.setattr(employers, "migrate_legacy", lambda: None)
    gate = threading.Barrier(4, timeout=10)
    used = {}

    def rows_for(e, terms, keep):
        gate.wait()                                           # all four are being read at the same time
        board = e["ref"]["board"]
        got = browser_policy.select(None, f"https://boards.example.org/{board}", "scan")
        used[board] = (got.backend, got.reason, threading.current_thread().name)
        return iter([{"source": "greenhouse", "source_id": f"{board}-1", "title": "Intern", "company": e["name"], "tenant": board,
                      "apply_url": f"https://boards.example.org/{board}/1", "jd_text": "d" * 300}])

    monkeypatch.setattr(employers, "rows_for", rows_for)
    with db.session() as s:
        s.add(Task(kind="discover", ref="scan", payload={"browser_backend": "nodriver"}))
    tasks.drain(max_tasks=1)
    assert {v[:2] for v in used.values()} == {("nodriver", "task override")} and len(used) == 4
    assert len({v[2] for v in used.values()}) == 4 and all(v[2].startswith("source") for v in used.values())
    with db.session() as s:
        assert s.query(Job).count() == 4 and s.query(Task).filter_by(kind="discover").first().status == "done"
    # the next scan, told nothing: the usual browser again
    used.clear()
    gate.reset()
    with db.session() as s:
        s.add(Task(kind="discover", ref="scan", payload={}))
    tasks.drain(max_tasks=1)
    assert {v[:2] for v in used.values()} == {("playwright", "default")}


def test_what_the_helpers_of_a_scoring_run_ask_the_model_is_counted_on_the_task(app_env, monkeypatch):
    """Postings are read by the model several at a time: the task's own count of model calls had none of them."""
    from autoapply import knowledge, llm, metering, scoring, tasks
    from autoapply.models import Job, Run, Task

    knowledge.write("profile", "# Profile\n- Computer Engineering\n")
    knowledge.write("scoring", "# Rules\n")
    with db.session() as s:
        for n in range(6):
            s.add(Job(source="greenhouse", source_id=f"j{n}", title=f"Software Intern {n}", company="Acme", tenant="acme", status="new", jd_text="Build services. " * 30))
    db.set_setting("scoring.parallel", 3)
    gate = threading.Barrier(3, timeout=10)
    calls = []

    def answer(prompt, schema, **kw):
        if len(calls) < 3:
            calls.append(1)
            gate.wait()
        with metering.call("json", "scoring"):
            calls.append(metering._ctx()["call_id"])
            llm.usage().count(1, 100, 10)
        return {"excluded": False, "exclusion_rule": "", "score": 5.0, "direction": "", "reason": "r", "term": "", "months": "", "summary": "s", "brief": ""}

    monkeypatch.setattr(llm, "json", answer)
    monkeypatch.setitem(tasks._handlers, "score", lambda t: scoring.score_pending())
    with db.session() as s:
        s.add(Task(kind="score", ref="all", payload={}))
    tasks.drain(max_tasks=1)
    with db.session() as s:
        t = s.query(Task).filter_by(kind="score").first()
        assert t.status == "done" and t.result["scored"] == 6
        r = s.query(Run).filter_by(kind="llm", task_id=t.id).one()
        assert (r.llm_calls, r.input_tokens, r.output_tokens) == (6, 600, 60)
        assert "scoring" in {x["stage"] for x in t.stages}
    assert len({c for c in calls if c != 1}) == 6


def test_every_pool_and_every_thread_a_request_starts_is_given_the_context():
    """Work handed to another thread takes what it belongs to with it: there is one way of handing it over."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "backend" / "autoapply"
    bare = []
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"pool\.(map|submit)\(([^,)]*)", src):
            if not m.group(2).startswith("context.carried("):
                bare.append(f"{p.name}: {m.group(0)}")
        if p.name == "main.py":            # a thread started while a request is answered goes on with the request's work
            bare += [f"{p.name}: {m.group(0)}" for m in re.finditer(r"threading\.Thread\(target=(?!context\.carried\()[^,)]*", src)]
    assert not bare, bare

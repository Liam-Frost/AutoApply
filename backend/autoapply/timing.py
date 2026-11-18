"""Where the time of a run goes.

A run - filling one application's form - is a sequence of things that each take time: a page loading, the program
setting a field, the AI thinking, a tool the AI called, a person at a window. Each is recorded here as a span with
its kind, so that afterwards three questions have answers: where did this run spend its time, which of it is the
program's to improve, and has it got better (improve.py asks them; the analysis page shows them).

    kind     what the time was spent on                         whose it is
    site     the site answering: a page loading, a wait for it   the site's - can only be waited out better
    driver   the program working the form: one field, one step  the program's
    ai       a request to the model                              the model's - fewer requests is the lever
    tool     a tool the AI called, by name                       the program's (the tool), the AI's (calling it)
    human    waiting for the applicant                           nobody's: never counted against a run

The recorder belongs to the thread that runs the task, like metering.py's: code anywhere under the run calls span()
or mark() and need not be handed anything. Without a run in progress they do nothing.

A span: {"k": kind, "n": name, "t": ms since the run began, "ms": how long, ...small extras (page, label, ok, rev)}.
Never an answer, never a value from a form: names of steps, tools and fields only.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Any, Iterator

KINDS = ("site", "driver", "ai", "tool", "human")
LIMIT = 800                 # spans kept per run: a run that loops must not fill the database
_tls = threading.local()


def begin() -> None:
    """A run starts in this thread."""
    _tls.run = {"t0": time.monotonic(), "spans": [], "dropped": 0}


def active() -> bool:
    return getattr(_tls, "run", None) is not None


def end() -> list[dict[str, Any]]:
    """The run is over: its spans, in the order they began."""
    run = getattr(_tls, "run", None)
    _tls.run = None
    if run is None:
        return []
    spans = sorted(run["spans"], key=lambda s: s["t"])
    if run["dropped"]:
        spans.append({"k": "driver", "n": "(not recorded)", "t": spans[-1]["t"] if spans else 0, "ms": 0, "count": run["dropped"]})
    return spans


def mark(kind: str, name: str, ms: float, *, started: float | None = None, **extra: Any) -> None:
    """Record something that took ``ms`` and has just ended (or began at monotonic time ``started``)."""
    run = getattr(_tls, "run", None)
    if run is None or kind not in KINDS:
        return
    if len(run["spans"]) >= LIMIT:
        run["dropped"] += 1
        return
    begun = started if started is not None else time.monotonic() - ms / 1000.0
    span = {"k": kind, "n": str(name)[:80], "t": max(0, int((begun - run["t0"]) * 1000)), "ms": max(0, int(ms))}
    for key, value in extra.items():
        if value not in (None, "", [], {}):
            span[key] = value if isinstance(value, (int, float, bool)) else str(value)[:120]
    run["spans"].append(span)


def inside(started: float) -> float:
    """Milliseconds already recorded for the stretch that began at monotonic time ``started``: the fields, requests,
    tools, loads and waits that happened in it. A step is recorded as what is left of its stretch (see the executor),
    so that summing the spans of a run gives the run's time once, not the inner parts twice."""
    run = getattr(_tls, "run", None)
    if run is None:
        return 0.0
    since = int((started - run["t0"]) * 1000) - 1
    return float(sum(s["ms"] for s in run["spans"] if s["t"] >= since and not str(s["n"]).startswith("step:")))


@contextlib.contextmanager
def span(kind: str, name: str, **extra: Any) -> Iterator[dict[str, Any]]:
    """Time what happens inside. The dictionary given can be added to (ok=False, a count) before it ends."""
    more: dict[str, Any] = {}
    began = time.monotonic()
    try:
        yield more
    except BaseException:
        more.setdefault("ok", False)
        raise
    finally:
        mark(kind, name, (time.monotonic() - began) * 1000.0, started=began, **{**extra, **more})


def timed_goto(page: Any) -> None:
    """Make a page record how long the site takes to answer each time it is sent somewhere."""
    if not active() or getattr(page, "_timed", False):
        return
    goto = page.goto

    def recording(url: str, *a: Any, **kw: Any) -> Any:
        from urllib.parse import urlparse

        with span("site", "load", host=urlparse(str(url)).netloc):
            return goto(url, *a, **kw)

    try:
        page.goto = recording
        page._timed = True
    except Exception:  # noqa: BLE001 - a page object that will not take it is simply not timed
        pass


# --- reading spans ------------------------------------------------------------------------------------------


def totals(spans: list[dict[str, Any]]) -> dict[str, int]:
    """Milliseconds by kind. Spans do not overlap: a step's span is what its stretch took beyond the fields, requests,
    tools and loads recorded inside it (inside()), and a tool span lies inside nothing else that is counted (the
    AI's own time is its requests, not the tools it waited for)."""
    out = {k: 0 for k in KINDS}
    for s in spans:
        if s.get("k") in out:
            out[s["k"]] += int(s.get("ms") or 0)
    return out


def working_ms(spans: list[dict[str, Any]]) -> int:
    """How long the run took without the time spent waiting for the applicant."""
    t = totals(spans)
    return sum(v for k, v in t.items() if k != "human")


def by_name(spans: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, int]]:
    """(kind, name) -> {"ms": total, "n": how often, "max": the longest one, "failed": how many did not succeed}."""
    out: dict[tuple[str, str], dict[str, int]] = {}
    for s in spans:
        key = (str(s.get("k")), str(s.get("n")))
        o = out.setdefault(key, {"ms": 0, "n": 0, "max": 0, "failed": 0})
        ms = int(s.get("ms") or 0)
        o["ms"] += ms
        o["n"] += 1
        o["max"] = max(o["max"], ms)
        if s.get("ok") is False or str(s.get("ok")) == "False":
            o["failed"] += 1
    return out


HUMAN_STEPS = ("handed_over",)


def stops_for_applicant(steps: list[dict[str, Any]] | None) -> int:
    """How many times a run handed the form to the applicant - to look at, to fill what only they can, to send.
    Counted from the run's steps (the step "handed_over"; one step, one stop), not from the spans of their time.
    (A task that stopped before there was a run - a sign-in, a challenge - is not a run: it is the task's outcome,
    "waiting", and is counted there.)"""
    return sum(1 for st in steps or [] if isinstance(st, dict) and st.get("op") in HUMAN_STEPS)


def takeovers(steps: list[dict[str, Any]] | None) -> int:
    """How many times the AI took a page over from the driver in a run."""
    return sum(1 for st in steps or [] if isinstance(st, dict) and st.get("op") == "repair")

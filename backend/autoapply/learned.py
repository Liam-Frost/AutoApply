"""What the program has learned about filling forms, kept so that it stays learned.

The agent finishes a form the driver could not, and knows afterwards what the driver should have done. That used to
end as a sentence in the notes for the site. Here it becomes something the program does next time:

  recipe   how to work a kind of control or when to wait on a site, as data the generic driver follows
           ("the Code list on this site is a button that opens a list; leave it alone when it already shows part
           of the wanted entry")
  plugin   code the agent wrote for a control no recipe can describe: a small Python module with set_value /
           get_value for the fields it knows

Both live under the data folder (data/learned), not in the program's own folder: an upgrade replaces the program
and leaves them. Each is a revision with a history:

  proposed   written, waiting for the applicant - only when the setting learned.mode is "ask"
  trial      passed the gate; in force, and watched: every run it takes part in is a trial
  active     held up in its trials
  reverted   did harm in a run (its own code or rule failed, or runs with it kept failing): out of force, kept
  parked     did not pass the gate, or was learned on another version of the program and has not passed again yet
  rejected   the applicant said no

The gate (before anything is in force): a plugin's code may only use what a driver uses (ALLOWED), must load, and
the saved pages of the site must still be read as before with the revision in force. The trial (in force): the
revision's part of a run is wrapped - if it raises or leaves its field wrong, the ordinary way takes over in the same
run and the revision gets a strike. A strike reverts it. A revision can therefore make a run slower once; it cannot
make an application wrong: the read-back against the approved draft and the submit rules are the executor's and are
not the revision's to touch.

Honest limit: a plugin is Python running as the program. The allow-list keeps it to the page and the widget
helpers and is checked before every load; it is a guard against a careless or confused agent, not a sandbox against
a hostile one.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("autoapply.learned")

STATUSES = ("proposed", "trial", "active", "reverted", "parked", "rejected")
IN_FORCE = ("trial", "active")
TRIALS_TO_PROMOTE = 2       # good runs before a revision is taken to hold up
BAD_TRIALS_TO_REVERT = 2    # failed runs with it in force (without a strike of its own) before it is taken out
SLOWER = 1.25               # a revision whose runs take this much longer than before does not hold up

# what a recipe may say about a control
DO = ("list_button", "search_pick", "native", "react_select", "leave_if_shown")
# what a plugin may import, and the names it may not use at all
ALLOWED = {"re", "time", "typing", "__future__", "autoapply.ats.widgets", "autoapply.ats.base"}
FORBIDDEN = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "getattr", "setattr", "delattr", "vars", "input", "breakpoint", "exit", "quit"}

_lock = threading.RLock()
_tls = threading.local()
_plugins: dict[str, Any] = {}


def root() -> Path:
    return config.DATA / "learned"


def _index() -> Path:
    return root() / "index.json"


def revisions() -> list[dict[str, Any]]:
    try:
        return json.loads(_index().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(revs: list[dict[str, Any]]) -> None:
    root().mkdir(parents=True, exist_ok=True)
    tmp = _index().with_suffix(".tmp")
    tmp.write_text(json.dumps(revs, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_index())


def get(rev_id: str) -> dict[str, Any] | None:
    return next((r for r in revisions() if r["id"] == rev_id), None)


def _update(rev_id: str, **changes: Any) -> dict[str, Any] | None:
    with _lock:
        revs = revisions()
        rev = next((r for r in revs if r["id"] == rev_id), None)
        if rev is None:
            return None
        rev.update(changes)
        if "status" in changes:
            rev.setdefault("history", []).append({"at": _now(), "status": changes["status"], "why": changes.get("why_status", "")})
        _save(revs)
        return rev


def _now() -> str:
    from .models import now

    return now().isoformat(timespec="seconds")


def version() -> str:
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', (config.ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def content(rev: dict[str, Any]) -> str:
    """The recipe or the code of a revision, as text."""
    try:
        return (root() / rev["id"] / ("plugin.py" if rev["kind"] == "plugin" else "recipe.json")).read_text(encoding="utf-8")
    except OSError:
        return ""


# --- the gate -------------------------------------------------------------------------------------------------


class Refused(ValueError):
    """Why a revision may not be in force; the message is kept with it."""


def check_recipe(recipe: Any) -> dict[str, Any]:
    if not isinstance(recipe, dict):
        raise Refused("a recipe is an object")
    out: dict[str, Any] = {"controls": [], "waits": []}
    for c in recipe.get("controls") or []:
        when, do = c.get("when") or {}, c.get("do")
        if do not in DO:
            raise Refused(f"unknown way to work a control: {do!r} (known: {', '.join(DO)})")
        if not isinstance(when.get("label"), str) or not when["label"].strip():
            raise Refused("a control rule names the field it is for (when.label, a regular expression on its label)")
        try:
            re.compile(when["label"])
        except re.error as e:
            raise Refused(f"when.label is not a regular expression: {e}") from e
        out["controls"].append({"when": {"label": when["label"], **({"type": str(when["type"])} if when.get("type") else {})}, "do": do,
                                "wait_ms": max(0, min(int(c.get("wait_ms") or 0), 5000))})
    for w in recipe.get("waits") or []:
        if w.get("after") not in ("load", "field", "step"):
            raise Refused("a wait is after 'load', 'field' or 'step'")
        out["waits"].append({"after": w["after"], "ms": max(0, min(int(w.get("ms") or 0), 8000))})
    if not out["controls"] and not out["waits"]:
        raise Refused("the recipe says nothing")
    return out


def check_code(code: str) -> None:
    """A plugin's code may import only what a driver works with, and may not reach for the rest of Python."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise Refused(f"the code does not parse: {e}") from e
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED:
                    raise Refused(f"the code imports {a.name}: only {', '.join(sorted(ALLOWED))} may be imported")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") not in ALLOWED or node.level:
                raise Refused(f"the code imports from {node.module}: only {', '.join(sorted(ALLOWED))} may be imported")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN:
            raise Refused(f"the code uses {node.id}(), which a plugin may not")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            raise Refused(f"the code reaches for {node.attr}, which a plugin may not")
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if not names & {"set_value", "get_value"}:
        raise Refused("a plugin defines set_value(page, q, value, w) and/or get_value(page, q, w)")


def _load(rev: dict[str, Any]) -> Any:
    """The plugin's module, checked every time before it is loaded (the file can have been edited)."""
    key = f"{rev['id']}:{(root() / rev['id'] / 'plugin.py').stat().st_mtime}"
    if key not in _plugins:
        code = content(rev)
        check_code(code)
        scope: dict[str, Any] = {"__name__": f"autoapply_learned_{rev['id']}"}
        exec(compile(code, f"learned/{rev['id']}/plugin.py", "exec"), scope)  # noqa: S102 - checked above; see the module's note on what that is worth
        _plugins[key] = scope
    return _plugins[key]


def gate(rev: dict[str, Any]) -> dict[str, Any]:
    """Check a revision before it may be in force. Returns what was checked; raises Refused."""
    from . import fixtures

    if rev["kind"] == "recipe":
        check_recipe(json.loads(content(rev) or "{}"))
    else:
        _load(rev)
    ats = rev["target"] if not rev["target"].startswith("site-") else "generic"
    before = fixtures.run_all(ats)
    with forcing([rev]):
        after = fixtures.run_all(ats)
    ok_before = {r["fixture"] for r in before["results"] if r["ok"]}
    broke = [r["fixture"] for r in after["results"] if not r["ok"] and r["fixture"] in ok_before]
    if broke:
        raise Refused(f"with it, saved pages that were read correctly are not any more: {', '.join(broke[:5])}")
    return {"fixtures": after["fixtures"], "at": _now(), "version": version()}


# --- adding, deciding -----------------------------------------------------------------------------------------


def add(kind: str, target: str, title: str, why: str, body: str, *, from_run: int | None = None, expected: str = "", baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep a new revision and take it through the gate. In force at once (as a trial) unless the applicant decides
    (setting learned.mode = "ask"), in which case it waits as proposed."""
    from . import db

    if kind not in ("recipe", "plugin"):
        raise Refused(f"unknown kind {kind}")
    rev = {"id": uuid.uuid4().hex[:10], "kind": kind, "target": target, "title": title.strip()[:120], "why": why.strip()[:1500], "expected": expected.strip()[:400],
           "from_run": from_run, "created": _now(), "status": "parked", "version": version(), "trials": [], "strikes": 0, "baseline": baseline or {}, "history": []}
    folder = root() / rev["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("plugin.py" if kind == "plugin" else "recipe.json")).write_text(body, encoding="utf-8")
    with _lock:
        _save([*revisions(), rev])
    try:
        checked = gate(rev)
    except Refused as e:
        return _update(rev["id"], status="parked", why_status=str(e)[:400]) or rev
    except Exception as e:  # noqa: BLE001 - a gate that cannot be run does not let anything through
        return _update(rev["id"], status="parked", why_status=f"the gate could not be run: {type(e).__name__}: {e}"[:400]) or rev
    ask = (db.get_setting("learned.mode") or "auto") == "ask"
    rev = _update(rev["id"], gate=checked, status="proposed" if ask else "trial", why_status="等你确认" if ask else "通过了检查，开始试用") or rev
    if ask:
        from . import notify

        notify.add_todo("learned", f"程序学到了一个新做法：{rev['title']}", body=rev["why"][:600], ref=f"learned:{rev['id']}", payload={"id": rev["id"], "target": target, "kind": kind})
    return rev


def decide(rev_id: str, action: str) -> dict[str, Any]:
    """The applicant's word: approve | reject | revert | retry (through the gate again)."""
    rev = get(rev_id)
    if rev is None:
        raise KeyError(rev_id)
    from . import notify

    if action == "approve" and rev["status"] == "proposed":
        rev = _update(rev_id, status="trial", why_status="你采用了，开始试用")
    elif action == "reject" and rev["status"] in ("proposed", "parked"):
        rev = _update(rev_id, status="rejected", why_status="你没有采用")
    elif action == "revert" and rev["status"] in IN_FORCE:
        rev = _update(rev_id, status="reverted", why_status="你撤回了")
    elif action == "retry" and rev["status"] in ("parked", "reverted"):
        try:
            rev = _update(rev_id, gate=gate(rev), status="trial", why_status="再次通过了检查，重新试用", strikes=0, trials=[], version=version())
        except Refused as e:
            rev = _update(rev_id, status="parked", why_status=str(e)[:400])
    else:
        raise Refused(f"a revision that is {rev['status']} cannot be {action}d")
    notify.close_todos("learned", f"learned:{rev_id}")
    return rev or {}


def recheck_after_upgrade() -> int:
    """What was learned on another version of the program goes through the gate again before it is used: the driver
    it leans on may have changed. Called when the program starts. Returns how many were parked."""
    parked = 0
    for rev in revisions():
        if rev["status"] in IN_FORCE and rev.get("version") != version():
            try:
                _update(rev["id"], gate=gate(rev), version=version())
            except Exception as e:  # noqa: BLE001
                _update(rev["id"], status="parked", why_status=f"是在 {rev.get('version') or '更早的'} 版上学到的，在 {version()} 版上没有通过检查：{e}"[:400])
                parked += 1
    return parked


# --- in force during a run ------------------------------------------------------------------------------------


class forcing:
    """With these revisions in force in this thread (the gate, tests)."""

    def __init__(self, revs: list[dict[str, Any]]):
        self.revs = revs

    def __enter__(self) -> None:
        self.before = getattr(_tls, "force", None)
        _tls.force = {"revs": self.revs, "strikes": {}, "used": set()}

    def __exit__(self, *exc: Any) -> None:
        _tls.force = self.before


def begin(targets: list[str]) -> None:
    """A run starts: what was learned for its site and its system is in force for it."""
    revs = [r for r in revisions() if r["status"] in IN_FORCE and r["target"] in targets]
    _tls.force = {"revs": revs, "strikes": {}, "used": set()}


def in_force() -> list[str]:
    f = getattr(_tls, "force", None)
    return [r["id"] for r in f["revs"]] if f else []


def _strike(rev: dict[str, Any], why: str) -> None:
    f = getattr(_tls, "force", None)
    if f is not None:
        f["strikes"][rev["id"]] = why[:300]
    log.warning("learned revision %s (%s) failed in a run: %s", rev["id"], rev["title"], why[:200])


def _rules(q: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    f = getattr(_tls, "force", None)
    out = []
    for rev in (f["revs"] if f else []):
        if rev["kind"] != "recipe" or rev["id"] in f["strikes"]:
            continue
        try:
            recipe = json.loads(content(rev))
        except ValueError:
            continue
        for c in recipe.get("controls") or []:
            when = c.get("when") or {}
            if re.search(when.get("label", "$^"), q.label or "", re.I) and (not when.get("type") or when["type"] == q.type):
                out.append((rev, c))
    return out


def _shows_part(shown: Any, entry: Any) -> bool:
    """Every word of what is shown is a word of the entry, and the entry has more ("+1" for "+1 Canada")."""
    words = lambda v: [t for t in re.split(r"[\s,;|/()]+", str(v if v is not None else "").lower()) if t]  # noqa: E731
    s, e = words(shown), words(entry)
    return bool(s) and len(s) < len(e) and all(x in e for x in s)


def set_value(page: Any, q: Any, value: Any, loc: Any, tag: str) -> bool:
    """Fill a field the way that was learned for it. True: done. False: nothing was learned for it, or what was
    learned did not work - the caller goes on as it always did, and the revision has a strike."""
    from .ats import widgets as w
    from .ats.base import values_equal

    f = getattr(_tls, "force", None)
    if not f or not f["revs"]:
        return False
    for rev in f["revs"]:
        if rev["kind"] != "plugin" or rev["id"] in f["strikes"]:
            continue
        try:
            fn = _load(rev).get("set_value")
            if fn is not None and fn(page, q, value, w) is True:
                f["used"].add(rev["id"])
                return True
        except Exception as e:  # noqa: BLE001 - whatever it is, the ordinary way takes over
            _strike(rev, f"{type(e).__name__}: {e}")
    for rev, rule in _rules(q):
        try:
            do = rule["do"]
            if rule.get("wait_ms"):
                page.wait_for_timeout(rule["wait_ms"])
            if do == "leave_if_shown":
                shown = (loc.inner_text() if tag == "button" else loc.input_value()) or ""
                if not (values_equal(value, shown.strip()) or _shows_part(shown.strip(), value)):
                    continue                    # it does not show the wanted entry: not this rule's case
            elif do == "list_button":
                w.workday_listbox(page, loc, str(value))
            elif do == "search_pick":
                w.search_pick(page, loc, str(value))
            elif do == "native":
                w.select_native(loc, str(value))
            elif do == "react_select":
                w.react_select(page, loc, str(value))
            f["used"].add(rev["id"])
            return True
        except Exception as e:  # noqa: BLE001
            _strike(rev, f"{rule['do']} on {q.label!r}: {type(e).__name__}: {e}")
    return False


def get_value(page: Any, q: Any) -> Any:
    """What a field holds, read the way a plugin learned to read it; NotImplemented when none does."""
    from .ats import widgets as w

    f = getattr(_tls, "force", None)
    for rev in (f["revs"] if f else []):
        if rev["kind"] != "plugin" or rev["id"] in f["strikes"]:
            continue
        try:
            fn = _load(rev).get("get_value")
            if fn is not None:
                got = fn(page, q, w)
                if got is not NotImplemented and got is not None:
                    f["used"].add(rev["id"])
                    return got
        except Exception as e:  # noqa: BLE001
            _strike(rev, f"get_value: {type(e).__name__}: {e}")
    return NotImplemented


def wait_after(page: Any, what: str) -> None:
    """The waits that were learned for this site ('load', 'field', 'step')."""
    f = getattr(_tls, "force", None)
    for rev in (f["revs"] if f else []):
        if rev["kind"] != "recipe" or rev["id"] in f["strikes"]:
            continue
        try:
            for w in json.loads(content(rev)).get("waits") or []:
                if w.get("after") == what and w.get("ms"):
                    page.wait_for_timeout(int(w["ms"]))
                    f["used"].add(rev["id"])
        except Exception as e:  # noqa: BLE001
            _strike(rev, f"wait after {what}: {type(e).__name__}")


def drop() -> None:
    """The run is over and is no trial (a walk that only reads the form): nothing is judged by it."""
    _tls.force = None


def end(*, ok: bool, working_ms: int, interventions: int, run_id: int | None) -> list[dict[str, Any]]:
    """The run is over: every revision that was in force is judged by it. Returns what changed, for the record."""
    f = getattr(_tls, "force", None)
    _tls.force = None
    changed: list[dict[str, Any]] = []
    if not f:
        return changed
    for rev in f["revs"]:
        now_rev = get(rev["id"])
        if now_rev is None or now_rev["status"] not in IN_FORCE:
            continue
        strike = f["strikes"].get(rev["id"])
        trial = {"run": run_id, "at": _now(), "ok": bool(ok) and not strike, "ms": int(working_ms), "human": int(interventions), "used": rev["id"] in f["used"], **({"strike": strike} if strike else {})}
        trials = [*now_rev.get("trials", []), trial][-20:]
        if strike:
            changed.append(_update(rev["id"], trials=trials, strikes=int(now_rev.get("strikes") or 0) + 1, status="reverted", why_status=f"在一次运行里出错，已退回原来的做法：{strike}") or {})
            continue
        used = [t for t in trials if t.get("used")]
        good = [t for t in used if t["ok"]]
        bad = [t for t in used if not t["ok"]]
        base = (now_rev.get("baseline") or {}).get("median_ms")
        if now_rev["status"] == "trial" and len(bad) >= BAD_TRIALS_TO_REVERT and len(bad) > len(good):
            changed.append(_update(rev["id"], trials=trials, status="reverted", why_status=f"用了它的 {len(bad)} 次运行没有填完") or {})
        elif now_rev["status"] == "trial" and len(good) >= TRIALS_TO_PROMOTE:
            ms = sorted(t["ms"] for t in good)[len(good) // 2]
            if base and ms > base * SLOWER:
                changed.append(_update(rev["id"], trials=trials, status="reverted", why_status=f"用了它之后每次约 {ms / 1000:.0f} 秒，之前约 {base / 1000:.0f} 秒，没有变快") or {})
            else:
                changed.append(_update(rev["id"], trials=trials, status="active", why_status=f"在 {len(good)} 次运行里表现正常") or {})
        else:
            _update(rev["id"], trials=trials)
    return [c for c in changed if c]

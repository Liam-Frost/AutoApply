"""Looking at a run for what the program should do better next time, and having the agent write that down as
something the program then does (learned.py).

After every run that filled a form:

  1. review()   where did the time go, compared with earlier runs on the same site? What was done over and over?
                Plain arithmetic on the run's spans (timing.py) - no AI. The applicant's own time is never counted.
  2. propose()  only when the review found something: the agent is given the findings, what the take-over agent
                wrote about the run, and what is already learned for the site, and may write one or two revisions -
                a recipe (data the generic driver follows) or, where no recipe can say it, a plugin (code).
  3. learned.add() takes each through the gate; it is then in force as a trial, or waits for the applicant when the
                setting learned.mode is "ask".

What a finding is, so that the agent is not sent after noise:
  - a kind of step that took much longer than it usually does on this site (several times the median, and seconds
    more in absolute terms - a page that loads in 3 s instead of 1 s is not a finding);
  - the same thing done repeatedly: take-overs of the same page, a tool that failed again and again;
  - a field the driver could not fill, which the take-over then filled.
Time spent waiting for the model is reported but is not by itself a finding: the lever there is fewer requests,
which shows up as repeated take-overs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from . import db, learned, llm, timing
from .models import Run

log = logging.getLogger("autoapply.improve")

HISTORY = 20                # earlier runs on the same site a run is compared with
ENOUGH = 3                  # ... and how many of them there must be before "usual" means anything
TIMES = 3.0                 # a step is slow when it took this many times its usual ...
AT_LEAST_MS = 8000          # ... and at least this much longer
REPEATED = 3                # the same step this often in one run is a finding whatever it took


def _median(xs: list[int]) -> int:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def usual(site: str, ats: str, before_id: int | None = None) -> dict[str, Any]:
    """What runs on this site (or, for a site seen too rarely, this system) usually take: per kind of step and as a whole."""
    with db.session() as s:
        q = s.query(Run).filter(Run.kind == "execute", Run.spans.isnot(None))
        if before_id is not None:
            q = q.filter(Run.id < before_id)
        rows = [(r.site, r.ats, r.spans or [], r.ok) for r in q.order_by(Run.id.desc()).limit(400)]
    mine = [r for r in rows if site and r[0] == site][:HISTORY]
    if len(mine) < ENOUGH:
        mine = [r for r in rows if r[1] == ats][:HISTORY]
    per: dict[tuple[str, str], list[int]] = {}
    whole: list[int] = []
    for _site, _ats, spans, ok in mine:
        if not ok:
            continue
        whole.append(timing.working_ms(spans))
        for key, v in timing.by_name(spans).items():
            per.setdefault(key, []).append(v["ms"])
    return {"runs": len(whole), "median_ms": _median(whole), "steps": {k: _median(v) for k, v in per.items() if len(v) >= ENOUGH}}


def review(run_id: int) -> dict[str, Any]:
    """What stands out in a run. {"findings": [...], "totals": {...}, "working_ms", "usual": {...}}"""
    with db.session() as s:
        r = s.get(Run, run_id)
        if r is None:
            raise KeyError(run_id)
        spans, site, ats, ok, steps = list(r.spans or []), r.site or "", r.ats, bool(r.ok), list(r.steps or [])
    base = usual(site, ats, before_id=run_id)
    findings: list[dict[str, Any]] = []
    for (kind, name), v in sorted(timing.by_name(spans).items(), key=lambda kv: -kv[1]["ms"]):
        if kind == "human":
            continue
        normal = base["steps"].get((kind, name))
        if kind != "ai" and normal is not None and v["ms"] > normal * TIMES and v["ms"] - normal > AT_LEAST_MS:
            findings.append({"what": "slow", "kind": kind, "step": name, "ms": v["ms"], "usual_ms": normal, "times": v["n"]})
        if kind == "tool" and v["failed"] >= REPEATED:
            findings.append({"what": "tool_failed_repeatedly", "kind": kind, "step": name, "failed": v["failed"], "of": v["n"], "ms": v["ms"]})
        if kind == "driver" and name == "field" and v["failed"]:
            labels = sorted({str(sp.get("label")) for sp in spans if sp.get("k") == "driver" and sp.get("n") == "field" and str(sp.get("ok")) == "False"})
            findings.append({"what": "fields_not_filled_by_the_driver", "fields": labels[:12], "ms": v["ms"]})
    repairs = [st for st in steps if st.get("op") == "repair"]
    if len(repairs) >= 2:
        findings.append({"what": "taken_over_repeatedly", "times": len(repairs), "causes": [str(st.get("cause") or "")[:200] for st in repairs][:6]})
    return {"run": run_id, "site": site, "ats": ats, "ok": ok, "findings": findings[:12], "totals": timing.totals(spans), "working_ms": timing.working_ms(spans), "usual": {"runs": base["runs"], "median_ms": base["median_ms"]}}


def after_run(run_id: int, changed: list[dict[str, Any]]) -> None:
    """Called by the executor when a run has been recorded. Queues the look at it when there is something to look at."""
    if changed:
        from . import notify

        for rev in changed:
            word = {"active": "已经稳定生效", "reverted": "已撤回"}.get(rev.get("status", ""), rev.get("status", ""))
            notify.send("task_result", f"程序学到的做法“{rev.get('title', '')}”{word}：{rev.get('why_status', '')}", ref=f"learned:{rev.get('id')}", path="/analytics?tab=timing")
    if not db.get_setting("learned.enabled"):
        return
    if review(run_id)["findings"]:
        from . import tasks

        tasks.enqueue("improve", ref=f"run:{run_id}", payload={"run_id": run_id}, priority=300)


PROPOSAL = llm.obj({
    "revisions": {"type": "array", "items": llm.obj({
        "kind": {"type": "string", "enum": ["recipe", "plugin"]},
        "scope": {"type": "string", "enum": ["site", "system"], "description": "site: this employer's site only; system: every site of this application system"},
        "title": {"type": "string", "description": "what the program will do differently, in one line"},
        "why": {"type": "string", "description": "which finding this answers and why it will help; what was seen in the run"},
        "expected": {"type": "string", "description": "what should be better afterwards, measurably (fewer take-overs of step X, field Y filled by the driver)"},
        "recipe": {"type": "string", "description": "for kind=recipe: the recipe as JSON text; otherwise empty"},
        "code": {"type": "string", "description": "for kind=plugin: the Python module; otherwise empty"},
    })},
    "nothing_because": {"type": "string", "description": "when no revision is proposed: why not (the time was the site's or the model's; one-off; already learned)"},
})

RULES = """You improve a program that fills in job application forms. A run has just ended and something in it stood out.
Decide whether the program should do something differently next time on this site, and if so write it down as a
revision the program will follow. Propose nothing when the time was the site's or the model's, when it was a one-off,
or when what you would write is already learned. At most two revisions; one well-aimed is better.

Two kinds of revision:

RECIPE - data the generic driver follows. Prefer this whenever it can say what is needed.
  {"controls": [{"when": {"label": "<regular expression on the field's label>", "type": "<select|text|...; optional>"},
                 "do": "<one of: list_button, search_pick, native, react_select, leave_if_shown>", "wait_ms": 0}],
   "waits": [{"after": "<load|field|step>", "ms": 500}]}
  list_button    the control is a button that opens a list of entries; open it and click the entry
  search_pick    the list has to be searched: type into it and choose the entry that is the wanted one
  native         an ordinary <select>
  react_select   a text box with a list under it (react-select and its relatives)
  leave_if_shown the control already shows the wanted entry, or a part of it ("+1" for "+1 Canada"): leave it alone
  A rule applies to fields whose label matches; keep the expression as narrow as the field ("^Code$", not "Code").

PLUGIN - Python, only when no recipe can say it. One module with either or both of:
  def set_value(page, q, value, w) -> bool    # True when it filled the field; False/None to leave it to the driver
  def get_value(page, q, w)                   # what the field holds, or NotImplemented
  page is a Playwright page; q has .id .label .type .options .locator; w is autoapply.ats.widgets (set_text,
  select_native, react_select, search_pick, workday_listbox, pick_option ...). Return False for every field the
  module is not written for - check q.label first. It may import only: re, time, typing, autoapply.ats.widgets,
  autoapply.ats.base. No files, no network, no other modules. It never presses a button that submits, never signs
  in, never invents a value: it puts the given value into the field, or reads what the field holds.

Never put an answer, a name, an e-mail address or any value from an application into a revision: only how the form
is worked. Write title, why and expected in Simplified Chinese (they are shown to the applicant); the recipe and
the code in English."""


def _reports(run_dir: str) -> list[dict[str, Any]]:
    """What the take-over agent wrote about the run: cause and suggestion of each take-over, newest last."""
    out = []
    try:
        files = sorted(Path(run_dir).glob("repair_*.json"), key=lambda p: p.stat().st_mtime)[-6:]
    except OSError:
        return out
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rep, prob = d.get("report") or {}, d.get("problem") or {}
        tools = [{"tool": st.get("tool"), "ok": st.get("ok"), "ms": st.get("ms"), "said": str(st.get("output") or "")[:160]} for st in (d.get("steps") or [])
                 if st.get("tool") not in ("read_page", "list_controls", "screenshot")][:14]
        out.append({"problem": str(prob.get("message") or "")[:200], "fields": [str(x.get("label")) for x in (prob.get("failures") or prob.get("mismatches") or [])][:8],
                    "cause": str(rep.get("cause") or "")[:500], "suggestion": str(rep.get("suggestion") or "")[:700], "tools": tools})
    return out


def propose(run_id: int) -> dict[str, Any]:
    """Have the agent look at a run and write what the program should do differently. Returns what became of it."""
    found = review(run_id)
    if not found["findings"]:
        return {"skipped": "nothing stands out in this run"}
    with db.session() as s:
        r = s.get(Run, run_id)
        run_dir, site, ats = r.dir, r.site or "", r.ats
    have = [{"id": v["id"], "kind": v["kind"], "target": v["target"], "status": v["status"], "title": v["title"], "body": learned.content(v)[:1500]}
            for v in learned.revisions() if v["target"] in (site, ats) and v["status"] in ("trial", "active", "proposed", "reverted")]
    prompt = (f"<site>{site or ats}</site>\n<system>{ats}</system>\n"
              f"<findings>\n{json.dumps(found['findings'], ensure_ascii=False, indent=1)}\n</findings>\n"
              f"<time_by_kind_ms>{json.dumps(found['totals'])}</time_by_kind_ms>\n<usual_for_this_site>{json.dumps(found['usual'])}</usual_for_this_site>\n"
              f"<what_the_take_over_agent_wrote>\n{json.dumps(_reports(run_dir), ensure_ascii=False, indent=1)}\n</what_the_take_over_agent_wrote>\n"
              f"<already_learned_for_this_site>\n{json.dumps(have, ensure_ascii=False, indent=1)}\n</already_learned_for_this_site>")
    out = llm.json(prompt, PROPOSAL, system=RULES, max_tokens=6000)
    base = usual(site, ats)
    made = []
    for p in (out.get("revisions") or [])[:2]:
        body = (p.get("recipe") if p.get("kind") == "recipe" else p.get("code")) or ""
        if not body.strip():
            continue
        target = site if p.get("scope") == "site" and site else ats
        rev = learned.add(p["kind"], target, p.get("title") or "", p.get("why") or "", body, from_run=run_id, expected=p.get("expected") or "",
                          baseline={"runs": base["runs"], "median_ms": base["median_ms"]})
        made.append({"id": rev["id"], "status": rev["status"], "title": rev["title"], "why_status": rev.get("why_status", "")})
    return {"findings": len(found["findings"]), "revisions": made, "nothing_because": (out.get("nothing_because") or "")[:300]}

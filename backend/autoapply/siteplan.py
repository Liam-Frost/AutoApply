"""What the agent has worked out about a site's form, kept so that the next posting there needs no agent for it.

A site without a coded driver used to be explored from nothing every time: the agent read each step of each posting's
form again, at the same cost. What it found on a step - which questions are there, what kind of control each is, how to
find it - is the site's, not the posting's, so it is kept here per site and used again: on the next posting the program
takes a known step from the plan, answers its questions from the profile and fills them with the generic driver. The
agent is called for what is new or what has changed.

This is how the agent improves the program's handling of a site - within limits that keep it safe:

* a plan holds structure only - labels, kinds of control, choices, where a control is, length limits, the names of the
  steps. Never an answer, never a value from an application, never code;
* a place (selector) enters the plan only after it was checked against the live page, and never one built on an id the
  site generates afresh on each visit;
* a plan is advice, checked each time it is used: a step is taken from it only when every place it names is on the page;
  a place that is not found counts against the entry, and an entry that fails twice is dropped, so a site that changes
  its form is read by the agent again instead of being filled from an out-of-date plan;
* plans are plain JSON files under the data folder, one per site: they can be read, edited and deleted.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from . import config
from .ats.base import norm_question

log = logging.getLogger("autoapply.siteplan")

KINDS = ("text", "textarea", "select", "radio", "checkbox", "date", "multiselect")
GENERATED = re.compile(r"#[\w-]*[0-9a-f]{8}-[0-9a-f]{4}|#:r\w*:|#(?:input|radio|select|field)-?\d+\b|^@label:|^input\[type=['\"]?file['\"]?\]$")


def _path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in key)
    return config.DATA / "sites" / f"{safe}.json"


def load(key: str) -> dict[str, Any]:
    p = _path(key)
    try:
        plan = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        plan = {}
    plan.setdefault("steps", {})
    return plan


def _save(key: str, plan: dict[str, Any]) -> None:
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def _same_step(a: str, b: str) -> bool:
    a, b = norm_question(a), norm_question(b)
    return bool(a) and bool(b) and (a in b or b in a)


def learn(key: str, pages: list[str], questions: list[dict[str, Any]], read: list[str]) -> int:
    """Take into the site's plan what a finished walk of one posting established. ``read``: the steps that were read
    completely (a step that was only partly seen is not a step the plan can stand in for). Returns how many questions
    the plan holds afterwards."""
    if not key:
        return 0
    plan = load(key)
    for i, name in enumerate(pages or []):
        title = re.sub(r"\s*\((not yet visible|[^)]{40,})\)\s*$", "", str(name)).strip()
        if not title or re.search(r"review|submit|summary|confirm", title, re.I) or not any(_same_step(title, r) for r in read or []):
            continue
        rows = []
        for q in questions:
            sel = str((q.get("locator") or {}).get("selector") or "").strip()
            if int(q.get("page") or 0) != i or q.get("type") not in KINDS or not sel or GENERATED.search(sel) or not str(q.get("label") or "").strip():
                continue
            rows.append({"label": str(q["label"])[:400], "type": q["type"], "options": [str(o) for o in q.get("options") or []][:80], "required": bool(q.get("required")),
                         "selector": sel[:300], "max_length": int(q.get("max_length") or 0), "misses": 0})
        if not rows:
            continue
        old = next((k for k in plan["steps"] if _same_step(k, title)), None)
        kept = {norm_question(r["label"]): r for r in (plan["steps"].pop(old)["questions"] if old else [])}
        kept.update({norm_question(r["label"]): r for r in rows})      # what was just seen replaces what was known
        plan["steps"][title] = {"questions": list(kept.values())[:120]}
    plan["pages"] = [str(p)[:120] for p in pages or []][:30]
    _save(key, plan)
    return sum(len(s["questions"]) for s in plan["steps"].values())


def step(key: str, title: str) -> list[dict[str, Any]]:
    """The questions the plan knows on the step with this title ([] when the plan does not know the step)."""
    plan = load(key)
    hit = next((k for k in plan["steps"] if _same_step(k, title)), None)
    return [dict(q) for q in plan["steps"][hit]["questions"]] if hit else []


def missed(key: str, title: str, labels: list[str]) -> None:
    """Places of the plan that were not on the page: counted, and dropped the second time."""
    plan = load(key)
    hit = next((k for k in plan["steps"] if _same_step(k, title)), None)
    if not hit:
        return
    gone = {norm_question(x) for x in labels}
    left = []
    for q in plan["steps"][hit]["questions"]:
        if norm_question(q["label"]) in gone:
            q["misses"] = int(q.get("misses") or 0) + 1
            if q["misses"] >= 2:
                continue
        left.append(q)
    if left:
        plan["steps"][hit]["questions"] = left
    else:
        plan["steps"].pop(hit)
    _save(key, plan)

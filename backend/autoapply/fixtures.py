"""DOM fixtures for driver regression (plan sections 7.5 and 7.7).

A fixture is one saved form page (HTML with scripts and typed values removed)
plus the questions the driver is expected to recognise on it. ``run_all``
replays every fixture through the current driver code offline, so a driver
change that stops recognising an old page is caught before a real application.

What they guard - and what they do not. Every site's form is read by the agent
now; the questions of a draft do not come from this code. What the driver still
does on every run is find each question's control on the page, fill it and read
it back. A fixture is a page on which that worked (it is saved after a fill that
was verified), and replaying it asks: does the current code still find those
controls and read them the same way? So the samples protect the driver's side of
filling and reading back - finding the controls and reading them. They say
nothing about reading a form for the first time (that is the agent's), and
nothing about whether typing into a control works (a replay has no scripts;
that is found out in a run, or in the trial of a revision).

A sample that stops matching is evidence, and which of the two it is evidence
of cannot be told from the sample: the page it was saved from may have been
rebuilt since, or the code may have lost something it could do. So it is never
thrown away for failing. It stays, marked with since when and what was missing
(``record``), and leaves only when the form itself has spoken again: a newer
sample of the same form page that passes (``archive_superseded``) - and then it
is moved aside, not deleted.

Fixtures live under ``data/fixtures/<ats>/`` (they can contain the applicant's
answers as page text, so they stay out of git).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import config
from .ats import registry
from .ats.base import FormSchema, Question, diff_schemas
from .models import now



def root() -> Path:
    return config.DATA / "fixtures"

KEEP_PER_ATS = 12       # samples kept per system - of the ones that are not failing; a failing one is not pruned by count
KEEP_ARCHIVED = 30      # superseded samples kept aside per system


def _clean(html: str) -> str:
    html = re.sub(r"<script\b[^>]*>.*?</script\b[^>]*>", "", html, flags=re.S | re.I)
    html = re.sub(r'(<input[^>]*type="password"[^>]*value=")[^"]*', r"\1", html)
    return html


def save(schema: FormSchema, page: Any, page_index: int, *, reason: str = "") -> str:
    """Save the current page as a fixture for ``schema.ats``. Returns the fixture path."""
    d = root() / schema.ats
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{now().strftime('%Y%m%d_%H%M%S')}_{schema.tenant or 'x'}_p{page_index + 1}_{reason or 'x'}"[:90]
    stem = re.sub(r"[^\w.-]", "_", stem)
    (d / f"{stem}.html").write_text(_clean(page.content()), encoding="utf-8")
    meta = {
        "ats": schema.ats, "tenant": schema.tenant, "page": page_index, "reason": reason, "url": page.url, "source": schema.source,
        "saved_at": now().isoformat(),
        "questions": [asdict(q) for q in schema.questions if q.page == page_index],
    }
    (d / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    fine = [p for p in sorted(d.glob("*.json")) if not _failing(p)]
    for p in fine[:-KEEP_PER_ATS]:
        p.unlink(missing_ok=True)
        p.with_suffix(".html").unlink(missing_ok=True)
    return str(d / f"{stem}.html")


def _meta(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _failing(path: Path) -> bool:
    return (_meta(path).get("check") or {}).get("ok") is False


def _when(path: Path, meta: dict[str, Any]) -> str:
    """When a sample was saved, for telling the later of two: written on it, or (the ones from before that) the start
    of its name - which has seconds only, so two saved in the same second are told apart by what is written."""
    stamp = path.stem[:15]
    return str(meta.get("saved_at") or (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}" if stamp[:8].isdigit() else ""))


def form_key(meta: dict[str, Any]) -> tuple[str, str, int, str]:
    """Which page of which form a sample is of: the system, the employer, the page, and the address without what
    follows "?" (two samples of one posting's form are the same form; another posting's is another)."""
    url = str(meta.get("url") or "").split("#")[0].split("?")[0].rstrip("/").lower()
    return str(meta.get("ats") or ""), str(meta.get("tenant") or ""), int(meta.get("page") or 0), url


def _driver_for(meta: dict[str, Any], qs: list[Question]):  # noqa: ANN202
    if meta.get("source") == "agent" or registry.get(meta["ats"]) is None:
        from .ats.generic_driver import GenericDriver

        return GenericDriver(FormSchema(ats=meta["ats"], source="agent", questions=qs))
    return registry.get(meta["ats"])


def check(page: Any, meta_path: Path) -> dict[str, Any]:
    """Replay one fixture on ``page`` (a Playwright page with JavaScript disabled)."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    idx = int(meta["page"])
    expected = [Question(**q) for q in meta["questions"]]
    out: dict[str, Any] = {"fixture": meta_path.stem, "ats": meta["ats"], "expected": len(expected)}
    try:
        page.set_content(meta_path.with_suffix(".html").read_text(encoding="utf-8"), wait_until="domcontentloaded")
        live = _driver_for(meta, expected).live_questions(page, idx)
    except Exception as e:  # noqa: BLE001
        return {**out, "ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    for q in live:
        q.page = idx
    diff = diff_schemas(FormSchema(ats=meta["ats"], questions=expected), FormSchema(ats=meta["ats"], questions=live), page=idx)
    # Extra controls seen live (page chrome) are fine; what matters is what went missing or changed.
    missing = [q["label"] for q in diff["removed"]]
    changed = [c["after"]["label"] for c in diff["changed"]]
    return {**out, "ok": not missing and not changed, "recognised": len(live), "missing": missing[:20], "changed": changed[:20]}


def record(results: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Write on each sample how the replay went: when, and for a failing one since when and what was wrong.

    Returns the names ("ats/fixture") of the samples that fail for the first time (``new``), that still fail
    (``still``) and that failed before and pass now (``recovered``)."""
    out: dict[str, list[str]] = {"new": [], "still": [], "recovered": []}
    at = now().isoformat(timespec="seconds")
    for r in results:
        path = root() / r["ats"] / f"{r['fixture']}.json"
        meta = _meta(path)
        if not meta:
            continue
        was = meta.get("check") or {}
        name = f"{r['ats']}/{r['fixture']}"
        if r["ok"]:
            if was.get("ok") is False:
                out["recovered"].append(name)
            meta["check"] = {"ok": True, "at": at}
        else:
            out["still" if was.get("ok") is False else "new"].append(name)
            meta["check"] = {"ok": False, "at": at, "failing_since": was.get("failing_since") or at,
                             **{k: r[k] for k in ("error", "missing", "changed") if r.get(k)}}
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def archive_superseded() -> list[str]:
    """Move aside the failing samples that the form itself has replaced: a later sample of the same form page that
    passes. (Not the ones that merely fail: nothing says which side changed.) Returns their names."""
    moved: list[str] = []
    if not root().exists():
        return moved
    by_form: dict[tuple[str, str, int, str], list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(root().glob("*/*.json")):
        meta = _meta(path)
        if meta:
            by_form.setdefault(form_key(meta), []).append((path, meta))
    for rows in by_form.values():
        rows.sort(key=lambda r: (_when(*r), r[0].name))
        for n, (path, meta) in enumerate(rows):
            if (meta.get("check") or {}).get("ok") is not False:
                continue
            newer = next((p for p, m in rows[n + 1:] if (m.get("check") or {}).get("ok") is True), None)
            if newer is None:
                continue
            aside = path.parent / "archive"
            aside.mkdir(exist_ok=True)
            meta["check"] = {**meta["check"], "superseded_by": newer.stem, "archived_at": now().isoformat(timespec="seconds")}
            (aside / path.name).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            path.unlink(missing_ok=True)
            html = path.with_suffix(".html")
            if html.exists():
                html.replace(aside / html.name)
            moved.append(f"{meta.get('ats')}/{path.stem}")
            for old in sorted(aside.glob("*.json"))[:-KEEP_ARCHIVED]:
                old.unlink(missing_ok=True)
                old.with_suffix(".html").unlink(missing_ok=True)
    return moved


def failing(ats: str | None = None) -> list[dict[str, Any]]:
    """The samples that did not match at the last replay: {name, ats, since, missing, changed, error}."""
    out = []
    for path in sorted(root().glob(f"{ats or '*'}/*.json")) if root().exists() else []:
        c = _meta(path).get("check") or {}
        if c.get("ok") is False:
            out.append({"name": f"{path.parent.name}/{path.stem}", "ats": path.parent.name, "fixture": path.stem, "since": c.get("failing_since", ""),
                        "missing": c.get("missing", []), "changed": c.get("changed", []), "error": c.get("error", "")})
    return out


def run_all(ats: str | None = None) -> dict[str, Any]:
    metas = sorted(root().glob(f"{ats or '*'}/*.json")) if root().exists() else []
    if not metas:
        return {"fixtures": 0, "failed": 0, "results": []}
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(java_script_enabled=False)
        page = ctx.new_page()
        for m in metas:
            results.append(check(page, m))
        b.close()
    return {"fixtures": len(results), "failed": sum(1 for r in results if not r["ok"]), "results": results}

"""DOM fixtures for driver regression (plan sections 7.5 and 7.7).

A fixture is one saved form page (HTML with scripts and typed values removed)
plus the questions the driver is expected to recognise on it. ``run_all``
replays every fixture through the current driver code offline, so a driver
change that stops recognising an old page is caught before a real application.

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

KEEP_PER_ATS = 12


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
        "questions": [asdict(q) for q in schema.questions if q.page == page_index],
    }
    (d / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    old = sorted(d.glob("*.json"))[:-KEEP_PER_ATS]
    for p in old:
        p.unlink(missing_ok=True)
        p.with_suffix(".html").unlink(missing_ok=True)
    return str(d / f"{stem}.html")


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


def drop(ats: str, name: str) -> int:
    """Remove a saved page that no longer matches what the program reads from it (1 when something was removed)."""
    n = 0
    for f in (root() / ats).glob(f"{name}.*"):
        try:
            f.unlink()
            n = 1
        except OSError:
            pass
    return n


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

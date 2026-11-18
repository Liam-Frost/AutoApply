"""What a learned plugin has to keep to before it is tried on an application (part of the gate, learned.gate).

A plugin is code the agent wrote for one control of one site. From the moment it is in force it is asked about every
field of every form on that site - set_value for each, get_value for each - and its tools are offered to the agent
that takes over there. The saved pages of the site tell whether those forms are still *read* as before (fixtures.py);
they have no scripts, so they cannot tell what the plugin does when it is let at a control. This page can. It is an
ordinary form - a text box, a list, a tick box, a file, a box inside a frame - none of which the plugin was written
for, and on it the plugin has to be honest:

  write    set_value either declines (anything but True) and leaves the field as it was, or says True - and then the
           field holds what it was given. Saying True for a field it did not fill marks the field as done; the
           read-back catches that later, in somebody's application.
  read     get_value either declines (NotImplemented / None) or returns what the field holds.
  upload   a file field is given the file that was handed over, or left alone - never another.
  frame    the same for a field inside a frame.
  aside    nothing else changes: the other fields keep their values, the page stays where it is, and nothing is
           sent - the form's Submit is counted. The tools a plugin offers keep to that as well.
  decline  a field that is not the plugin's is declined, not failed on: a plugin that raises on a field it does not
           know would be taken out at its first run, after having slowed it.

What this cannot tell: whether the plugin works the control it *was* written for - that control is on the site, not
here. That is what the trial is for (learned.py). The contract is what can be known before anybody's application is
the test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Contract</title></head><body>
<form id="c_form" action="about:blank#sent" onsubmit="window.sent = (window.sent || 0) + 1; return false">
  <label for="c_text">Contract: preferred name</label><input id="c_text" name="c_text" value="as it was">
  <label for="c_area">Contract: notes</label><textarea id="c_area" name="c_area">two
lines</textarea>
  <label for="c_select">Contract: country</label>
  <select id="c_select" name="c_select"><option value="">Choose</option><option value="ca" selected>Canada</option><option value="fr">France</option><option value="jp">Japan</option></select>
  <label><input type="checkbox" id="c_check" name="c_check"> Contract: agree</label>
  <label for="c_file">Contract: attachment</label><input type="file" id="c_file" name="c_file">
  <iframe id="c_frame" title="Contract: frame" srcdoc="<label for='c_inner'>Contract: reference code</label><input id='c_inner' value='inner as it was'>"></iframe>
  <button type="submit" id="c_submit">Submit application</button>
</form>
</body></html>"""

# (id, label, type, the value a plugin is handed for it)
FIELDS: list[tuple[str, str, str, Any]] = [
    ("c_text", "Contract: preferred name", "text", "Robin"),
    ("c_area", "Contract: notes", "textarea", "one line"),
    ("c_select", "Contract: country", "select", "France"),
    ("c_check", "Contract: agree", "checkbox", True),
    ("c_file", "Contract: attachment", "file", ""),          # the path is put in when the page is opened
    ("c_inner", "Contract: reference code", "text", "RC-42"),
]


def _questions(upload: str) -> list[Any]:
    from .ats.base import Question

    out = []
    for fid, label, kind, value in FIELDS:
        q = Question(id=fid, label=label, type=kind, options=["Canada", "France", "Japan"] if kind == "select" else [],
                     locator={"selector": f"#{fid}", **({"frame": "#c_frame"} if fid == "c_inner" else {})})
        out.append((q, upload if kind == "file" else value))
    return out


def _state(page: Any) -> dict[str, Any]:
    """What every field of the contract page holds, and whether the page is still what it was."""
    here = page.evaluate("""() => ({
        c_text: document.getElementById('c_text') ? document.getElementById('c_text').value : null,
        c_area: document.getElementById('c_area') ? document.getElementById('c_area').value : null,
        c_select: document.getElementById('c_select') ? (document.getElementById('c_select').selectedOptions[0] || {}).label || '' : null,
        c_check: document.getElementById('c_check') ? document.getElementById('c_check').checked : null,
        c_file: document.getElementById('c_file') ? [...document.getElementById('c_file').files].map(f => f.name).join(',') : null,
        sent: window.sent || 0, title: document.title})""")
    try:
        here["c_inner"] = page.frame_locator("#c_frame").locator("#c_inner").input_value(timeout=2000)
    except Exception:  # noqa: BLE001 - the frame is gone: that is a change, and it is reported as one
        here["c_inner"] = None
    here["url"] = page.url
    return here


def _holds(kind: str, value: Any, held: Any) -> bool:
    from .ats.base import values_equal

    if kind == "file":
        return bool(held) and held == Path(str(value)).name
    if kind == "checkbox":
        return held is bool(value)
    return values_equal(value, held)


def _others(before: dict[str, Any], after: dict[str, Any], mine: str = "") -> list[str]:
    out = []
    for k, was in before.items():
        if k == mine or after.get(k) == was:
            continue
        out.append("it sent the form" if k == "sent" else "it took the page somewhere else" if k in ("url", "title") else
                   f"the field {k} changed from {was!r} to {after.get(k)!r}")
    return out


def check_plugin(module: dict[str, Any]) -> list[str]:
    """Let the plugin at the contract page. Returns what it did that it may not - nothing, when it kept to the contract."""
    from playwright.sync_api import sync_playwright

    from . import gate
    from .ats import widgets as w

    setter, getter = module.get("set_value"), module.get("get_value")
    tools = [(t, module.get(f"tool_{t['name']}")) for t in module.get("TOOLS") or []]
    if setter is None and getter is None and not tools:
        return []
    found: list[str] = []
    with tempfile.TemporaryDirectory(prefix="autoapply-contract-") as tmp, sync_playwright() as pw:
        upload = Path(tmp) / "contract_resume.pdf"
        upload.write_bytes(b"%PDF-1.4 contract")
        browser = pw.chromium.launch(headless=True)
        try:
            def fresh() -> Any:
                page = browser.new_page()
                page.set_default_timeout(4000)      # a plugin that waits for its own control does not find it here: it is not to wait long
                page.set_content(PAGE, wait_until="load")
                page.frame_locator("#c_frame").locator("#c_inner").wait_for(state="attached")
                return page

            for q, value in _questions(str(upload)):
                if setter is None:
                    break
                page = fresh()      # each field on a page of its own: what one call leaves behind is not the next one's
                before = _state(page)
                try:
                    said = setter(gate.guarded(page), q, value, w)
                except Exception as e:  # noqa: BLE001
                    found.append(f"set_value failed on a field that is not its own ({q.label}): {type(e).__name__}: {str(e)[:160]} - it is to decline (return False)")
                    page.close()
                    continue
                after = _state(page)
                if said is True:
                    if not _holds(q.type, value, after.get(q.id)):
                        found.append(f"set_value said it had filled '{q.label}' with {value!r}, and the field holds {after.get(q.id)!r}")
                    found += [f"set_value on '{q.label}': {x}" for x in _others(before, after, q.id)]
                else:
                    found += [f"set_value declined '{q.label}' and still: {x}" for x in _others(before, after)]
                page.close()
            if getter is not None:
                page = fresh()
                held = _state(page)
                for q, _ in _questions(str(upload)):
                    if q.type == "file":
                        continue      # an empty file field holds nothing to read
                    try:
                        got = getter(gate.guarded(page), q, w)
                    except Exception as e:  # noqa: BLE001
                        found.append(f"get_value failed on a field that is not its own ({q.label}): {type(e).__name__}: {str(e)[:160]} - it is to decline (return NotImplemented)")
                        continue
                    if got is NotImplemented or got is None:
                        continue
                    if not _holds(q.type, got, held.get(q.id)):
                        found.append(f"get_value read '{q.label}' as {got!r}, and the field holds {held.get(q.id)!r}")
                found += [f"get_value: {x}" for x in _others(held, _state(page))]
                page.close()
            for t, fn in tools:
                if fn is None:
                    continue
                page = fresh()
                before = _state(page)
                try:
                    fn(gate.guarded(page), w, **{k: {"string": "contract", "number": 1, "boolean": True}[v] for k, v in (t.get("params") or {}).items()})
                except Exception:  # noqa: BLE001 - a tool whose control is not on this page says so; that is what it is to do
                    pass
                after = _state(page)
                found += [f"the tool {t['name']}: {x}" for x in _others({k: before[k] for k in ("sent", "url", "title", "c_file")}, after)]
                page.close()
        finally:
            browser.close()
    return found[:8]


def check(module: dict[str, Any]) -> list[str]:
    """check_plugin, on a thread of its own: the browser that is started for it cannot be started on a thread that
    already has a page open (a run in progress, a test)."""
    from concurrent.futures import ThreadPoolExecutor

    from . import context

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="contract") as pool:
        return pool.submit(context.carried(check_plugin), module).result()

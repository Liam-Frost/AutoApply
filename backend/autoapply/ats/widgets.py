"""L1 widget library: reliable operations on form controls (Playwright sync API).

Every operation acts, then reads the control back; a mismatch raises
``DriverError`` with enough context for the repair agent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PWTimeout

from .base import DriverError, values_equal

T = 8000  # default per-operation timeout (ms)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def pick_option(options: list[str], wanted: str) -> int:
    """Index of the option matching ``wanted``: exact, then case-insensitive, then prefix/contains."""
    w = _norm(wanted)
    normed = [_norm(o) for o in options]
    if w in normed:  # exact match wins even when duplicated
        return normed.index(w)
    for test in (lambda o: o.startswith(w), lambda o: w.startswith(o), lambda o: w in o):
        hits = [i for i, o in enumerate(normed) if o and test(o)]
        if len(hits) == 1:
            return hits[0]
    raise DriverError("option not found or ambiguous", expected=wanted, seen=" / ".join(options)[:500])


def pick_option_or_none(options: list[str], wanted: str) -> int | None:
    try:
        return pick_option(options, wanted)
    except DriverError:
        return None


# --- plain inputs --------------------------------------------------------------


def set_text(loc: Locator, value: str) -> None:
    """Fill an <input>/<textarea>, including React-controlled ones, and verify."""
    loc.scroll_into_view_if_needed(timeout=T)
    loc.fill(str(value), timeout=T)
    got = loc.input_value(timeout=T)
    if not values_equal(value, got):
        # React masks (phone) may reformat; retry with real typing.
        loc.fill("", timeout=T)
        loc.press_sequentially(str(value), delay=15, timeout=T * 3)
        got = loc.input_value(timeout=T)
        if not values_equal(value, got):
            raise DriverError("text did not stick", expected=str(value), seen=got)
    loc.blur()


def set_checkbox(loc: Locator, checked: bool = True) -> None:
    if loc.is_checked() != checked:
        try:
            loc.set_checked(checked, timeout=T)
        except PWTimeout:
            loc.evaluate("(e) => e.click()")
    if loc.is_checked() != checked:
        raise DriverError("checkbox did not change", expected=str(checked), seen=str(loc.is_checked()))


def select_native(loc: Locator, label: str) -> None:
    opts = loc.locator("option").all_inner_texts()
    i = pick_option(opts, label)
    loc.select_option(index=i, timeout=T)
    got = loc.evaluate("(e) => e.selectedOptions[0] ? e.selectedOptions[0].text : ''")
    if not values_equal(opts[i], got):
        raise DriverError("select did not change", expected=opts[i], seen=got)


def upload(loc: Locator, paths: list[str | Path]) -> None:
    """Set files on an <input type=file> (works when the input is hidden)."""
    files = [str(Path(p)) for p in paths]
    for f in files:
        if not Path(f).exists():
            raise DriverError("file to upload does not exist", expected=f)
    loc.set_input_files(files, timeout=T * 2)


# --- react-select (Greenhouse job-boards, Ashby-like comboboxes) ---------------


def react_select(page: Page, input_loc: Locator, label: str, *, type_to_filter: bool = False) -> str:
    """Choose an option in a react-select whose <input> is ``input_loc``. Returns the chosen text."""
    input_loc.scroll_into_view_if_needed(timeout=T)
    input_loc.click(timeout=T)
    listbox_id = input_loc.get_attribute("aria-controls")
    if type_to_filter:
        input_loc.press_sequentially(label[:30], delay=20)
    lb = page.locator(f"[id='{listbox_id}']") if listbox_id else page.locator("[role=listbox]:visible").last
    try:
        lb.wait_for(state="visible", timeout=3000)
    except PWTimeout:  # a click that landed before the widget was ready does not open it
        input_loc.press("ArrowDown")
        lb.wait_for(state="visible", timeout=T)
    options = lb.locator("[role=option]")
    texts = [t.strip() for t in options.all_inner_texts()]
    for _ in range(20):  # option lists can be fetched on open or after typing
        if texts and (not type_to_filter or pick_option_or_none(texts, label) is not None):
            break
        page.wait_for_timeout(300)
        texts = [t.strip() for t in options.all_inner_texts()]
    if not texts:
        raise DriverError("dropdown has no options", expected=label)
    i = pick_option(texts, label)
    options.nth(i).click(timeout=T)
    return texts[i]


def react_select_value(input_loc: Locator) -> str:
    return input_loc.evaluate(
        """(e) => {
            const own = e.closest('[class*="control"]');  // never read a neighbouring select's value
            let c = own || e.parentElement;
            for (let k = 0; k < (own ? 1 : 6) && c; k++) {
                const v = c.querySelector('[class*="single-value"], [class*="singleValue"]');
                if (v) return v.innerText.trim();
                const multi = [...c.querySelectorAll('[class*="multi-value__label"], [class*="multiValue"] > div:first-child')];
                if (multi.length) return multi.map(m => m.innerText.trim()).join('|');
                c = c.parentElement;
            }
            return '';
        }"""
    )


# --- Workday -------------------------------------------------------------------


def workday_listbox(page: Page, button: Locator, label: str) -> str:
    """Workday dropdown rendered as a <button aria-haspopup=listbox>."""
    button.scroll_into_view_if_needed(timeout=T)
    button.click(timeout=T)
    opts = page.locator("[role=listbox]:visible [role=option]")
    opts.first.wait_for(state="visible", timeout=T)
    texts = [t.strip() for t in opts.all_inner_texts()]
    i = pick_option(texts, label)
    opts.nth(i).click(timeout=T)
    page.wait_for_timeout(400)
    got = button.inner_text().strip()
    if not values_equal(texts[i], got) and _norm(texts[i]) not in _norm(got):
        raise DriverError("Workday dropdown did not change", expected=texts[i], seen=got)
    return texts[i]


def workday_prompt(page: Page, search_input: Locator, path: list[str]) -> None:
    """Workday hierarchical prompt ("How did you hear about us"): click through ``path``."""
    search_input.scroll_into_view_if_needed(timeout=T)
    search_input.click(timeout=T)
    for step in path:
        opts = page.locator("[data-automation-id=promptOption]:visible, [data-automation-id=promptLeafNode]:visible")
        opts.first.wait_for(state="visible", timeout=T)
        texts = [t.strip() for t in opts.all_inner_texts()]
        i = pick_option(texts, step)
        opts.nth(i).click(timeout=T)
        page.wait_for_timeout(500)
    page.keyboard.press("Escape")


def workday_date(page: Page, month_spin: Locator, mmddyyyy: str) -> None:
    """Workday date made of month/day/year spinbuttons: focus the first, type digits."""
    month_spin.click(timeout=T)
    page.keyboard.type(re.sub(r"\D", "", mmddyyyy), delay=40)


# --- generic helpers -----------------------------------------------------------


def by_name_or_id(page: Page, name: str) -> Locator:
    return page.locator(f"[id='{name}'], [name='{name}']").first


def visible_text(page: Page, limit: int = 20000) -> str:
    return page.evaluate("(n) => (document.querySelector('main') || document.body).innerText.slice(0, n)", limit)


def describe_inputs(page: Page, root: str = "body") -> list[dict[str, Any]]:
    """Structural dump of form controls; used for live-schema checks and DOM fixtures."""
    return page.evaluate(
        """(root) => {
        const out = [];
        const r = document.querySelector(root) || document.body;
        const labelOf = (e) => {
            if (e.id) { const l = r.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) return l.innerText.trim(); }
            const al = e.getAttribute('aria-label'); if (al) return al.trim();
            const lb = e.getAttribute('aria-labelledby');
            if (lb) { const t = lb.split(' ').map(i => (document.getElementById(i)||{}).innerText||'').join(' ').trim(); if (t) return t; }
            const wrap = e.closest('label, fieldset, [class*="field"], [class*="question"]');
            if (wrap) { const l = wrap.querySelector('label, legend'); if (l) return l.innerText.trim(); }
            return '';
        };
        for (const e of r.querySelectorAll('input:not([type=hidden]), select, textarea, button[aria-haspopup=listbox]')) {
            const st = getComputedStyle(e);
            const type = e.tagName === 'SELECT' ? 'select' : e.tagName === 'TEXTAREA' ? 'textarea' : e.tagName === 'BUTTON' ? 'listbox' : (e.type || 'text');
            out.push({
                tag: e.tagName.toLowerCase(), type, id: e.id || '', name: e.name || '',
                label: labelOf(e).replace(/\\s+/g, ' ').slice(0, 300),
                required: e.required || e.getAttribute('aria-required') === 'true',
                visible: !!(e.offsetParent || st.position === 'fixed') || type === 'file',
                options: e.tagName === 'SELECT' ? [...e.options].map(o => o.text.trim()).filter(Boolean) : [],
                role: e.getAttribute('role') || '',
                maxlength: e.maxLength > 0 && e.maxLength < 100000 ? e.maxLength : 0,
                value: type === 'checkbox' || type === 'radio' ? e.checked : type === 'file' ? [...(e.files||[])].map(f => f.name).join('|') : type === 'listbox' ? e.innerText.trim() : type === 'password' ? '' : (e.value || ''),
            });
        }
        return out;
    }""",
        root,
    )

"""L1 widget library: reliable operations on form controls (Playwright sync API).

Every operation acts, then reads the control back; a mismatch raises
``DriverError`` with enough context for the repair agent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page
from playwright.sync_api import Error as PWError
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


_LEAVES_JS = r"""(term) => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e); return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const t = term.toLowerCase(); const out = [];
  const scope = document.querySelector('[role=listbox], [role=dialog], [role=menu]') ? '[role=option], [role=listbox] li, [role=menuitem], [role=dialog] li, [role=dialog] [tabindex]' : 'li, [role=option], [role=menuitem], div, span';
  for (const e of document.querySelectorAll(scope)) {
    if (!vis(e) || e.closest('input, textarea, select')) continue;
    const text = (e.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 90 || !text.toLowerCase().includes(t)) continue;
    if ([...e.children].some((c) => (c.innerText || '').toLowerCase().includes(t))) continue;      // the innermost element that says it
    e.setAttribute('data-autoapply-hit', String(out.length)); out.push(text);
    if (out.length >= 40) break;
  }
  return out;
}"""


def _search_term(label: str) -> str:
    """What to type to find an entry: its first part ("Vancouver" of "Vancouver, BC, Canada")."""
    return re.split(r"[,(/|]", str(label))[0].strip()[:30] or str(label)[:30]


def _best_entry(texts: list[str], wanted: str) -> int | None:
    """The entry that is the wanted one: the same text, or the same place written with fewer or more parts
    ("Vancouver, Canada" for "Vancouver, BC, Canada") - and only when exactly one entry is."""
    i = pick_option_or_none(texts, wanted)
    if i is not None:
        return i
    parts = lambda s: {p for p in (_norm(x) for x in re.split(r"[,/|()]", s)) if p}  # noqa: E731
    want = parts(wanted)
    hits = [k for k, t in enumerate(texts) if parts(t) and (parts(t) <= want or want <= parts(t))]
    return hits[0] if len(hits) == 1 else None


def search_entries(page: Page, loc: Locator, term: str) -> list[str]:
    """Open a pick-list and search it the way a person does: click it, type into whatever takes the typing (the list's own
    search box when it has one), and read what it then offers. The list is left open, with every entry found marked
    (data-autoapply-hit) so that one of them can be clicked. Typing is real key presses: setting a search box's value
    by program does not make such a list search, and on some it closes the list."""
    loc.scroll_into_view_if_needed(timeout=T)
    loc.click(timeout=T)
    page.wait_for_timeout(500)
    typing = page.evaluate("() => { const a = document.activeElement; return !!a && a.type !== 'password' && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.isContentEditable); }")
    if not typing:
        box = page.locator("input[type=search]:visible, [role=searchbox]:visible, input[placeholder*='earch' i]:visible, [role=combobox]:visible input:visible").last
        if box.count():
            box.click(timeout=T)
    page.keyboard.type(term, delay=70)
    found: list[str] = []
    for _ in range(12):      # the entries are fetched after the typing
        page.wait_for_timeout(350)
        found = page.evaluate(_LEAVES_JS, term)
        if found:
            break
    return found


def search_pick(page: Page, loc: Locator, label: str) -> str:
    """Choose ``label`` in a pick-list that has to be searched. Returns the entry that was chosen."""
    term = _search_term(label)
    texts = search_entries(page, loc, term)
    i = _best_entry(texts, label)
    if i is None:
        page.keyboard.press("Escape")
        raise DriverError("option not found or ambiguous" if texts else "the list offers nothing for this search", expected=label, seen="; ".join(texts[:12]))
    page.locator(f"[data-autoapply-hit='{i}']").first.click(timeout=T)
    page.wait_for_timeout(500)
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


def _words(v: object) -> list[str]:
    return [t for t in re.split(r"[\s,;|/()]+", str(v if v is not None else "").lower()) if t]


def shows_part(shown: object, entry: object) -> bool:
    """Does a control show only a part of the entry it was given?

    A list of phone codes has the entries "+1 United States", "+1 Canada", "+1 Bahamas" ...; once one is chosen its
    button reads "+1". What is shown is then true of the entry and says less than it: every word of it is a word of
    the entry, and the entry has more. Reading such a control cannot tell which entry it holds - the list can
    (held_choice)."""
    s, e = _words(shown), _words(entry)
    return bool(s) and len(s) < len(e) and all(w in e for w in s)


_OPTIONS = "[role=listbox]:visible [role=option]"
_HELD_JS = """(els) => { const e = els.find(x => x.getAttribute('aria-selected') === 'true' || x.getAttribute('aria-checked') === 'true'
    || x.getAttribute('aria-current') === 'true' || x.dataset.selected === 'true' || x.dataset.state === 'checked');
  return e ? (e.innerText || '').trim() : null; }"""


def held_choice(page: Page, button: Locator) -> str | None:
    """Which entry a closed list holds, asked of the list itself: it is opened, the entry it marks as chosen is read,
    and it is closed again without choosing anything. None when the list marks none (some do not), or cannot be opened -
    then nothing is known, which is not the same as "something else"."""
    try:
        button.scroll_into_view_if_needed(timeout=T)
        button.click(timeout=T)
        opts = page.locator(_OPTIONS)
        opts.first.wait_for(state="visible", timeout=T)
        held = opts.evaluate_all(_HELD_JS)
    except (PWTimeout, PWError):
        held = None
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    except PWError:
        pass
    return held


def workday_listbox(page: Page, button: Locator, label: str) -> str:
    """A dropdown rendered as a button that opens a list (<button aria-haspopup=listbox>, or role=combobox)."""
    button.scroll_into_view_if_needed(timeout=T)
    button.click(timeout=T)
    opts = page.locator(_OPTIONS)
    opts.first.wait_for(state="visible", timeout=T)
    texts = [t.strip() for t in opts.all_inner_texts()]
    i = pick_option(texts, label)
    opts.nth(i).click(timeout=T)
    page.wait_for_timeout(400)
    got = button.inner_text().strip()
    if values_equal(texts[i], got) or _norm(texts[i]) in _norm(got):
        return texts[i]
    if shows_part(got, texts[i]):
        # The button shows less than the entry ("+1" for "+1 Canada"): that it did not change to the entry's text is not
        # a failure. Whether the entry was taken is asked of the list. A list that marks another entry did not take it;
        # one that marks none has nothing to add - the entry was clicked and what is shown is part of it.
        held = held_choice(page, button)
        if held is None or values_equal(held, texts[i]):
            return texts[i]
        raise DriverError("the list holds another entry than the one that was chosen", expected=texts[i], seen=held)
    raise DriverError("Workday dropdown did not change", expected=texts[i], seen=got)


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
    # The box is often covered by the text that shows its value, so a click on it never lands; the keyboard works as
    # soon as the box has the focus, however it got it.
    try:
        month_spin.scroll_into_view_if_needed(timeout=T)
        month_spin.click(timeout=2500)
    except PWTimeout:
        month_spin.focus(timeout=T)
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

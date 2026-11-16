"""Driver for forms that were mapped by the agent (FormSchema.source == "agent").

The agent's reconnaissance records one CSS selector per question. This driver
replays an approved draft against those selectors with the ordinary widget
helpers. It is not in the registry: the executor builds one per schema.

It never submits. Driverless ATS always run with the manual policy, so the
user clicks Submit in the visible window.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, TimeoutError as PWTimeout

from .. import learned, timing
from . import widgets as w
from .base import DriverError, FormSchema, JobRef, PasswordPolicy, Question, norm_question

SUBMIT_RE = re.compile(r"\b(submit|send application|finish|complete application|confirm and)\b", re.I)
DONE_RE = r"thank(s| you) for (applying|your (application|interest|submission))|thank you|application (has been |was |is )?(received|submitted|sent|complete)|successfully (submitted|applied)|we(.ve| have) received|submission (received|complete)"


class FieldFailures(DriverError):
    """Some fields on a page could not be set; the rest were. Carries the list for the repair agent."""

    def __init__(self, page: int, failures: list[dict[str, str]]) -> None:
        super().__init__(
            f"{len(failures)} field(s) could not be filled", page=page,
            question="; ".join(f["label"] for f in failures)[:300], seen="; ".join(f["error"] for f in failures)[:400],
        )
        self.failures = failures

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "failures": self.failures}


# What a step of a form looks like. Forms keep every step in the page and show one (hidden forms and panels are ignored),
# and the first <form> of a page is often not the application at all (a hidden log-out form), so nothing here relies on
# "the first form" or on text that is not visible.
_STEP_JS = r"""() => {
  const vis = (e) => !!(e.offsetParent || e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const root = [...document.querySelectorAll('main, [role=main]')].find(vis) || document.body;
  const all = (sel) => [...root.querySelectorAll(sel)].filter(vis);
  // the form's own "you are here": standard marks first, then the ones progress bars use (anywhere on the page - a progress
  // bar often sits outside the main area), without the "current step 3 of 6" that is read out to screen readers
  const marks = '[aria-current=step], [aria-current=page], [aria-current=true], [role=tab][aria-selected=true], [data-automation-id=progressBarActiveStep], '
              + '[class*=step][class*=active], [class*=step][class*=current], [class*=progress] [class*=active]';
  const here = (scope) => [...scope.querySelectorAll(marks)].filter(vis)
      .map((e) => clean((e.innerText || e.getAttribute('aria-label') || '').replace(/(current|active)?\s*step \d+ of \d+/ig, ' '))).filter((t) => t && t.length > 2);
  let current = here(root);
  if (!current.length) current = here(document.body);
  const loading = /^\s*(loading|please wait)\b/i.test((root.innerText || '').slice(0, 200)) || !!document.querySelector('[data-automation-id=loadingSpinner], [aria-busy=true]');
  const heads = all('h1, h2, h3, legend');
  const controls = all('input:not([type=hidden]), select, textarea, [role=combobox], [role=radiogroup], [contenteditable=true]');
  const buttons = all('button, [role=button], input[type=submit], input[type=button]');
  const label = (e) => clean((e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label') || e.getAttribute('placeholder') || '');
  let title = current.find((t) => t) || '';
  if (!title && heads.length) {
    const first = controls[0] || buttons[0];
    let best = heads[0];
    if (first) for (const h of heads) if (h.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING) best = h;
    title = clean(best.innerText);
  }
  const parts = [current, heads.map((h) => clean(h.innerText)), controls.map((e) => e.tagName + ':' + (e.getAttribute('type') || '') + ':' + (e.getAttribute('name') || '') + ':' + label(e)),
                 buttons.map((b) => clean(b.innerText || b.value || b.getAttribute('aria-label')))];
  return { title, parts: JSON.stringify(parts), loading, controls: controls.length };
}"""


REVIEW_RE = re.compile(r"\b(review|summary|preview|check your (answers|application|details))\b|核对|预览|确认并提交|检查并提交", re.I)

# Is this control shown to the applicant now? Forms keep the controls of other steps in the page: in panels that are not
# displayed, or in collapsed sections that are clipped away (a summary with "show all answers"). A native input that is
# hidden behind its own styling (file inputs, custom radio buttons) is judged by its label or parent.
_SHOWN_JS = r"""(e) => {
  const laid = (n) => !!(n && (n.offsetParent || n.getClientRects().length));
  let n = (e.type !== 'file' && laid(e)) ? e : [e.labels && e.labels[0], e.parentElement].find(laid);
  if (!n || getComputedStyle(n).visibility === 'hidden') return false;
  const r = n.getBoundingClientRect();
  for (let a = n.parentElement; a && a !== document.documentElement; a = a.parentElement) {
    const st = getComputedStyle(a);
    if (st.visibility === 'hidden' || +st.opacity === 0) return false;
    if (/hidden|clip/.test(st.overflowY + st.overflowX)) {      // clipped away by a collapsed or cut-off container?
      const c = a.getBoundingClientRect();
      if (c.height < 2 || c.width < 2 || r.top >= c.bottom || r.bottom <= c.top || r.left >= c.right || r.right <= c.left) return false;
    }
  }
  return true;
}"""


_UNFOLD_JS = r"""() => {
  const says = /^(show|view|see|expand)\s+(all\s+)?(my\s+)?(answers|responses|details)$|^(show|expand)\s+all$|^(显示|展开|查看)(全部|所有)?(答案|回答|详情)?$/i;
  let n = 0;
  for (let round = 0; round < 3; round++) {
    const todo = [...document.querySelectorAll('button, a, [role=button], summary')].filter((e) => {
      const t = (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
      if (!says.test(t) || !(e.offsetParent || e.getClientRects().length)) return false;
      if (e.tagName === 'A') { const h = (e.getAttribute('href') || '').trim(); if (h && h !== '#' && !h.toLowerCase().startsWith('javascript')) return false; }
      // a button without a type counts as "submit" for the browser; what it says is what tells it apart here
      return (e.getAttribute('type') || '').toLowerCase() !== 'submit' && e.getAttribute('aria-expanded') !== 'true';
    });
    if (!todo.length || n >= 30) break;
    for (const e of todo.slice(0, 30 - n)) { e.click(); n++; }
  }
  return n;
}"""


def _same_label(label: str) -> re.Pattern[str]:
    """Matches a label that is this question: the same words from the start, followed by nothing or by decoration only."""
    words = r"\s+".join(re.escape(w) for w in label.split())
    return re.compile(r"^\s*" + words + r"\s*(?:$|[*:：?？(（\[\-–—]|(?:required|optional|必填|选填)\b)", re.I)


def _loc(page: Page, q: Question) -> Locator:
    """The control for a question: by the selector recorded when the form was read, else by its label.
    Many forms generate their ids (#input-16, #:r5:) afresh on every visit, so the recorded selector alone is not enough;
    the label is what the applicant saw and what stays the same."""
    sel = (q.locator or {}).get("selector") or q.id
    by_label_only = sel.startswith("@label:")  # a question the take-over discovered: it has no selector, only its label
    loc = page.locator("[data-autoapply-none]" if by_label_only else sel).first
    label = re.sub(r"\s+", " ", q.label or "").strip().rstrip("*").strip()
    positional = bool(POSITIONAL.search(sel))  # "the 3rd select": right only while the form shows exactly the fields it showed when it was read
    same = _same_label(label) if label else None
    if positional and label and q.type != "file":
        for make in (lambda: page.get_by_label(label, exact=True), lambda: page.get_by_role("combobox", name=label, exact=True),
                     lambda: page.get_by_role("radiogroup", name=same), lambda: page.get_by_role("group", name=same)):
            try:
                c = make()
                if c.count() == 1:
                    return c.first
            except Exception:  # noqa: BLE001
                continue
    try:
        if not by_label_only and loc.count():
            return loc
    except Exception:  # noqa: BLE001 - a selector this page cannot parse
        pass
    if label:
        # The label has to BE the question (give or take a "*", "(required)", a colon): a label that only contains the
        # question's words belongs to another question - "First Name" is not "Legal First Name".
        cands = [lambda: page.get_by_label(label, exact=True), lambda: page.get_by_role("radiogroup", name=same), lambda: page.get_by_role("group", name=same),
                 lambda: page.get_by_role("combobox", name=same), lambda: page.get_by_label(same),
                 # a question whose text sits in a label / legend / heading next to its control
                 lambda: page.locator("fieldset, [role=group], [role=radiogroup], .form-group, [class*=question], [class*=field]").filter(
                     has=page.locator("label, legend, h2, h3, h4, h5, h6, p, span, [class*=label], [class*=title]").filter(has_text=same)).last]
        for make in cands:
            try:
                c = make()
                if c.count():
                    return c.first if hasattr(c, "first") else c
            except Exception:  # noqa: BLE001
                continue
    return loc


def _tag(loc: Locator) -> tuple[str, str]:
    return loc.evaluate("(e) => [e.tagName.toLowerCase(), (e.getAttribute('type') || '').toLowerCase()]")


_BOXES_JS = r"""(root) => [...root.querySelectorAll('input[type=checkbox]')].map((i) => {
    const lab = (i.labels && i.labels[0]) || i.closest('label') || i.parentElement;
    return { label: ((lab && lab.innerText) || i.getAttribute('aria-label') || i.value || '').replace(/\s+/g, ' ').trim(), checked: i.checked };
})"""

_SUGGEST = "[role=option]:visible, .dropdown-results:visible > *, .pac-item:visible, ul.ui-autocomplete:visible li, [class*=suggestion]:visible li"
_chosen: dict[str, tuple[str, str]] = {}  # question id -> (draft wording, suggestion the form accepted for it)


def _is_group(loc: Locator, tag: str) -> bool:
    return tag not in ("select", "button", "input") and loc.locator("input[type=checkbox]").count() > 0


def _check_group(loc: Locator, q: Question, want: list[Any]) -> None:
    """Tick exactly the wanted options in a container of checkboxes."""
    seen = loc.evaluate(_BOXES_JS)
    idx = {w.pick_option([o["label"] for o in seen], str(v)) for v in want}
    boxes = loc.locator("input[type=checkbox]")
    for i, o in enumerate(seen):
        if (i in idx) != o["checked"]:
            w.set_checkbox(boxes.nth(i), i in idx)


def _autocomplete(page: Page, loc: Locator, q: Question, value: str) -> bool:
    """Text inputs that only accept a suggestion (city pickers): type, then take the best-matching suggestion."""
    hint = " ".join(str(loc.get_attribute(a) or "") for a in ("role", "aria-autocomplete", "id", "name", "class")).lower()
    if not ("combobox" in hint or "list" in hint.split() or re.search(r"location|city|autocomplete", hint + " " + q.label.lower())):
        return False
    loc.click(timeout=w.T)
    loc.fill("")
    first = value.split(",")[0].strip()
    loc.press_sequentially(first, delay=40)
    opts = page.locator(_SUGGEST)
    texts: list[str] = []
    for _ in range(12):
        page.wait_for_timeout(300)
        texts = [t.strip() for t in opts.all_inner_texts() if t.strip()]
        if texts:
            break
    if not texts:  # an ordinary text box after all
        loc.fill(value)
        return True
    parts = [p.strip().lower() for p in value.split(",")[1:] if p.strip()]
    cands = [(i, t) for i, t in enumerate(texts) if t.lower().startswith(first.lower())] or list(enumerate(texts))
    i, text = max(cands, key=lambda c: (sum(1 for p in parts if p in c[1].lower()), -c[0]))
    opts.nth(i).click(timeout=w.T)
    page.wait_for_timeout(300)
    _chosen[q.id] = (value, loc.input_value())
    return True


def set_value(page: Page, q: Question, value: Any) -> None:
    """Put ``value`` into the control for ``q``, choosing the widget helper from the element itself."""
    loc = _loc(page, q)
    if loc.count() == 0:
        raise DriverError("control not found", question=q.label, expected=str((q.locator or {}).get("selector") or q.id))
    tag, typ = _tag(loc)
    if q.type != "file" and learned.set_value(page, q, value, loc, tag):
        learned.wait_after(page, "field")
        return                  # filled the way that was learned for this field (learned.py); a way that fails falls through to here
    try:
        _set_ordinary(page, q, value, loc, tag, typ)
    finally:
        learned.wait_after(page, "field")      # a wait learned for "after a field" holds for every field, however it was filled


def _set_ordinary(page: Page, q: Question, value: Any, loc: Any, tag: str, typ: str) -> None:
    if tag in ("input", "textarea") and q.type not in ("file", "checkbox", "radio"):
        try:
            locked = loc.evaluate("(e) => e.readOnly || e.disabled")
        except Exception:  # noqa: BLE001
            locked = False
        if locked:  # the site fills this in itself and does not let it be changed (the account's e-mail, a fixed country)
            shown = (loc.input_value() or "").strip()
            if shown and (shown.lower() == str(value).strip().lower() or not str(value).strip()):
                return
            if shown:
                raise DriverError("the site has locked this field to a different value", question=q.label, expected=str(value), seen=shown)
            raise DriverError("the site has locked this field and left it empty", question=q.label, expected=str(value))
    if q.type == "file":
        if tag == "input" and typ == "file":
            w.upload(loc, [str(value)])
        else:  # a button that opens the file chooser
            with page.expect_file_chooser(timeout=w.T) as fc:
                loc.click(timeout=w.T)
            fc.value.set_files(str(value))
        page.wait_for_timeout(800)
    elif q.type in ("multiselect", "checkbox") and _is_group(loc, tag):
        _check_group(loc, q, value if isinstance(value, list) else ([] if value in (False, "False") else [value]))
    elif q.type == "checkbox":
        w.set_checkbox(loc, bool(value) and str(value) != "False")
    elif q.type == "radio":
        _radio(page, loc, tag, typ, str(value))
    elif q.type in ("select", "multiselect"):
        for v in value if isinstance(value, list) else [value]:
            if tag == "select":
                w.select_native(loc, str(v))
            elif tag == "button":
                w.workday_listbox(page, loc, str(v))
            else:
                try:
                    w.react_select(page, loc, str(v))
                except (DriverError, PWTimeout):
                    # not a list that shows its entries when opened: one that is searched (a location or school picker)
                    page.keyboard.press("Escape")
                    w.search_pick(page, loc, str(v))
    elif tag == "input" and _autocomplete(page, loc, q, str(value)):
        pass
    else:
        w.set_text(loc, str(value))


def _radios(page: Page, loc: Locator, tag: str, typ: str) -> Locator:
    """The radio buttons of a question. ``loc`` is one radio of the group, the group's container, or a part of the group
    (the label of one choice, which is what a take-over often records as the place of the question): then the group is
    the set of radios that share a name with the nearest one."""
    if tag == "input" and typ == "radio":
        name = loc.get_attribute("name")
        return page.locator(f"input[type=radio][name='{name}']") if name else loc
    radios = loc.locator("input[type=radio]")
    if radios.count():
        return radios
    name = loc.evaluate("""(e) => {
        const own = e.tagName === 'LABEL' && e.control && e.control.type === 'radio' ? e.control : null;
        for (let n = e; !own && n; n = n.parentElement) { const r = n.querySelector('input[type=radio]'); if (r) return r.name || ''; }
        return own ? own.name || '' : ''; }""")
    return page.locator(f"input[type=radio][name='{name}']") if name else radios


def _radio(page: Page, loc: Locator, tag: str, typ: str, value: str) -> None:
    radios = _radios(page, loc, tag, typ)
    labels = radios.evaluate_all(
        "(els) => els.map(e => ((e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label') || e.value || '').trim())"
    )
    if not labels:
        raise DriverError("no radio buttons in this group", expected=value)
    w.set_checkbox(radios.nth(w.pick_option(labels, value)), True)


def get_value(page: Page, q: Question) -> Any:
    loc = _loc(page, q)
    if loc.count() == 0:
        return None
    known = learned.get_value(page, q)
    if known is not NotImplemented:
        return known
    tag, typ = _tag(loc)
    if q.type == "file":
        if tag == "input" and typ == "file":
            names = loc.evaluate("(e) => [...(e.files || [])].map(f => f.name)")
            if names:
                return names[0]
        # custom uploaders replace the input: look for the file name near the control
        return loc.evaluate(
            r"""(e) => { let n = e; for (let i = 0; i < 4 && n; i++, n = n.parentElement) {
                 const m = (n.innerText || '').match(/[\w .()\-]+\.(pdf|docx?|txt|rtf)/i); if (m) return m[0].trim(); } return ''; }"""
        )
    if q.type in ("multiselect", "checkbox") and _is_group(loc, tag):
        return [o["label"] for o in loc.evaluate(_BOXES_JS) if o["checked"]]
    if q.type == "checkbox":
        return loc.is_checked()
    if q.type == "radio":
        return _radios(page, loc, tag, typ).evaluate_all(
            "(els) => { const e = els.find(x => x.checked); return e ? ((e.labels && e.labels[0] && e.labels[0].innerText) || e.value || '').trim() : ''; }"
        )
    if tag == "select":
        vals = loc.evaluate("(e) => [...e.selectedOptions].filter(o => o.value !== '').map(o => o.text.trim())")
        return vals if q.type == "multiselect" else (vals[0] if vals else "")
    if tag == "button":
        return (loc.inner_text() or "").strip()
    if q.type in ("select", "multiselect"):
        got = w.react_select_value(loc)
        if got or tag != "input":
            return got
        # a combobox that is a plain text input holding the chosen option's text (not a react-select)
    shown = loc.input_value()
    pair = _chosen.get(q.id)
    return pair[0] if pair and shown and shown == pair[1] else shown


def value_visible(page: Page, q: Question, expected: Any) -> bool:
    """Is the expected value shown at the control, even though it cannot be read back from it?
    Custom drop-downs keep their own <input> empty and show the choice as a chip or a label next to it; an uploaded
    file often replaces its upload button with the file's name somewhere on the page.
    The question's own label is left out of what is searched, and a value is matched as a whole word: "No" is not
    found in "Notice"."""
    want = [str(x).strip() for x in (expected if isinstance(expected, list) else [expected]) if str(x).strip()]
    if not want:
        return False
    try:
        if q.type == "file":
            names = [Path(w_).name for w_ in want]
            body = page.inner_text("body", timeout=5000) + " " + " ".join(page.evaluate(
                "() => [...document.querySelectorAll('input:not([type=hidden]):not([type=password])')].map(i => i.value).filter(Boolean)"))
            return all(n in body or Path(n).stem in body for n in names)
        loc = _loc(page, q)
        if not loc.count():
            return False
        near = loc.evaluate(r"""(e) => { let n = e, out = ''; for (let i = 0; i < 7 && n; i++, n = n.parentElement) {
                                 const vals = [...n.querySelectorAll('input:not([type=hidden]):not([type=password]), textarea')].map(x => x.value).join(' ');
                                 const next = (n.innerText || '') + ' ' + (n.value || '') + ' ' + vals;
                                 if (next.length > 700 && out) break; out = next; if (out.length > 700) break; }
                               return out.replace(/\s+/g, ' '); }""")
        low = near.lower().replace(re.sub(r"\s+", " ", q.label or "").strip().lower() or "~no label~", " ")
        return all(re.search(r"(?<![a-z0-9])" + re.escape(w_.lower()) + r"(?![a-z0-9])", low) is not None for w_ in want)
    except Exception:  # noqa: BLE001
        return False


FORWARD_RE = re.compile(r"^\s*(next|next step|next page|continue|save (and|&) (continue|next)|skip|skip (and|&) continue|skip for now|not now|no,? thanks|proceed|"
                        r"go to (the )?next step|下一步|继续|保存并继续|跳过|暂不)\s*[›»→>]*\s*$", re.I)
POSITIONAL = re.compile(r":nth-(match|of-type|child|last-child)|:nth\(|>>\s*nth=|:first-(child|of-type)|:last-(child|of-type)", re.I)
APPLY_RE = re.compile(r"^\s*(apply|apply now|apply here|apply online|apply for (this|the) (job|position|role)|apply to (this )?(job|position|role)|start (your )?application|"
                      r"begin application|申请|立即申请|申请(该|此)?(职位|岗位))\s*$", re.I)
NOTICE = re.compile(r"privacy (notice|statement|policy)|data (privacy|protection|processing)|how we (use|process|handle) your (data|information)|"
                    r"candidate privacy|personal (data|information)|隐私|个人信息|数据处理", re.I)
NOTICE_OK = re.compile(r"^(i understand|i acknowledge|acknowledge|i agree|agree|accept|accept all|ok|okay|got it|continue|confirm|我已了解|我知道了|同意|接受|确认|继续)\.?$", re.I)
NOTICE_NOT = re.compile(r"submit (your |my |the )?application|review (and|&) submit|提交申请", re.I)


def acknowledge_notice(page: Page) -> bool:
    """Close a blocking dialog that only informs about data handling. Returns True if one was acknowledged.
    Nothing else is ever clicked here: the dialog must talk about privacy / data, must not be about submitting,
    and the button must be a plain acknowledgement."""
    from .. import db

    if not db.get_setting("consent.acknowledge_notices"):
        return False
    try:
        dialogs = page.locator("[role=dialog]:visible, [role=alertdialog]:visible, dialog[open]")
        for i in range(min(dialogs.count(), 3)):
            d = dialogs.nth(i)
            text = re.sub(r"\s+", " ", d.inner_text(timeout=3000))[:4000]
            if not NOTICE.search(text) or NOTICE_NOT.search(text):
                continue
            btns = d.locator("button:visible, [role=button]:visible, input[type=submit]:visible, input[type=button]:visible")
            for j in range(min(btns.count(), 8)):
                b = btns.nth(j)
                label = re.sub(r"\s+", " ", (b.inner_text() or b.get_attribute("value") or "")).strip()
                if NOTICE_OK.match(label):
                    b.click(timeout=5000)
                    page.wait_for_timeout(1200)
                    return True
    except Exception:  # noqa: BLE001 - a dialog that will not answer is left to the next step
        pass
    return False


class GenericDriver:
    requires_login = False
    verify_per_page = True  # earlier pages are gone by the time the last one is reached
    password_policy = PasswordPolicy()

    def __init__(self, schema: FormSchema) -> None:
        self.ats = schema.ats
        self.schema = schema

    def detect(self, url: str) -> JobRef | None:
        return None

    def open_application(self, page: Page, ref: JobRef) -> None:
        page.goto(self.schema.url or ref.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        self.reveal_form(page)

    def reveal_form(self, page: Page) -> bool:
        """Many postings show the form only after "Apply for this job" is clicked (the address stays the same, so the
        address recorded with the draft leads to the posting, not the form). If none of the mapped controls is there,
        click that button. Returns True when a click was made."""
        first = [q for q in self.schema.questions if q.page == 0 and q.type != "file"][:12]   # file inputs are usually hidden
        try:
            if not first or any(_loc(page, q).count() and _loc(page, q).first.is_visible() for q in first):
                return False
        except Exception:  # noqa: BLE001
            return False
        for name in [n for n in (self.schema.extra.get("apply_button"),) if n] + [APPLY_RE]:
            for role in ("button", "link"):
                btn = page.get_by_role(role, name=name).first
                try:
                    if btn.count() and btn.is_visible():
                        label = (btn.inner_text() or "").strip()
                        if SUBMIT_RE.search(label):
                            continue
                        btn.click(timeout=w.T)
                        page.wait_for_timeout(2500)
                        return True
                except Exception:  # noqa: BLE001 - not clickable: try the next candidate
                    continue
        return False

    def live_questions(self, page: Page, page_index: int = 0) -> list[Question]:
        """The mapped questions whose control is on the page now (a missing control shows up as 'removed')."""
        return [Question(**{**q.__dict__, "options": []}) for q in self.schema.questions if q.page == page_index and _loc(page, q).count() > 0]

    def present(self, page: Page, answers: dict[str, Any]) -> list[Question]:
        """The answered questions whose control is on the page right now, whatever page they were recorded on.
        A form with several steps shows them in its own order, skips steps it already has, and resumes where it stopped."""
        out = []
        # "The file box" names no box in particular: on a form with several steps it matches the résumé box of one step
        # and the transcript box of another. Such an upload belongs to the step it was read on, and nowhere else.
        title = norm_question(self.step_title(page))
        here = next((k for k, name in enumerate(self.schema.pages or []) if title and (title in norm_question(str(name)) or norm_question(str(name)) in title)), -1)
        for q in self.schema.questions:
            if q.id not in answers:
                continue
            sel = str((q.locator or {}).get("selector") or "")
            if q.type == "file" and re.fullmatch(r"input\[type=['\"]?file['\"]?\]", sel.strip()) and here >= 0 and q.page != here:
                continue
            try:
                loc = _loc(page, q)
                if not loc.count():
                    continue
                if loc.evaluate(_SHOWN_JS):
                    out.append(q)
            except Exception:  # noqa: BLE001 - a selector this page cannot parse: not here
                continue
        return out

    def forward(self, page: Page) -> bool:
        """Go to the next step with the form's own forward button: the ones recorded when the form was read, else the usual
        names (Next, Continue, Save and continue, Skip & continue ...). Never a button that submits. True when the page changed."""
        before = self.signature(page)
        names: list[Any] = [n for n in (self.schema.extra.get("next_buttons") or []) if n and not SUBMIT_RE.search(n)] + [FORWARD_RE]
        for name in names:
            for role in ("button", "link"):
                try:
                    for btn in page.get_by_role(role, name=name, exact=isinstance(name, str)).all()[:6]:
                        if not btn.is_visible() or not btn.is_enabled():
                            continue
                        if SUBMIT_RE.search((btn.inner_text() or "").strip()):
                            continue
                        btn.click(timeout=w.T)
                        for _ in range(12):
                            page.wait_for_timeout(500)
                            if self.signature(page) != before:
                                return True
                except Exception:  # noqa: BLE001 - not clickable: try the next candidate
                    continue
        return False

    @staticmethod
    def _buttons(page: Page) -> list[str]:
        # Read in one go, inside the page. Going through the buttons one by one from outside broke whenever the page drew
        # itself again in between (a busy single-page form does, constantly) - and "no buttons" then read as "this is not
        # the last step", on a page with a Submit button in plain sight.
        js = """() => [...document.querySelectorAll('button, [role=button], input[type=submit], input[type=button]')]
            .filter((e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e); return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; })
            .map((e) => (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim()).filter(Boolean).slice(0, 200)"""
        for _ in range(3):
            try:
                return list(page.evaluate(js))
            except Exception:  # noqa: BLE001 - between two renders: look again
                page.wait_for_timeout(300)
        return []

    def at_review(self, page: Page) -> bool:
        """Is this the last step: a button that submits is showing and there is no forward button?"""
        texts = self._buttons(page)
        return any(SUBMIT_RE.search(t) for t in texts) and not any(FORWARD_RE.match(t) for t in texts)

    def is_review_step(self, page: Page) -> bool:
        """The last step, and the form itself calls it a review: a summary of the answers with the button that submits.
        Nothing is filled in here - whatever controls the page still carries belong to the steps it summarises."""
        return self.at_review(page) and bool(REVIEW_RE.search(self.step_title(page)))

    @staticmethod
    def open_summaries(page: Page) -> int:
        """A review page often keeps the answers of each step folded ("Show all answers"). Unfold them, so that what the
        page will send can be compared with the draft. Only controls that unfold something on the page: never a link
        that leads elsewhere, never a button that goes on or submits. Returns how many were opened."""
        try:
            return int(page.evaluate(_UNFOLD_JS))
        except Exception:  # noqa: BLE001
            return 0

    def form_gone(self, page: Page, answers: dict[str, Any]) -> bool:
        """No question of the application and no button that leads on or submits is showing any more."""
        texts = self._buttons(page)
        return not any(SUBMIT_RE.search(t) or FORWARD_RE.match(t) for t in texts) and not self.present(page, answers)

    @staticmethod
    def settle(page: Page, seconds: float = 12) -> None:
        """Wait until the step has stopped changing: between two steps a form shows a frame without its questions, and a
        step that is read then looks like one with nothing on it (three of those in a row once ended a walk as "going
        round in circles")."""
        last, same = "", 0
        for _ in range(int(seconds / 0.5)):
            try:
                now_ = page.evaluate(_STEP_JS)
            except Exception:  # noqa: BLE001 - the page is being replaced
                now_ = {"parts": "", "loading": True, "controls": 0}
            same = same + 1 if (now_["parts"] == last and not now_.get("loading")) else 0
            last = now_["parts"]
            if same >= 2 and (now_.get("controls") or same >= 6):      # steady, and showing something (or steadily empty for 3 s)
                return
            page.wait_for_timeout(500)

    @staticmethod
    def signature(page: Page) -> str:
        """Changes when the form shows another step (the address often stays the same). A step is told by what can be
        seen of it: the step the form marks as current, the headings, the controls and the buttons. Error messages are
        not part of it - a form that refuses to go on and shows a message is still on the same step."""
        import hashlib

        try:
            seen = page.evaluate(_STEP_JS)["parts"]
        except Exception:  # noqa: BLE001
            seen = ""
        return page.url + "|" + hashlib.sha256(seen.encode()).hexdigest()[:16]

    @staticmethod
    def step_title(page: Page) -> str:
        """The step the form marks as current, else the heading above its first visible control."""
        try:
            return page.evaluate(_STEP_JS)["title"] or ""
        except Exception:  # noqa: BLE001
            return ""

    def fill_page(self, page: Page, schema: FormSchema, page_index: int, answers: dict[str, Any]) -> None:
        self.fill_questions(page, [q for q in schema.questions if q.page == page_index and q.id in answers], answers, page_index)

    def _same_entries_other_order(self, page: Page, todo: list[Question], answers: dict[str, Any]) -> dict[str, Any]:
        """Text fields of this step that together already hold exactly the wanted entries, only in other places (three
        website rows carried over from an earlier application): they are left where they are, and the answers take the
        order the form has. Retyping them makes two rows equal for a moment; forms that refuse duplicates then keep an
        error on the step and will not go on. Returns {question id: the value its field holds}."""
        norm = lambda v: str(v or "").strip().rstrip("/").lower()  # noqa: E731
        off: list[tuple[Question, str]] = []
        for q in todo:
            if q.type not in ("text", "textarea") or isinstance(answers.get(q.id), (list, dict, bool)):
                continue
            try:
                loc = _loc(page, q)
                if not loc.count() or _tag(loc)[0] not in ("input", "textarea"):
                    continue
                cur = loc.input_value(timeout=2000)
            except Exception:  # noqa: BLE001
                continue
            if norm(cur) != norm(answers[q.id]) and cur.strip():      # an empty field is simply to be filled; it is no part of this
                off.append((q, cur))
        if len(off) < 2:
            return {}
        if sorted(norm(cur) for _, cur in off) != sorted(norm(answers[q.id]) for q, _ in off):
            return {}
        return {q.id: cur for q, cur in off}

    def fill_questions(self, page: Page, todo: list[Question], answers: dict[str, Any], page_index: int = 0) -> None:
        failures = []
        acknowledge_notice(page)
        self.kept = self._same_entries_other_order(page, todo, answers)
        answers.update(self.kept)      # from here on the answer of each of these fields is what the field holds
        todo = [q for q in todo if q.id not in self.kept]
        # Files first: many forms parse an uploaded résumé and overwrite other fields with what they find.
        files = [q for q in todo if q.type == "file"]
        for q in files + [q for q in todo if q.type != "file"]:
            try:
                if q.type == "file" and Path(str(answers[q.id])).name in page.inner_text("body", timeout=5000):
                    continue      # the form already shows this very file name (kept from an earlier visit): not uploaded a second time
                with timing.span("driver", "field", label=q.label[:60], type=q.type, page=page_index):
                    set_value(page, q, answers[q.id])
                if q.type == "file" and q is files[-1]:
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:  # noqa: BLE001 - a busy page is not an error
                        pass
                    page.wait_for_timeout(1500)
                if q.type == "file":
                    acknowledge_notice(page)  # uploading a résumé is what usually brings the data-privacy notice up
            except Exception as e:  # noqa: BLE001 - collect, then let the repair agent see all of them
                if acknowledge_notice(page):  # the control was covered by a notice: one more try now that it is gone
                    try:
                        set_value(page, q, answers[q.id])
                        continue
                    except Exception as e2:  # noqa: BLE001
                        e = e2
                failures.append({"id": q.id, "label": q.label, "error": f"{type(e).__name__}: {e}"[:200]})
        # Documents the form kept from an earlier application, next to the ones just attached: named, so that the
        # executor has them replaced instead of sending an old résumé along with the new one.
        self.stale_files = []
        for q in files:
            try:
                want = Path(str(answers[q.id])).name
                near = _loc(page, q).evaluate(
                    r"""(e) => { let n = e; for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
                         const m = (n.innerText || '').match(/[\w .()\-]+\.(pdf|docx?|rtf)/ig); if (m && m.length) return m.map(x => x.trim()); } return []; }""")
                old = [x for x in dict.fromkeys(near) if x and x != want and want not in x]
                if old:
                    self.stale_files.append({"label": q.label, "want": want, "old": old[:4]})
            except Exception:  # noqa: BLE001
                continue
        if failures:
            raise FieldFailures(page_index, failures)

    def next_page(self, page: Page) -> bool:
        if self.forward(page):
            return True
        names = self.schema.extra.get("next_buttons") or []
        for name in [n for n in names if n] + ["Next", "Continue", "Save and Continue", "Save & Continue"]:
            if SUBMIT_RE.search(name):
                continue
            btn = page.get_by_role("button", name=name, exact=True).or_(page.get_by_role("link", name=name, exact=True)).first
            if btn.count() and btn.is_visible():
                before = page.url + str(len(page.content()))
                btn.click(timeout=w.T)
                page.wait_for_timeout(2000)
                return page.url + str(len(page.content())) != before
        return False

    def read_back(self, page: Page, schema: FormSchema, page_index: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for q in schema.questions:
            if page_index is not None and q.page != page_index:
                continue
            try:
                v = get_value(page, q)
            except Exception:  # noqa: BLE001 - an unreadable control is simply not verified
                continue
            if v is not None:
                out[q.id] = v
        return out

    def submit(self, page: Page) -> None:
        """Press the button that sends the application. Called by the executor only: for an approved draft whose form was
        filled, read back and left nothing for the applicant, under a submit policy that says the program submits.
        The button has to be the one that sends - on the last step, by its name - and there has to be exactly one."""
        if not self.at_review(page):
            raise DriverError("not on the last step of the form: nothing is submitted", seen=self.step_title(page))
        root = page.locator("main, [role=main]").first if page.locator("main, [role=main]").count() else page.locator("body")
        btns = root.locator("button:visible, input[type=submit]:visible, [role=button]:visible")
        hits = [i for i in range(btns.count()) if SUBMIT_RE.search((btns.nth(i).inner_text() or btns.nth(i).get_attribute("value") or "").strip())
                and not re.search(r"\b(later|draft|save)\b", (btns.nth(i).inner_text() or ""), re.I)]
        if len(hits) != 1:
            raise DriverError("could not tell which button submits the application", seen=f"{len(hits)} candidates")
        btns.nth(hits[0]).click(timeout=w.T)
        # The page after it: a confirmation, or the form saying what is wrong. A form that sends in place shows neither
        # for a while - its button reads "Sending..." and nothing else has changed. That is not "the form is gone":
        # deciding then (it once took the program 0.6 s) reports a failure for an application that is on its way.
        quiet = 0
        for i in range(120):
            page.wait_for_timeout(500)
            try:
                if self.confirmation(page) is not None:
                    break
                busy = self.sending(page)
                if not busy and i >= 6 and self.form_gone(page, {}):
                    break
                if not busy and any(SUBMIT_RE.search(t) for t in self._buttons(page)):
                    quiet += 1      # the button is back as it was: the site answered (an error under a field, most likely)
                    if quiet >= 8:
                        break
                else:
                    quiet = 0
            except Exception:  # noqa: BLE001 - between two pages
                continue

    @staticmethod
    def sending(page: Page) -> bool:
        """Is the form in the middle of sending: a button that says so, or a busy mark on the form?"""
        try:
            return bool(page.evaluate("""() => {
              const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const said = [...document.querySelectorAll('button, [role=button], input[type=submit]')].some((e) => vis(e)
                && /^(sending|submitting|processing|uploading|please wait|loading|saving)\\b|正在(提交|发送)|提交中|发送中/i.test((e.innerText || e.value || '').trim()));
              const busy = [...document.querySelectorAll('form[aria-busy=true], [role=progressbar], [aria-busy=true] button')].some(vis);
              return said || busy;
            }"""))
        except Exception:  # noqa: BLE001
            return True

    def confirmation(self, page: Page) -> dict[str, Any] | None:
        body = page.inner_text("body")
        m = re.search(rf"[^\n]*({DONE_RE})[^\n]*", body, re.I) or re.search(rf"[^\n]*({DONE_RE})[^\n]*", page.title() or "", re.I)   # some sites say it in the title only
        if m:
            return {"url": page.url, "text": m.group(0).strip()[:300]}
        if re.search(r"[?&]result=(success|submitted|duplicate)\b", page.url, re.I):      # the address says it; keep what the page shows with it
            return {"url": page.url, "text": " ".join(body.split())[:300]}
        return None

    def already_applied(self, page: Page, ref: JobRef) -> bool:
        return False

    def form_errors(self, page: Page) -> list[str]:
        from . import audit

        return audit.texts([i for i in audit.page_issues(page) if i["kind"] != "empty_required"])[:10]

    @staticmethod
    def file_name(path: str) -> str:
        return Path(path).name

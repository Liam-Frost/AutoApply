"""What the form itself says is wrong, read from the page without any model.

After a page has been filled, the form is the authority on whether it is complete: it marks controls as invalid,
prints messages next to them, and has required controls that are still empty (often ones that only appeared after an
answer was chosen, which no draft could have known about). ``page_issues`` collects exactly that. The executor runs it
after the driver and again after the AI take-over, so nobody - driver, agent or program - can call a page filled
while the page says otherwise.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

_JS = r"""() => {
  const vis = (e) => { if (!e || !e.getBoundingClientRect) return false; const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
                       return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => ((e && e.innerText) || '').replace(/\s+/g, ' ').trim();
  const byIds = (ids) => (ids || '').split(/\s+/).filter(Boolean).map((i) => txt(document.getElementById(i))).filter(Boolean).join(' ');
  const labelOf = (e) => {
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l && txt(l)) return txt(l); }
    const lb = byIds(e.getAttribute('aria-labelledby')); if (lb) return lb;
    const al = e.getAttribute('aria-label'); if (al) return al.trim();
    const wrap = e.closest('label, fieldset, [role=group], [role=radiogroup], [class*="field"], [class*="question"], [class*="form-group"]');
    if (wrap) { const l = wrap.querySelector('label, legend'); if (l && txt(l)) return txt(l); }
    return (e.getAttribute('placeholder') || e.name || '').trim();
  };
  const clean = (s) => s.replace(/\s*\*\s*$/, '').trim().slice(0, 200);
  const selOf = (e) => e.id ? `[id="${e.id}"]` : (e.name ? `${e.tagName.toLowerCase()}[name="${e.name}"]` : '');
  const PLACEHOLDER = /^(select|choose|search|please select|pick|--|type to search|start typing)\b/i;
  const PROBLEM = /error|invalid|not valid|required|cannot|can't|must|missing|blank|incorrect|please (enter|select|provide|choose|complete|fill|upload)|enter a valid|too (long|short)|at least|必填|不能为空|无效|有误|请(输入|选择|填写|上传)/i;
  const out = []; const said = new Set(); const flagged = new Set();

  // 1. controls the form marks as invalid, with the message it attaches to them
  for (const e of document.querySelectorAll('[aria-invalid="true"]')) {
    if (!vis(e)) continue;
    const msg = byIds((e.getAttribute('aria-describedby') || '') + ' ' + (e.getAttribute('aria-errormessage') || ''));
    const key = selOf(e) || labelOf(e); if (flagged.has(key)) continue; flagged.add(key);
    if (msg) said.add(msg);
    out.push({ kind: 'invalid', label: clean(labelOf(e)), message: msg.slice(0, 240), selector: selOf(e), value: (e.value || '').slice(0, 80) });
  }

  // 2. error messages printed on the page that are not already attached to a control above
  const ERR = '[role=alert], [aria-live=assertive], .error, .field-error, .invalid-feedback, [class*="error-message"], [class*="errorMessage"], '
            + '[class*="error_message"], [class*="field-error"], [class*="fieldError"], [class*="validation-error"], [class*="input-error"]';
  for (const e of document.querySelectorAll(ERR)) {
    if (!vis(e)) continue;
    const t = txt(e); if (!t || t.length > 240 || !PROBLEM.test(t)) continue;
    if ([...said].some((s) => s.includes(t) || t.includes(s))) continue;
    said.add(t);
    out.push({ kind: 'message', label: '', message: t, selector: '', value: '' });
  }

  // 3. required controls that are still empty
  const required = (e) => e.required || e.getAttribute('aria-required') === 'true';
  const groups = new Set();
  for (const e of document.querySelectorAll('input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=button]), select, textarea')) {
    if (!required(e) || e.disabled || e.readOnly) continue;
    const type = (e.type || '').toLowerCase();
    let empty;
    if (type === 'radio') {
      if (!e.name || groups.has(e.name)) continue; groups.add(e.name);
      const all = [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(e.name)}"]`)];
      if (!all.some(vis) && !all.some((r) => vis(r.closest('label') || r.parentElement))) continue;
      empty = !all.some((r) => r.checked);
    } else if (type === 'checkbox') {
      if (!vis(e) && !vis(e.closest('label') || e.parentElement)) continue;
      empty = !e.checked;
    } else {
      if (!vis(e)) continue;
      empty = !(e.value || '').trim();
      if (empty && e.getAttribute('role') === 'combobox') {
        // a custom drop-down keeps its <input> empty and shows the choice (or its chips) beside it
        let n = e.parentElement, shown = '';
        for (let i = 0; i < 2 && n; i++, n = n.parentElement) { shown = txt(n); if (shown) break; }
        shown = shown.replace(e.getAttribute('placeholder') || '\u0000', '').replace(/[×✕]/g, '').trim();
        if (shown && !PLACEHOLDER.test(shown)) empty = false;
      }
    }
    if (!empty) continue;
    const key = selOf(e) || labelOf(e); if (flagged.has(key)) continue; flagged.add(key);
    out.push({ kind: 'empty_required', label: clean(labelOf(e)), message: '', selector: selOf(e), value: '' });
  }
  for (const g of document.querySelectorAll('[role=radiogroup][aria-required="true"], [role=group][aria-required="true"]')) {
    if (!vis(g)) continue;
    if (g.querySelector('input[type=radio], input[type=checkbox], [role=radio], [role=checkbox]')) {
      if (g.querySelector('input:checked, [aria-checked="true"]')) continue;
    } else {
      // a group without tick boxes is a pick-list that shows what was chosen as chips or text (multi-select widgets)
      const shown = txt(g).replace(/[×✕]/g, '').trim();
      if (shown && !PLACEHOLDER.test(shown)) continue;
    }
    const label = clean(byIds(g.getAttribute('aria-labelledby')) || g.getAttribute('aria-label') || txt(g.querySelector('legend, label')));
    if (flagged.has(label)) continue; flagged.add(label);
    out.push({ kind: 'empty_required', label, message: '', selector: g.id ? `[id="${g.id}"]` : '', value: '' });
  }
  return out.slice(0, 40);
}"""


def page_issues(page: Page) -> list[dict[str, Any]]:
    """Problems the form shows right now: [{kind: invalid | message | empty_required, label, message, selector, value}].
    An unreadable page gives an empty list: this check adds findings, it never blocks on its own failure."""
    try:
        return page.evaluate(_JS)
    except Exception:  # noqa: BLE001 - navigation in progress, closed window
        return []


def describe(issue: dict[str, Any]) -> str:
    """One line for a person or a model."""
    label, msg = issue.get("label") or "", issue.get("message") or ""
    if issue.get("kind") == "empty_required":
        return f"{label or 'a required field'}: required, still empty"
    if label and msg:
        return f"{label}: {msg}"
    return msg or f"{label}: the form marks this field as invalid"


def not_stale(now: list[dict[str, Any]], before: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the form reports now, without free-standing messages that were already there before the fields were changed.
    Such a message says what was wrong when the form last checked; many forms leave it until they are asked again. A
    field the form marks invalid, or a required field that is empty, is read from the control itself and always counts."""
    old = {describe(it) for it in before if it.get("kind") == "message"}
    return [it for it in now if not (it.get("kind") == "message" and describe(it) in old)]


def texts(issues: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for it in issues:
        d = describe(it)
        if d not in seen:
            seen.append(d)
    return seen

"""Was Submit pressed on this page?

A run can end without having seen the page that says "thank you": the applicant closed the window, the site was slow,
the confirmation is worded in a way nothing recognises. What to do next depends on one fact - whether the form was
sent. "Fill it in again" is right when it was not and a second application when it was. So the page is watched for it:
a form being submitted, or a button that submits being pressed where the site sends without a form. What is seen is
kept in the tab (it has to outlive the page that Submit leaves behind).

Watching does not stop or change anything on the page.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("autoapply.submitwatch")

KEY = "__autoapply_submit"

# the same words as ats.generic_driver.SUBMIT_RE: what a button that sends an application is called
_JS = r"""(() => {
  if (window.__autoapplyWatch) return; window.__autoapplyWatch = true;
  const KEY = '%s';
  const before = () => {
    let raw = '';
    try { raw = sessionStorage.getItem(KEY) || ''; } catch (e) { /* storage is closed to this page: what this page itself saw is all there is */ }
    try { return JSON.parse(raw || window[KEY] || 'null'); } catch (e) { return null; }
  };
  const mark = (how, sends, by, size) => {
    const was = before();
    if (was && was.sends && !sends) return;      // "the application was sent" is not written over by a later "went on a step"
    const seen = JSON.stringify({how, sends: !!sends, by: (by || '').slice(0, 120), size: size || 0, url: location.href, at: Date.now()});
    try { sessionStorage.setItem(KEY, seen); } catch (e) { /* storage is closed to this page */ }
    window[KEY] = seen;
  };
  const SENDS = /\b(submit|send application|finish|complete application|confirm and)\b/i;
  const name = (el) => [el.innerText, el.value, el.getAttribute && el.getAttribute('aria-label'), el.title].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
  document.addEventListener('submit', (ev) => {
    // A form is sent when it goes on a step as much as when the application goes out. Which it was is told by the
    // button that sent it; sent without one (Enter in a field, script), by whether the form has a button that sends.
    const f = ev.target, by = ev.submitter;
    const buttons = f && f.querySelectorAll ? [...f.querySelectorAll('button, input[type=submit], input[type=image]')].filter((b) => !b.type || b.type === 'submit' || b.type === 'image') : [];
    // (how much of a form it is: a search box with a button called "Submit" is a form of one field)
    const size = f && f.querySelectorAll ? [...f.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea')].length : 0;
    mark('form', by ? SENDS.test(name(by)) : buttons.some((b) => SENDS.test(name(b))), by ? name(by) : '', size);
  }, true);
  document.addEventListener('click', (ev) => {
    const b = ev.target && ev.target.closest && ev.target.closest('button, [role=button], input[type=submit], input[type=button], a');
    // a button of a form says it by the form's own event (which does not come when the form refuses to be sent);
    // one that is not part of a form is all there is to see where the site sends by itself
    if (b && !b.form && SENDS.test(name(b))) mark('button', true, name(b), 99);
  }, true);
})()""" % KEY


def install(page: Any) -> None:
    """Watch this page and the ones that follow it in the same window."""
    try:
        page.context.add_init_script(_JS)
    except Exception as e:  # noqa: BLE001 - a window that cannot be watched is still a window the applicant can use
        log.info("could not watch the window for a submission: %s", type(e).__name__)
    try:
        page.evaluate(_JS)
    except Exception as e:  # noqa: BLE001
        log.info("could not watch the page for a submission: %s", type(e).__name__)


def sent(page: Any) -> dict[str, Any] | None:
    """What was seen of the APPLICATION being sent in this window: the control that sends it was pressed, or a form was
    sent by it (not a step of the form being left by "Next")."""
    got = seen(page)
    return got if got and got.get("sends") and int(got.get("size") or 0) >= 3 else None


def seen(page: Any) -> dict[str, Any] | None:
    """What was seen of a form being sent in this window ({how: "form" | "button", sends, by, url, at}), if anything."""
    try:
        raw = page.evaluate("() => { try { return sessionStorage.getItem('%s') || window['%s'] || ''; } catch (e) { return window['%s'] || ''; } }" % (KEY, KEY, KEY))
    except Exception:  # noqa: BLE001 - between two pages, or the window is gone: ask again later
        return None
    if not raw:
        return None
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):       # not what the watcher writes: nothing was seen
        return None
    return got if isinstance(got, dict) and got.get("how") else None

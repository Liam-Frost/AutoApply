"""No tool of an agent sends an application.

An agent reads forms, fills what the driver could not, finds the way to the next step. Sending the application is not
among the things it does: that is the applicant's decision, carried out by the executor after the read-back, or by the
applicant in their window.

That used to be a line in the click tool: "refuse when the button's text says Submit". It looked at the text and the
value only, so a button that is named by an ``aria-label`` (an icon) passed; and it was one tool of several that act on
whatever selector they are given - the tool that opens a list clicks, the tool that types clicks first, and the key tool
would press Space on a focused Submit button, or Enter in a field (which sends the form) as long as some list was open
somewhere on the page.

So the question "would this send the application?" is asked here, of the element the action lands on, by every tool
that clicks or presses a key - the reading agent's, the take-over agent's, and the tools a learned plugin adds (which
get a page that asks it for them, ``guarded``).

What is asked:
- a click: is the target, or the button it is inside, named like a control that sends an application? Named by any
  of the ways a control gets a name: its text, its value, ``aria-label``, ``title``, ``aria-labelledby``, an image's
  ``alt``. "Next", "Continue", "Save and continue" are not such names, whatever the button's type: many forms use a
  submit-type button to go on.
- Space or Enter on something that is pressed like a button: the same as a click on it.
- Enter in a field: sends the form the field is in. Allowed only where Enter means "take this entry" - the focus is in
  a list of options or in the box that owns an open one - and in a text area, where it is a new line.
- typing: a line break in what is typed is an Enter (see above).

It cannot be asked of script run inside the page; a plugin's source is checked for that when it is learned
(``scan_script``). And whatever gets past all of it is seen (submitwatch) and treated as what it is: a submission
whose outcome is not known.
"""
from __future__ import annotations

import re
from typing import Any

from .ats.generic_driver import SUBMIT_RE


class Refused(PermissionError):
    """The action would send the application (or cannot be shown not to)."""


# what the action lands on: the element itself, or - for a click on something inside a button - the button
_ABOUT = r"""(el) => {
  el = el || document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return {none: true};
  const pressed = el.closest ? el.closest('button, [role=button], a[href], [role=link], input[type=submit], input[type=button], input[type=image], input[type=reset], summary') : null;
  const t = pressed || el;
  const txt = (n) => ((n && (n.innerText || n.textContent)) || '').replace(/\s+/g, ' ').trim();
  const by = (t.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map((id) => txt(document.getElementById(id))).join(' ');
  const pics = [...t.querySelectorAll('img[alt], svg title, [aria-label]')].map((n) => n.getAttribute('alt') || n.getAttribute('aria-label') || txt(n)).join(' ');
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
  const role = (el.getAttribute('role') || '').toLowerCase();
  const owns = el.getAttribute('aria-controls') || el.getAttribute('aria-owns') || '';
  const open = (id) => { const n = id && document.getElementById(id); return !!(n && n.getClientRects().length); };
  return {
    pressed: !!pressed,
    name: [txt(t), t.value, t.getAttribute('aria-label'), t.title, by, pics].filter(Boolean).join(' | ').slice(0, 300),
    tag, type, role,
    area: tag === 'textarea' || el.isContentEditable,
    field: (tag === 'input' && !['button', 'submit', 'image', 'reset', 'checkbox', 'radio', 'file'].includes(type)) || tag === 'select',
    // "Enter takes this entry": the focus is on an option or inside a list of them, or in the box that owns an open list
    in_list: !!(el.closest && el.closest('[role=listbox], [role=option], [role=menu], [role=menuitem], [role=tree], [role=grid]'))
             || el.getAttribute('aria-expanded') === 'true' || !!el.getAttribute('aria-activedescendant') || owns.split(/\s+/).some(open),
  };
}"""


def about(page: Any, loc: Any = None) -> dict[str, Any]:
    """What an action would land on: ``loc``, or what has the focus."""
    try:
        got = loc.evaluate(_ABOUT) if loc is not None else page.evaluate(_ABOUT)
    except Exception as e:  # noqa: BLE001 - nothing is there to act on, or the page is between two addresses
        raise Refused(f"refused: could not look at what this would act on ({type(e).__name__}); read the page again and name the control") from e
    return got if isinstance(got, dict) else {"none": True}


def _sends(info: dict[str, Any]) -> bool:
    return bool(info.get("pressed")) and bool(SUBMIT_RE.search(str(info.get("name") or "")))


def check_click(page: Any, loc: Any) -> dict[str, Any]:
    """May this be clicked? Raises Refused when it is the control that sends the application. Returns what it is."""
    info = about(page, loc)
    if _sends(info):
        raise Refused(f"refused: '{str(info['name'])[:80]}' sends the application; that is not available to the agent")
    return info


def check_key(page: Any, key: str, loc: Any = None) -> dict[str, Any]:
    """May this key be pressed on ``loc`` (or on what has the focus)?"""
    if key not in ("Enter", "Space", " ", "NumpadEnter"):
        return {}
    info = about(page, loc)
    if info.get("none"):
        if key in ("Enter", "NumpadEnter"):
            raise Refused("refused: nothing has the focus; Enter is for taking an entry of an open list")
        return info
    if info.get("pressed"):       # pressing a key on a button is pressing the button
        if _sends(info):
            raise Refused(f"refused: '{str(info['name'])[:80]}' sends the application; that is not available to the agent")
        return info
    if key in ("Enter", "NumpadEnter") and not info.get("area") and not info.get("in_list"):
        raise Refused("refused: Enter in a field sends the form. It is available where it takes an entry of an open list (focus on the list or on the box that owns it) "
                      "and in a text area")
    return info


def check_typing(page: Any, text: str, loc: Any = None) -> None:
    """A line break in typed text is an Enter."""
    if "\n" in text or "\r" in text:
        check_key(page, "Enter", loc)


# --- the page a learned plugin gets -----------------------------------------------------------------------------------

_LOCATORS = ("locator", "get_by_role", "get_by_text", "get_by_label", "get_by_placeholder", "get_by_test_id", "get_by_title", "get_by_alt_text", "frame_locator",
             "filter", "or_", "and_", "nth")
_PROPS = ("first", "last", "owner", "content_frame")
_CLICKS = ("click", "dblclick", "tap", "check", "uncheck", "set_checked", "dispatch_event")


class _Guarded:
    """A page, a frame or a locator that asks ``check_click`` / ``check_key`` before it acts. Everything else is the
    real thing's: what it reads, what it waits for, what it fills."""

    __slots__ = ("_real", "_page")

    def __init__(self, real: Any, page: Any) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_page", page)

    def __getattr__(self, name: str) -> Any:
        real, page = self._real, self._page
        value = getattr(real, name)
        if name in _PROPS:
            return _Guarded(value, page)
        if name == "keyboard":
            return _Keys(value, page)
        if name in _LOCATORS:
            return lambda *a, **k: _Guarded(value(*[x._real if isinstance(x, _Guarded) else x for x in a], **k), page)
        if name == "all":
            return lambda *a, **k: [_Guarded(x, page) for x in value(*a, **k)]
        if name in _CLICKS:
            def act(*a: Any, **k: Any) -> Any:
                if name == "dispatch_event" and not (a and str(a[0]).lower() in ("click", "submit", "mousedown", "mouseup", "pointerdown", "pointerup", "keydown", "keyup", "keypress")):
                    return value(*a, **k)
                if name == "dispatch_event" and str(a[0]).lower() == "submit":
                    raise Refused("refused: a learned tool does not send a form")
                # called on the page with a selector (page.click("#x")), or on a locator
                target = real.locator(a[0]).first if a and isinstance(a[0], str) and hasattr(real, "goto") else real
                check_click(page, target)
                return value(*a, **k)
            return act
        if name in ("press", "press_sequentially", "type"):
            def key(*a: Any, **k: Any) -> Any:
                on_page = hasattr(real, "goto")
                target = real.locator(a[0]).first if on_page and a else real
                what = (a[1] if on_page and len(a) > 1 else a[0]) if a else ""
                if name == "press":
                    check_key(page, str(what), target)
                else:
                    check_typing(page, str(what), target)
                return value(*a, **k)
            return key
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._real, name, value)

    def __repr__(self) -> str:
        return f"guarded({self._real!r})"


class _Keys:
    __slots__ = ("_real", "_page")

    def __init__(self, real: Any, page: Any) -> None:
        self._real, self._page = real, page

    def press(self, key: str, **k: Any) -> Any:
        check_key(self._page, key)
        return self._real.press(key, **k)

    def type(self, text: str, **k: Any) -> Any:
        check_typing(self._page, text)
        return self._real.type(text, **k)

    def insert_text(self, text: str) -> Any:
        return self._real.insert_text(text)

    def down(self, key: str) -> Any:
        check_key(self._page, key)
        return self._real.down(key)

    def up(self, key: str) -> Any:
        return self._real.up(key)


def guarded(page: Any) -> Any:
    """The page a learned plugin works on: the same page, asking before it clicks or presses."""
    return page if isinstance(page, _Guarded) else _Guarded(page, page)


def real(page: Any) -> Any:
    """The page behind a guarded one (for the program's own helpers that were handed a plugin's page)."""
    return page._real if isinstance(page, _Guarded) else page


# what script inside the page can do that no tool here can be asked about
_IN_PAGE = re.compile(r"\.submit\s*\(|requestSubmit\s*\(|\.click\s*\(|dispatchEvent\s*\(|\bMouseEvent\b|\bKeyboardEvent\b|\bSubmitEvent\b", re.I)


def scan_script(text: str) -> str:
    """Why a piece of text a plugin carries may not be learned, read as script for the page ('' when nothing in it goes
    round the gate): it sends a form, clicks or fakes a key from inside the page, where what it lands on cannot be
    looked at first. (Asked of the plugin's string constants - its Python clicks through the guarded page.)"""
    m = _IN_PAGE.search(text or "")
    return f"it acts from script inside the page ({m.group(0).strip()}): click and press through the page's locators, so that what is pressed can be checked first" if m else ""

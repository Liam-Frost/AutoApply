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
get a page that asks it for them, ``guarded``: every way that page has of clicking or pressing - its own, a locator's,
an element's, the keyboard's, the mouse's - with the arguments passed by position or by name, and so does everything
it hands out).

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

_CLICKS = ("click", "dblclick", "tap", "check", "uncheck", "set_checked", "dispatch_event")
_KEYS = ("press", "press_sequentially", "type")
# events that press something when they are made up and sent to an element
_PRESSES = ("click", "mousedown", "mouseup", "pointerdown", "pointerup", "keydown", "keyup", "keypress", "touchstart", "touchend")


def _named(a: tuple[Any, ...], k: dict[str, Any], *names: str) -> dict[str, Any]:
    """The arguments of a call by their names, however each was passed: ``press("Enter")`` and ``press(key="Enter")``
    are the same call, and were not the same to a gate that read ``a[0]``."""
    got = dict(zip(names, a))
    got.update({n: k[n] for n in names if n in k})
    return got


def _bare(x: Any) -> Any:
    return x._real if isinstance(x, _Guarded) else x


def _wrap(x: Any, page: Any) -> Any:
    """Whatever a guarded thing hands out that can itself click or press - a locator, a frame, an element handle, another
    page of the window, a list of them - asks too. The rest (text, numbers, what a script returned) is what it is."""
    if x is None or isinstance(x, (_Guarded, _Keys, _Point, str, bytes, int, float, bool, dict)):
        return x
    if isinstance(x, (list, tuple)):
        return type(x)(_wrap(i, page) for i in x)
    if any(hasattr(x, n) for n in ("click", "locator", "new_page", "pages", "is_done")) or (hasattr(x, "__enter__") and type(x).__module__.startswith("playwright")):
        return _Guarded(x, x if hasattr(x, "goto") and hasattr(x, "keyboard") else page)
    return x


class _Guarded:
    """A page, a frame, a locator or an element that asks ``check_click`` / ``check_key`` before it acts. Everything else
    is the real thing's: what it reads, what it waits for, what it fills - and what it hands out asks in its turn."""

    __slots__ = ("_real", "_page", "_kept")

    def __init__(self, real: Any, page: Any) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_page", page)
        object.__setattr__(self, "_kept", {})

    def __getattr__(self, name: str) -> Any:
        real, page = self._real, self._page
        value = getattr(real, name)
        if name == "keyboard":
            return _Keys(value, page)
        if name in ("mouse", "touchscreen"):      # one for the page's life: where the pointer was moved to is remembered
            return self._kept.setdefault(name, _Point(value, page))
        on_page = hasattr(real, "goto")       # a page or a frame: its actions take the selector first
        first = ("selector",) if on_page else ()
        if name in _CLICKS:
            def act(*a: Any, **k: Any) -> Any:
                got = _named(a, k, *first, *(("type",) if name == "dispatch_event" else ()))
                if name == "dispatch_event":
                    event = str(got.get("type") or k.get("kind") or "").lower()
                    if event == "submit":
                        raise Refused("refused: a learned tool does not send a form")
                    if event not in _PRESSES:
                        return _wrap(value(*a, **k), page)
                # called on the page with a selector (page.click("#x"), page.click(selector="#x")), or on a locator
                target = real.locator(got["selector"]).first if on_page and isinstance(got.get("selector"), str) else real
                check_click(page, target)
                return _wrap(value(*a, **k), page)
            return act
        if name in _KEYS:
            def key(*a: Any, **k: Any) -> Any:
                what = "key" if name == "press" else "text"
                got = _named(a, k, *first, what)
                target = (real.locator(got["selector"]).first if isinstance(got.get("selector"), str) else None) if on_page else real
                (check_key if name == "press" else check_typing)(page, str(got.get(what) or ""), target)
                return _wrap(value(*a, **k), page)
            return key
        if callable(value):
            return lambda *a, **k: _wrap(value(*[_bare(x) for x in a], **{n: _bare(x) for n, x in k.items()}), page)
        return _wrap(value, page)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._real, name, value)

    def __enter__(self) -> Any:       # "with page.expect_popup() as p": the page that comes of it asks too
        return _wrap(self._real.__enter__(), self._page)

    def __exit__(self, *exc: Any) -> Any:
        return self._real.__exit__(*exc)

    def __repr__(self) -> str:
        return f"guarded({self._real!r})"


class _Keys:
    __slots__ = ("_real", "_page")

    def __init__(self, real: Any, page: Any) -> None:
        self._real, self._page = real, page

    def press(self, *a: Any, **k: Any) -> Any:
        check_key(self._page, str(_named(a, k, "key").get("key") or ""))
        return self._real.press(*a, **k)

    def type(self, *a: Any, **k: Any) -> Any:
        check_typing(self._page, str(_named(a, k, "text").get("text") or ""))
        return self._real.type(*a, **k)

    def insert_text(self, *a: Any, **k: Any) -> Any:
        return self._real.insert_text(*a, **k)

    def down(self, *a: Any, **k: Any) -> Any:
        check_key(self._page, str(_named(a, k, "key").get("key") or ""))
        return self._real.down(*a, **k)

    def up(self, *a: Any, **k: Any) -> Any:
        return self._real.up(*a, **k)


# what is at a point of the page: the element there, looked for through the shadow roots it may be inside; a frame is
# a page of its own, and what is in it cannot be seen from here
_AT = r"""([x, y]) => {
  let el = document.elementFromPoint(x, y);
  while (el && el.shadowRoot && el.shadowRoot.elementFromPoint) {
    const inner = el.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === el) break;
    el = inner;
  }
  if (!el) return {none: true};
  if (/^(iframe|frame|object|embed)$/i.test(el.tagName)) return {frame: true};
  return (%s)(el);
}""" % _ABOUT


class _Point:
    """The mouse and the touch screen press where, not what. The gate looks at what is there."""

    __slots__ = ("_real", "_page", "_at")

    def __init__(self, real: Any, page: Any) -> None:
        self._real, self._page, self._at = real, page, None

    def _check(self, x: Any, y: Any) -> None:
        try:
            info = self._page.evaluate(_AT, [float(x), float(y)])
        except Exception as e:  # noqa: BLE001
            raise Refused(f"refused: could not look at what is at that point ({type(e).__name__}); click through a locator") from e
        info = info if isinstance(info, dict) else {"none": True}
        if info.get("frame"):
            raise Refused("refused: that point is inside a frame, where what is pressed cannot be looked at from the page; click through the frame's locator")
        if _sends(info):
            raise Refused(f"refused: '{str(info['name'])[:80]}' sends the application; that is not available to the agent")

    def _press(self, name: str, a: tuple[Any, ...], k: dict[str, Any]) -> Any:
        got = _named(a, k, "x", "y")
        if got.get("x") is None or got.get("y") is None:
            raise Refused("refused: a click needs the point it lands on")
        self._check(got["x"], got["y"])
        self._at = (got["x"], got["y"])
        return getattr(self._real, name)(*a, **k)

    def click(self, *a: Any, **k: Any) -> Any:
        return self._press("click", a, k)

    def dblclick(self, *a: Any, **k: Any) -> Any:
        return self._press("dblclick", a, k)

    def tap(self, *a: Any, **k: Any) -> Any:
        return self._press("tap", a, k)

    def move(self, *a: Any, **k: Any) -> Any:
        got = _named(a, k, "x", "y")
        self._at = (got.get("x"), got.get("y")) if got.get("x") is not None and got.get("y") is not None else None
        return self._real.move(*a, **k)

    def down(self, *a: Any, **k: Any) -> Any:
        if self._at is None:
            raise Refused("refused: the button would go down where the gate has not looked; move the mouse there first, or click through a locator")
        self._check(*self._at)
        return self._real.down(*a, **k)

    def __getattr__(self, name: str) -> Any:      # up, wheel: nothing is pressed by them
        return getattr(self._real, name)


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

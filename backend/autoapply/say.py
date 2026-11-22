"""What the program says to the applicant, by key (plan §3, C3): ``say("server.lifecycle.sent", company=...)``.

A message is made where the program has something to say and rendered where it leaves the program: in an answer of
the API in the language of the page that asked (the ``X-Lang`` header), in a notification in the language set for the
program. In between it is a string - the Chinese the program has always written - so that everything that compares,
stores, cuts or logs it does what it did; it only carries its key and its values along.

The messages are in ``frontend/src/locales/server/<lang>.json`` (English the source, a note for translators on each),
next to the interface's own: one list of languages, one way to translate. A message a language lacks is said in
English; a message no catalog has (a text kept from before) is said as it was written.
"""
from __future__ import annotations

import json
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config

SOURCE = "zh"          # what the program's strings hold: the language it was written in, whatever the catalogs' source
FALLBACK = "en"        # the catalogs' source: what is said when a language lacks a message
_page_lang: ContextVar[str] = ContextVar("page_lang", default="")


def catalog_dir() -> Path:
    return config.ROOT / "frontend" / "src" / "locales" / "server"


@lru_cache(maxsize=8)
def _catalog(lang: str) -> dict[str, str]:
    try:
        return json.loads((catalog_dir() / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# What the program's Chinese wording was when its messages were given keys (2.0.2): text kept before that is found by
# it, whatever the wording has become since. (The file is that release's server/zh.json, never changed.)
KEPT_AS = "zh-2.0.2"


def reload() -> None:
    _catalog.cache_clear()
    _patterns.cache_clear()


# --- plural forms: in the order of the language's categories (as the interface's catalog.js) ---------------------------
def _form(lang: str, n: Any, forms: list[str]) -> str:
    if len(forms) == 1:
        return forms[0]
    try:
        n = abs(float(n))
    except (TypeError, ValueError):
        return forms[-1]
    if lang.startswith("fr"):
        cat = 0 if n < 2 else 1
    elif lang.startswith(("zh", "ja", "ko")):
        cat = 0
    else:
        cat = 0 if n == 1 else 1
    return forms[min(cat, len(forms) - 1)]


def _fill(text: str, params: dict[str, Any], lang: str) -> str:
    if "|" in text and "n" in params:      # (plural forms only in a message that counts: one that has an n)
        text = _form(lang, params["n"], [f.strip() for f in text.split("|")])
    return re.sub(r"\{(\w+)\}", lambda m: str(render(params[m.group(1)], lang)) if m.group(1) in params else m.group(0), text)


class Msg(str):
    """A message: the string the program has always written (Chinese), and its key and values."""

    key: str
    params: dict[str, Any]

    def __new__(cls, key: str, params: dict[str, Any], text: str) -> Msg:
        m = super().__new__(cls, text)
        m.key, m.params = key, params
        return m

    # A message cut to a length it is shorter than, or stripped of spaces it does not have, is still the message.
    def __getitem__(self, i: Any) -> str:
        out = str.__getitem__(self, i)
        return self if out == self else out

    def strip(self, chars: str | None = None) -> str:
        out = str.strip(self, chars)
        return self if out == self else out

    def in_lang(self, lang: str) -> str:
        if lang == SOURCE:
            return str(self)
        text = _catalog(lang).get(self.key) or _catalog(FALLBACK).get(self.key)
        return _fill(text, self.params, lang) if text else str(self)

    def data(self) -> dict[str, Any]:
        """To be kept (in a database column): rendered again in whatever language it is read in."""
        return {"key": self.key, "params": {k: (v.data() if isinstance(v, Msg) else v) for k, v in self.params.items()}}

    # Messages put together ("评了 4 个岗位" + "，2 个排进了申请") stay messages, part by part.
    def __add__(self, other: Any) -> Any:
        return Joined([self, other]) if isinstance(other, str) else NotImplemented

    def __radd__(self, other: Any) -> Any:
        return Joined([other, self]) if isinstance(other, str) else NotImplemented


class Joined(Msg):
    """Several pieces one after another - messages and plain text - each said in the language asked for."""

    def __new__(cls, parts: list[Any]) -> Joined:
        flat: list[Any] = []
        for p in parts:
            flat += p.parts if isinstance(p, Joined) else [p]
        m = str.__new__(cls, "".join(str(p) for p in flat))
        m.key, m.params, m.parts = "", {}, flat
        return m

    def in_lang(self, lang: str) -> str:
        return "".join(p.in_lang(lang) if isinstance(p, Msg) else str(p) for p in self.parts)

    def data(self) -> dict[str, Any]:
        return {"join": [p.data() if isinstance(p, Msg) else str(p) for p in self.parts]}


def join(sep: str, parts: Any) -> Any:
    """``sep.join(parts)`` that keeps the messages among the parts."""
    parts = list(parts)
    if not isinstance(sep, Msg) and not any(isinstance(p, Msg) for p in parts):
        return sep.join(parts)
    out: list[Any] = []
    for i, p in enumerate(parts):
        out += ([sep] if i else []) + [p]
    return Joined(out)


def say(key: str, **params: Any) -> Msg:
    text = _catalog(SOURCE).get(key)
    if text is None:
        text = _catalog(FALLBACK).get(key, key)
    return Msg(key, params, _fill(text, params, SOURCE))


def from_data(data: Any, fallback: str = "") -> str:
    """A message kept with ``Msg.data()`` (or the text kept before messages had keys)."""
    if isinstance(data, dict) and isinstance(data.get("join"), list):
        return Joined([from_data(p, p) if isinstance(p, dict) else p for p in data["join"]])
    if isinstance(data, dict) and data.get("key"):
        params = {k: (from_data(v) if isinstance(v, dict) and v.get("key") else v) for k, v in (data.get("params") or {}).items()}
        return say(str(data["key"]), **params)
    return fallback


# --- kept in the database ------------------------------------------------------------------------------------------------
KEPT = "\x1f"        # a kept message: KEPT + its data (JSON) + "\x1e" + the text it said; anything else: a text as it was written


def keep(value: Any) -> Any:
    if isinstance(value, Msg):
        return KEPT + json.dumps(value.data(), ensure_ascii=False) + "\x1e" + str(value)
    return value


def kept(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(KEPT) and "\x1e" in value:
        data, _, text = value[1:].partition("\x1e")
        try:
            return from_data(json.loads(data), text) or text
        except ValueError:
            return text
    return value


def keep_all(value: Any) -> Any:
    """Every message in a structure kept (for JSON)."""
    if isinstance(value, Msg):
        return keep(value)
    if isinstance(value, dict):
        return {k: keep_all(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [keep_all(v) for v in value]
    return value


def kept_all(value: Any) -> Any:
    if isinstance(value, str):
        return kept(value)
    if isinstance(value, dict):
        return {k: kept_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [kept_all(v) for v in value]
    return value


def dumps(value: Any) -> str:
    """JSON as the database keeps it: messages with their keys."""
    return json.dumps(keep_all(value), ensure_ascii=False)


def loads(text: str) -> Any:
    return kept_all(json.loads(text))


# --- what was kept before messages had keys -------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _patterns() -> list[tuple[int, Any, str, bool]]:
    """Every message's Chinese wording as a pattern, its values as groups - the longest wording first. A wording with
    almost nothing of its own ("{what} · {company}") would take any text for itself: it is left out. A message whose
    wording has changed since its text was kept is found by the wording it had then as well."""
    now = _catalog(SOURCE)
    wordings = [(key, text, False) for key, text in now.items()]
    wordings += [(key, text, True) for key, text in _catalog(KEPT_AS).items() if key in now and now[key] != text]
    out = []
    for key, text, old in wordings:
        if "|" in text:
            continue
        literal = re.sub(r"\{\w+\}", "", text)
        if len(re.findall(r"[\u4e00-\u9fff]", literal)) < 2:
            continue
        names: list[str] = []

        def group(m: Any) -> str:
            name = m.group(1)
            if name in names:
                return f"(?P={name})"
            names.append(name)
            return f"(?P<{name}>.+?)"

        rx = re.sub(r"\\\{(\w+)\\\}", group, re.escape(text))
        try:
            out.append((len(literal), re.compile(rx + r"\Z", re.S), key, old))
        except re.error:
            continue
    return sorted(out, key=lambda x: -x[0])


def recognise(text: str, depth: int = 0) -> Msg | None:
    """The message a text is, when the program wrote it before its messages had keys (a card's title, an application's
    latest event): found by its Chinese wording, its values taken back out of it. None when it is no message - the
    applicant, an employer or the AI wrote it, or it was put together from several."""
    if not isinstance(text, str) or isinstance(text, Msg) or not re.search(r"[\u4e00-\u9fff]", text) or len(text) > 2000:
        return None
    for _n, rx, key, old in _patterns():
        m = rx.match(text)
        if m is None:
            continue
        params: dict[str, Any] = {}
        for name, value in m.groupdict().items():
            inner = recognise(value, depth + 1) if depth < 2 else None
            params[name] = inner if inner is not None else value
        msg = say(key, **params)
        if old or str(msg) == text:      # (an old wording was matched whole: said now, it reads differently)
            return msg
    return None


def recognise_kept() -> int:
    """Once: the cards' titles and texts and the applications' latest events the program wrote before its messages had
    keys are kept as the messages they are - read in whatever language from then on. What is not one of the program's
    messages stays as it was written. Returns how many were found."""
    from sqlalchemy.orm.attributes import flag_modified

    from . import db
    from .models import Application, Todo

    n = 0
    with db.session() as s:
        for row, columns in [*((t, ("title", "body")) for t in s.query(Todo)), *((a, ("last_event",)) for a in s.query(Application))]:
            for col in columns:
                value = getattr(row, col)
                found = recognise(value) if value and not isinstance(value, Msg) else None
                if found is not None:
                    setattr(row, col, found)
                    flag_modified(row, col)      # (the message is the same string as before: told it changed, it is written)
                    n += 1
    return n


def language_name(lang: str) -> str:
    """A language as the model is told it ("Simplified Chinese", "French"): from the list of the program's languages."""
    try:
        listed = json.loads((catalog_dir().parent / "languages.json").read_text(encoding="utf-8"))["languages"]
    except (OSError, ValueError, KeyError):
        listed = []
    return next((x.get("english") or x.get("name") for x in listed if x.get("id") == lang), "Simplified Chinese" if lang == "zh" else "English")


# --- where messages leave the program ------------------------------------------------------------------------------------
def page_lang() -> str:
    """The language of the page that asked (set per request), else the one set for the program."""
    got = _page_lang.get()
    if got:
        return got
    from . import i18n

    return i18n.lang()


def set_page_lang(lang: str) -> Any:
    return _page_lang.set(lang if re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", lang or "") else "")


def render(value: Any, lang: str | None = None) -> Any:
    """Every message in ``value`` (a string, a list, a dict, nested) in ``lang`` (the page's, when not said)."""
    lang = lang or page_lang()
    if isinstance(value, Msg):
        return value.in_lang(lang)
    if isinstance(value, dict):
        return {k: render(v, lang) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [render(v, lang) for v in value]
    return value

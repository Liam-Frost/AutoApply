"""Region packs (``regions.json``): how application forms in a country ask about the right to work, what else they
ask (diversity monitoring, consents), the formats they expect, and what is never filled in automatically.

Two uses:
* ``asks`` - what the applicant's profile should state for the countries they apply in (shown on the profile page
  and given to the AI that drafts a profile from a résumé);
* ``notes`` - a short briefing for the AI that answers a form's questions for a job in that country.

A pack describes how forms ask, not what the law is, and it never supplies an answer: answers come from the profile.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("regions.json")


@lru_cache(maxsize=1)
def packs() -> dict[str, dict[str, Any]]:
    data = json.loads(FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def pack_for(country: str) -> tuple[str, dict[str, Any]] | None:
    """The pack that covers a country code: its own, or a shared one that lists it (the EU pack)."""
    c = (country or "").upper()
    all_ = packs()
    if c in all_:
        return c, all_[c]
    for key, p in all_.items():
        if c in (p.get("countries") or []):
            return key, p
    return None


def _unique(countries: list[str] | set[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for c in countries:
        hit = pack_for(c)
        if hit and hit[0] not in [k for k, _ in out]:
            out.append(hit)
    return out


def asks(countries: list[str]) -> list[str]:
    """What the profile should state for these countries."""
    return [f"{p['name']['en']}: {line}" for _, p in _unique(countries) for line in p.get("profile") or []]


def notes(countries: list[str] | set[str]) -> str:
    """Briefing for answering a form in these countries ('' when no pack covers them)."""
    parts = []
    for _, p in _unique(sorted(countries)):
        parts.append(
            f"{p['name']['en']}:\n" + "\n".join(f"- {q}" for q in p.get("questions") or [])
            + (f"\n- Diversity questions: {p['diversity']}" if p.get("diversity") else "")
            + (f"\n- Formats: {p['formats']}" if p.get("formats") else "")
            + (f"\n- Consents: {p['consents']}" if p.get("consents") else "")
            + (f"\n- Never fill in, leave for the applicant: {p['never']}" if p.get("never") else "")
        )
    return "\n\n".join(parts)


def for_location(location: str) -> str:
    from .intake import countries_of

    return notes(countries_of(location or ""))


def view(countries: list[str], lang: str = "zh") -> list[dict[str, Any]]:
    """For the profile page."""
    out = []
    for k, p in _unique(countries):
        t = p.get(lang) if lang != "en" else None   # the pack's text in the interface language, where it has one
        get = lambda key, p=p, t=t: (t or {}).get(key) or p.get(key) or ("" if key != "profile" else [])  # noqa: E731
        out.append({"code": k, "name": p["name"].get(lang) or p["name"]["en"], "profile": get("profile"), "diversity": get("diversity"),
                    "consents": get("consents"), "never": get("never")})
    return out

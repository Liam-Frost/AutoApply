"""What the program knows about a site - in one place, under one key.

It used to be kept in five: notes in a playbook file, the steps of the form in a JSON file, recipes and plugins in a
folder of their own, and half a dozen facts about signing in spread over settings - each under its own spelling of
the site's name and with its own idea of when it is out of date. Taking a revision out left its note behind; a site
that turned out to sign in elsewhere moved one of the five.

Now a site is a row (models.Site), and this module is the only way to it:

    key             "generic:careers.acme.com" for a site without a driver of its own, "workday:acme.wd1" for one on a
                    system that has one, "idp:google" for a sign-in provider. (How a whole system is worked - "workday",
                    "greenhouse" - is kept under the system's name; its notes are the applicant's playbook for it.)
    account(key)    where the site signs in: itself, or the site it turned out to share its sign-in with (same_as)
    fact / set_fact what was found out: sso_offered, needs_window, session_browser, driver_written
    notes / note    what the AI wrote down about working the site, newest first
    plan / save_plan  the steps of its form (siteplan.py reads and writes through here)
    revisions       what was learned for it as recipes and plugins (learned.py keeps their text as files - code has to
                    be a file - and their record beside it; here they are found by site)
    about           all of it, for one site: what the AI is given, and what the analysis page shows
    forget / move   the whole of it, at once

What is NOT here: answers (answers.py) - an answer is the applicant's, not the site's, and outlives it.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from . import db
from .models import Site, now

log = logging.getLogger("autoapply.sites")

FACTS = {"sso_offered": [], "needs_window": False, "session_browser": "", "driver_written": False}
KEEP_NOTES = 12


def norm(key: str | None) -> str:
    """A site's key, from any of the spellings that were in use ("site-careers.acme.com" was the one for notes, steps
    and revisions)."""
    key = str(key or "")
    return "generic:" + key[5:] if key.startswith("site-") else key


def of_form(schema: Any) -> str:
    """Where what is learned about working this form is kept: the site (the key its account has, "workday:acme.wd1"),
    for a form the agent explored - also on a system that has a driver; the system, for a form a coded driver reads
    (every site of that system has the same one)."""
    if getattr(schema, "source", "") == "agent" and getattr(schema, "tenant", ""):
        return f"{schema.ats}:{schema.tenant}"
    return str(schema.ats)


def explored(key: str) -> bool:
    """Is this one site (whose form the agent explored), and not a whole system or a sign-in provider?"""
    key = norm(key)
    return ":" in key and not key.startswith("idp:")


def name(key: str) -> str:
    """The site as it is shown: its address, or the system's name."""
    key = norm(key)
    return key.split(":", 1)[1] if ":" in key else key


def _row(s: Any, key: str, *, make: bool = False) -> Site | None:
    row = s.get(Site, key)
    if row is None and make:
        row = Site(key=key, facts={}, notes=[], steps={})
        s.add(row)
    return row


# --- where a site signs in ---------------------------------------------------------------------------------------

def account(key: str | None) -> str:
    """The key the site's sign-in is kept under: its own, or that of the site it signs in on."""
    key = norm(key)
    if not key:
        return ""
    with db.session() as s:
        row = s.get(Site, key)
        return str(row.same_as) if row is not None and row.same_as else key


def link(key: str, other: str) -> None:
    """This site signs in where ``other`` does (the same employer's postings under another address; a provider's own site)."""
    key, other = norm(key), norm(other)
    if not key or not other or key == other:
        return
    with db.session() as s:
        _row(s, key, make=True).same_as = other


def links() -> dict[str, str]:
    with db.session() as s:
        return {r.key: r.same_as for r in s.query(Site).filter(Site.same_as != "")}


# --- what was found out ------------------------------------------------------------------------------------------

def fact(key: str, what: str, default: Any = None) -> Any:
    if what not in FACTS:
        raise KeyError(what)
    with db.session() as s:
        row = s.get(Site, norm(key))
        got = (row.facts or {}).get(what) if row is not None else None
    return got if got is not None else (FACTS[what] if default is None else default)


def set_fact(key: str, what: str, value: Any) -> None:
    if what not in FACTS:
        raise KeyError(what)
    key = norm(key)
    if not key:
        return
    with db.session() as s:
        row = _row(s, key, make=True)
        if (row.facts or {}).get(what) != value:
            row.facts = {**(row.facts or {}), what: value}


def having(what: str) -> list[str]:
    """The sites for which this was found out (a true or non-empty value)."""
    with db.session() as s:
        return sorted(r.key for r in s.query(Site) if (r.facts or {}).get(what))


# --- notes -------------------------------------------------------------------------------------------------------

def notes(key: str) -> str:
    """What was written down about working this site, as the AI is given it: newest first. For a system with a driver
    of its own this is the applicant's playbook for it (knowledge.py) - theirs to read and edit."""
    from . import knowledge

    key = norm(key)
    if ":" not in key:
        return knowledge.playbook(key)
    with db.session() as s:
        row = s.get(Site, key)
        rows = list(row.notes or []) if row is not None else []
    return "\n".join(f"- ({n.get('at', '')}) {n.get('text', '')}" for n in rows)


def note(key: str, text: str, *, keep: int = KEEP_NOTES) -> None:
    """Remember something the AI found out about working this site. The same thing said again moves to the top; the
    oldest are dropped."""
    from . import knowledge

    key, text = norm(key), re.sub(r"\s+", " ", text or "").strip()
    if not key or not text:
        return
    if ":" not in key:
        knowledge.add_site_note(key, text, keep=keep)
        return
    with db.session() as s:
        row = _row(s, key, make=True)
        rest = [n for n in (row.notes or []) if n.get("text") != text[:1200]]
        row.notes = [{"at": date.today().isoformat(), "text": text[:1200]}, *rest][:keep]


# --- the steps of its form -----------------------------------------------------------------------------------------

def plan(key: str) -> dict[str, Any]:
    with db.session() as s:
        row = s.get(Site, norm(key))
        got = dict(row.steps or {}) if row is not None else {}
    got.setdefault("steps", {})
    return got


def save_plan(key: str, plan: dict[str, Any]) -> None:
    key = norm(key)
    if not key:
        return
    with db.session() as s:
        _row(s, key, make=True).steps = plan


# --- all of it -----------------------------------------------------------------------------------------------------

def revisions(key: str) -> list[dict[str, Any]]:
    from . import learned

    key = norm(key)
    return [r for r in learned.revisions() if norm(r.get("target")) == key]


def about(key: str) -> dict[str, Any]:
    """Everything the program knows about one site."""
    key = norm(key)
    got = plan(key)
    with db.session() as s:
        row = s.get(Site, key)
        facts = {**FACTS, **((row.facts or {}) if row is not None else {})}
        same_as = str(row.same_as or "") if row is not None else ""
        updated = row.updated_at.isoformat() if row is not None and row.updated_at else ""
        kept = list(row.notes or []) if row is not None and ":" in key else []
    return {"key": key, "name": name(key), "explored": explored(key), "signs_in_on": same_as, "facts": facts, "updated": updated,
            "notes": kept if ":" in key else [{"at": "", "text": ln[2:]} for ln in notes(key).splitlines() if ln.startswith("- ")][:KEEP_NOTES],
            "steps": [{"title": t, "questions": [str(q.get("label") or "")[:120] for q in (st.get("questions") or [])]} for t, st in (got.get("steps") or {}).items()],
            "revisions": [{k: r.get(k) for k in ("id", "kind", "title", "why", "status", "why_status", "created", "origin")} for r in revisions(key)]}


def listing() -> list[dict[str, Any]]:
    """Every site something is known about, with how much."""
    from . import learned

    revs: dict[str, int] = {}
    for r in learned.revisions():
        if r.get("status") in ("trial", "active", "proposed"):
            revs[norm(r.get("target"))] = revs.get(norm(r.get("target")), 0) + 1
    out = []
    with db.session() as s:
        keys = {r.key: r for r in s.query(Site)}
        for key in sorted({*keys, *revs}):
            r = keys.get(key)
            steps = (r.steps or {}).get("steps") or {} if r is not None else {}
            out.append({"key": key, "name": name(key), "explored": explored(key), "signs_in_on": str(r.same_as or "") if r is not None else "",
                        "notes": len(r.notes or []) if r is not None else 0, "steps": len(steps), "questions": sum(len(v.get("questions") or []) for v in steps.values()),
                        "revisions": revs.get(key, 0), "facts": {k: v for k, v in ((r.facts or {}) if r is not None else {}).items() if v},
                        "updated": r.updated_at.isoformat() if r is not None and r.updated_at else ""})
    return out


def forget(key: str) -> dict[str, int]:
    """Drop what was learned about working this site - notes, steps, and its revisions taken out of force. Where it
    signs in and which browser its sign-in lives in are kept: those are about the account, and still true."""
    from . import learned

    key = norm(key)
    out = {"notes": 0, "steps": 0, "revisions": 0}
    with db.session() as s:
        row = s.get(Site, key)
        if row is not None:
            out["notes"], out["steps"] = len(row.notes or []), len((row.steps or {}).get("steps") or {})
            row.notes, row.steps = [], {}
            row.facts = {k: v for k, v in (row.facts or {}).items() if k != "driver_written"}
    for r in revisions(key):
        if r.get("status") in ("trial", "active", "proposed"):
            learned._update(r["id"], status="reverted", why_status="这个网站学到的内容被整体清除了")
            out["revisions"] += 1
    return out


def move(old: str, new: str) -> bool:
    """The site is now reached under another address: everything known about it goes with it."""
    from . import learned

    old, new = norm(old), norm(new)
    if not old or not new or old == new:
        return False
    with db.session() as s:
        a = s.get(Site, old)
        if a is None:
            return False
        b = _row(s, new, make=True)
        b.same_as = b.same_as or a.same_as
        b.facts = {**(a.facts or {}), **(b.facts or {})}
        seen = {n.get("text") for n in (b.notes or [])}
        b.notes = [*(b.notes or []), *[n for n in (a.notes or []) if n.get("text") not in seen]][:KEEP_NOTES]
        if not (b.steps or {}).get("steps"):
            b.steps = a.steps
        s.delete(a)
        for other in s.query(Site).filter(Site.same_as == old):
            other.same_as = new
    for r in learned.revisions():
        if norm(r.get("target")) == old:
            learned._update(r["id"], target=new)
    return True


# --- from the five places it used to be kept in -------------------------------------------------------------------------

def migrate() -> dict[str, int]:
    """Bring what earlier versions kept elsewhere into the one place. Run once at start; what is read is left where it
    was (files are moved into a folder named "migrated" beside them), so that going back a version loses nothing."""
    import json
    import shutil

    from sqlalchemy import text

    from . import config, knowledge, learned

    done = {"links": 0, "facts": 0, "notes": 0, "plans": 0, "revisions": 0, "runs": 0}
    from .models import Account, Job

    with db.session() as s:      # "site-acme.wd1" named a site by its last part only: which system it is on is in the accounts and the postings
        known = {k.split(":", 1)[1]: k for (k,) in s.query(Account.tenant_key) if ":" in k and not k.startswith("idp:")}
        for ats, tenant in s.query(Job.ats, Job.tenant).filter(Job.ats != "", Job.tenant != "").distinct():
            known.setdefault(tenant, f"{ats}:{tenant}")

    def was(old: str) -> str:
        """The key of what used to be filed as "site-<last part>"."""
        return known.get(old[5:], "generic:" + old[5:]) if old.startswith("site-") else old
    for key, other in (db.get_setting("accounts.alias") or {}).items():
        link(key, other)
        done["links"] += 1
    for key, offered in (db.get_setting("sso.offered") or {}).items():
        set_fact(key, "sso_offered", list(offered or []))
        done["facts"] += 1
    for key in db.get_setting("browser.visible_sites") or []:
        set_fact(key, "needs_window", True)
        done["facts"] += 1
    for key, made in (db.get_setting("browser.session_made_in") or {}).items():
        set_fact(key, "session_browser", str(made))
        done["facts"] += 1
    for key in db.get_setting("learned.drivers_written") or []:
        set_fact(was(key), "driver_written", True)
        done["facts"] += 1
    books = config.PLAYBOOKS
    for p in sorted(books.glob("site-*.md")) if books.exists() else []:
        body = p.read_text(encoding="utf-8")
        lines = [m for ln in body.splitlines() if (m := re.match(r"^- \((\d{4}-\d{2}-\d{2})\) (.+)$", ln))]
        rest = "\n".join(ln for ln in body.splitlines() if not re.match(r"^- \(\d{4}-\d{2}-\d{2}\) ", ln) and ln.strip() != knowledge.NOTES_HEAD.strip()).strip()
        key = was(p.stem)
        with db.session() as s:
            row = _row(s, key, make=True)
            have = {n.get("text") for n in (row.notes or [])}
            new = [{"at": m[1], "text": m[2].strip()[:1200]} for m in lines if m[2].strip() not in have]
            if rest and rest[:1200] not in have:        # whatever else the file said (written by hand): kept as a note of its own
                new.append({"at": date.today().isoformat(), "text": re.sub(r"\s+", " ", rest)[:1200]})
            row.notes = [*(row.notes or []), *new][:KEEP_NOTES]
        done["notes"] += len(new)
        (books / "migrated").mkdir(exist_ok=True)
        shutil.move(str(p), str(books / "migrated" / p.name))
    plans = config.DATA / "sites"
    for p in sorted(plans.glob("*.json")) if plans.exists() else []:
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = was(p.stem)
        if not plan(key)["steps"]:
            save_plan(key, got)
            done["plans"] += 1
        (plans / "migrated").mkdir(exist_ok=True)
        shutil.move(str(p), str(plans / "migrated" / p.name))
    for r in learned.revisions():
        if str(r.get("target") or "").startswith("site-"):
            learned._update(r["id"], target=was(r["target"]))
            done["revisions"] += 1
    with db.session() as s:
        got = s.execute(text("UPDATE runs SET site = (CASE WHEN ats IS NULL OR ats = '' THEN 'generic' ELSE ats END) || ':' || substr(site, 6) WHERE site LIKE 'site-%'"))
        done["runs"] = int(got.rowcount or 0)
    if any(done.values()):
        log.info("what was known about sites is kept in one place now: %s", done)
    return done


__all__ = ["about", "account", "explored", "fact", "forget", "having", "link", "links", "listing", "migrate", "move", "name", "norm", "note", "notes",
           "of_form", "plan", "revisions", "save_plan", "set_fact", "now"]

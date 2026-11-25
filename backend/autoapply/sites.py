"""What the program knows about a site - in one place, under one key.

A site is a row (models.Site), and this module is the only way to it:

    key             "generic:careers.acme.com" for an employer's own site, "workday:acme.wd1" for one on a recruiting
                    system that keeps an account per employer, "idp:google" for a sign-in provider, "system:workday"
                    for what agents noted about a system on every employer's site. ``key_of`` gives it for an address.
    account(key)    where the site signs in: itself, or the site it turned out to share its sign-in with (same_as)
    fact / set_fact what was found out: sso_offered, needs_window, session_browser, sign_in_hosts, second_factor
    notes / note    what an agent wrote down about working the site, newest first
    about           all of it, for one site
    forget / move   the whole of it, at once
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from . import db
from .models import Site, now

log = logging.getLogger("autoapply.sites")

# sign_in_hosts: the hosts this site sends the window to for its sign-in, on which its password was typed and worked
# ("atozpublic.idprism-auth.amazon.com" for www.amazon.jobs): the site's own sign-in, though on another address.
# second_factor: did the last sign-in with the stored password ask for an approval on the applicant's phone (True / False;
# None while that is not known)? A sign-in that will ring their phone is not begun by the program in their quiet hours.
FACTS = {"sso_offered": [], "needs_window": False, "session_browser": "", "sign_in_hosts": [], "second_factor": None,
         # the provider the applicant signs in to this site with (a key of browser.identities): chosen on the site's
         # sign-in card - its work then follows that provider's browser (browser_policy), and the agent uses the
         # site's own "Sign in with ..."
         "sign_in_via": ""}
KEEP_NOTES = 12


def norm(key: str | None) -> str:
    """A site's key, from any of the spellings that were in use ("site-careers.acme.com" was the one for notes, steps
    and revisions)."""
    key = str(key or "")
    return "generic:" + key[5:] if key.startswith("site-") else key


# Recruiting systems that are told by the address, and how a site on one is named (the names accounts, sessions and
# notes have been kept under since before there was an agent: they are found again under the same name).
SYSTEMS = {"myworkdayjobs.com": "workday", "myworkdaysite.com": "workday", "greenhouse.io": "greenhouse", "ashbyhq.com": "ashby", "apply.workable.com": "workable",
           "oraclecloud.com": "oracle", "eightfold.ai": "eightfold", "smartrecruiters.com": "smartrecruiters", "lever.co": "lever", "icims.com": "icims",
           "pdportal.apsc.ubc.ca": "pdportal"}


def where(url: str) -> tuple[str, str]:
    """(system, the employer's name on it) for an address on a recruiting system that is told by its address;
    ("", host) for any other."""
    from urllib.parse import parse_qs, urlparse

    from .errors import host_is

    u = urlparse(url if "//" in (url or "") else f"https://{url}")
    host = u.netloc.lower()
    system = next((name for suffix, name in SYSTEMS.items() if host_is(u.hostname or "", suffix)), "")
    if system == "workday":
        return system, host.split(".myworkday")[0]                      # "acme.wd1"
    if system == "pdportal":
        return system, "ubc"
    if system in ("greenhouse", "ashby", "lever", "smartrecruiters", "workable"):      # one address for every employer: the employer is the first part of the path
        first = next((x for x in u.path.split("/") if x and x not in ("embed", "job_app", "jobs")), "")
        board = (parse_qs(u.query).get("for") or [first])[0]
        return (system, board.lower()) if board else ("", host)
    if system:
        return system, host.split(".")[0]
    return "", host


def key_of(url: str) -> str:
    """The name the program keeps this site's session, account and notes under."""
    system, name = where(url)
    return f"{system}:{name}" if system else f"generic:{name}"


def explored(key: str) -> bool:
    """Is this one site, and not a whole system or a sign-in provider?"""
    key = norm(key)
    return ":" in key and not key.startswith(("idp:", "system:"))


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


def found_out(key: str, what: str) -> bool:
    """Has this been found out about the site at all (an empty list found is not the same as never looked)?"""
    if what not in FACTS:
        raise KeyError(what)
    with db.session() as s:
        row = s.get(Site, norm(key))
        return row is not None and what in (row.facts or {})


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
        digest, raw = _split(list(row.notes or []) if row is not None else [])
    said = "\n".join(f"- ({n.get('at', '')}) {n.get('text', '')}" for n in raw)
    if not digest:
        return said
    return (f"How this site is worked (distilled on {digest.get('at', '')} from earlier runs' notes):\n{digest.get('text', '')}"
            + (f"\n\nNoted since:\n{said}" if said else ""))


# --- the notes, distilled ------------------------------------------------------------------------------------------
# A site's notes are lines, newest first, each one what one run found out. They used to be kept to the newest twelve,
# the oldest dropped - and what was dropped was often what still held (how the form goes), while what stayed was what
# one run met once. Now, when there are twelve, the model writes them - with what was distilled before - into one
# account of how the site is worked, and what holds for every site on its recruiting system goes to the system's notes
# (2026-11-25, the owner: "the notes should get better with every application"). The lines that went into it are kept
# with it, to be read on the sites page. Until that is done, more lines are kept than twelve, up to twice as many.
DIGEST_KEEPS = 48       # the lines kept with the account they went into (the newest)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _split(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(the distilled account, or None; the lines noted since it, newest first)."""
    return next((n for n in rows if n.get("digest")), None), [n for n in rows if not n.get("digest")]


def system_of(key: str) -> str:
    """The recruiting system a site is on, by the name its notes are kept under ("system:<name>") - when the program
    knows that system (a playbook ships for it); '' for an employer's own site."""
    from .agent import brief

    ats = norm(key).split(":", 1)[0]
    return ats if ats in brief.playbooks() else ""


def distill_due(key: str) -> bool:
    with db.session() as s:
        row = s.get(Site, norm(key))
        return row is not None and len(_split(list(row.notes or []))[1]) >= KEEP_NOTES


def queue_due() -> list[str]:
    """Every site with as many lines as are distilled (notes from before they were): distilled, in the background."""
    from . import tasks

    with db.session() as s:
        due = [r.key for r in s.query(Site) if ":" in r.key and len(_split(list(r.notes or []))[1]) >= KEEP_NOTES]
    for key in due:
        tasks.enqueue("notes", ref=key, payload={"key": key}, priority=190)
    return due


def note(key: str, text: str, *, keep: int = KEEP_NOTES) -> None:
    """Remember something the AI found out about working this site. The same thing said again moves to the top. Once
    there are ``keep`` lines, they are distilled (in the background: distill); lines beyond twice that are dropped,
    oldest first, should that not happen."""
    from . import knowledge

    key, text = norm(key), re.sub(r"\s+", " ", text or "").strip()
    if not key or not text:
        return
    if ":" not in key:
        knowledge.add_site_note(key, text, keep=keep)
        return
    with db.session() as s:
        row = _row(s, key, make=True)
        digest, raw = _split(list(row.notes or []))
        raw = [{"at": date.today().isoformat(), "text": text[:1200]}, *[n for n in raw if n.get("text") != text[:1200]]][: keep * 2]
        row.notes = [*([digest] if digest else []), *raw]
        due = len(raw) >= keep
    if due:
        from . import tasks

        tasks.enqueue("notes", ref=key, payload={"key": key}, priority=190)


DISTILL = """You keep what an application agent has learned about working one employer's careers site, so that the
next application there goes straight through. You are given what was written before (an account distilled earlier,
if any) and the notes runs left since, newest first.

Write one account of how this site is worked, for the agent to read before it starts:
- in short sections by stage, those that apply: getting to the form; signing in or registering; the form, step by
  step; files; sending and the confirmation; what to watch out for;
- only what is concrete and still holds: labels, buttons, addresses, selectors and orders as they were noted, word for
  word; where notes disagree, the newer one holds; leave out what happened once and says nothing about the site (a
  posting that was closed, a run that was interrupted, a question one posting asked);
- nothing about the applicant: no e-mail address, name, phone number, password or answer of theirs - say "the
  applicant's address" and the like;
- at most about 2,500 characters, in English.

Separately, under "system": what you learned that holds for every site on the recruiting system named below, not for
this employer only - each a sentence or two; none when nothing does, or when no system is named."""


def distill(key: str) -> dict[str, Any]:
    """Write a site's notes into one account (DISTILL); what holds for its whole recruiting system goes to that
    system's notes. The lines that went in are kept with the account; lines noted while the model wrote stay lines."""
    import json as _json

    from . import llm

    key = norm(key)
    with db.session() as s:
        row = s.get(Site, key)
        digest, raw = _split(list(row.notes or []) if row is not None else [])
    if not raw:
        return {"distilled": 0}
    system = "" if key.startswith("system:") else system_of(key)
    schema = llm.obj({"how": {"type": "string"}, "system": {"type": "array", "items": {"type": "string"}}})
    on = system or "(none: an employer's own site)"
    out = llm.json(f"<site>{name(key)} ({key})</site>\n<recruiting_system>{on}</recruiting_system>\n\n"
                   f"<written_before>\n{(digest or {}).get('text') or '(nothing yet)'}\n</written_before>\n\n<notes>\n"
                   + "\n".join(_json.dumps(n, ensure_ascii=False) for n in raw) + "\n</notes>", schema, system=DISTILL)
    how = _EMAIL.sub("(the applicant's address)", str(out.get("how") or "")).strip()[:6000]
    if not how:
        return {"distilled": 0}
    went = {(n.get("at"), n.get("text")) for n in raw}
    with db.session() as s:
        row = _row(s, key, make=True)
        _, now_raw = _split(list(row.notes or []))
        kept = [n for n in now_raw if (n.get("at"), n.get("text")) not in went]       # (noted while the model wrote)
        folded = [{"at": n.get("at", ""), "text": n.get("text", "")} for n in raw] + list((digest or {}).get("from") or [])
        row.notes = [{"at": date.today().isoformat(), "text": how, "digest": True, "from": folded[:DIGEST_KEEPS]}, *kept]
    up = [_EMAIL.sub("(the applicant's address)", " ".join(str(x).split()))[:600] for x in (out.get("system") or [])][:4] if system else []
    for x in up:
        if x:
            note(f"system:{system}", x)
    return {"distilled": len(raw), "system": len(up)}


def set_digest(key: str, text: str) -> None:
    """The applicant's own wording of how a site is worked (the sites page): it takes the place of the account."""
    key, text = norm(key), str(text or "").strip()[:6000]
    with db.session() as s:
        row = _row(s, key, make=True)
        digest, raw = _split(list(row.notes or []))
        if not text:
            row.notes = raw
            return
        row.notes = [{**(digest or {"from": []}), "at": date.today().isoformat(), "text": text, "digest": True, "by": "applicant"}, *raw]


# --- all of it -----------------------------------------------------------------------------------------------------

def about(key: str) -> dict[str, Any]:
    """Everything the program knows about one site."""
    key = norm(key)
    with db.session() as s:
        row = s.get(Site, key)
        facts = {**FACTS, **{k: v for k, v in ((row.facts or {}) if row is not None else {}).items() if k in FACTS}}
        same_as = str(row.same_as or "") if row is not None else ""
        updated = row.updated_at.isoformat() if row is not None and row.updated_at else ""
        digest, kept = _split(list(row.notes or [])) if row is not None and ":" in key else (None, [])
    return {"key": key, "name": name(key), "explored": explored(key), "signs_in_on": same_as, "facts": facts, "updated": updated, "digest": digest,
            "notes": kept if ":" in key else [{"at": "", "text": ln[2:]} for ln in notes(key).splitlines() if ln.startswith("- ")][:KEEP_NOTES]}


def listing() -> list[dict[str, Any]]:
    """Every site something is known about, with how much."""
    with db.session() as s:
        return [{"key": r.key, "name": name(r.key), "explored": explored(r.key), "signs_in_on": str(r.same_as or ""), "notes": len(r.notes or []),
                 "facts": {k: v for k, v in (r.facts or {}).items() if v and k in FACTS}, "updated": r.updated_at.isoformat() if r.updated_at else ""}
                for r in s.query(Site).order_by(Site.key)]


def forget(key: str) -> dict[str, int]:
    """Drop what was written down about working this site. Where it signs in and which browser its sign-in lives in
    are kept: those are about the account, and still true."""
    key = norm(key)
    out = {"notes": 0}
    with db.session() as s:
        row = s.get(Site, key)
        if row is not None:
            out["notes"] = len(row.notes or [])
            row.notes, row.steps = [], {}
    return out


def move(old: str, new: str) -> bool:
    """The site is now reached under another address: everything known about it goes with it."""
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
        # (one account of how the site is worked: the new address's, else the old one's - the other's text goes on as a
        # line, to be distilled with the rest; lines beyond twice the number distilled at are dropped, as in note())
        db_, rb = _split(list(b.notes or []))
        da, ra = _split(list(a.notes or []))
        seen = {n.get("text") for n in rb}
        raw = [*rb, *[n for n in ra if n.get("text") not in seen]]
        if db_ and da:
            raw.append({"at": da.get("at", ""), "text": str(da.get("text", ""))[:1200]})
        digest = db_ or da
        b.notes = [*([digest] if digest else []), *raw[: KEEP_NOTES * 2]]
        s.delete(a)
        for other in s.query(Site).filter(Site.same_as == old):
            other.same_as = new
    return True


# --- from the five places it used to be kept in -------------------------------------------------------------------------

def migrate() -> dict[str, int]:
    """Bring what earlier versions kept elsewhere into the one place. Run once at start; what is read is left where it
    was (files are moved into a folder named "migrated" beside them), so that going back a version loses nothing."""
    import shutil

    from sqlalchemy import text

    from . import config, knowledge

    done = {"links": 0, "facts": 0, "notes": 0, "runs": 0}
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
    with db.session() as s:
        got = s.execute(text("UPDATE runs SET site = (CASE WHEN ats IS NULL OR ats = '' THEN 'generic' ELSE ats END) || ':' || substr(site, 6) WHERE site LIKE 'site-%'"))
        done["runs"] = int(got.rowcount or 0)
    if any(done.values()):
        log.info("what was known about sites is kept in one place now: %s", done)
    return done


__all__ = ["about", "account", "explored", "fact", "forget", "having", "key_of", "link", "links", "listing", "migrate", "move", "name", "norm", "note", "notes",
           "set_fact", "where", "now"]

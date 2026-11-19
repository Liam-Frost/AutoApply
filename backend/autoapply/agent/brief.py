"""What the agent is told about one application: all of it, in one piece.

Not a slice per step and not a schema: the posting as it reads, the applicant's profile as they wrote it, their
résumé, the files they have, what earlier work on this site wrote down, what earlier runs on this application did,
and the record the applicant approved when there is one. What to make of it is the agent's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MANUAL = Path(__file__).with_name("apply.md")

# How a run may end as far as sending goes. (The applicant's setting decides which of these a run is given.)
MODES = {
    "prepare": "PREPARE ONLY. Work the application up to the point where one press would send it to the employer, and do not make that press. "
               "Fill and save every step on the way. Then report what the application holds and what is still open.",
    "send": "SEND. The applicant has approved the record below. Open the application, read back what the site holds, bring it in line with the approved record "
            "(a site that parsed the résumé again may have changed things), and send it. If something differs from the record in a way you cannot put right, "
            "do not send: report the difference.",
    "auto": "SEND IF NOTHING IS OPEN. Work the application to the end. If every question has an answer from what you were given and nothing is in doubt, send it. "
            "If a question is open or you are unsure of something that matters, do not send: stop before the last press and report, as in a prepare run.",
    "verify": "FIND OUT WHETHER IT WENT OUT. An earlier run wrote that it was about to send this application and then stopped without saying what came of it. "
              "Do not touch the form and do not send anything. Look where the site shows the applicant's applications (a dashboard, 'My applications', the posting's own page "
              "saying 'applied'), and at the applicant's mail from this employer. Then report: `submitted` with the confirmation if it is out; `ready` if the site shows it "
              "as not sent (a draft, or not there at all); `needs_you` if you cannot tell - say what you saw.",
    "hand_over": "STOP AT THE LAST STEP. Work the application up to the point where one press would send it and do not make that press. Then call `hand_window`: "
                 "the applicant looks it over and presses it themselves in this window. When the window comes back to you, find out what they did (look at the page, "
                 "at the site's list of applications) and report it: `submitted` with the confirmation, or `ready` if it was not sent.",
}


@dataclass
class Applicant:
    profile: str = ""
    stories: str = ""
    resume: str = ""                                          # the résumé as text
    files: dict[str, str] = field(default_factory=dict)       # the name the agent uses -> path on disk
    file_notes: dict[str, str] = field(default_factory=dict)  # name -> what it is ("résumé (PDF)", "transcript")
    login: str = ""                                           # the e-mail accounts are made with


@dataclass
class Posting:
    company: str = ""
    title: str = ""
    url: str = ""
    text: str = ""            # the posting as it reads
    deadline: str = ""
    extra: str = ""           # anything else known (term, place, documents asked for)


def site_key(url: str) -> str:
    """The name the program keeps this site's session, account and notes under."""
    from .. import sites

    return sites.key_of(url)


MANUAL_TEXT = MANUAL.read_text(encoding="utf-8")       # as it ships: what the applicant's own version (prompts.py) starts from


def manual() -> str:
    """The manual as the agent gets it: the applicant's version if they changed it, with what is fixed after it."""
    from .. import prompts

    return prompts.get("apply")


# --- what is known about recruiting systems -------------------------------------------------------------------------
# Two kinds of notes reach the agent. What ships with the program (playbooks/*.md): what is true of a recruiting
# system on every employer's site - written from applications made by hand, kept free of anything about a person.
# And what agents wrote down themselves while they worked (sites.note): about one site, or about a system.
PLAYBOOKS = Path(__file__).with_name("playbooks")


def playbooks() -> dict[str, tuple[list[str], str]]:
    """{name: (the hosts it is about, its text)}"""
    out = {}
    for p in sorted(PLAYBOOKS.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        first, _, rest = text.partition("\n")
        hosts = [h.strip().lower() for h in first.split(":", 1)[1].split(",")] if first.lower().startswith("hosts:") else []
        out[p.stem] = (hosts, rest.strip() if hosts else text.strip())
    return out


def playbook_for(url: str) -> tuple[str, str]:
    """(name, text) of the playbook about the system this address is on, or ("", "")."""
    host = (urlparse(url).hostname or "").lower()
    for name, (hosts, text) in playbooks().items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name, text
    return "", ""


def about(name: str) -> str:
    """Everything written down about a recruiting system: what ships with the program, then what agents noted."""
    from .. import sites

    from .. import knowledge

    name = name.strip().lower()
    shipped = playbooks().get(name, ([], ""))[1]
    noted = sites.notes(f"system:{name}")
    own = knowledge.playbook(name).strip() if name in knowledge.list_playbooks() else ""      # what the applicant keeps about this system themselves
    return "\n\n".join(x for x in (shipped, ("The applicant's own notes:\n" + own) if own else "", ("Noted while working:\n" + noted) if noted else "") if x)


def goal(posting: Posting, applicant: Applicant, *, mode: str, site_notes: str = "", systems: list[str] | None = None, journal: str = "",
         record: dict[str, Any] | None = None, answers: dict[str, str] | None = None, account: str = "", budget: str = "") -> str:
    """The whole context of this run, as the first thing the agent reads."""
    import json

    parts = [
        "# This application",
        f"Employer: {posting.company}\nRole: {posting.title}\nWhere to apply: {posting.url}"
        + (f"\nDeadline: {posting.deadline}" if posting.deadline else "") + (f"\n{posting.extra}" if posting.extra else ""),
        f"<posting>\n{posting.text.strip() or '(the text of the posting is not on record: read it on the site)'}\n</posting>",
        "# Mode",
        MODES[mode],
        "# The applicant",
        f"<profile>\n{applicant.profile.strip()}\n</profile>",
    ]
    if applicant.stories.strip():
        parts.append(f"<stories>\n{applicant.stories.strip()}\n</stories>")
    if applicant.resume.strip():
        parts.append(f"<resume>\n{applicant.resume.strip()[:30000]}\n</resume>")
    if applicant.files:
        parts.append("Files you may upload (by these names):\n" + "\n".join(f"- {name!r}: {applicant.file_notes.get(name, '')}".rstrip(": ") for name in applicant.files))
    else:
        parts.append("There are no files of the applicant to upload.")
    if applicant.login:
        parts.append(f"The e-mail address accounts are made and signed in with: {applicant.login}")
    parts += ["# This site", account or "The program has no account on record for this site."]
    parts.append(f"<site_notes>\n{site_notes.strip()}\n</site_notes>" if site_notes.strip() else "Nothing has been written down about this site yet. You are the first: leave notes.")
    if systems:
        parts.append("Notes exist about these recruiting systems (read one with `notes` when you see the site runs on it): " + ", ".join(systems))
    if answers:
        parts += ["# What the applicant answered when asked about this application", "\n".join(f"- {q}\n  → {a}" for q, a in answers.items())]
    if record:
        parts += ["# The record of this application" + (" (approved by the applicant)" if record.get("approved_by_the_applicant") else " (from the last run)"),
                  f"<record>\n{json.dumps(record, ensure_ascii=False, indent=1)[:40000]}\n</record>"]
    if journal.strip():
        parts += ["# Earlier runs on this application",
                  "What was written down then, oldest first. The site may not have kept everything: read back what is there before you go on.",
                  f"<journal>\n{journal.strip()[-12000:]}\n</journal>"]
    if budget:
        parts += ["# Budget", budget]
    parts += ["# Language", reads()]
    return "\n\n".join(parts)


def reads() -> str:
    """Which language the applicant reads the program in: what the agent writes for them is in it."""
    from .. import db

    lang = "English" if (db.get_setting("ui.lang") or "zh") == "en" else "Simplified Chinese"
    return (f"The applicant reads this program in {lang}. Write for them in it: `log` lines, the `why` of a question you `ask`, where an answer comes from (`from`), "
            "and your report's summary and open points. Keep names, quoted text of the form and what you enter on the form as they are; write notes about sites (`note`) in English.")


def applicant_on_file(channel: str = "") -> Applicant:
    """The applicant as the program knows them: their profile, stories, résumé and active files."""
    from .. import db, knowledge
    from ..materials import _doc_text
    from ..models import Document

    kinds = {"resume_site": "résumé (PDF, for employers' sites)", "resume_portal": "résumé (PDF, for the school portal)", "resume_docx": "résumé (Word)",
             "transcript": "transcript", "portfolio": "portfolio", "certificate": "certificate", "reference": "reference", "writing_sample": "writing sample"}
    a = Applicant(profile=knowledge.read("profile"), stories=knowledge.stories(), login=str(db.get_setting("account.email") or ""))
    with db.session() as s:
        for d in s.query(Document).filter(Document.active == 1, Document.job_id.is_(None), Document.kind.in_(tuple(kinds))).order_by(Document.id.desc()):
            if not Path(d.path).exists() or d.name in a.files:
                continue
            a.files[d.name], a.file_notes[d.name] = d.path, kinds[d.kind]
            if not a.resume and d.kind in ("resume_site", "resume_portal", "resume_docx"):
                a.resume = _doc_text(d.path)
    return a

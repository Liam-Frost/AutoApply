"""The Markdown knowledge base: profile.md, scoring.md, playbooks/*.md.

Both the user and the agent edit these. Every save keeps a version so any
change (especially agent-appended rules) can be reviewed and rolled back.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import config, db
from .models import ProfileVersion

DOCS = {"profile": config.PROFILE_MD, "scoring": config.SCORING_MD, "stories": config.STORIES_MD}

EMPTY_STORIES = """# My stories

Real situations from your own experience, used to answer open questions on application forms
("tell us about a time you ...", "describe a challenge", "why this field"). One story per heading.
Write what happened in your own words - the program only rephrases and shortens, it never adds to them.

## (example - replace or delete) A conflict in a team project

- Situation:
- What I did:
- Result:
- Good for questions about: teamwork, conflict, communication
"""

PROFILE_SECTIONS = [
    "Identity & contact",
    "Education",
    "Work authorization",
    "Availability",
    "Standard answers",
    "Experience",
    "Rules",
    "Materials",
    "Agent-added",
]

EMPTY_PROFILE = "# Applicant profile\n\n" + "\n".join(f"## {s}\n\n" for s in PROFILE_SECTIONS)

LEGACY_SCORING = """# Scoring rules

Score every posting 0-10 for fit after reading the FULL job description.
Never score from the title alone; if the description is missing, leave the job unscored.

## Hard exclusions (do not apply; score 0 and name the rule)

- Work term is 12 or 16 months only.
- Summer term of 8 months or longer (exceeds availability).
- Requires citizenship or permanent residency, or a security clearance.
- States that no visa sponsorship is available now or in the future.
- French is mandatory.
- Graduation window does not include the applicant's graduation date.
- Open only to Master's or PhD students.

## Fit (0-10)

- 9-10: core backend, full-stack, or ML/AI engineering roles.
- 7-8.5: related or mixed software roles (embedded/firmware, DevOps, test automation with real coding).
- 5-6.5: adjacent (QA-heavy, security analyst, hardware verification).
- below 5: off-target (electrical, mechanical, research assistant, marketing).
"""


DEFAULT_SCORING = """# Scoring rules

Score every posting 0-10 for fit after reading the FULL job description.
Never score from the title alone; if the description is missing, leave the job unscored.

## Hard exclusions (do not apply; score 0 and name the rule)

- The posting requires a licence, clearance or citizenship the applicant does not have.

## Fit (0-10)

- 9-10: the core of what the applicant is looking for.
- 7-8.5: closely related roles where most of the work matches.
- 5-6.5: adjacent roles; some overlap, not the target.
- below 5: off-target.
"""


def read(doc: str = "profile") -> str:
    p = DOCS[doc]
    if not p.exists():
        return EMPTY_PROFILE if doc == "profile" else EMPTY_STORIES if doc == "stories" else DEFAULT_SCORING
    return p.read_text(encoding="utf-8")


def write(doc: str, content: str, *, source: str = "user", note: str = "") -> int:
    """Save a document and record a version. Returns the version id."""
    DOCS[doc].write_text(content, encoding="utf-8")
    with db.session() as s:
        v = ProfileVersion(doc=doc, content=content, source=source, note=note)
        s.add(v)
        s.flush()
        return v.id


def versions(doc: str = "profile", limit: int = 50) -> list[dict]:
    with db.session() as s:
        rows = s.query(ProfileVersion).filter_by(doc=doc).order_by(ProfileVersion.id.desc()).limit(limit).all()
        return [
            {"id": r.id, "source": r.source, "note": r.note, "created_at": r.created_at.isoformat(), "size": len(r.content)}
            for r in rows
        ]


def restore(version_id: int) -> str:
    with db.session() as s:
        v = s.get(ProfileVersion, version_id)
        if v is None:
            raise KeyError(version_id)
        doc, content = v.doc, v.content
    write(doc, content, source="user", note=f"restored version {version_id}")
    return content


# --- sections ------------------------------------------------------------------

_H2 = re.compile(r"^## +(.+?)\s*$", re.M)


def stories() -> str:
    """The stories the applicant actually wrote ('' while it is still the empty template)."""
    p = DOCS["stories"]
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8")
    body = re.sub(r"(?s)## \(example.*?(?=\n## |\Z)", "", txt)
    return txt.strip() if re.search(r"(?m)^## ", body) and len(re.sub(r"\s", "", body)) > 120 else ""


def split_sections(md: str) -> list[dict]:
    """Split on level-2 headings. The text before the first heading is 'preamble'."""
    out, last, name = [], 0, "preamble"
    for m in _H2.finditer(md):
        body = md[last : m.start()]
        if name != "preamble" or body.strip():
            out.append({"title": name, "body": body.strip("\n")})
        name, last = m.group(1), m.end()
    out.append({"title": name, "body": md[last:].strip("\n")})
    return out


def join_sections(sections: list[dict]) -> str:
    parts = []
    for sec in sections:
        if sec["title"] == "preamble":
            parts.append(sec["body"].rstrip() + "\n")
        else:
            parts.append(f"## {sec['title']}\n\n{sec['body'].rstrip()}\n")
    return "\n".join(parts)


def append_rule(text: str, *, source: str = "agent", section: str = "Agent-added", note: str = "") -> int:
    """Append a dated bullet to a section (created if missing)."""
    md = read("profile")
    secs = split_sections(md)
    line = f"- {text.strip()} ({source}, {date.today().isoformat()})"
    for sec in secs:
        if sec["title"].lower() == section.lower() or (section.lower() == "standard answers" and "standard answers" in sec["title"].lower()):
            sec["body"] = (sec["body"].rstrip() + "\n" + line).strip("\n")
            break
    else:
        secs.append({"title": section, "body": line})
    return write("profile", join_sections(secs), source=source, note=note or text[:80])


def agent_added(limit: int = 30) -> list[dict]:
    """Recent agent-written versions, for the 'recently added by the agent' panel."""
    with db.session() as s:
        rows = (
            s.query(ProfileVersion)
            .filter_by(doc="profile", source="agent")
            .order_by(ProfileVersion.id.desc())
            .limit(limit)
            .all()
        )
        return [{"id": r.id, "note": r.note, "created_at": r.created_at.isoformat()} for r in rows]


def remove_line(text_fragment: str) -> bool:
    """Undo an agent-added bullet by removing the line that contains the fragment."""
    md = read("profile")
    lines = md.split("\n")
    kept = [ln for ln in lines if not (ln.startswith("- ") and text_fragment in ln)]
    if len(kept) == len(lines):
        return False
    write("profile", "\n".join(kept), source="user", note=f"removed: {text_fragment[:60]}")
    return True


def playbook(ats: str) -> str:
    p = config.PLAYBOOKS / f"{re.sub(r'[^A-Za-z0-9._-]', '_', ats)}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# --- structured parts of the profile -------------------------------------------------
# Salary, notice period and referees are asked on forms in fixed shapes (a number and a currency, a name and an e-mail),
# so they are entered in a form instead of free text. They are stored as settings and written into two sections of the
# profile, which is what every prompt reads. Those two sections belong to the form: saving it rewrites them.

MANAGED = {"compensation": "Compensation and notice period", "referees": "Referees"}
CONTACT = {"anytime": "may be contacted at any stage", "after_offer": "contact only after an offer", "ask_first": "ask the applicant before giving these details to anyone"}


def structured() -> dict:
    return {"compensation": db.get_setting("profile.compensation") or {}, "referees": db.get_setting("profile.referees") or []}


def _money(c: dict) -> str:
    lo, hi = str(c.get("min") or "").strip(), str(c.get("max") or "").strip()
    amount = f"{lo}–{hi}" if lo and hi and lo != hi else (lo or hi)
    if not amount:
        return ""
    per = {"year": "per year", "month": "per month", "hour": "per hour"}.get(c.get("period") or "year", "per year")
    return f"{amount} {(c.get('currency') or '').strip()} {per}".replace("  ", " ").strip()


def compensation_md(c: dict) -> str:
    lines = []
    money = _money(c)
    if c.get("policy") == "ask":
        lines.append("- Salary / compensation questions: **do not state a figure**. Leave the question for the applicant to answer each time.")
    elif money:
        lines.append(f"- Expected salary: **{money}**" + (" (negotiable; where a form allows text, say so)" if c.get("negotiable") else "") + ".")
        lines.append("- Where a form wants a single number, give the lower end of the range. Where the question is optional, leave it empty.")
    if (c.get("current") or "").strip() and c.get("share_current"):
        lines.append(f"- Current salary (may be stated when a form requires it): {c['current'].strip()}.")
    elif (c.get("current") or "").strip():
        lines.append("- Current salary: the applicant does not disclose it. If a form requires it, leave the question for the applicant.")
    if (c.get("notice") or "").strip():
        lines.append(f"- Notice period: {c['notice'].strip()}.")
    if (c.get("start") or "").strip():
        lines.append(f"- Earliest start date: {c['start'].strip()}.")
    if (c.get("notes") or "").strip():
        lines.append(f"- {c['notes'].strip()}")
    return "\n".join(lines)


def referees_md(rs: list) -> str:
    lines = []
    for r in rs:
        if not (r.get("name") or "").strip():
            continue
        who = ", ".join(x for x in ((r.get("title") or "").strip(), (r.get("org") or "").strip()) if x)
        bits = [f"**{r['name'].strip()}**" + (f" ({who})" if who else "")]
        if (r.get("relation") or "").strip():
            bits.append(f"relationship: {r['relation'].strip()}")
        if (r.get("email") or "").strip():
            bits.append(f"e-mail {r['email'].strip()}")
        if (r.get("phone") or "").strip():
            bits.append(f"phone {r['phone'].strip()}")
        bits.append(CONTACT.get(r.get("contact") or "ask_first", CONTACT["ask_first"]))
        lines.append("- " + "; ".join(bits) + ".")
    if lines:
        lines.append("- Give a referee's details only in the fields a form provides for referees, never in free text, and only for the referees listed here.")
    return "\n".join(lines)


def set_structured(data: dict) -> int:
    """Save the form and rewrite its two sections of the profile (a section with nothing in it is removed)."""
    comp = dict(data.get("compensation") or {})
    refs = [dict(r) for r in data.get("referees") or [] if (r.get("name") or "").strip()]
    db.set_setting("profile.compensation", comp)
    db.set_setting("profile.referees", refs)
    bodies = {MANAGED["compensation"]: compensation_md(comp), MANAGED["referees"]: referees_md(refs)}
    secs = [sec for sec in split_sections(read("profile")) if sec["title"] not in bodies]
    secs += [{"title": t, "body": b} for t, b in bodies.items() if b]
    return write("profile", join_sections(secs), source="user", note="薪资与推荐人")


NOTES_HEAD = "## Learned by the program on earlier runs"


def add_site_note(key: str, text: str, *, keep: int = 12) -> None:
    """Remember something the AI take-over found out about a site or system. Notes sit at the top of that playbook
    (newest first, the oldest dropped), where the next exploration and the next take-over read them."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return
    p = config.PLAYBOOKS / f"{re.sub(r'[^A-Za-z0-9._-]', '_', key)}.md"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    notes, rest = [], old
    if old.startswith(NOTES_HEAD):
        block, _, rest = old.partition("\n\n")
        notes = [ln for ln in block.splitlines()[1:] if ln.startswith("- ")]
    notes = [ln for ln in notes if re.sub(r"^- \(\d{4}-\d{2}-\d{2}\) ", "", ln) != text]
    notes.insert(0, f"- ({date.today().isoformat()}) {text[:1200]}")
    p.write_text(NOTES_HEAD + "\n" + "\n".join(notes[:keep]) + "\n\n" + rest.lstrip("\n"), encoding="utf-8")


def list_playbooks() -> list[str]:
    return sorted(p.stem for p in Path(config.PLAYBOOKS).glob("*.md"))

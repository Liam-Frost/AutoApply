"""UBC Engineering Co-op PD Portal (Orbis) as a job source.

The portal is read by the agent (agent/scan.py): it signs in with the stored login - the university's, with a second
factor the applicant approves on their phone - finds the list of postings and gives them to the program. How the
list was read the last time, down to the script, is in the agent's notes about this kind of portal
(agent/playbooks/orbis.md) and in what it wrote down itself; nothing here runs before the agent does.

What is here: which browser the portal lets in, and how a posting's text becomes a row of the postings table. The
session is kept under ``pdportal:ubc``.
"""

from __future__ import annotations

from ..say import say as T

import re
from datetime import datetime
from typing import Any, Iterator

from .. import browser, notify
from ..errors import NeedsHuman

TENANT = "pdportal:ubc"
BASE = "https://pdportal.apsc.ubc.ca"
POSTINGS = f"{BASE}/myAccount/co-op/postings.htm"


def _field(text: str, key: str, n: int = 300) -> str:
    i = text.find(key)
    if i < 0:
        return ""
    chunk = text[i + len(key) : i + len(key) + n].strip()
    return (chunk.split("\n")[0] if chunk else "").strip()


def _deadline(text: str) -> str:
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"Application Deadline:\s*([A-Z][a-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M)", flat)
    if not m:
        return ""
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y %I:%M %p").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


def parse_detail(pid: str, text: str) -> dict[str, Any]:
    flat = re.sub(r"\s+", " ", text)
    jd_i, req_i = text.find("Job Description:"), text.find("Job Requirements:")
    end_i = text.find("APPLICATION INFORMATION")
    jd = text[jd_i : end_i if end_i > jd_i else jd_i + 12000] if jd_i >= 0 else ""
    proc = _field(text, "Application Receipt Procedure:")
    site = (re.search(r"If by Website, go to:\s*(https?://\S+)", flat) or [None, ""])[1]
    term = _field(text, "Co-op Work Term:")
    m = re.match(r"(\d{4})\s*-\s*(\w+)", term)
    return {
        "source": "pdportal", "source_id": pid,
        "title": _field(text, "Job Title:"), "company": _field(text, "Company:") or _field(text, "Organization:"),
        "term": f"{m.group(2)} {m.group(1)}" if m else term,
        "months": " ".join(re.sub(r"months?", " ", _field(text, "Length of Work Term:")).split()),
        "location": _field(text, "Job Location:"), "salary": _field(text, "Salary ($):"),
        "deadline": _deadline(text), "docs_required": _field(text, "Application Documents Required:"),
        "channel": "PD Portal" if "system" in proc.lower() else "employer site",
        "apply_url": site if site and "system" not in proc.lower() else f"{POSTINGS}#posting={pid}",
        "ats": "pdportal" if "system" in proc.lower() else "",
        "jd_text": jd.strip() + ("\n\nJob Requirements:" + text[req_i + 17 : req_i + 6000] if req_i >= 0 and req_i > (end_i if end_i > 0 else 10**9) else ""),
    }


def refused(page: Any) -> bool:
    """Is this the firewall's page instead of the portal's?"""
    try:
        return bool(re.search(r"cloudflare|just a moment|attention required", page.title(), re.I)
                    or re.search(r"you have been blocked|verify(ing)? you are human|checking your browser", page.inner_text("body")[:600], re.I))
    except Exception:  # noqa: BLE001 - a page that cannot be read yet is not a refusal
        return False


def firewall(page: Any) -> None:
    """The firewall answered instead of the portal. First time: remember that the portal wants a window and say so
    (RefusedHidden - the caller tries again). In a window as well: its pass has run out, which signing in renews."""
    from .. import db

    if browser.needs_window(TENANT):
        raise browser.RefusedHidden()
    if db.get_setting("browser.nodriver_enabled"):
        notify.add_todo("takeover", "PD Portal（CWL + Duo）", ref=f"account:{TENANT}", payload={"tenant_key": TENANT, "ats": "pdportal", "url": f"{BASE}/home.htm"},
                        body=T("server.sources.pdportal.thePortalsFirewallDid"))
        raise NeedsHuman("PD Portal's firewall did not let the browser in: signing in again renews its pass", kind="login", url=f"{BASE}/home.htm")
    notify.add_todo("config", T("server.sources.pdportal.pdPortalRefusedThe"), ref="config:pdportal-blocked",
                    body=T("server.sources.pdportal.thePortalsProtectionRefused"))
    raise RuntimeError("blocked by the site's firewall (Cloudflare): automated browsers are refused")


def _when(said: Any) -> str:
    """A deadline as the agent gave it, in the form the program keeps ('' when it is not a date it can read)."""
    said = " ".join(str(said or "").split())
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%B %d, %Y %I:%M %p", "%b %d, %Y %I:%M %p", "%B %d, %Y"):
        try:
            return datetime.strptime(said[:40], fmt).strftime("%Y-%m-%d %H:%M" if "%H" in fmt or "%I" in fmt else "%Y-%m-%d 23:59")
        except ValueError:
            continue
    return ""


def row_of(p: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A posting the agent saved, as a row of the postings table - and what about it the agent should look at again.
    What the agent read itself stands; what it left out is read from the posting's text by ``parse_detail``."""
    pid = str(p.get("id") or "").strip()
    text = str(p.get("text") or "")[:40000]
    row = parse_detail(pid, text) if text.strip() else {"source": "pdportal", "source_id": pid, "title": "", "company": "", "deadline": "", "jd_text": "", "channel": "", "apply_url": "", "ats": ""}
    look: list[str] = []
    from ..discover import company_name

    for mine, theirs in (("title", "title"), ("company", "company"), ("term", "term"), ("months", "months"), ("location", "location"), ("salary", "salary"), ("docs_required", "documents")):
        if str(p.get(theirs) or "").strip():
            row[mine] = " ".join(str(p[theirs]).split())[:300]
    if row.get("company"):
        row["company"] = company_name(row["company"])      # (the page's text can run the posting's fields into the name)
    if str(p.get("deadline") or "").strip():
        when = _when(p["deadline"])
        if when:
            row["deadline"] = when
        else:
            look.append(f"deadline {str(p['deadline'])[:40]!r} was not understood (give it as YYYY-MM-DD HH:MM)")
    how = str(p.get("how_to_apply") or "").strip().lower()
    if how == "portal":
        row.update(channel="PD Portal", ats="pdportal", apply_url=f"{POSTINGS}#posting={pid}")
    elif how == "website" and str(p.get("apply_url") or "").startswith("http"):
        row.update(channel="employer site", ats="", apply_url=str(p["apply_url"]).strip())
    elif how:
        row.update(channel=how[:40], ats="")
    if not text.strip():
        look.append("no text")
    if not row.get("title"):
        look.append("no title")
    return row, look


def _facts() -> str:
    """What the program knows that bears on signing in now: said to the agent, which decides."""
    from .. import db, sites, tasks
    from ..models import Todo

    out = []
    if tasks.running_by_hand():
        out.append("The applicant started this scan themselves, just now.")
    elif notify.quiet_now():
        out.append("It is inside the applicant's quiet hours (nothing is pushed to their phone now), and they did not start this scan themselves. "
                   "A sign-in that asks for an approval on their phone would ring it and most likely not be answered.")
    if sites.fact(TENANT, "second_factor"):
        out.append("The last sign-in here asked for an approval on the applicant's phone.")
    with db.session() as s:
        card = s.query(Todo).filter_by(kind="takeover", ref=f"account:{TENANT}", status="open").order_by(Todo.id.desc()).first()
        if card is not None:
            out.append(f"A card asking the applicant to sign in to this site by hand has been open since {card.created_at:%Y-%m-%d %H:%M} (UTC) and is not dealt with yet: {str(card.body or '')[:200]}")
    return "\n".join(f"- {x}" for x in out)


def collector(known_ids: set[str]) -> tuple[Any, list[str], dict[str, dict[str, Any]]]:
    """(keep, listed, rows): ``keep`` stores what the agent saves into the other two, and answers with what the agent
    is shown of it."""
    listed: list[str] = []
    rows: dict[str, dict[str, Any]] = {}

    def keep(ids: list[str], postings: list[dict[str, Any]]) -> str:
        listed[:] = list(dict.fromkeys([*listed, *ids]))
        shown = []
        for p in postings:
            row, look = row_of(p)
            if not row["source_id"]:
                continue
            rows[row["source_id"]] = row
            shown.append(f"  {row['source_id']} | {row.get('title') or '?'} | {row.get('company') or '?'} | deadline {row.get('deadline') or '?'} | applied for: {row.get('channel') or '?'}"
                         + (f" {row['apply_url']}" if row.get("channel") == "employer site" else "") + (f"   <- {'; '.join(look)}" if look else ""))
        missing = [i for i in listed if i not in known_ids and i not in rows]
        return (f"{len(listed)} postings are listed; the program had the text of {sum(1 for i in listed if i in known_ids)} of them. Stored so far: {len(rows)}."
                + ("\nStored now:\n" + "\n".join(shown[:80]) + (f"\n  ... and {len(shown) - 80} more, stored the same way" if len(shown) > 80 else "") if shown else "")
                + (f"\nListed, new, and not stored yet: {', '.join(missing[:60])}" + (" ..." if len(missing) > 60 else "") if missing else "\nNothing that is listed is missing."))

    return keep, listed, rows


def scan(known_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    """Yield every live posting. The text is read only for ids not in ``known_ids``; known ones are yielded as bare
    ids so the caller can keep them online."""
    try:
        yield from _scan(known_ids)
    except browser.RefusedHidden:           # nothing was yielded yet: once more, now in a window
        yield from _scan(known_ids)


def _scan(known_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    from .. import auth
    from ..agent import scan as agent_scan

    if known_ids is None:
        from .. import db
        from ..models import Job

        with db.session() as s:
            known_ids = {j.source_id for j in s.query(Job).filter(Job.source == "pdportal", Job.jd_text != "")}
    keep, listed, rows = collector(known_ids)

    with browser.open_page(TENANT, url=POSTINGS, operation="scan") as page:
        page.goto(POSTINGS, wait_until="domcontentloaded")
        for _ in range(15):                 # the firewall's own check of the browser passes by itself in a real window: give it the time
            if not refused(page):
                break
            page.wait_for_timeout(1000)
        else:
            firewall(page)
        out = agent_scan.read(page, site=TENANT, name="UBC PD Portal (co-op postings)", url=POSTINGS, known=known_ids, keep=keep, facts=_facts(), system="orbis")
        if listed or rows:
            notify.close_todos("config", "config:pdportal-blocked")      # the portal let this browser in: a card that said it did not is settled
            browser.save_state(TENANT, page.context)
    if not listed and not rows:
        if out.get("needs_applicant"):
            waits = auth.ask_to_sign_in(TENANT, "PD Portal（CWL + Duo）", out["needs_applicant"], url=f"{BASE}/home.htm")
            raise NeedsHuman(out["needs_applicant"], kind="login", url=f"{BASE}/home.htm", waits_for=waits)
        raise RuntimeError(f"the portal's postings were not read: {out.get('why') or 'the agent gave no reason'}")
    if not out.get("ok"):
        listed[:] = list(dict.fromkeys([*listed, *known_ids]))      # a scan that did not finish takes nothing offline
    for i in listed:
        if i in known_ids and i not in rows:
            yield {"source": "pdportal", "source_id": i}
    for row in rows.values():
        if row.get("jd_text") or row.get("title"):
            yield row

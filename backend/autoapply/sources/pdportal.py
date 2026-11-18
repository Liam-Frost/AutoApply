"""UBC Engineering Co-op PD Portal (Orbis) as a job source.

Login is CWL + Duo, which only the user can do. Policy (plan 5.5): no keep-alive;
when a scan finds the session expired it raises NeedsHuman, a to-do and a
Telegram message are created, and the scan resumes after the user signs in via
takeover (session saved under tenant key ``pdportal:ubc``).

Mechanics (from the hand-driven sessions, 2026-09..11; not yet exercised by this code
because it needs a live CWL session):
  * postings.htm -> submit the keyword widget with an empty keyword to list everything
  * rows carry onclick="...buildForm({...postingId...})"; the object is the token set
    needed to POST for a posting's detail page
  * paging: loadPostingTable('', 'ID', 'Reverse', '<page>', 'advanced', '', null)
  * detail: POST /myAccount/co-op/postings.htm with that object + postingId
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterator

from .. import browser, notify
from ..ats.base import NeedsHuman

TENANT = "pdportal:ubc"
BASE = "https://pdportal.apsc.ubc.ca"
POSTINGS = f"{BASE}/myAccount/co-op/postings.htm"

_LIST_JS = r"""async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const grab = () => [...new Set([...document.querySelectorAll('[onclick*=postingId]')]
      .map(e => (e.getAttribute('onclick').match(/postingId[^0-9]{1,6}(\d{5,7})/) || [])[1]).filter(Boolean))];
  const el = document.querySelector('[onclick*=postingId][onclick*=infoForPostings]');
  if (!el) return {ids: [], obj: null};
  const m = el.getAttribute('onclick').match(/buildForm\((\{[\s\S]*?\})\s*,/);
  const obj = (0, eval)('(' + m[1] + ')'); delete obj.postingId;
  const all = new Set(grab());
  const pages = [...document.querySelectorAll('a')].map(a => (a.getAttribute('onclick') || '').match(/loadPostingTable\([^)]*?'(\d+)'\s*,\s*'advanced'/)).filter(Boolean).map(m => +m[1]);
  const last = Math.max(1, ...pages);
  for (let p = 2; p <= last; p++) {
    window.loadPostingTable('', 'ID', 'Reverse', String(p), 'advanced', '', null);
    await sleep(3500);
    grab().forEach(i => all.add(i));
  }
  return {ids: [...all], obj};
}"""

_DETAIL_JS = r"""async ([obj, ids]) => {
  const out = [];
  for (const id of ids) {
    try {
      const r = await fetch('/myAccount/co-op/postings.htm', {method: 'POST', body: new URLSearchParams({...obj, postingId: id})});
      const d = document.createElement('div'); d.innerHTML = await r.text();
      const x = (d.querySelector('main') || d).innerText.replace(/[ \t]+/g, ' ');
      out.push({id, text: x.slice(0, 40000)});
    } catch (e) { out.push({id, text: ''}); }
  }
  return out;
}"""


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


def scan(known_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    """Yield every live posting. Details are fetched only for ids not in ``known_ids``;
    known ones are yielded as bare ids so the caller can keep them online."""
    try:
        yield from _scan(known_ids)
    except browser.RefusedHidden:           # nothing was yielded yet: once more, now in a window
        yield from _scan(known_ids)


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
                        body="门户的防护没有放行这次访问，即使是在普通浏览器的窗口里。重新登录一次 PD Portal 就会重新通过它的验证。")
        raise NeedsHuman("PD Portal's firewall did not let the browser in: signing in again renews its pass", kind="login", url=f"{BASE}/home.htm")
    notify.add_todo("config", "PD Portal 拒绝了自动扫描", ref="config:pdportal-blocked",
                    body="门户的防护挡住了这次用的浏览器，这不是登录问题。到“设置 → 系统与数据 → 浏览器兼容”打开 nodriver（PD Portal 的规则已经预置），再扫描一次。")
    raise RuntimeError("blocked by the site's firewall (Cloudflare): automated browsers are refused")


def sign_in(page: Any) -> None:
    """The scan found the portal signed out. It is signed in to the way an application is (auth.ensure_session: the
    university's login that still holds, else the saved login name and password, the phone for the second factor) -
    and the applicant is asked only when that does not get there. Leaves the window on the postings page."""
    from .. import auth
    from ..ats.pdportal import PDPortalDriver

    driver = PDPortalDriver()
    ref = driver.detect(POSTINGS)
    try:
        auth.ensure_session(page, driver, ref)
    except NeedsHuman as e:
        if not e.waits_for:
            e.waits_for = auth.ask_to_sign_in(ref, "PD Portal", e.reason, url=e.url or f"{BASE}/home.htm")
        raise
    page.goto(POSTINGS, wait_until="domcontentloaded")
    page.wait_for_selector("#widgetSearch", state="attached", timeout=20000)


def _signed_out(page: Any) -> bool:
    try:  # the postings page has the search widget only when signed in; otherwise it is a login / SSO page
        page.wait_for_selector("#widgetSearch", state="attached", timeout=10000)
    except Exception:  # noqa: BLE001
        return True
    return "notLoggedIn" in page.url or "Not Logged In" in page.inner_text("body")[:500]


def _own(page: Any, known: set[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """The program's own reading of the page as it is now: every listed posting's id, and the text of the new ones."""
    if page.evaluate("() => !!document.getElementById('widgetSearch')"):
        page.evaluate("() => { const f = document.getElementById('widgetSearch'); f.widget1Keyword.value = ''; setTimeout(() => f.submit(), 50); }")
        page.wait_for_load_state("domcontentloaded")
    page.wait_for_selector("[onclick*=postingId]", timeout=30000)
    listing = page.evaluate(_LIST_JS)
    ids, obj = listing["ids"], listing["obj"]
    if not ids or not obj:
        raise RuntimeError("no row that opens a posting was found on this page (looked for [onclick*=postingId][onclick*=infoForPostings] with buildForm({...}))")
    fresh = [i for i in ids if i not in known]
    details: list[dict[str, Any]] = []
    for k in range(0, len(fresh), 10):
        details += page.evaluate(_DETAIL_JS, [obj, fresh[k : k + 10]])
    return ids, details


def _by_the_agent(page: Any, known: set[str], problem: str, got: dict[str, Any]) -> None:
    """The program could not read the portal by itself: the window goes to the agent (agent/scan.py). What is
    collected lands in ``got``; when the agent does not get there either, the applicant is asked, or the scan fails
    with what the agent found."""
    from .. import sites, tasks
    from ..agent import scan as agent_scan
    from ..models import Todo
    from .. import db

    ref = f"account:{TENANT}"
    with db.session() as s:
        asked = s.query(Todo).filter_by(kind="takeover", ref=ref, status="open").count()
    if asked:           # the applicant was asked to sign in and has not yet: not tried again, their phone not rung again
        raise NeedsHuman("PD Portal is signed out, and the card that asks for the sign-in is still open", kind="login", url=f"{BASE}/home.htm", waits_for=ref)
    if notify.quiet_now() and not tasks.running_by_hand():      # a sign-in here rings the applicant's phone
        raise NeedsHuman("PD Portal is signed out; it is not signed in to during the quiet hours", kind="login", url=f"{BASE}/home.htm")

    def collect(script: str) -> str:
        if script:
            res = page.evaluate(script, sorted(known)) or {}
            ids = [str(i) for i in (res.get("ids") or []) if str(i).strip()]
            details = [{"id": str(d.get("id")), "text": str(d.get("text") or "")[:40000]} for d in (res.get("details") or []) if isinstance(d, dict)]
        else:
            ids, details = _own(page, known)
        if not ids:
            raise ValueError("the script returned no posting ids")
        read = [d for d in details if d["text"] and parse_detail(d["id"], d["text"])["title"]]
        new = [i for i in ids if i not in known]
        if new and not read:
            raise ValueError(f"{len(ids)} postings are listed, {len(new)} of them new, but no new posting's text could be read (a posting's text has lines such as "
                             "'Job Title:', 'Organization:', 'Application Deadline:', 'Application Receipt Procedure:', 'Job Description:')")
        got.update(ids=ids, details=read)
        return f"{len(ids)} postings are listed; {len(new)} are new to the program, and the text of {len(read)} was read. " + (
            "That is all of it: end with done." if len(read) >= len(new) else f"The text of {len(new) - len(read)} new ones is missing: collect again if it can be had, or end with done and say so.")

    out = agent_scan.take_over(page, site=TENANT, name="UBC PD Portal (co-op postings)", url=POSTINGS, problem=problem, collect=collect,
                               hint=f"The program already has the text of {len(known)} postings; a script of yours gets their ids as its one argument, and needs no details for them.")
    if got.get("ids"):
        return
    if out.get("needs_applicant"):
        notify.add_todo("takeover", "PD Portal（CWL + Duo）", ref=ref, body=out["needs_applicant"], payload={"tenant_key": TENANT, "ats": "pdportal", "url": f"{BASE}/home.htm"})
        raise NeedsHuman(out["needs_applicant"], kind="login", url=f"{BASE}/home.htm", waits_for=ref)
    sites.note(TENANT, f"A scan could not be made: {out.get('why') or problem}"[:600])
    raise RuntimeError(f"the portal could not be read, by the program ({problem[:200]}) or by the agent ({out.get('why') or 'no reason given'})")


def _scan(known_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    from ..agent import work

    if known_ids is None:
        from .. import db
        from ..models import Job

        with db.session() as s:
            known_ids = {j.source_id for j in s.query(Job).filter(Job.source == "pdportal", Job.jd_text != "")}
    got: dict[str, Any] = {}
    with browser.open_page(TENANT, url=POSTINGS, operation="scan") as page:
        page.goto(POSTINGS, wait_until="domcontentloaded")
        for _ in range(15):                 # the firewall's own check of the browser passes by itself in a real window: give it the time
            if not refused(page):
                break
            page.wait_for_timeout(1000)
        else:
            firewall(page)
        problem = ""
        if _signed_out(page):
            if work.enabled():
                problem = "The portal is signed out: the postings page shows a sign-in instead of its search form."
            else:
                sign_in(page)
        if not problem:
            try:
                ids, details = _own(page, known_ids)
                got.update(ids=ids, details=details)
            except Exception as e:  # noqa: BLE001 - the page is not what the script was written for: the agent looks at it
                if not work.enabled():
                    raise
                problem = f"The program's collecting script failed on the postings page: {type(e).__name__}: {str(e)[:500]}"
        if problem:
            _by_the_agent(page, known_ids, problem, got)
        notify.close_todos("config", "config:pdportal-blocked")      # the portal let this browser in: a card that said it did not is settled
        browser.save_state(TENANT, page.context)
    for i in got["ids"]:
        if i in known_ids:
            yield {"source": "pdportal", "source_id": i}
    for d in got["details"]:
        if d.get("text"):
            yield parse_detail(d["id"], d["text"])

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
    with browser.open_page(TENANT, url=POSTINGS, operation="scan") as page:
        page.goto(POSTINGS, wait_until="domcontentloaded")
        if "Cloudflare" in page.title() or "you have been blocked" in page.inner_text("body")[:400]:
            # The site's firewall refused this browser. Not a login problem: which browser the portal gets is a setting.
            notify.add_todo("config", "PD Portal 拒绝了自动扫描", ref="config:pdportal-blocked",
                            body="门户的防护挡住了这次扫描用的浏览器，这不是登录问题。到“设置 → 浏览器后端”打开 nodriver（PD Portal 的规则已经预置），再扫描一次。")
            raise RuntimeError("blocked by the site's firewall (Cloudflare): automated browsers are refused")
        try:  # the postings page has the search widget only when signed in; otherwise it is a login / SSO page
            page.wait_for_selector("#widgetSearch", state="attached", timeout=10000)
            signed_in = True
        except Exception:  # noqa: BLE001
            signed_in = False
        if not signed_in or "notLoggedIn" in page.url or "Not Logged In" in page.inner_text("body")[:500]:
            notify.add_todo("takeover", "PD Portal（CWL + Duo）", body="岗位扫描需要 PD Portal 的登录状态。", ref=f"account:{TENANT}",
                            payload={"tenant_key": TENANT, "ats": "pdportal", "url": f"{BASE}/home.htm"})
            raise NeedsHuman("PD Portal session expired", kind="login", url=f"{BASE}/home.htm")
        page.evaluate("() => { const f = document.getElementById('widgetSearch'); f.widget1Keyword.value = ''; setTimeout(() => f.submit(), 50); }")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_selector("[onclick*=postingId]", timeout=30000)
        listing = page.evaluate(_LIST_JS)
        ids, obj = listing["ids"], listing["obj"]
        browser.save_state(TENANT, page.context)
        if known_ids is None:
            from .. import db
            from ..models import Job

            with db.session() as s:
                known_ids = {j.source_id for j in s.query(Job).filter(Job.source == "pdportal", Job.jd_text != "")}
        fresh = [i for i in ids if i not in known_ids]
        for i in ids:
            if i in known_ids:
                yield {"source": "pdportal", "source_id": i}
        for k in range(0, len(fresh), 10):
            for d in page.evaluate(_DETAIL_JS, [obj, fresh[k : k + 10]]):
                if d["text"]:
                    yield parse_detail(d["id"], d["text"])

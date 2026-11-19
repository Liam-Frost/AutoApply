"""The employer's side of the evaluation forms: serves them, keeps what each one saved, and records what was sent.

A form's page posts its whole state to /__/save at every step and to /__/submit when the application is sent; a page
opened again starts from what was saved (/__/load) - as a real site keeps a draft application. A run is judged by what
arrived here, never by what a page says about itself.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FORMS = Path(__file__).with_name("forms")
POSTINGS = {
    "profile_first": {
        "company": "Northwind", "title": "Software Developer Intern, Winter 2027 - Waterloo or Toronto",
        "text": "Northwind builds logistics software used by 40,000 warehouses. As a Software Developer Intern you will join the routing team for four or eight months, "
                "starting in January 2027, in Waterloo or Toronto. You will build backend services in Go and Python on PostgreSQL, write tests, and ship to production with "
                "the team's on-call engineers. Requirements: enrolled in a bachelor's programme in computer engineering, computer science or similar; one earlier internship "
                "or substantial project work; fluent in one backend language. To apply, upload a résumé; no cover letter is needed.",
    },
    "embedded": {
        "company": "Fabrikam", "title": "Backend Developer Co-op", "frame": True,
        "text": "Fabrikam makes scheduling software for hospitals. The platform team is hiring a Backend Developer Co-op for January to April 2027 in Toronto (hybrid). "
                "You will work on the appointment service: a Go service on PostgreSQL that 300 clinics depend on every morning. You will fix real bugs in your first week, "
                "own one feature end to end, and be on the release rotation with a mentor. We look for: solid Go or Python, SQL you are not afraid of, and evidence that "
                "you have shipped something other people used. A cover letter is optional.",
    },
    "account": {
        "company": "Tailspin Toys", "title": "Platform Engineering Intern",
        "text": "Tailspin Toys runs one of the largest online toy stores in Canada. The platform group is hiring a Platform Engineering Intern for a four-month term from "
                "January 2027, on site in Toronto, Ontario. You will work on the order pipeline (Python services, PostgreSQL, Docker on Kubernetes), automate one manual "
                "release step, and write the runbook for it. Requirements: enrolled in an engineering or computer science degree, comfortable in Python, able to work on "
                "site for the full term. Applications are made through our careers portal, where you create an account first.",
    },
}


# --- a co-op portal: postings behind a sign-in, listed on two pages, each opened by a POST with a token ------------------
# Shaped like the portals universities run (Orbis), and not identical to the one the agent's notes were written from:
# the rows carry their token under another name, so the script in the notes does not work as it stands.
PORTAL_POSTINGS = [
    ("151001", "Backend Developer Co-op", "Northwind", "December 1, 2026 11:59 PM", "Online via system", "", "Cover Letter, Resume", "2027 - Winter", "4 months", "Vancouver, BC"),
    ("151002", "Data Engineer Co-op", "Fabrikam", "December 3, 2026 09:00 AM", "Online via system", "", "Resume, Transcript", "2027 - Winter", "8 months", "Toronto, ON"),
    ("151003", "Firmware Developer Co-op", "Contoso Devices", "November 30, 2026 11:59 PM", "Employer Website", "https://careers.contoso-devices.example/jobs/771", "Resume", "2027 - Winter", "4 or 8 months", "Burnaby, BC"),
    ("151004", "QA Automation Co-op", "Tailspin Toys", "December 10, 2026 05:00 PM", "Online via system", "", "Resume", "2027 - Summer", "4 months", "Remote"),
    ("151005", "Site Reliability Co-op", "Adatum", "December 12, 2026 11:59 PM", "Online via system", "", "Cover Letter, Resume, Transcript", "2027 - Winter", "8 months", "Calgary, AB"),
    ("151006", "Machine Learning Co-op", "Woodgrove Bank", "December 15, 2026 11:59 PM", "Employer Website", "https://woodgrove.example/careers/ml-coop", "Resume", "2027 - Summer", "4 months", "Toronto, ON"),
    ("151007", "Full-Stack Developer Co-op", "Litware", "December 18, 2026 11:59 PM", "Online via system", "", "Resume", "2027 - Winter", "4 months", "Victoria, BC"),
]
PORTAL_USER, PORTAL_PAGE = "achen01", 4
PORTAL_CSS = "<meta charset='utf-8'><style>body{font:14px/1.5 system-ui;max-width:900px;margin:24px auto}td,th{padding:4px 10px;border-bottom:1px solid #ddd;text-align:left}.chip{background:#eef;padding:2px 8px;border-radius:10px}</style>"


def portal_rows(page: int) -> str:
    rows = PORTAL_POSTINGS[(page - 1) * PORTAL_PAGE: page * PORTAL_PAGE]
    return "".join(
        f"<tr><td>{pid}</td><td><a href='javascript:void(0)' class='np-view-btn' onclick=\"orbisApp.buildForm({{'action':'_-_-Tk{pid[-2:]}9','rand':'4821','postingId':'{pid}'}}, '/portal/posting', '').submit()\">{title}</a></td>"
        f"<td>{org}</td><td>{deadline}</td></tr>" for pid, title, org, deadline, *_ in rows)


def portal_list(keyword: str | None) -> str:
    head = (f"<!doctype html>{PORTAL_CSS}<title>Co-op postings - Contoso University Co-op Portal</title><p>Signed in as {PORTAL_USER} · <a href='/portal/logout'>Log out</a></p><h1>Co-op postings</h1>"
            "<form id='widgetSearch' method='get' action='/portal/postings'><input type='hidden' name='search' value='1'>"
            "<input name='widget1Keyword' value='Keyword' aria-label='Keyword' style='color:#999'> <button type='submit'>Search</button></form>")
    if keyword is None:
        return head + "<p>Search the postings, or leave the keyword empty to see all of them.</p>"
    if keyword.strip():
        return head + f"<p><span class='chip'>Keyword: {keyword} <a href='/portal/postings?search=1&widget1Keyword='>Remove</a></span></p><p>0 results.</p>"
    pages = -(-len(PORTAL_POSTINGS) // PORTAL_PAGE)
    return (head + f"<p>{len(PORTAL_POSTINGS)} postings</p><table><thead><tr><th>ID</th><th>Title</th><th>Organization</th><th>Deadline</th></tr></thead><tbody id='postingsBody'>{portal_rows(1)}</tbody></table>"
            "<p>Page: " + " ".join(f"<a href='javascript:void(0)' onclick=\"loadPostingTable('', 'ID', 'Reverse', '{n}', 'advanced', '', null)\">{n}</a>" for n in range(1, pages + 1)) + "</p>"
            "<script>window.orbisApp = {buildForm(obj, action, target) { const f = document.createElement('form'); f.method = 'post'; f.action = action; if (target) f.target = target;"
            " for (const [k, v] of Object.entries(obj)) { const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i); } document.body.appendChild(f); return f; }};"
            " window.loadPostingTable = async (a, b, c, page) => { const r = await fetch('/portal/table?page=' + page); document.getElementById('postingsBody').innerHTML = await r.text(); };</script>")


def portal_posting(pid: str) -> str:
    row = next((r for r in PORTAL_POSTINGS if r[0] == pid), None)
    if row is None:
        return ""
    _, title, org, deadline, how, url, docs, term, length, place = row
    return (f"<!doctype html>{PORTAL_CSS}<title>{title} - Contoso University Co-op Portal</title><nav><a href='/portal/postings'>Back to postings</a></nav><main><h1>{title}</h1>"
            f"<h2>JOB POSTING INFORMATION</h2><p>Job Title: {title}</p><p>Organization: {org}</p><p>Co-op Work Term: {term}</p><p>Length of Work Term: {length}</p><p>Job Location: {place}</p>"
            f"<p>Job Description: {org} is hiring a {title} for the {term.split(' - ')[-1].lower()} term. You will work with a small team, ship to production in your first month and present your work at the end of the term.</p>"
            f"<p>Job Requirements: enrolled in a co-op programme in engineering or computer science; one earlier work term or substantial project work.</p>"
            f"<h2>APPLICATION INFORMATION</h2><p>Application Deadline: {deadline}</p><p>Application Receipt Procedure: {how}</p>" + (f"<p>If by Website, go to: {url}</p>" if url else "")
            + f"<p>Application Documents Required: {docs}</p><h2>ORGANIZATION INFORMATION</h2><p>{org}</p></main>")


class Site:
    def __init__(self, port: int = 0) -> None:
        self.saved: dict[str, Any] = {}        # form -> the state it last saved
        self.sent: dict[str, list[Any]] = {}   # form -> every state that was sent as an application
        self.portal_password = ""              # the co-op portal's sign-in: set by whoever runs the evaluation, never printed
        self.portal: dict[str, Any] = {"signed_in": 0, "refused": 0, "searches": [], "opened": []}      # what the portal saw
        self.lock = threading.Lock()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, code: int, body: bytes, kind: str = "text/html; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                u = urlparse(self.path)
                name = u.path.rsplit("/", 1)[-1]
                if u.path.startswith("/jobs/") and name in POSTINGS and POSTINGS[name].get("frame"):
                    # the employer's own page, with the recruiting system's form in a frame from another origin
                    p, port = POSTINGS[name], self.server.server_address[1]
                    return self._send(200, (f"<!doctype html><meta charset='utf-8'><title>{p['title']} | {p['company']}</title><main style='max-width:760px;margin:30px auto;"
                                            f"font:15px/1.6 system-ui'><h1>{p['title']}</h1><p>{p['text']}</p><h2>Apply</h2>"
                                            f"<iframe title='Application form' src='http://localhost:{port}/forms/{name}' style='width:100%;height:1500px;border:0'></iframe></main>").encode())
                if u.path.startswith("/jobs/") and name in POSTINGS:
                    p = POSTINGS[name]
                    return self._send(200, (f"<!doctype html><meta charset='utf-8'><title>{p['title']} - {p['company']} Careers</title><main style='max-width:720px;margin:40px auto;"
                                            f"font:15px/1.6 system-ui'><h1>{p['title']}</h1><p>{p['text']}</p><p><a href='/forms/{name}' aria-label='Apply'><button>Apply</button></a></p></main>").encode())
                if u.path.startswith("/forms/") and (FORMS / f"{name}.html").exists():
                    return self._send(200, (FORMS / f"{name}.html").read_bytes())
                if u.path.startswith("/portal/"):
                    if u.path == "/portal/logout":
                        self.send_response(302)
                        self.send_header("Location", "/portal/login")
                        self.send_header("Set-Cookie", "psession=; Path=/; Max-Age=0")
                        self.end_headers()
                        return None
                    if "psession=in" not in (self.headers.get("Cookie") or "") or u.path == "/portal/login":
                        if u.path != "/portal/login":
                            self.send_response(302)
                            self.send_header("Location", "/portal/login")
                            self.end_headers()
                            return None
                        return self._send(200, (f"<!doctype html>{PORTAL_CSS}<title>Contoso University Login</title><h1>Contoso University Login</h1><p>Not Logged In. Sign in with your campus login to "
                                                "open the co-op portal.</p><form method='post' action='/portal/login'><p><label for='user'>Login name</label> <input id='user' name='j_username'></p>"
                                                "<p><label for='pw'>Password</label> <input id='pw' name='j_password' type='password'></p><button type='submit'>Log in</button></form>").encode())
                    q = parse_qs(u.query, keep_blank_values=True)
                    if u.path == "/portal/postings":
                        keyword = q.get("widget1Keyword", [""])[0] if q.get("search") else None
                        if keyword is not None:
                            with site.lock:
                                site.portal["searches"].append(keyword)
                        return self._send(200, portal_list(keyword).encode())
                    if u.path == "/portal/table":
                        return self._send(200, portal_rows(int(q.get("page", ["1"])[0] or 1)).encode())
                    return self._send(404, b"not found")
                if u.path == "/__/state":      # for whoever judges a run from another process
                    form = parse_qs(u.query).get("form", [""])[0]
                    with site.lock:
                        return self._send(200, json.dumps({"saved": site.saved.get(form) or {}, "sent": site.sent.get(form) or []}).encode(), "application/json")
                if u.path == "/__/load":
                    form = parse_qs(u.query).get("form", [""])[0]
                    with site.lock:
                        return self._send(200, json.dumps(site.saved.get(form) or {}).encode(), "application/json")
                self._send(404, b"not found")

            def do_POST(self) -> None:  # noqa: N802
                u = urlparse(self.path)
                form = parse_qs(u.query).get("form", [""])[0]
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if u.path.startswith("/portal/"):
                    f = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
                    if u.path == "/portal/login":
                        ok = bool(site.portal_password) and f.get("j_username") == PORTAL_USER and f.get("j_password") == site.portal_password
                        with site.lock:
                            site.portal["signed_in" if ok else "refused"] += 1
                        self.send_response(302)
                        self.send_header("Location", "/portal/postings" if ok else "/portal/login")
                        if ok:
                            self.send_header("Set-Cookie", "psession=in; Path=/; Max-Age=7200")
                        self.end_headers()
                        return None
                    signed_in = "psession=in" in (self.headers.get("Cookie") or "")
                    page = portal_posting(f.get("postingId", "")) if signed_in and f.get("action", "").startswith("_-_-Tk") else ""
                    if page:
                        with site.lock:
                            site.portal["opened"].append(f["postingId"])
                    return self._send(200 if page else 403, (page or "<title>Not Logged In</title><p>Not Logged In, or the posting cannot be opened this way.</p>").encode())
                try:
                    state = json.loads(body or b"{}")
                except ValueError:
                    return self._send(400, b"{}", "application/json")
                with site.lock:
                    site.saved[form] = state
                    if u.path == "/__/submit":
                        site.sent.setdefault(form, []).append(state)
                self._send(200, b"{}", "application/json")

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


if __name__ == "__main__":      # the site by itself, so that it outlives the runs that work on it:  python eval/server.py 8765
    import sys
    import time

    s = Site(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print(s.base, flush=True)
    while True:
        time.sleep(3600)

"""The employer's side of the evaluation forms: serves them, keeps what each one saved, and records what was sent.

A form's page posts its whole state to /__/save at every step and to /__/submit when the application is sent; a page
opened again starts from what was saved (/__/load) - as a real site keeps a draft application. A run is judged by what
arrived here, never by what a page says about itself.
"""
from __future__ import annotations

import json
from html import escape
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FORMS = Path(__file__).with_name("forms")
PAGES = {p.stem: p for p in FORMS.glob("*.html")}
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
    "widgets": {
        "company": "Adatum", "title": "Software Developer Co-op (Toronto)",
        "text": "Adatum builds payment terminals and the software behind them. The merchant platform team in Toronto is hiring a Software Developer Co-op for an eight-month "
                "term, January to August 2027. You will work in TypeScript and Go on the services that settle two million card payments a day, pair with a senior developer, "
                "and take one improvement from idea to production. We look for students in computer engineering or computer science with one earlier work term or serious "
                "project work. The role is based in our Toronto office; we also have offices in Calgary and Montréal. Apply with a résumé.",
    },
    "returning": {
        "company": "Litware", "title": "Full-Stack Developer Intern (Winter 2027)",
        "text": "Litware makes inventory software for independent bookshops. We are hiring a Full-Stack Developer Intern for January to April 2027, in our Toronto office "
                "or remote within Canada. You will work across a React front end and a Python API on PostgreSQL, and ship something bookshops use in your first month. "
                "Requirements: enrolled in a bachelor's programme in computing; TypeScript and Python; one earlier internship or substantial project. Applications are made "
                "in Litware Careers, signed in with your account.",
    },
    "closed": {
        "company": "Woodgrove Bank", "title": "Platform Engineering Intern (Winter 2027)", "closed": True,
        "text": "Woodgrove Bank's cloud platform group is hiring a Platform Engineering Intern for January to April 2027 in Toronto. You will work on the internal "
                "deployment tooling (Go, Kubernetes, Terraform) with a team of eight. Requirements: enrolled in an engineering or computer science degree; comfortable "
                "with Linux and one systems language.",
    },
}


# --- a co-op portal: postings behind a sign-in, listed on two pages, each opened by a POST with a token ------------------
# Shaped like the portals universities run (Orbis), and not identical to the one the agent's notes were written from:
# the rows carry their token under another name, so the script in the notes does not work as it stands.
PORTAL_POSTINGS = [
    ("151001", "Backend Developer Co-op", "Northwind", "December 1, 2026 11:59 PM", "Online via system", "", "Cover Letter, Resume", "2027 - Winter", "4 months", "Toronto, ON"),
    ("151002", "Data Engineer Co-op", "Fabrikam", "December 3, 2026 09:00 AM", "Online via system", "", "Resume, Transcript", "2027 - Winter", "8 months", "Toronto, ON"),
    ("151003", "Firmware Developer Co-op", "Contoso Devices", "November 30, 2026 11:59 PM", "Employer Website", "https://careers.contoso-devices.example/jobs/771", "Resume", "2027 - Winter", "4 or 8 months", "Burnaby, BC"),
    ("151004", "QA Automation Co-op", "Tailspin Toys", "December 10, 2026 05:00 PM", "Online via system", "", "Resume", "2027 - Summer", "4 months", "Remote"),
    ("151005", "Site Reliability Co-op", "Adatum", "December 12, 2026 11:59 PM", "Online via system", "", "Cover Letter, Resume, Transcript", "2027 - Winter", "8 months", "Calgary, AB"),
    ("151006", "Machine Learning Co-op", "Woodgrove Bank", "December 15, 2026 11:59 PM", "Employer Website", "https://woodgrove.example/careers/ml-coop", "Resume", "2027 - Summer", "4 months", "Toronto, ON"),
    ("151007", "Full-Stack Developer Co-op", "Litware", "December 18, 2026 11:59 PM", "Online via system", "", "Resume", "2027 - Winter", "4 months", "Victoria, BC"),
]
PORTAL_USER, PORTAL_PAGE = "achen01", 4
PORTAL_CSS = ("<meta charset='utf-8'><style>body{font:14px/1.5 system-ui;max-width:900px;margin:24px auto}td,th{padding:4px 10px;border-bottom:1px solid #ddd;text-align:left}"
              ".chip{background:#eef;padding:2px 8px;border-radius:10px}.err{color:#b00}nav a{margin-right:14px}label{display:block;margin:10px 0 2px}</style>")
PORTAL_NAV = ("<nav><a href='/portal/postings'>Co-op postings</a><a href='/portal/documents'>My Documents</a><a href='/portal/applications'>Applications</a><a href='/portal/logout'>Log out</a>"
              "<small style='float:right;color:#888'>Powered by Orbis</small></nav>")
DOC_TYPES = {"Cover Letter": "Cover letters", "Resume": "Resumes", "Transcript": "Transcripts"}      # what a posting asks for -> the type a document is uploaded as


def portal_rows(page: int) -> str:
    rows = PORTAL_POSTINGS[(page - 1) * PORTAL_PAGE: page * PORTAL_PAGE]
    return "".join(
        f"<tr><td>{pid}</td><td><a href='javascript:void(0)' class='np-view-btn' onclick=\"orbisApp.buildForm({{'action':'_-_-Tk{pid[-2:]}9','rand':'4821','postingId':'{pid}'}}, '/portal/posting', '').submit()\">{title}</a></td>"
        f"<td>{org}</td><td>{deadline}</td></tr>" for pid, title, org, deadline, *_ in rows)


def portal_list(keyword: str | None) -> str:
    head = (f"<!doctype html>{PORTAL_CSS}<title>Co-op postings - Contoso University Co-op Portal</title><p>Signed in as {PORTAL_USER}</p>{PORTAL_NAV}<h1>Co-op postings</h1>"
            "<form id='widgetSearch' method='get' action='/portal/postings'><input type='hidden' name='search' value='1'>"
            "<input name='widget1Keyword' value='Keyword' aria-label='Keyword' style='color:#999'> <button type='submit'>Search</button></form>")
    if keyword is None:
        return head + "<p>Search the postings, or leave the keyword empty to see all of them.</p>"
    if keyword.strip():
        return head + f"<p><span class='chip'>Keyword: {escape(keyword)} <a href='/portal/postings?search=1&widget1Keyword='>Remove</a></span></p><p>0 results.</p>"
    pages = -(-len(PORTAL_POSTINGS) // PORTAL_PAGE)
    return (head + f"<p>{len(PORTAL_POSTINGS)} postings</p><table><thead><tr><th>ID</th><th>Title</th><th>Organization</th><th>Deadline</th></tr></thead><tbody id='postingsBody'>{portal_rows(1)}</tbody></table>"
            "<p>Page: " + " ".join(f"<a href='javascript:void(0)' onclick=\"loadPostingTable('', 'ID', 'Reverse', '{n}', 'advanced', '', null)\">{n}</a>" for n in range(1, pages + 1)) + "</p>"
            "<script>window.orbisApp = {buildForm(obj, action, target) { const f = document.createElement('form'); f.method = 'post'; f.action = action; if (target) f.target = target;"
            " for (const [k, v] of Object.entries(obj)) { const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i); } document.body.appendChild(f); return f; }};"
            " window.loadPostingTable = async (a, b, c, page) => { const r = await fetch('/portal/table?page=' + page); document.getElementById('postingsBody').innerHTML = await r.text(); };</script>")


def portal_posting(pid: str, applied: bool = False) -> str:
    row = next((r for r in PORTAL_POSTINGS if r[0] == pid), None)
    if row is None:
        return ""
    _, title, org, deadline, how, url, docs, term, length, place = row
    act = ("<p><b>You have applied to this posting.</b></p>" if applied else
           f"<form method='get' action='/portal/apply'><input type='hidden' name='postingId' value='{pid}'><button type='submit'>APPLY</button></form>" if how == "Online via system" else
           "<p><button type='button' disabled>Express Intention to Apply</button></p>")
    return (f"<!doctype html>{PORTAL_CSS}<title>{title} - Contoso University Co-op Portal</title>{PORTAL_NAV}{act}<main><h1>{title}</h1>"
            f"<h2>JOB POSTING INFORMATION</h2><p>Job ID: {pid}</p><p>Job Title: {title}</p><p>Organization: {org}</p><p>Co-op Work Term: {term}</p><p>Length of Work Term: {length}</p><p>Job Location: {place}</p>"
            f"<p>Job Description: {org} is hiring a {title} for the {term.split(' - ')[-1].lower()} term. You will work with a small team, ship to production in your first month and present your work at the end of the term.</p>"
            f"<p>Job Requirements: enrolled in a co-op programme in engineering or computer science; one earlier work term or substantial project work.</p>"
            f"<h2>APPLICATION INFORMATION</h2><p>Application Deadline: {deadline}</p><p>Application Receipt Procedure: {how}</p>" + (f"<p>If by Website, go to: {url}</p>" if url else "")
            + f"<p>Application Documents Required: {docs}</p><h2>ORGANIZATION INFORMATION</h2><p>{org}</p></main>")


def portal_documents(docs: list[dict[str, Any]]) -> str:
    rows = "".join(f"<tr><td>{escape(d['name'])}</td><td>{escape(d['type'])}</td><td>{escape(d['file'])}</td></tr>" for d in docs) or "<tr><td colspan='3'>You have not uploaded any documents.</td></tr>"
    return (f"<!doctype html>{PORTAL_CSS}<title>My Documents - Contoso University Co-op Portal</title>{PORTAL_NAV}<h1>My Documents</h1>"
            f"<table><thead><tr><th>Name</th><th>Type</th><th>File</th></tr></thead><tbody>{rows}</tbody></table><p><a href='/portal/upload'>Upload Document</a></p>")


def portal_upload() -> str:
    return (f"<!doctype html>{PORTAL_CSS}<title>Upload a Document - Contoso University Co-op Portal</title>{PORTAL_NAV}<h1>Upload a Document</h1>"
            "<label for='docName'>Name</label><input id='docName'><label for='docType'>Type</label><select id='docType'><option value=''></option>"
            + "".join(f"<option>{t}</option>" for t in (*DOC_TYPES.values(), "Other"))
            + "</select><label for='fileUpload'>File (PDF or Word)</label><input type='file' id='fileUpload'><p class='err' id='err' role='alert'></p><p><a href='javascript:void(0)' id='up'>Upload Document</a></p>"
            "<script>document.getElementById('up').onclick = async () => { const f = document.getElementById('fileUpload').files[0], name = document.getElementById('docName').value.trim(), type = document.getElementById('docType').value;"
            " if (!f || !name || !type) { document.getElementById('err').textContent = 'A name, a type and a file are required.'; return; }"
            " await fetch('/portal/upload', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, type, file: f.name, size: f.size})}); location.href = '/portal/documents'; };</script>")


def portal_apply(pid: str, docs: list[dict[str, Any]], err: str = "") -> str:
    row = next((r for r in PORTAL_POSTINGS if r[0] == pid and r[4] == "Online via system"), None)
    if row is None:
        return ""
    need = [x.strip() for x in row[6].split(",")]
    picks = ""
    for n in need:
        mine = [(i, d) for i, d in enumerate(docs) if d["type"] == DOC_TYPES[n]]
        picks += (f"<label for='doc_{n.replace(' ', '_')}'>{n} *</label>"
                  + (f"<select id='doc_{n.replace(' ', '_')}' name='doc_{n.replace(' ', '_')}'><option value=''></option>" + "".join(f"<option value='{i}'>{escape(d['name'])}</option>" for i, d in mine) + "</select>"
                     if mine else f"<p>You have no document of the type {DOC_TYPES[n]}. Upload one under <a href='/portal/documents'>My Documents</a> first.</p>"))
    return (f"<!doctype html>{PORTAL_CSS}<title>Apply - {row[1]} - Contoso University Co-op Portal</title>{PORTAL_NAV}<h1>Apply: {row[1]} ({row[2]})</h1><p>Job ID: {pid}. This posting requires: {row[6]}.</p>"
            f"<p class='err' role='alert'>{err}</p><form method='post' action='/portal/apply'><input type='hidden' name='postingId' value='{pid}'>"
            "<p><label style='display:inline'><input type='radio' name='pkg' value='existing' disabled> Use an existing application package (you have none)</label></p>"
            "<p><label style='display:inline'><input type='radio' name='pkg' value='custom' id='custom'> Create a customized application package</label></p>"
            f"<div id='package' style='display:none'><label for='packageName'>Package Name *</label><input id='packageName' name='packageName'>{picks}<p><button type='submit'>Submit Application</button></p></div></form>"
            "<script>document.getElementById('custom').onchange = () => { document.getElementById('package').style.display = 'block'; };</script>")


class Site:
    def __init__(self, port: int = 0) -> None:
        self.saved: dict[str, Any] = {}        # form -> the state it last saved
        self.sent: dict[str, list[Any]] = {}   # form -> every state that was sent as an application
        self.portal_password = ""              # the co-op portal's sign-in: set by whoever runs the evaluation, never printed
        self.portal: dict[str, Any] = {"signed_in": 0, "refused": 0, "searches": [], "opened": [], "documents": [], "applications": [], "apply_refused": 0}      # what the portal saw
        self.logins: dict[str, dict[str, Any]] = {}      # form -> {"email", "password", "signed_in", "refused"}: an account the applicant already has on that site
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

            def _to(self, where: str, cookie: str = "") -> None:
                self.send_response(302)
                self.send_header("Location", where)
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                u = urlparse(self.path)
                name = u.path.rsplit("/", 1)[-1]
                if u.path.startswith("/jobs/") and name in POSTINGS and POSTINGS[name].get("closed"):
                    # a posting that has been taken down: its text is still there, the way in is not; the employer's other openings are listed under it
                    p = POSTINGS[name]
                    return self._send(200, (f"<!doctype html><meta charset='utf-8'><title>{p['title']} - {p['company']} Careers</title><main style='max-width:720px;margin:40px auto;"
                                            f"font:15px/1.6 system-ui'><h1>{p['title']}</h1><p style='background:#fde8e8;padding:10px 14px;border-radius:6px'><b>This job is no longer accepting applications.</b> "
                                            f"It was filled on November 12, 2026.</p><p>{p['text']}</p><h2>Other openings at {p['company']}</h2><ul>"
                                            "<li>Platform Engineering Intern (Summer 2027) - <a href='/forms/embedded'>Apply</a></li><li>Data Analyst Intern (Winter 2027) - <a href='/forms/embedded'>Apply</a></li></ul></main>").encode())
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
                if u.path.startswith("/forms/") and name in PAGES:      # (only the forms that are there: a name from an address is never made into a path)
                    return self._send(200, PAGES[name].read_bytes())
                if u.path.startswith("/portal/"):
                    if u.path == "/portal/logout":
                        return self._to("/portal/login", "psession=; Path=/; Max-Age=0")
                    if "psession=in" not in (self.headers.get("Cookie") or "") or u.path == "/portal/login":
                        if u.path != "/portal/login":
                            return self._to("/portal/login")
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
                    with site.lock:
                        docs, apps = list(site.portal["documents"]), list(site.portal["applications"])
                    if u.path == "/portal/documents":
                        return self._send(200, portal_documents(docs).encode())
                    if u.path == "/portal/upload":
                        return self._send(200, portal_upload().encode())
                    if u.path == "/portal/applications":
                        rows = "".join(f"<tr><td>{a['id']}</td><td>{a['title']}</td><td>{a['org']}</td><td>Application Submitted</td><td>{escape(a['package'])}</td></tr>" for a in apps) or "<tr><td colspan='5'>No applications.</td></tr>"
                        return self._send(200, (f"<!doctype html>{PORTAL_CSS}<title>Applications - Contoso University Co-op Portal</title>{PORTAL_NAV}<h1>Applications</h1>"
                                                f"<table><thead><tr><th>Job ID</th><th>Title</th><th>Organization</th><th>Status</th><th>Package</th></tr></thead><tbody>{rows}</tbody></table>").encode())
                    if u.path == "/portal/apply":
                        pid = q.get("postingId", [""])[0]
                        if any(a["id"] == pid for a in apps):
                            return self._send(200, portal_posting(pid, applied=True).encode())
                        page = portal_apply(pid, docs)
                        return self._send(200 if page else 404, (page or "not found").encode())
                    return self._send(404, b"not found")
                if u.path == "/__/state":      # for whoever judges a run from another process
                    form = parse_qs(u.query).get("form", [""])[0]
                    with site.lock:
                        return self._send(200, json.dumps({"saved": site.saved.get(form) or {}, "sent": site.sent.get(form) or [], "everything_sent": {k: len(v) for k, v in site.sent.items()}}).encode(), "application/json")
                if u.path == "/__/load":
                    form = parse_qs(u.query).get("form", [""])[0]
                    with site.lock:
                        return self._send(200, json.dumps(site.saved.get(form) or {}).encode(), "application/json")
                self._send(404, b"not found")

            def do_POST(self) -> None:  # noqa: N802
                u = urlparse(self.path)
                form = parse_qs(u.query).get("form", [""])[0]
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if u.path == "/portal/upload":      # (the page sends what it is uploading as JSON: its name, its type, the file's name)
                    if "psession=in" not in (self.headers.get("Cookie") or ""):
                        return self._send(403, b"{}", "application/json")
                    try:
                        d = json.loads(body or b"{}")
                    except ValueError:
                        return self._send(400, b"{}", "application/json")
                    with site.lock:
                        site.portal["documents"].append({"name": str(d.get("name") or "")[:80], "type": str(d.get("type") or "")[:40], "file": str(d.get("file") or "")[:120], "size": int(d.get("size") or 0)})
                    return self._send(200, b"{}", "application/json")
                if u.path.startswith("/portal/"):
                    f = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
                    if u.path == "/portal/login":
                        ok = bool(site.portal_password) and f.get("j_username") == PORTAL_USER and f.get("j_password") == site.portal_password
                        with site.lock:
                            site.portal["signed_in" if ok else "refused"] += 1
                        return self._to("/portal/postings" if ok else "/portal/login", "psession=in; Path=/; Max-Age=7200" if ok else "")
                    signed_in = "psession=in" in (self.headers.get("Cookie") or "")
                    if u.path == "/portal/apply" and signed_in:
                        pid = f.get("postingId", "")
                        row = next((r for r in PORTAL_POSTINGS if r[0] == pid and r[4] == "Online via system"), None)
                        with site.lock:
                            docs = list(site.portal["documents"])
                        if row is None:
                            return self._send(404, b"not found")
                        chosen, miss = {}, []
                        for n in [x.strip() for x in row[6].split(",")]:
                            i = f.get("doc_" + n.replace(" ", "_"), "")
                            if i.isdigit() and int(i) < len(docs) and docs[int(i)]["type"] == DOC_TYPES[n]:
                                chosen[n] = docs[int(i)]
                            else:
                                miss.append(n)
                        if f.get("pkg") != "custom" or not f.get("packageName", "").strip() or miss:
                            with site.lock:
                                site.portal["apply_refused"] += 1
                            why = "Choose 'Create a customized application package'." if f.get("pkg") != "custom" else "Give the package a name." if not f.get("packageName", "").strip() else f"Choose a document for: {', '.join(miss)}."
                            return self._send(200, portal_apply(pid, docs, why).encode())
                        with site.lock:
                            site.portal["applications"].append({"id": pid, "title": row[1], "org": row[2], "package": f["packageName"].strip()[:80], "documents": chosen})
                        return self._send(200, (f"<!doctype html>{PORTAL_CSS}<title>Application submitted - Contoso University Co-op Portal</title>{PORTAL_NAV}"
                                                f"<p>Your online application has been submitted for {row[1]} (Job ID: {pid}).</p>").encode())
                    with site.lock:
                        applied = any(a["id"] == f.get("postingId") for a in site.portal["applications"])
                    page = portal_posting(f.get("postingId", ""), applied) if signed_in and f.get("action", "").startswith("_-_-Tk") else ""
                    if page:
                        with site.lock:
                            site.portal["opened"].append(f["postingId"])
                    return self._send(200 if page else 403, (page or "<title>Not Logged In</title><p>Not Logged In, or the posting cannot be opened this way.</p>").encode())
                try:
                    state = json.loads(body or b"{}")
                except ValueError:
                    return self._send(400, b"{}", "application/json")
                if u.path == "/__/login":      # a site the applicant has an account on: the site checks the password, the page never holds it
                    with site.lock:
                        acct = site.logins.setdefault(form, {"email": "", "password": "", "signed_in": 0, "refused": 0})
                        ok = bool(acct["password"]) and str(state.get("email") or "").strip().lower() == acct["email"].lower() and state.get("pw") == acct["password"]
                        acct["signed_in" if ok else "refused"] += 1
                    return self._send(200, json.dumps({"ok": ok}).encode(), "application/json")
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

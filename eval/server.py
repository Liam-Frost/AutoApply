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
}


class Site:
    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}        # form -> the state it last saved
        self.sent: dict[str, list[Any]] = {}   # form -> every state that was sent as an application
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
                if u.path == "/__/load":
                    form = parse_qs(u.query).get("form", [""])[0]
                    with site.lock:
                        return self._send(200, json.dumps(site.saved.get(form) or {}).encode(), "application/json")
                self._send(404, b"not found")

            def do_POST(self) -> None:  # noqa: N802
                u = urlparse(self.path)
                form = parse_qs(u.query).get("form", [""])[0]
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    state = json.loads(body or b"{}")
                except ValueError:
                    return self._send(400, b"{}", "application/json")
                with site.lock:
                    site.saved[form] = state
                    if u.path == "/__/submit":
                        site.sent.setdefault(form, []).append(state)
                self._send(200, b"{}", "application/json")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

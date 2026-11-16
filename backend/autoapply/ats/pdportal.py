"""UBC PD Portal (Orbis) driver for "Online via system" postings.

Login is CWL + Duo: this driver never signs in; an expired session raises
NeedsHuman and the user signs in through takeover (tenant key ``pdportal:ubc``).

Flow (from the pd-portal playbook, hand-driven 2026-09..11):
  posting page -> APPLY -> "create a customized application package" ->
  one <select> per document type (30 Summary Sheet, 11 Cover letters, 12 Resumes,
  13 Transcripts, 17 Other) listing documents already in My Documents ->
  Package Name -> Submit Application ->
  "Your online application has been submitted for ... (Job ID: ...)".
A new cover letter is first uploaded to My Documents (type 11) and then selected.

Not yet exercised by this code (needs a live CWL session); run the first
applications with the manual submit policy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from . import widgets as w
from .base import DriverError, FormSchema, JobRef, NeedsHuman, PasswordPolicy, Question

BASE = "https://pdportal.apsc.ubc.ca"
POSTINGS = f"{BASE}/myAccount/co-op/postings.htm"
DOCS = f"{BASE}/myAccount/co-op/myDocuments.htm"
SELECTS = {"30": "Co-op Student Summary Sheet", "11": "Cover Letter", "12": "Resume", "13": "Transcript", "17": "Other document"}

_OPEN_JS = r"""(id) => {
  const el = document.querySelector('[onclick*=postingId][onclick*=infoForPostings]');
  if (!el) return false;
  const m = el.getAttribute('onclick').match(/buildForm\((\{[\s\S]*?\})\s*,/);
  const obj = (0, eval)('(' + m[1] + ')');
  setTimeout(() => window.orbisAppSr.buildForm({...obj, postingId: id}, '', '_self').submit(), 50);
  return true;
}"""


class PDPortalDriver:
    ats = "pdportal"
    requires_login = True
    sso = True  # CWL + Duo: never automated, always handed to the user
    password_policy = PasswordPolicy()

    def detect(self, url: str) -> JobRef | None:
        u = urlparse(url)
        if u.netloc.lower() != "pdportal.apsc.ubc.ca":
            return None
        m = re.search(r"posting=(\d+)", u.fragment + "&" + u.query)
        return JobRef(self.ats, "ubc", m.group(1) if m else "", url, u.netloc.lower())

    def login_url(self, ref: JobRef) -> str:
        return f"{BASE}/home.htm"

    @staticmethod
    def signed_in_url(url: str) -> bool:
        """Cloudflare refuses the portal's sign-in page to automated browsers, so sign-in happens
        in a plain browser window; this tells the takeover when it has succeeded."""
        return "pdportal.apsc.ubc.ca/myAccount" in url

    def is_logged_in(self, page: Page, ref: JobRef, navigate: bool = True) -> bool:
        if navigate:
            page.goto(POSTINGS, wait_until="domcontentloaded")
        if "pdportal.apsc.ubc.ca/myAccount" not in page.url:
            return False
        return "Not Logged In" not in page.inner_text("body")[:600]

    def login(self, page: Page, ref: JobRef, email: str, password: str) -> None:
        raise NeedsHuman("PD Portal uses CWL + Duo; please sign in yourself.", kind="login", url=self.login_url(ref))

    def register(self, page: Page, ref: JobRef, email: str, password: str) -> str:
        raise NeedsHuman("PD Portal uses CWL + Duo; please sign in yourself.", kind="login", url=self.login_url(ref))

    # --- navigation ------------------------------------------------------------------

    def _open_posting(self, page: Page, ref: JobRef) -> None:
        page.goto(POSTINGS, wait_until="domcontentloaded")
        if not self.is_logged_in(page, ref, navigate=False):
            raise NeedsHuman("PD Portal session expired", kind="login", url=self.login_url(ref))
        try:      # the list's search form: without it this is not the postings page, whatever its address says
            page.wait_for_selector("#widgetSearch", state="attached", timeout=20000)
        except Exception as e:  # noqa: BLE001
            body = ""
            try:
                body = re.sub(r"\s+", " ", page.inner_text("body"))[:300]
            except Exception:  # noqa: BLE001
                pass
            if re.search(r"just a moment|verify(ing)? you are human|checking your browser|cloudflare|access denied", f"{page.title()} {body}", re.I):
                raise DriverError("PD Portal 拦下了这个浏览器窗口（人机验证页），没有显示岗位列表。请在“设置 → 浏览器”里打开“普通浏览器”后重试。", seen=body) from e
            if re.search(r"log ?in|sign ?in|CWL", body, re.I):
                raise NeedsHuman("PD Portal session expired", kind="login", url=self.login_url(ref)) from e
            raise DriverError(f"PD Portal 没有显示岗位列表，页面内容：{body[:160] or '（空白）'}", seen=body) from e
        page.evaluate("() => { const f = document.getElementById('widgetSearch'); f.widget1Keyword.value = ''; setTimeout(() => f.submit(), 50); }")
        page.wait_for_selector("[onclick*=postingId]", timeout=30000)
        if not page.evaluate(_OPEN_JS, ref.job_id):
            raise DriverError("could not open the posting from the list", expected=ref.job_id)
        page.wait_for_function("(id) => document.body.innerText.includes(id)", arg=ref.job_id, timeout=30000)
        page.wait_for_load_state("domcontentloaded")

    def already_applied(self, page: Page, ref: JobRef) -> bool:
        self._open_posting(page, ref)
        return "Application Submitted" in page.inner_text("body")

    def open_application(self, page: Page, ref: JobRef) -> None:
        if ref.job_id not in page.inner_text("body")[:3000]:
            self._open_posting(page, ref)
        btn = page.locator("button, a").filter(has_text=re.compile(r"^\s*APPLY\s*$")).first
        if btn.count() == 0:
            raise DriverError("APPLY button not found (deadline passed or already applied)", seen=page.url)
        btn.click()
        page.wait_for_selector("input[type=radio]", timeout=20000)
        page.evaluate(
            """() => { const r = [...document.querySelectorAll('input[type=radio]')].find(r => /CUSTOMIZED/i.test((r.closest('div,label,tr')||document.body).innerText)); if (r) r.click(); }"""
        )
        page.wait_for_selector("select[name='12']", timeout=15000)

    # --- schema ------------------------------------------------------------------------

    def live_questions(self, page: Page, page_index: int = 0, with_options: bool = False) -> list[Question]:
        # Options are the user's My Documents list, which changes between recon and execution;
        # they are left out of the live check so a new document is not reported as form drift.
        qs = []
        for name, label in SELECTS.items():
            sel = page.locator(f"select[name='{name}']")
            if sel.count() == 0:
                continue
            opts = [re.sub(r"\s*\(Date created:.*$", "", t).strip() for t in sel.locator("option").all_inner_texts()]
            opts = [o for o in opts if o and not o.startswith("--")] if with_options else []
            if name == "11":
                qs.append(Question(id="11", label=label, type="file", required=False, options=opts, locator={"select": True}))
            else:
                qs.append(Question(id=name, label=label, type="select", required=False, options=opts))
        qs.append(Question(id="package", label="Package Name", type="text", required=True, help="Use <Company>_<JobID>."))
        return qs

    def get_schema(self, ref: JobRef, page: Any | None = None, answers: Any | None = None) -> FormSchema:
        if page is None:
            raise DriverError("PD Portal reconnaissance needs a signed-in page")
        self._open_posting(page, ref)
        body = page.inner_text("body")
        need = (re.search(r"Application Documents Required:\s*([^\n]+)", body) or [None, ""])[1].lower()
        self.open_application(page, ref)
        qs = self.live_questions(page, with_options=True)
        req = {"30": "summary sheet" in need, "11": "cover letter" in need, "12": "resume" in need, "13": "transcript" in need, "17": False}
        for q in qs:
            if q.id in req:
                q.required = req[q.id]
                if not req[q.id]:
                    q.help = "Not required by this posting: leave unselected."
        return FormSchema(ats=self.ats, tenant="ubc", job_ref=ref.job_id, url=ref.url, requires_login=True, source="walk",
                          pages=["Application package"], questions=qs, extra={"docs_required": need})

    # --- fill --------------------------------------------------------------------------

    def _upload_to_my_documents(self, page: Page, path: str, name: str, type_value: str = "11") -> None:
        """Upload a file to My Documents. The submit link needs two clicks after a file is chosen."""
        page.goto(DOCS, wait_until="domcontentloaded")
        if name in page.inner_text("body"):
            return
        page.locator("a, button").filter(has_text=re.compile(r"Upload Document")).first.click()
        page.wait_for_selector("input[type=file]", timeout=15000)
        form = page.locator("form").filter(has=page.locator("input[type=file]")).first
        w.set_text(form.locator("input[type=text]").first, name)
        form.locator("select").first.select_option(value=type_value)
        w.upload(form.locator("input[type=file]").first, [path])
        link = page.locator("a").filter(has_text=re.compile(r"^\s*Upload Document\s*$")).last
        for _ in range(2):
            if "Upload a Document" not in page.inner_text("body"):
                break
            link.click()
            page.wait_for_timeout(3000)
        if "Upload a Document" in page.inner_text("body"):
            raise DriverError("document upload form did not submit", expected=name)

    def fill_page(self, page: Page, schema: FormSchema, page_index: int, answers: dict[str, Any]) -> None:
        cl = answers.get("11")
        ref = JobRef(self.ats, "ubc", schema.job_ref, schema.url, "pdportal.apsc.ubc.ca")
        if cl and Path(str(cl)).exists():
            doc_name = Path(str(cl)).stem[:60]
            self._upload_to_my_documents(page, str(cl), doc_name)
            self._open_posting(page, ref)
            self.open_application(page, ref)
            answers = {**answers, "11": doc_name}
        for name in SELECTS:
            val = answers.get(name)
            if not val:
                continue
            sel = page.locator(f"select[name='{name}']")
            texts = sel.locator("option").all_inner_texts()
            idx = next((i for i, t in enumerate(texts) if t.strip().startswith(str(val))), None)
            if idx is None:
                raise DriverError("document is not in My Documents", question=SELECTS[name], expected=str(val), seen=" / ".join(t.strip()[:40] for t in texts)[:400])
            sel.select_option(index=idx)
        pkg = self._package_input(page)
        w.set_text(pkg, str(answers.get("package") or f"Application_{schema.job_ref}"))

    def _package_input(self, page: Page):
        lab = page.locator("label").filter(has_text=re.compile(r"Package Name")).first
        if lab.count():
            fid = lab.get_attribute("for")
            if fid:
                return page.locator(f"[id='{fid}']")
        return page.locator("input[type=text]:visible").last

    def next_page(self, page: Page) -> bool:
        return False

    def read_back(self, page: Page, schema: FormSchema, page_index: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in SELECTS:
            sel = page.locator(f"select[name='{name}']")
            if sel.count():
                t = sel.evaluate("(e) => e.selectedIndex > 0 ? e.selectedOptions[0].text : ''")
                t = re.sub(r"\s*\(Date created:.*$", "", t).strip()
                out[name] = (t + ".pdf") if name == "11" and t else t  # compared against the uploaded file's name
        out["package"] = self._package_input(page).input_value()
        return out

    def submit(self, page: Page) -> None:
        page.locator("button, input[type=submit]").filter(has_text=re.compile(r"Submit Application")).first.click(timeout=w.T)

    def confirmation(self, page: Page) -> dict[str, Any] | None:
        try:
            page.wait_for_function("() => /Your online application has been submitted/i.test(document.body.innerText)", timeout=30000)
        except PWTimeout:
            return None
        m = re.search(r"Your online application has been submitted[^\n]*", page.inner_text("body"))
        return {"url": page.url, "text": m.group(0) if m else "submitted"}

    def form_errors(self, page: Page) -> list[str]:
        return [t.strip() for t in page.locator(".alert-danger:visible, .error:visible").all_inner_texts() if t.strip()][:10]

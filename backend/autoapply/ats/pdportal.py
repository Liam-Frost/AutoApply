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
# The portal's sign-in, read off the live pages (2026-11): "Student Login" leads here; the portal sends the window to the
# university's login (CWL, a Shibboleth page: #username, #password, button _eventId_proceed), which sends it on to Duo
# for the second factor and then back to /secure/sso-student.htm -> /myAccount/...
SSO_ENTRY = f"{BASE}/Shibboleth.sso/Login?entityID=https://authentication.ubc.ca&target={BASE}/secure/sso-student.htm"
IDP_HOST = "authentication.ubc.ca"          # the only address the CWL password is ever typed on
SECOND_FACTOR_HOST = re.compile(r"(^|\.)duosecurity\.com$")
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
    sso = True  # signs in through the university's login (CWL): there is nothing to register, and the password is the university's
    second_factor_wait = 180     # seconds the applicant has to approve the sign-in on their phone
    password_policy = PasswordPolicy()
    read_by_agent = False        # the portal does not allow programs to explore it: its form is read by this driver only (drafts.recon)

    @staticmethod
    def fixed_answer(q: Question, job: Any) -> tuple[Any, str] | None:
        """The portal's package form: its document pickers and the package's name follow rules, and need no model."""
        if q.id == "package":
            company = "".join(c if c.isalnum() else "_" for c in (job.company or "Application")).strip("_")[:40]
            return f"{company}_{job.source_id}", "naming rule <Company>_<JobID>"
        if q.type == "select":
            if not q.required:
                return "", "not required by this posting"
            if len(q.options) == 1:
                return q.options[0], "only document of this type in My Documents"
        return None

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

    def _sign_in(self, page: Page, ref: JobRef, user: str = "", password: str = "") -> bool:
        """Go through the portal's sign-in, from its own entry, as far as it goes without a person. True: signed in.

        What each page gets:
        - the portal's entry: followed. When the university's login still holds, it comes straight back signed in.
        - the university's login (CWL): the stored login name and password, once, and only on its own address. Without
          them: False - nothing is typed, the applicant signs in. Asked for the password a second time: the login
          refused it (DriverError "sign-in rejected") - it is not typed again.
        - Duo: the applicant is told to approve on their phone, and the program waits for it (second_factor_wait).
          Nothing is pressed there except "this is my device", which Duo asks after an approval.
        The pages of Duo could not be looked at while writing this (they come after the password); what is done there
        is kept to what does not depend on their make-up: wait until the window is back on the portal."""
        page.goto(SSO_ENTRY, wait_until="domcontentloaded")
        typed = moved = asked = False
        waited, limit = 0, 45
        while waited < limit:
            host = urlparse(page.url).netloc.lower()
            if self.signed_in_url(page.url):
                page.wait_for_load_state("domcontentloaded")
                return "Not Logged In" not in page.inner_text("body")[:600]
            if host == IDP_HOST and page.locator("#password").count() and page.locator("#password").first.is_visible():
                if typed:
                    if not moved:
                        raise DriverError("the university's login did not answer after the password was sent", seen=host)
                    said = page.locator(".form-error, .form-element-wrapper .error, p.error").first
                    raise DriverError("sign-in rejected", seen=(said.inner_text().strip()[:200] if said.count() else "") or "the university's login asked for the password again")
                if not (user and password):
                    return False
                before = page.url
                page.locator("#username").first.fill(user)
                page.locator("#password").first.fill(password)     # never logged
                page.locator("button[name='_eventId_proceed']").first.click(timeout=w.T)
                typed = True
                for _ in range(15):
                    page.wait_for_timeout(1000)
                    waited += 1
                    if page.url != before:
                        moved = True
                        break
                continue
            if SECOND_FACTOR_HOST.search(host):
                if not asked:
                    asked, limit = True, waited + self.second_factor_wait
                    self._ask_for_the_phone()
                mine = page.locator("#trust-browser-button").or_(page.get_by_role("button", name=re.compile(r"yes, this is my device|trust (this )?browser", re.I))).first
                if mine.count() and mine.is_visible():
                    mine.click(timeout=w.T)
            page.wait_for_timeout(1000)
            waited += 1
        if asked:
            raise NeedsHuman(f"程序已经输入了 CWL 账号密码，等了 {self.second_factor_wait // 60} 分钟没有等到你在手机上批准 Duo。你方便的时候把这一条标为已处理，程序会重新登录并再发一次 Duo 请求；也可以自己登录一次。",
                             kind="login", url=self.login_url(ref))
        raise DriverError("the portal's sign-in did not finish", seen=urlparse(page.url).netloc)

    @staticmethod
    def _ask_for_the_phone() -> None:
        from .. import messages, notify

        notify.send("todo", messages.second_factor("UBC PD Portal", "Duo"), ref="account:pdportal:ubc")

    def resume(self, page: Page, ref: JobRef) -> bool:
        """The portal's session has run out. The university's login may still hold: then the portal's sign-in comes
        straight back signed in (after a Duo approval, if it wants one). Nothing is typed. False when the university's
        login asks for the password."""
        return self._sign_in(page, ref)

    def login(self, page: Page, ref: JobRef, email: str, password: str) -> None:
        """Sign in with the stored CWL login name (``email``) and password."""
        if not self._sign_in(page, ref, email, password):
            raise DriverError("the portal's sign-in did not end signed in", seen=urlparse(page.url).netloc)

    def register(self, page: Page, ref: JobRef, email: str, password: str) -> str:
        raise NeedsHuman("PD Portal signs in with your CWL: there is no account to register.", kind="login", url=self.login_url(ref))

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
            from .. import browser
            from ..sources import pdportal as source

            if source.refused(page):
                try:
                    source.firewall(page)       # a sign-in card, or the hint to switch the ordinary browser on - as for a scan
                except browser.RefusedHidden:
                    raise DriverError("PD Portal 的防护挡住了隐藏的浏览器（人机验证页）。已记下这个网站要在窗口里打开，重试即可。", seen=body) from e
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

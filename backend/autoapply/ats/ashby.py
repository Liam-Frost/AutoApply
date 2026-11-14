"""Ashby driver.

Schema: the hosted job page's own GraphQL endpoint (unofficial but public; no login)
  POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting
returns every form section and field with type, required flag and options.

Execution: https://jobs.ashbyhq.com/{org}/{posting}/application
Controls carry the field path as ``name`` (text/email/tel/textarea) or ``id`` (file).
Booleans are Yes/No buttons, selects are radio/checkbox lists or comboboxes,
Location is an autocomplete combobox, dates are typed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PWTimeout

from . import widgets as w
from .base import DriverError, FormSchema, JobRef, NeedsHuman, PasswordPolicy, Question, host_is

GQL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { "
    "jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { "
    "id title descriptionHtml locationName applicationForm { sections { title fieldEntries { ... on FormFieldEntry { id isRequired descriptionHtml field } } } } } }"
)
_TYPE = {
    "String": "text", "Email": "text", "Phone": "text", "Number": "text", "LongText": "textarea", "File": "file",
    "Boolean": "radio", "ValueSelect": "select", "MultiValueSelect": "multiselect", "Date": "date", "Location": "text",
    "Score": "text", "SocialLink": "text", "RichText": "textarea",
}


class AshbyDriver:
    ats = "ashby"
    requires_login = False
    password_policy = PasswordPolicy()

    def detect(self, url: str) -> JobRef | None:
        u = urlparse(url)
        if not host_is(u.hostname or "", "ashbyhq.com"):
            return None
        m = re.match(r"/([^/]+)/([0-9a-f-]{36})", u.path)
        if not m:
            return None
        return JobRef(self.ats, m.group(1), m.group(2), url, u.netloc.lower())

    def app_url(self, ref: JobRef) -> str:
        return f"https://jobs.ashbyhq.com/{ref.tenant}/{ref.job_id}/application"

    def get_schema(self, ref: JobRef, page: Any | None = None, answers: Any | None = None) -> FormSchema:
        r = httpx.post(GQL, json={"operationName": "ApiJobPosting", "variables": {"organizationHostedJobsPageName": ref.tenant, "jobPostingId": ref.job_id}, "query": QUERY},
                       headers={"User-Agent": "Mozilla/5.0", "content-type": "application/json"}, timeout=30)
        r.raise_for_status()
        jp = (r.json().get("data") or {}).get("jobPosting")
        if not jp:
            raise DriverError("posting not found on Ashby (closed or wrong id)", seen=str(r.text)[:200])
        qs: list[Question] = []
        for sec in (jp.get("applicationForm") or {}).get("sections", []):
            for fe in sec.get("fieldEntries", []):
                f = fe.get("field") or {}
                t = f.get("type", "String")
                qtype = _TYPE.get(t, "text")
                opts = [str(o.get("label", "")).strip() for o in f.get("selectableValues", []) or []]
                if t == "Boolean":
                    opts = ["Yes", "No"]
                if t == "EducationHistory":
                    qs += self._education_questions(f.get("path", ""), bool(fe.get("isRequired")), sec.get("title") or "")
                    continue
                qs.append(Question(
                    id=f.get("path", ""), label=re.sub(r"\s+", " ", f.get("title", "")).strip(), type=qtype, required=bool(fe.get("isRequired")),
                    options=opts, section=sec.get("title") or "", help=re.sub(r"<[^>]+>", " ", fe.get("descriptionHtml") or "").strip()[:500],
                    locator={"ashby_type": t},
                ))
        return FormSchema(ats=self.ats, tenant=ref.tenant, job_ref=ref.job_id, url=self.app_url(ref), title=jp.get("title", ""), company=ref.tenant,
                          source="api", pages=["Application"], questions=qs, extra={"content": jp.get("descriptionHtml", ""), "location": jp.get("locationName", "")})

    _MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    def _education_questions(self, path: str, required: bool, section: str) -> list[Question]:
        """Ashby's education block is one field in the API and six controls on the page (first entry only)."""
        def q(part: str, label: str, typ: str, req: bool, opts: list[str] | None = None, help_: str = "") -> Question:
            return Question(id=f"{path}::{part}", label=f"Education: {label}", type=typ, required=req, options=opts or [], section=section,
                            help=help_, locator={"ashby_type": "Education", "part": part, "parent": path})

        still = "If still studying, tick 'Still Student?' and leave the end date empty."
        return [
            q("school", "School", "text", required, help_="Most recent school, by its official name (the form searches a list of schools)."),
            q("degree", "Degree", "text", required, help_="e.g. Bachelor of Applied Science"),
            q("major", "Field of Study", "text", False),
            q("startMonth", "Start month", "select", False, self._MONTHS),
            q("startYear", "Start year", "text", False, help_="Four digits."),
            q("isCurrent", "Still Student?", "checkbox", False),
            q("endMonth", "End month", "select", False, self._MONTHS, still),
            q("endYear", "End year", "text", False, help_="Four digits. " + still),
        ]

    def _edu_control(self, page: Page, q: Question) -> Locator:
        parent, part = q.locator["parent"], q.locator["part"]
        if part == "school":
            lab = page.locator(f"label[for='{parent}-school']").first
            box = lab.locator("xpath=following::input[@role='combobox'][1]") if lab.count() else page.locator(f"label[for='{parent}']").locator("xpath=ancestor::*[contains(@class,'fieldEntry')][1]").locator("input[role=combobox]").first
        elif part in ("degree", "major", "isCurrent"):
            box = page.locator(f"[id='{parent}-{part}']")
        else:
            box = page.locator(f"[id='{parent}-{'startDate' if part.startswith('start') else 'endDate'}'] select").nth(0 if part.endswith("Month") else 1)
        if box.count() == 0:
            raise DriverError("education control not found on page", question=q.label, expected=part)
        return box.first

    def _fill_education(self, page: Page, q: Question, val: Any) -> None:
        part, box = q.locator["part"], self._edu_control(page, q)
        if part == "school":
            box.click(timeout=w.T)
            box.fill("")
            box.press_sequentially(str(val)[:40], delay=25)
            opts = page.locator("[role=option]:visible")
            try:
                opts.first.wait_for(state="visible", timeout=w.T)
            except PWTimeout as e:
                raise DriverError("no school suggestions appeared", question=q.label, expected=str(val)) from e
            page.wait_for_timeout(800)
            names = [t.strip().split("\n")[0].strip() for t in opts.all_inner_texts()]
            i = w.pick_option_or_none(names, str(val))
            if i is None:
                raise DriverError("school not in the form's list", question=q.label, expected=str(val), seen=" / ".join(names)[:300])
            opts.nth(i).click(timeout=w.T)
        elif part == "isCurrent":
            box.set_checked(str(val).lower() in ("true", "yes", "1"), force=True)
        elif part.endswith("Month") or part.endswith("Year"):
            w.select_native(box, str(val))
        else:
            w.set_text(box, str(val))

    def _read_education(self, page: Page, q: Question) -> Any:
        part, box = q.locator["part"], self._edu_control(page, q)
        if part == "isCurrent":
            return box.is_checked()
        if part.endswith("Month") or part.endswith("Year"):
            return box.evaluate("(e) => e.selectedIndex > 0 ? e.selectedOptions[0].text.trim() : ''")
        return box.input_value()

    # --- execution ---------------------------------------------------------------

    def open_application(self, page: Page, ref: JobRef) -> None:
        page.goto(self.app_url(ref), wait_until="domcontentloaded")
        try:
            page.locator("[name=_systemfield_name], [name=_systemfield_email]").first.wait_for(state="visible", timeout=20000)
        except PWTimeout as e:
            raise DriverError("application form did not load (posting may be closed)", seen=page.url) from e
        page.wait_for_timeout(800)

    def _entry(self, page: Page, q: Question) -> Locator:
        """The field's container: located by its label text."""
        lab = page.locator(f"label[for='{q.id}']").first  # the label points at the field's path
        if lab.count() == 0:
            lab = page.locator("label").filter(has_text=re.compile(r"^\s*" + re.escape(q.label[:80]))).first
        if lab.count() == 0:
            raise DriverError("field label not found on page", question=q.label)
        return lab.locator("xpath=ancestor::*[contains(@class,'fieldEntry') or contains(@class,'_field')][1]")

    def live_questions(self, page: Page, page_index: int = 0) -> list[Question]:
        out = []
        for c in w.describe_inputs(page, "form, body"):
            if not c["label"] or c["name"] == "g-recaptcha-response" or c["type"] in ("radio", "checkbox"):
                continue
            out.append(Question(id=c["name"] or c["id"], label=c["label"].rstrip("*").strip(), type={"email": "text", "tel": "text", "number": "text"}.get(c["type"], c["type"]), required=c["required"]))
        return out

    def fill_page(self, page: Page, schema: FormSchema, page_index: int, answers: dict[str, Any]) -> None:
        for q in schema.questions:
            val = answers.get(q.id)
            if val in (None, "", []):
                continue
            try:
                self._fill_one(page, q, val)
            except DriverError as e:
                e.question = e.question or q.label
                raise
            except PWTimeout as e:
                raise DriverError(f"timeout operating field: {str(e)[:200]}", question=q.label, expected=str(val)[:200]) from e

    def _fill_one(self, page: Page, q: Question, val: Any) -> None:
        t = q.locator.get("ashby_type", "String")
        if t == "Education":
            self._fill_education(page, q, val)
            return
        if t == "File":
            inp = page.locator(f"input[type=file][id='{q.id}']").first
            if inp.count() == 0:
                inp = self._entry(page, q).locator("input[type=file]").first
            w.upload(inp, [val] if not isinstance(val, list) else val)
            page.wait_for_timeout(1500)
            return
        if t == "Boolean":
            entry = self._entry(page, q)
            btn = entry.get_by_role("button", name=re.compile(rf"^{'Yes' if str(val).lower() in ('yes', 'true') else 'No'}$")).first
            btn.click(timeout=w.T)
            return
        if t in ("ValueSelect", "MultiValueSelect"):
            entry = self._entry(page, q)
            for v in val if isinstance(val, list) else [val]:
                opt = entry.locator("label").filter(has_text=re.compile(r"^\s*" + re.escape(str(v)) + r"\s*$")).first
                if opt.count():
                    opt.click(timeout=w.T)
                else:  # combobox variant
                    box = entry.locator("input[role=combobox], input[type=text]").first
                    self._combobox(page, box, str(v))
            return
        if t == "Location":
            box = self._entry(page, q).locator("input").first
            self._combobox(page, box, str(val), prefix_len=40)
            return
        loc = page.locator(f"[name='{q.id}']").first
        if loc.count() == 0:
            loc = self._entry(page, q).locator("input, textarea").first
        if t == "Date":
            loc.click(timeout=w.T)
            loc.fill(str(val), timeout=w.T)
            page.keyboard.press("Escape")
            return
        w.set_text(loc, str(val))

    def _combobox(self, page: Page, box: Locator, value: str, prefix_len: int = 30) -> None:
        box.click(timeout=w.T)
        box.press_sequentially(value[:prefix_len], delay=25)
        opts = page.locator("[role=option]:visible")
        try:
            opts.first.wait_for(state="visible", timeout=w.T)
        except PWTimeout as e:
            raise DriverError("no suggestions appeared", expected=value) from e
        page.wait_for_timeout(600)
        texts = [x.strip() for x in opts.all_inner_texts()]
        try:
            i = w.pick_option(texts, value)
        except DriverError:
            i = 0  # autocomplete: first suggestion for the typed prefix
        opts.nth(i).click(timeout=w.T)

    def next_page(self, page: Page) -> bool:
        return False

    def read_back(self, page: Page, schema: FormSchema, page_index: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for q in schema.questions:
            t = q.locator.get("ashby_type", "String")
            try:
                if t == "Education":
                    out[q.id] = self._read_education(page, q)
                elif t == "File":
                    entry = self._entry(page, q)
                    m = re.search(r"[^\n/\\]+\.(pdf|docx?|txt|rtf)\b", entry.inner_text(), re.I)
                    out[q.id] = m.group(0).strip() if m else ""
                elif t == "Boolean":
                    entry = self._entry(page, q)
                    out[q.id] = entry.evaluate(
                        """(e) => { const b = [...e.querySelectorAll('button')].find(b => /active|selected/i.test(b.className) || b.getAttribute('aria-pressed') === 'true' || b.getAttribute('aria-checked') === 'true'); return b ? b.innerText.trim() : ''; }"""
                    )
                elif t in ("ValueSelect", "MultiValueSelect"):
                    entry = self._entry(page, q)
                    vals = entry.evaluate(
                        """(e) => { const c = [...e.querySelectorAll('input[type=radio], input[type=checkbox]')].filter(i => i.checked).map(i => (i.closest('label') || document.querySelector(`label[for="${i.id}"]`) || i.parentElement).innerText.trim());
                                   if (c.length) return c; const i = e.querySelector('input[role=combobox], input[type=text]'); return i && i.value ? [i.value] : []; }"""
                    )
                    out[q.id] = vals if t == "MultiValueSelect" else (vals[0] if vals else "")
                elif t == "Location":
                    out[q.id] = self._entry(page, q).locator("input").first.input_value()
                else:
                    loc = page.locator(f"[name='{q.id}']").first
                    if loc.count() == 0:
                        loc = self._entry(page, q).locator("input, textarea").first
                    out[q.id] = loc.input_value()
            except DriverError:
                continue
        return out

    def submit(self, page: Page) -> None:
        if page.locator("iframe[src*=recaptcha][title*=challenge]:visible").count():
            raise NeedsHuman("the form shows a reCAPTCHA challenge", kind="captcha", url=page.url)
        page.get_by_role("button", name=re.compile(r"submit application", re.I)).first.click(timeout=w.T)

    def confirmation(self, page: Page) -> dict[str, Any] | None:
        try:
            page.wait_for_function("() => /successfully submitted|thank you|application (was|has been) (received|submitted)/i.test(document.body.innerText)", timeout=25000)
        except PWTimeout:
            return None
        return {"url": page.url, "text": w.visible_text(page, 1500)}

    def form_errors(self, page: Page) -> list[str]:
        return [t.strip() for t in page.locator("[class*=error]:visible, [role=alert]:visible").all_inner_texts() if t.strip()][:20]

    def already_applied(self, page: Page, ref: JobRef) -> bool:
        return False

    def is_logged_in(self, page: Page, ref: JobRef, navigate: bool = True) -> bool:
        return True

    def login(self, page: Page, ref: JobRef, email: str, password: str) -> None:
        return None

    def register(self, page: Page, ref: JobRef, email: str, password: str) -> str:
        return "ok"

    def login_url(self, ref: JobRef) -> str:
        return ""


def _name(p: str) -> str:
    return Path(p).name

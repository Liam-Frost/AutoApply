"""Greenhouse driver.

Schema comes from the public Job Board API (no browser needed):
  GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?questions=true
(verified 2026-11-12: returns standard fields and all custom questions with options).

Execution runs on the hosted embed form
  https://job-boards.greenhouse.io/embed/job_app?for={board}&token={id}
which uses react-select for dropdowns and element ids equal to the API field names.
Company-hosted pages that embed a legacy HTML form (native <select>, name=...)
are handled by the same code path: every control is located by id-or-name and
operated according to its actual tag.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from . import widgets as w
from .base import DriverError, FormSchema, JobRef, NeedsHuman, PasswordPolicy, Question, host_is

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?questions=true"
EMBED = "https://job-boards.greenhouse.io/embed/job_app?for={board}&token={job}"

_TYPE = {
    "input_text": "text",
    "textarea": "textarea",
    "input_file": "file",
    "multi_value_single_select": "select",
    "multi_value_multi_select": "multiselect",
    "input_hidden": "text",
}


class GreenhouseDriver:
    ats = "greenhouse"
    requires_login = False
    password_policy = PasswordPolicy()

    # --- detection -------------------------------------------------------------

    def detect(self, url: str) -> JobRef | None:
        u = urlparse(url)
        host = u.netloc.lower()
        qs = parse_qs(u.query)
        if host_is(u.hostname or "", "greenhouse.io"):
            m = re.search(r"/([^/]+)/jobs/(\d+)", u.path)
            if m:
                return JobRef(self.ats, m.group(1), m.group(2), url, host)
            if "for" in qs and "token" in qs:
                return JobRef(self.ats, qs["for"][0], qs["token"][0], url, host)
            return None
        if "gh_jid" in qs:
            # Company-hosted page: the board token is not in the URL. Resolved in
            # ``resolve_board`` by reading the page (needs a browser).
            return JobRef(self.ats, "", qs["gh_jid"][0], url, host, extra={"hosted": True})
        return None

    def resolve_board(self, page: Page, ref: JobRef) -> JobRef:
        """Find the board token on a company-hosted page (iframe src, script, or hidden input)."""
        if ref.tenant:
            return ref
        page.goto(ref.url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        token = page.evaluate(
            """() => {
                const f = [...document.querySelectorAll('iframe')].map(i => i.src).find(s => /greenhouse\\.io/.test(s));
                if (f) { const m = f.match(/[?&]for=([^&]+)/); if (m) return m[1]; }
                const h = document.querySelector('input[name=gh_board_token], input[name=board_token]');
                if (h && h.value) return h.value;
                const s = [...document.scripts].map(x => x.src + ' ' + x.textContent.slice(0, 5000)).join(' ');
                const m = s.match(/boards(?:-api)?\\.greenhouse\\.io\\/(?:v1\\/boards\\/|embed\\/job_board\\/js\\?for=)([a-z0-9_-]+)/i);
                return m ? m[1] : '';
            }"""
        )
        if not token:
            raise DriverError("could not find the Greenhouse board token on the company page", seen=ref.url)
        ref.tenant = token
        return ref

    # --- schema ----------------------------------------------------------------

    def get_schema(self, ref: JobRef, page: Any | None = None, answers: dict[str, Any] | None = None) -> FormSchema:
        if not ref.tenant:
            if page is None:
                raise DriverError("board token unknown; a browser page is required to resolve it")
            ref = self.resolve_board(page, ref)
        r = httpx.get(API.format(board=ref.tenant, job=ref.job_id), timeout=30, follow_redirects=True)
        if r.status_code == 404:
            raise DriverError("posting not found on the Greenhouse API (closed or wrong board token)", seen=str(r.url))
        r.raise_for_status()
        d = r.json()
        qs: list[Question] = []

        def add(label: str, required: bool, fields: list[dict], section: str, help_: str = "") -> None:
            files = [f for f in fields if f["type"] == "input_file"]
            main = files[0] if files else fields[0]
            qs.append(
                Question(
                    id=main["name"],
                    label=re.sub(r"\s+", " ", label).strip(),
                    type=_TYPE.get(main["type"], "text"),
                    required=bool(required),
                    options=[str(v.get("label", "")).strip() for v in main.get("values", [])],
                    section=section,
                    help=re.sub(r"<[^>]+>", " ", help_ or "").strip()[:500],
                    accept_text=bool(files) and len(fields) > 1,
                )
            )

        for q in d.get("questions", []):
            add(q["label"], q.get("required"), q["fields"], "application", q.get("description") or "")
        for q in d.get("location_questions", []) or []:
            if all(f["type"] == "input_hidden" for f in q["fields"]):
                continue  # longitude / latitude: set by the page when a location suggestion is picked
            add(q["label"], q.get("required"), q["fields"], "location")
        comp = d.get("compliance") or []
        for block in comp:
            for q in block.get("questions", []):
                add(q["label"], q.get("required"), q["fields"], "eeoc", block.get("description") or "")
        for block in [d.get("demographic_questions")] if d.get("demographic_questions") else []:
            for q in block.get("questions", []):
                qs.append(
                    Question(
                        id=f"demographic_{q['id']}",
                        label=q["label"],
                        type="multiselect" if q.get("type") == "multi_value_multi_select" else "select",
                        required=bool(q.get("required")),
                        options=[o["label"] for o in q.get("answer_options", [])],
                        section="demographic",
                    )
                )
        if page is not None:
            qs = self._with_page_extras(page, ref, qs)
        return FormSchema(
            ats=self.ats,
            tenant=ref.tenant,
            job_ref=ref.job_id,
            url=EMBED.format(board=ref.tenant, job=ref.job_id),
            title=d.get("title", ""),
            company=d.get("company_name", ""),
            source="api",
            pages=["Application"],
            questions=qs,
            extra={"absolute_url": d.get("absolute_url", ""), "content": d.get("content", "")},
        )

    # The hosted form can show an Education block that the API does not list.
    page_extras = True
    _EDU = re.compile(r"^(school|degree|discipline|start-month|start-year|end-month|end-year)--0$")

    def _with_page_extras(self, page: Page, ref: JobRef, qs: list[Question]) -> list[Question]:
        self.open_application(page, ref)
        extra: list[Question] = []
        for c in self.live_questions(page, 0):
            if not self._EDU.match(c.id):
                continue
            if c.type == "select" and not c.id.startswith("school"):  # school is a remote search; the others are short lists
                loc = w.by_name_or_id(page, c.id)
                opts = page.locator(f"[id='react-select-{c.id}-listbox'] [role=option]")
                try:
                    loc.scroll_into_view_if_needed(timeout=w.T)
                    loc.click(timeout=w.T)
                    try:
                        opts.first.wait_for(state="visible", timeout=3000)
                    except PWTimeout:
                        loc.press("ArrowDown")
                        opts.first.wait_for(state="visible", timeout=8000)
                    c.options = [t.strip() for t in opts.all_inner_texts()]
                    loc.press("Escape")
                except PWTimeout:
                    pass
            c.type = "text" if c.type == "number" else c.type
            c.section = "education"
            c.help = "Most recent education entry." + (" Type the school name as the form's search will list it." if c.id.startswith("school") else "")
            extra.append(c)
        if not extra:
            return qs
        # keep page order: education sits between the contact block and the custom questions
        at = next((i for i, q in enumerate(qs) if q.id.startswith("question_")), len(qs))
        return qs[:at] + extra + qs[at:]

    # --- execution -------------------------------------------------------------

    def open_application(self, page: Page, ref: JobRef) -> None:
        page.goto(EMBED.format(board=ref.tenant, job=ref.job_id), wait_until="domcontentloaded")
        try:
            page.locator("#first_name, [name=first_name]").first.wait_for(state="visible", timeout=20000)
        except PWTimeout as e:
            if "error=true" in page.url or page.locator("text=/no longer (open|accepting)/i").count():
                raise DriverError("posting is closed", seen=page.url) from e
            raise DriverError("application form did not load", seen=page.url) from e
        if page.locator("iframe[src*=recaptcha], iframe[src*=hcaptcha], .g-recaptcha").locator("visible=true").count():
            raise NeedsHuman("the form shows a CAPTCHA", kind="captcha", url=page.url)

    # API field name -> id on the hosted form, where they differ
    _ALIAS = {"location": "candidate-location"}

    def _find(self, page: Page, q: Question):
        loc = w.by_name_or_id(page, q.id)
        if loc.count() == 0 and q.id in self._ALIAS:
            loc = w.by_name_or_id(page, self._ALIAS[q.id])
        if loc.count() == 0 and q.id.startswith("demographic_"):
            loc = page.locator(f"[id='{q.id.split('_', 1)[1]}']")  # the page uses the bare question number
        return loc

    def _control(self, page: Page, q: Question):
        loc = self._find(page, q)
        if loc.count() == 0 and q.id == "race":
            # The hosted form asks "Are you Hispanic/Latino?" first and only then shows Race.
            hisp = page.locator("#hispanic_ethnicity")
            if hisp.count():
                w.react_select(page, hisp, "No")
                try:
                    page.locator("#race").wait_for(state="attached", timeout=5000)
                except PWTimeout:
                    pass
                loc = self._find(page, q)
        if loc.count() == 0:
            raise DriverError("field not found on page", question=q.label, expected=q.id)
        return loc

    def live_questions(self, page: Page, page_index: int = 0) -> list[Question]:
        out = []
        for c in w.describe_inputs(page, "form, #application-form, body"):
            if not c["label"] or c["type"] in ("search", "submit"):
                continue
            if c["id"].startswith("iti-") or c["name"] == "g-recaptcha-response" or c["id"].startswith("g-recaptcha"):
                continue
            if not c["id"] and not c["name"]:
                continue  # react-select's hidden validation input, a duplicate of the real control
            t = "select" if (c["role"] == "combobox" or c["type"] == "select") else c["type"]
            t = {"email": "text", "tel": "text", "url": "text"}.get(t, t)
            out.append(Question(id=c["id"] or c["name"], label=c["label"].rstrip("*").strip(), type=t, required=c["required"], options=c["options"]))
        return out

    def fill_page(self, page: Page, schema: FormSchema, page_index: int, answers: dict[str, Any]) -> None:
        # Phone country selector is not part of the API schema.
        country = page.locator("#country")
        from .generic_driver import FieldFailures

        failures = []
        if country.count() and answers.get("_phone_country"):
            want = str(answers["_phone_country"])
            for attempt in (1, 2):  # the widget sometimes is not ready on the first try
                try:
                    if not w.react_select_value(country).lower().startswith(want.lower()):
                        w.react_select(page, country, want, type_to_filter=True)
                    break
                except (DriverError, PWTimeout) as e:
                    try:
                        page.keyboard.press("Escape")
                        country.fill("")
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(800)
                    if attempt == 2:
                        failures.append({"id": "_phone_country", "label": "Phone country", "error": f"{type(e).__name__}: {str(e)[:160]}"})
        for q in schema.questions:
            if q.id not in answers or answers[q.id] in (None, "", []):
                continue
            val = answers[q.id]
            try:
                self._fill_one(page, q, val)
            except (DriverError, PWTimeout) as e:  # keep going: the repair agent gets the full list
                failures.append({"id": q.id, "label": q.label, "error": f"{type(e).__name__}: {str(e)[:160]}"})
                try:
                    page.keyboard.press("Escape")  # close a dropdown left open by the failed attempt
                except Exception:  # noqa: BLE001
                    pass
        if failures:
            raise FieldFailures(page_index, failures)

    def _fill_one(self, page: Page, q: Question, val: Any) -> None:
        if q.type == "file":
            self._upload(page, q, val if isinstance(val, list) else [val])
            return
        if q.id == "race" and "hispanic" in str(val).lower() and page.locator("#hispanic_ethnicity").count() and page.locator("#race").count() == 0:
            w.react_select(page, page.locator("#hispanic_ethnicity"), "Yes")
            self._race_via_hispanic = str(val)
            return
        loc = self._control(page, q)
        tag = loc.evaluate("(e) => e.tagName.toLowerCase()")
        itype = (loc.get_attribute("type") or "").lower()
        role = loc.get_attribute("role") or ""
        if q.id == "location" and role == "combobox":
            self._location = (str(val), self._pick_location(page, loc, str(val)))
        elif tag == "select":
            w.select_native(loc, str(val))
        elif tag == "fieldset":
            self._check_group(loc, q, val if isinstance(val, list) else [val])
        elif itype == "checkbox":
            w.set_checkbox(loc, bool(val))
        elif role == "combobox" or "select__input" in (loc.get_attribute("class") or ""):
            for v in val if isinstance(val, list) else [val]:
                w.react_select(page, loc, str(v), type_to_filter=q.id.startswith("school"))
        else:
            w.set_text(loc, str(val))

    _location: tuple[str, str] | None = None
    _race_via_hispanic: str | None = None

    def _pick_location(self, page: Page, loc: Any, want: str) -> str:
        """Location is a city autocomplete: type the city, take the suggestion that best matches
        the rest of the address ("Vancouver, BC, Canada" -> "Vancouver, British Columbia, Canada")."""
        parts = [p.strip() for p in want.split(",") if p.strip()]
        city = parts[0]
        loc.scroll_into_view_if_needed(timeout=w.T)
        loc.click(timeout=w.T)
        loc.press_sequentially(city, delay=40)
        opts = page.locator("[role=listbox]:visible [role=option]")
        texts: list[str] = []
        for _ in range(30):  # suggestions arrive from a remote lookup
            page.wait_for_timeout(300)
            texts = [t.strip() for t in opts.all_inner_texts()]
            if texts and not any(re.search(r"loading|searching", t, re.I) for t in texts) and not any(re.search(r"no (options|results)", t, re.I) for t in texts):
                break
        cands = [(i, t) for i, t in enumerate(texts) if w._norm(t).startswith(w._norm(city))]
        if not cands:
            raise DriverError("no location suggestion matches the city", question="Location", expected=want, seen=" / ".join(texts)[:300])

        def score(t: str) -> int:
            low = w._norm(t)
            return sum(1 for p in parts[1:] if w._norm(p) in low or (len(p) <= 3 and re.search(rf"\b{re.escape(p.lower())}\b", low)))

        i, text = max(cands, key=lambda c: (score(c[1]), -c[0]))
        opts.nth(i).click(timeout=w.T)
        return text

    _GROUP_JS = r"""(fs) => [...fs.querySelectorAll('input[type=checkbox], input[type=radio]')].map((i) => {
        const lab = (i.id && fs.querySelector(`label[for="${CSS.escape(i.id)}"]`)) || i.closest('label') || i.parentElement;
        return { label: (lab ? lab.innerText : '').replace(/\s+/g, ' ').trim(), checked: i.checked };
    })"""

    def _check_group(self, loc: Any, q: Question, want: list[Any]) -> None:
        """A multi-select rendered as a fieldset of checkboxes: tick exactly the wanted options."""
        want_n = [w._norm(str(v)) for v in want]
        boxes = loc.locator("input[type=checkbox], input[type=radio]")
        seen = loc.evaluate(self._GROUP_JS)
        missing = [v for v in want if w._norm(str(v)) not in [w._norm(o["label"]) for o in seen]]
        if missing:
            raise DriverError("option not found in checkbox group", question=q.label, expected=str(missing)[:200], seen=str([o["label"] for o in seen])[:300])
        for i, o in enumerate(seen):
            on = w._norm(o["label"]) in want_n
            if on != o["checked"]:
                box = boxes.nth(i)
                box.scroll_into_view_if_needed()
                box.set_checked(on, force=True)

    _FILE_JS = r"""([id, label]) => {
        // The hosted form removes the <input> once a file is accepted and shows
        // the file name inside the field group, so locate the group by label too.
        const norm = (t) => (t || '').replace(/\s+/g, ' ').replace(/\*+$/, '').trim().toLowerCase();
        const input = document.querySelector(`input[type=file][id="${id}"], input[type=file][name="${id}"]`);
        let group = null;
        if (input) { group = input.parentElement; for (let k = 0; k < 6 && group.parentElement && !group.querySelector('label, legend'); k++) group = group.parentElement; }
        if (!group) {
            const lab = [...document.querySelectorAll('label, legend, [class*=label]')].find(l => norm(l.innerText) === norm(label));
            if (lab) { group = lab.parentElement; for (let k = 0; k < 3 && group.parentElement && !/\.(pdf|docx?|txt|rtf)/i.test(group.innerText) && group.parentElement.querySelectorAll('label, legend').length <= 1; k++) group = group.parentElement; }
        }
        if (!group) return null;
        if (input && input.files && input.files.length) return [...input.files].map(f => f.name).join('|');
        const m = group.innerText.match(/[^\n\/]+\.(pdf|docx?|txt|rtf)\b/i);
        return m ? m[0].trim() : '';
    }"""

    def _uploaded_name(self, page: Page, q: Question) -> str | None:
        return page.evaluate(self._FILE_JS, [q.id, q.label])

    def _upload(self, page: Page, q: Question, paths: list[str]) -> None:
        from pathlib import Path

        want = Path(paths[0]).name
        inp = page.locator(f"input[type=file][id='{q.id}'], input[type=file][name='{q.id}']").first
        if inp.count() == 0:
            if w.values_equal(want, self._uploaded_name(page, q)):
                return  # already attached
            raise DriverError("file input not found", question=q.label, expected=q.id)
        # Prefer the visible "Attach" button (real file chooser); the hosted form
        # ignores files set directly on the hidden input until it is hydrated.
        group = inp.locator("xpath=ancestor::*[.//button][1]")
        btn = group.locator("button:has-text('Attach')").first
        if btn.count() and btn.is_visible():
            with page.expect_file_chooser(timeout=w.T) as fc:
                btn.click()
            fc.value.set_files(paths[0])
        else:
            w.upload(inp, paths[:1])
        for _ in range(20):
            page.wait_for_timeout(500)
            if w.values_equal(want, self._uploaded_name(page, q)):
                return
        raise DriverError("upload was not accepted by the form", question=q.label, expected=want, seen=str(self._uploaded_name(page, q)))

    def next_page(self, page: Page) -> bool:
        return False  # single-page form

    def read_back(self, page: Page, schema: FormSchema, page_index: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for q in schema.questions:
            if q.type == "file":
                out[q.id] = self._uploaded_name(page, q)
                continue
            loc = self._find(page, q)
            if loc.count() == 0:
                if q.id == "race" and self._race_via_hispanic and w.react_select_value(page.locator("#hispanic_ethnicity")) == "Yes":
                    out[q.id] = self._race_via_hispanic  # the form records Hispanic/Latino through its own question
                continue
            tag = loc.evaluate("(e) => e.tagName.toLowerCase()")
            itype = (loc.get_attribute("type") or "").lower()
            if q.id == "location" and (loc.get_attribute("role") or "") == "combobox":
                shown = w.react_select_value(loc)
                # The draft holds the applicant's wording; the page holds the suggestion chosen for it.
                out[q.id] = self._location[0] if self._location and shown and shown == self._location[1] else shown
            elif tag == "fieldset":
                out[q.id] = [o["label"] for o in loc.evaluate(self._GROUP_JS) if o["checked"]]
            elif tag == "select":
                out[q.id] = loc.evaluate("(e) => e.selectedIndex > 0 || (e.selectedOptions[0] && e.selectedOptions[0].value) ? e.selectedOptions[0].text.trim() : ''")
            elif itype == "checkbox":
                out[q.id] = loc.is_checked()
            elif (loc.get_attribute("role") or "") == "combobox":
                v = w.react_select_value(loc)
                out[q.id] = [x for x in v.split("|") if x] if q.type == "multiselect" else v
            else:
                out[q.id] = loc.input_value()
        return out

    def submit(self, page: Page) -> None:
        btn = page.locator("button[type=submit], input[type=submit]").filter(has_text=re.compile("submit", re.I)).first
        if btn.count() == 0:
            btn = page.get_by_role("button", name=re.compile("submit application", re.I)).first
        btn.click(timeout=w.T)

    _CODE_BOXES = "input[id*=security-input], input[id*=security_code], input[name*=security_code], input[autocomplete=one-time-code]"

    def needs_email_code(self, page: Page) -> bool:
        """Greenhouse sometimes asks for a security code e-mailed after Submit."""
        if page.locator(self._CODE_BOXES).count() > 0:
            return True
        return page.get_by_text(re.compile(r"security code|verification code", re.I)).count() > 0 and page.locator("input:visible").count() > 0

    def enter_email_code(self, page: Page, code: str) -> None:
        boxes = page.locator(self._CODE_BOXES)
        if boxes.count() == 0:
            raise DriverError("security code field not found", seen=page.url)
        code = code.strip()
        if boxes.count() > 1:  # one box per character; typed like a person would, so the page's own handlers run
            boxes.first.click()
            for i, ch in enumerate(code[: boxes.count()]):
                box = boxes.nth(i)
                if box.input_value() != "":
                    box.fill("")
                box.press_sequentially(ch, delay=60)
        else:
            boxes.first.click()
            boxes.first.fill("")
            boxes.first.press_sequentially(code, delay=60)
        page.wait_for_timeout(500)
        self.submit(page)

    def email_code_error(self, page: Page) -> str:
        """Text of an 'invalid / expired code' message, if the form shows one."""
        loc = page.get_by_text(re.compile(r"(invalid|incorrect|expired|wrong)[^.\n]{0,40}code|code[^.\n]{0,40}(invalid|incorrect|expired)", re.I))
        return loc.first.inner_text()[:200] if loc.count() else ""

    def confirmation(self, page: Page) -> dict[str, Any] | None:
        try:
            page.wait_for_function(
                "() => /thank you|application (has been )?(received|submitted)|we.ve received/i.test(document.body.innerText) || /confirmation/.test(location.href)",
                timeout=20000,
            )
        except PWTimeout:
            return None
        return {"url": page.url, "text": w.visible_text(page, 1500)}

    def form_errors(self, page: Page) -> list[str]:
        return [t.strip() for t in page.locator("[class*=error]:visible, [role=alert]:visible").all_inner_texts() if t.strip()][:20]

    def already_applied(self, page: Page, ref: JobRef) -> bool:
        return False  # no account; duplicates are prevented by our own records

    # --- auth: not applicable ----------------------------------------------------

    def is_logged_in(self, page: Page, ref: JobRef) -> bool:
        return True

    def login(self, page: Page, ref: JobRef, email: str, password: str) -> None:
        return None

    def register(self, page: Page, ref: JobRef, email: str, password: str) -> str:
        return "ok"

    def login_url(self, ref: JobRef) -> str:
        return ""

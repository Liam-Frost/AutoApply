"""Workday driver (multi-page, one account per tenant).

Verified against live pages (2026-11): URL shapes, the sign-in / create-account
form (data-automation-id: email, password, verifyPassword, createAccountCheckbox,
createAccountSubmitButton, signInLink, click_filter overlay, 'beecatcher' honeypot),
the progress bar, and the public cxs JSON API.
From logged-in sessions driven by hand in 2026-09..11: stable element ids
(name--legalName--firstName, address--city, source--source, phoneNumber--phoneType,
primaryQuestionnaire--<hash>), listbox buttons, the hierarchical "How did you hear"
prompt, "Use My Last Application" pre-fill, and that "Save and Continue" stores a
server-side draft without submitting. The logged-in page flow in this file has not
yet been exercised end to end by this code; treat first runs per tenant as manual-policy.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PWTimeout

from .. import timing
from . import widgets as w
from .base import DriverError, FormSchema, JobRef, NeedsHuman, PasswordPolicy, Question, SiteDown, host_is

A = "[data-automation-id='{}']"


def _a(page: Page | Locator, aid: str) -> Locator:
    return page.locator(A.format(aid))


class WorkdayDriver:
    ats = "workday"
    requires_login = True
    password_policy = PasswordPolicy(length=16, symbols="!@#$%&*")

    # --- detection ---------------------------------------------------------------

    def detect(self, url: str) -> JobRef | None:
        u = urlparse(url)
        host = u.netloc.lower()
        if not (host_is(u.hostname or "", "myworkdayjobs.com") or host_is(u.hostname or "", "myworkdaysite.com")):
            return None
        tenant = host.split(".myworkday")[0]  # e.g. "altera.wd1"
        parts = [p for p in u.path.split("/") if p]
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts = parts[1:]
        site = parts[0] if parts else ""
        m = re.search(r"/job/(.+?)(?:/apply.*)?$", u.path)
        job_path = m.group(1) if m else ""
        req = job_path.rsplit("_", 1)[-1] if "_" in job_path else ""
        return JobRef(self.ats, tenant, req, url, host, extra={"site": site, "job_path": job_path})

    def _base(self, ref: JobRef) -> str:
        return f"https://{ref.host}/en-US/{ref.extra['site']}"

    def job_url(self, ref: JobRef) -> str:
        return f"{self._base(ref)}/job/{ref.extra['job_path']}"

    def login_url(self, ref: JobRef) -> str:
        return f"{self._base(ref)}/login"

    # --- auth ----------------------------------------------------------------------

    def _goto(self, page: Page, url: str) -> None:
        """Navigate, and say so plainly when Workday is not serving the page."""
        r = page.goto(url, wait_until="domcontentloaded")
        status = r.status if r else 0
        if status >= 500 or page.locator("[data-automation-id='cloudflare_error']").count():
            raise SiteDown(f"Workday returned an error page (HTTP {status})", seen=url)
        try:  # the page is an empty shell until the app script loads
            page.wait_for_function("() => document.querySelectorAll('[data-automation-id]').length > 3", timeout=20000)
        except PWTimeout as e:
            if len(page.inner_text("body").strip()) < 20:
                raise SiteDown("Workday served an empty page (its application script did not load)", seen=url) from e

    def _dismiss_cookies(self, page: Page) -> None:
        btn = _a(page, "legalNoticeDeclineButton")  # decline non-essential cookies
        if btn.count() and btn.first.is_visible():
            btn.first.click()

    def is_logged_in(self, page: Page, ref: JobRef, navigate: bool = True) -> bool:
        if navigate:
            self._goto(page, f"{self._base(ref)}/userHome")
            # The header is drawn signed out first ("Sign In") and changes to the account menu once the page has asked
            # the server who is there - a second or two later. Looking at the first thing that appears made a session
            # that had just been signed in to look signed out, every time. The answer is in once the account menu is
            # there, or once the page's own content is (it comes after the header has settled).
            settled = f"{A.format('utilityButtonAccountTasksMenu')}, {A.format('signInSubmitButton')}, {A.format('welcomeMsgHeader')}, {A.format('applicationsSectionHeading')}"
            try:
                page.wait_for_selector(settled, timeout=20000)
            except PWTimeout:
                return False
            if not _a(page, "utilityButtonAccountTasksMenu").count() and not _a(page, "signInSubmitButton").count():
                try:      # the content is there; one more moment for a header that is still changing
                    page.wait_for_selector(A.format("utilityButtonAccountTasksMenu"), timeout=4000)
                except PWTimeout:
                    pass
            self._dismiss_cookies(page)
        return _a(page, "utilityButtonAccountTasksMenu").count() > 0 and _a(page, "signInSubmitButton").count() == 0

    def _click_covered(self, page: Page, aid: str) -> None:
        """Workday covers primary buttons with a click_filter overlay; click that when present."""
        btn = _a(page, aid).first
        btn.wait_for(state="attached", timeout=w.T)
        page.wait_for_timeout(1000)  # a click that lands before the form is hydrated is silently dropped
        # The real <button> is aria-hidden; the clickable element is the click_filter in the same wrapper.
        flt = btn.locator("xpath=ancestor::*[.//*[@data-automation-id='click_filter']][1]").locator("[data-automation-id='click_filter']").first
        if flt.count():
            flt.click(timeout=w.T)
        else:
            btn.click(timeout=w.T)

    def _auth_error(self, page: Page) -> str:
        err = page.locator(f"{A.format('errorMessage')}, [role=alert]").first
        return err.inner_text().strip() if err.count() and err.is_visible() else ""

    def login(self, page: Page, ref: JobRef, email: str, password: str) -> None:
        self._goto(page, self.login_url(ref))
        self._dismiss_cookies(page)
        if _a(page, "signInSubmitButton").count() == 0 and _a(page, "signInLink").count():
            _a(page, "signInLink").first.click()
        try:
            page.wait_for_function("() => document.querySelector(\"[data-automation-id='email']\") || /\\/userHome\\b/.test(location.href)", timeout=20000)
        except PWTimeout:
            pass
        if re.search(r"/userHome\b", page.url) and _a(page, "email").count() == 0:
            return      # the sign-in page sent us on to the candidate home: this session is signed in already
        _a(page, "email").first.wait_for(state="visible", timeout=20000)
        _a(page, "email").first.fill(email)
        _a(page, "password").first.fill(password)  # never logged
        self._click_covered(page, "signInSubmitButton")
        try:
            page.wait_for_function(
                "() => document.querySelector(\"[data-automation-id='utilityButtonAccountTasksMenu']\") || document.querySelector(\"[data-automation-id='errorMessage']\")",
                timeout=20000,
            )
        except PWTimeout:
            pass
        if self._captcha(page):
            raise NeedsHuman("Workday is asking for a human verification at sign-in", kind="captcha", url=page.url)
        err = self._auth_error(page)
        if err:
            if re.search(r"verify|verification|activate", err, re.I):
                raise NeedsHuman(f"The account needs e-mail verification: {err[:150]}", kind="login", url=page.url)
            raise DriverError("sign-in rejected", seen=err[:200])

    def register(self, page: Page, ref: JobRef, email: str, password: str) -> str:
        self._goto(page, f"{self.job_url(ref)}/apply/applyManually")
        self._dismiss_cookies(page)
        _a(page, "verifyPassword").first.wait_for(state="visible", timeout=20000)
        _a(page, "email").first.fill(email)
        _a(page, "password").first.fill(password)
        _a(page, "verifyPassword").first.fill(password)
        cb = _a(page, "createAccountCheckbox").first
        if cb.count():
            w.set_checkbox(cb, True)
        # the 'beecatcher' honeypot input is deliberately left empty
        self._click_covered(page, "createAccountSubmitButton")
        try:
            page.wait_for_function(
                "() => document.querySelector(\"[data-automation-id='utilityButtonAccountTasksMenu']\") || document.querySelector(\"[data-automation-id='errorMessage']\") || /verify your (email|account)|verification email/i.test(document.body.innerText)",
                timeout=25000,
            )
        except PWTimeout:
            pass
        if self._captcha(page):
            raise NeedsHuman("Workday is asking for a human verification at registration", kind="captcha", url=page.url)
        err = self._auth_error(page)
        if err:
            if re.search(r"already (exists|in use|registered)|sign in to (this|your) account|account .* exists", err, re.I):
                return "exists"
            return f"error: {err[:150]}"
        if re.search(r"verify your (email|account)|verification email", page.inner_text("body"), re.I):
            return "verify_email"
        if _a(page, "verifyPassword").count() and _a(page, "verifyPassword").first.is_visible():
            return "error: the sign-up form is still showing; it was not accepted"  # never report success on no evidence
        return "ok"

    def _captcha(self, page: Page) -> bool:
        return page.locator("iframe[src*=recaptcha]:visible, iframe[src*=hcaptcha]:visible, iframe[title*=challenge]:visible").count() > 0

    def already_applied(self, page: Page, ref: JobRef) -> bool:
        self._goto(page, f"{self._base(ref)}/userHome")
        page.wait_for_timeout(2500)
        return bool(ref.job_id) and ref.job_id in page.inner_text("body")

    # --- page helpers --------------------------------------------------------------

    def _page_title(self, page: Page) -> str:
        cur = _a(page, "progressBarActiveStep").first
        if cur.count():
            return re.sub(r"current step \d+ of \d+", "", cur.inner_text()).strip()
        h = page.locator("h2").first
        return h.inner_text().strip() if h.count() else ""

    def _steps(self, page: Page) -> list[str]:
        items = page.locator(f"{A.format('progressBar')} li")
        return [re.sub(r"(current |completed )?step \d+ of \d+", "", t).strip() for t in items.all_inner_texts()]

    def _wait_page(self, page: Page) -> None:
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_function("() => !/\\bLoading\\b/.test((document.querySelector('main') || document.body).innerText.slice(0, 4000))", timeout=20000)
        except PWTimeout:
            pass
        # A step of the form shows its progress bar before its fields (with "Use My Last Application" the fields come
        # with the earlier answers, seconds later). Reading it in between finds nothing - and an empty draft looked ready.
        if _a(page, "progressBar").count() and not re.search(r"^review$", self._page_title(page), re.I):
            try:
                page.wait_for_selector("main input:not([type=hidden]), main textarea, main button[aria-haspopup=listbox]", state="visible", timeout=20000)
            except PWTimeout:
                pass
        page.wait_for_timeout(700)

    def open_application(self, page: Page, ref: JobRef) -> None:
        self._goto(page, f"{self.job_url(ref)}/apply")
        self._dismiss_cookies(page)
        self._wait_page(page)
        # "Start Your Application": prefer the previous application's data when there is one.
        # The choice is a link that loads the form; a click that lands before the page is ready is dropped, and the form
        # takes a few seconds to appear. So: click, wait for the form's progress bar, and click once more if nothing moved.
        for attempt in range(2):
            if _a(page, "progressBar").count():
                break
            before = page.url
            for aid, label in (("useMyLastApplication", "Use My Last Application"), ("applyManually", "Apply Manually")):
                btn = _a(page, aid).or_(page.get_by_role("button", name=label)).or_(page.get_by_role("link", name=label)).first
                if btn.count() and btn.is_visible():
                    if attempt == 0:
                        page.wait_for_timeout(1000)
                    btn.click()
                    break
            try:
                page.wait_for_selector(A.format("progressBar"), timeout=30000 if page.url != before or attempt else 12000)
            except PWTimeout:
                pass
        self._wait_page(page)
        if _a(page, "progressBar").count() == 0:
            raise DriverError("application flow did not open", seen=page.url)

    # --- structure -------------------------------------------------------------------

    _kept: list[str] = []      # rows the last fill_page left as the site holds them

    _SKIP_IDS = re.compile(r"extension$|countryPhoneCode$|middleName$|addressLine2$")

    def live_questions(self, page: Page, page_index: int = 0) -> list[Question]:
        """Questions on the current page, with dropdown options read by opening each list."""
        qs: list[Question] = []
        seen_groups: set[str] = set()
        for c in w.describe_inputs(page, "main, [data-automation-id=applyFlowPage]"):
            if not c["visible"] or c["type"] in ("password", "search", "hidden"):
                continue
            cid = c["id"]
            if c["type"] == "file":      # the upload box has no id of its own on some sites; it is the résumé all the same
                if not any(q.id == "file::resume" for q in qs):
                    qs.append(Question(id="file::resume", label="Resume/CV", type="file", required=True, page=page_index))
                continue
            if not cid or self._SKIP_IDS.search(cid):
                continue
            label = re.sub(r"\s*(Select One|Required)\s*", " ", c["label"]).strip().rstrip("*").strip()
            if c["type"] in ("listbox", "checkbox", "text", "textarea") and (not label or c["type"] in ("checkbox", "listbox")):
                # questionnaire steps put the question in the field's frame (a legend or a rich-text block), not in a label
                frame = self._frame(page, cid)
                if c["type"] == "checkbox" and frame["boxes"] > 1 and frame["text"]:
                    if frame["text"] not in seen_groups:      # several tick boxes under one question: one question, many choices
                        seen_groups.add(frame["text"])
                        qs.append(Question(id=f"checks::{frame['text']}", label=frame["text"], type="multiselect", required=frame["required"], options=frame["options"], page=page_index))
                    continue
                # a list button's own "label" is often the choice it shows ("75-79%"): the frame has the question
                label = frame["text"] if c["type"] == "listbox" and frame["text"] else (label or frame["text"])
            if c["type"] == "radio":
                grp = page.locator(f"[id='{cid}']").locator("xpath=ancestor::fieldset[1]")
                gl = grp.locator("legend").first.inner_text().strip().rstrip("*") if grp.count() and grp.locator("legend").count() else label
                if gl in seen_groups:
                    continue
                seen_groups.add(gl)
                opts = [t.strip() for t in grp.locator("label").all_inner_texts()] if grp.count() else ["Yes", "No"]
                qs.append(Question(id=f"radio::{gl}", label=gl, type="radio", required=True, options=opts, page=page_index))
                continue
            if c["type"] == "listbox":
                btn = page.locator(f"[id='{cid}']")
                opts = self._listbox_options(page, btn)
                qs.append(Question(id=cid, label=label, type="select", required=True, options=opts, page=page_index))
                continue
            if cid == "source--source" or c.get("role") == "combobox" and "source" in cid:
                qs.append(Question(id=cid, label=label or "How Did You Hear About Us?", type="select", required=True, page=page_index, locator={"prompt": True}))
                continue
            if c["type"] == "checkbox":
                qs.append(Question(id=cid, label=label or "Acknowledgement", type="checkbox", required=c["required"], page=page_index))
                continue
            if not label:
                continue
            qtype = "textarea" if c["type"] == "textarea" else "date" if c["role"] == "spinbutton" else "text"
            if qtype == "date" and not cid.endswith("Month-input") and "dateSectionMonth" not in cid:
                continue  # one question per date (anchored on the month box)
            qs.append(Question(id=cid, label=label, type=qtype, required=c["required"] or c["label"].strip().endswith("*"), page=page_index))
        # "First Name" under "Legal Name" and under "Preferred Name" are two questions: one label for both got them one
        # answer (and the legal name was overwritten with the preferred one). The id names the section.
        seen = collections.Counter(q.label for q in qs if q.type in ("text", "textarea"))
        for q in qs:
            parts = q.id.split("--")
            if q.type in ("text", "textarea") and seen[q.label] > 1 and len(parts) >= 3 and not re.search(r"-\d+$", parts[-2]):
                q.label = f"{re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', parts[-2]).title()}: {q.label}"
        return qs

    def _frame(self, page: Page, cid: str) -> dict[str, Any]:
        """The question a control belongs to, read from the frame Workday draws around a field."""
        try:
            return page.locator(f"[id='{cid}']").first.evaluate(r"""(e) => {
                const f = e.closest("[data-automation-id^='formField']") || e.closest('fieldset');
                const head = f && f.querySelector('legend, [data-automation-id=richText], label');
                const raw = head ? head.innerText.replace(/\s+/g, ' ').trim() : '';
                const boxes = f ? [...f.querySelectorAll('input[type=checkbox]')] : [];
                return { text: raw.replace(/\s*\*\s*$/, '').trim().slice(0, 400), required: /\*\s*$/.test(raw) || !!(head && head.querySelector('abbr')), boxes: boxes.length,
                         options: boxes.map((b) => ((b.labels && b.labels[0] && b.labels[0].innerText) || '').trim()).filter(Boolean) }; }""")
        except Exception:  # noqa: BLE001
            return {"text": "", "required": False, "boxes": 0, "options": []}

    def _listbox_options(self, page: Page, btn: Locator) -> list[str]:
        try:
            # A list that is still open from the field before would be read as this field's choices (the phone codes
            # were once recorded as the countries, and the next visit looked like a changed form): close it first, and
            # read the list this button opens.
            if page.locator("[role=listbox]:visible").count():
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            btn.scroll_into_view_if_needed(timeout=w.T)
            btn.click(timeout=w.T)
            own = btn.get_attribute("aria-controls") or ""
            box = page.locator(f"[id='{own}']") if own and page.locator(f"[id='{own}']").count() else page.locator("[role=listbox]:visible").last
            opts = box.locator("[role=option]")
            opts.first.wait_for(state="visible", timeout=w.T)
            texts = [t.strip() for t in opts.all_inner_texts() if t.strip() and t.strip() != "Select One"]
            page.keyboard.press("Escape")
            try:
                box.wait_for(state="hidden", timeout=2000)
            except PWTimeout:
                page.wait_for_timeout(200)
            return texts
        except PWTimeout:
            page.keyboard.press("Escape")
            return []

    def get_schema(self, ref: JobRef, page: Any | None = None, answers: Callable[[FormSchema], dict[str, Any]] | None = None) -> FormSchema:
        """Walk the application page by page up to Review, filling as we go so that
        conditional questions appear. "Save and Continue" stores a draft; nothing is submitted."""
        if page is None or answers is None:
            raise DriverError("Workday reconnaissance needs a signed-in page and an answer callback")
        self.open_application(page, ref)
        steps = self._steps(page)
        schema = FormSchema(ats=self.ats, tenant=ref.tenant, job_ref=ref.job_id, url=f"{self.job_url(ref)}/apply", requires_login=True, source="walk",
                            title=_a(page, "jobTitleHeading").first.inner_text().strip() if _a(page, "jobTitleHeading").count() else "")
        idx = 0
        for _ in range(12):
            title = self._page_title(page)
            if re.search(r"^review$", title, re.I) or page.get_by_role("button", name=re.compile(r"^submit$", re.I)).count():
                break
            if re.search(r"create account|sign in", title, re.I):
                raise NeedsHuman("not signed in", kind="login", url=page.url)
            schema.pages.append(title or f"Page {idx + 1}")
            # conditional questions: fill, re-read, fill again until the page stops growing
            known: dict[str, Question] = {}
            for _round in range(4):
                qs = self.live_questions(page, idx)
                fresh = [q for q in qs if q.id not in known]
                if not fresh:
                    break
                for q in fresh:
                    known[q.id] = q
                partial = FormSchema(ats=self.ats, tenant=ref.tenant, questions=fresh)
                fill = answers(partial)
                # Reading goes on past a field the driver cannot work: it is noted, and the form says at "Save and
                # Continue" whether it matters. (One date box used to end the whole reading with nothing to show.)
                for q, why in self.fill_page(page, partial, idx, fill, tolerant=True):
                    schema.extra.setdefault("walk_issues", []).append({"page": idx, "label": q.label[:120], "why": why[:200]})
                for qid in self._kept:      # rows left as the site holds them: the draft shows what is there
                    try:
                        schema.extra.setdefault("held", {})[qid] = page.locator(f"[id='{qid}']").first.input_value(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                page.wait_for_timeout(800)
            schema.questions.extend(known.values())
            if not known and idx == 0:
                # the first step of an application always asks something: nothing read means the page was not read
                raise DriverError("the application form opened but its fields could not be read", page=idx, seen=page.url)
            if not self.next_page(page):
                errs = self.form_errors(page)
                # Unanswered required questions stop the walk here; the draft lists them as unresolved.
                schema.extra["stopped_at"] = {"page": idx, "errors": errs[:10]}
                break
            idx += 1
        schema.extra["steps"] = steps
        return schema

    # --- fill ------------------------------------------------------------------------

    def _rows_as_they_are(self, page: Page, todo: list[Question], answers: dict[str, Any]) -> set[str]:
        """Several rows of the same question (the websites of "My Experience", carried over from the last application):
        what counts is which entries are there, not which row holds which. When the rows already hold exactly the wanted
        entries they are left alone - retyping them in another order makes two rows equal for a moment, and the form
        answers "You can't add duplicate website URLs" and stays on the step. When they differ, the rows are emptied
        first, so that no entry meets its own copy. Returns the ids that need no filling."""
        norm = lambda v: str(v or "").strip().rstrip("/").lower()  # noqa: E731
        groups: dict[str, list[Question]] = {}
        for q in todo:      # rows are numbered in their ids: webAddress-4--url, webAddress-5--url
            if q.type == "text" and re.search(r"-\d+--", q.id) and answers.get(q.id) not in (None, "", []):
                groups.setdefault(re.sub(r"-\d+--", "-#--", q.id), []).append(q)
        settled: set[str] = set()
        for qs in groups.values():
            if len(qs) < 2:
                continue
            try:
                have = [norm(page.locator(f"[id='{q.id}']").first.input_value(timeout=3000)) for q in qs]
            except Exception:  # noqa: BLE001 - not plain text boxes: filled one by one as before
                continue
            want = [norm(answers[q.id]) for q in qs]
            if sorted(have) == sorted(want):
                settled.update(q.id for q in qs)
            elif len(set(want)) < len(want):
                # The answers cannot tell the rows apart (one answer for "URL", three rows): rows that hold something are
                # the applicant's own entries from last time and stay; an empty row gets an entry that is not there yet.
                spare = [v for v in dict.fromkeys(str(answers[q.id]) for q in qs) if norm(v) not in have]
                for q, h in zip(qs, have):
                    if h or not spare:
                        settled.add(q.id)
                    else:
                        answers[q.id] = spare.pop(0)
            elif any(have):
                for q in qs:
                    try:
                        page.locator(f"[id='{q.id}']").first.fill("", timeout=w.T)
                    except PWTimeout:
                        pass
        return settled

    def fill_page(self, page: Page, schema: FormSchema, page_index: int, answers: dict[str, Any], tolerant: bool = False) -> list[tuple[Question, str]]:
        """Fill the page's questions. ``tolerant`` (reading a form): a field that cannot be worked is returned with the
        reason instead of ending everything; otherwise it raises, as filling an approved draft must."""
        todo = [q for q in schema.questions
                if not (q.page != page_index and schema.source != "api" and len({x.page for x in schema.questions}) > 1) and answers.get(q.id) not in (None, "", [])]
        settled = self._rows_as_they_are(page, todo, answers)
        self._kept = sorted(settled)
        failed: list[tuple[Question, str]] = []
        for q in todo:
            if q.id in settled:
                continue
            val = answers.get(q.id)
            try:
                with timing.span("driver", "field", label=q.label[:60], type=q.type, page=page_index):
                    self._fill_one(page, q, val)
            except DriverError as e:
                if tolerant:
                    failed.append((q, str(e)))
                    continue
                e.question, e.page = e.question or q.label, page_index
                raise
            except PWTimeout as e:
                if tolerant:
                    failed.append((q, f"timeout operating field: {str(e)[:160]}"))
                    page.keyboard.press("Escape")
                    continue
                raise DriverError(f"timeout operating field: {str(e)[:160]}", page=page_index, question=q.label, expected=str(val)[:200]) from e
        return failed

    def _fill_one(self, page: Page, q: Question, val: Any) -> None:
        if q.id == "file::resume":
            self._upload(page, val if isinstance(val, list) else [val])
            return
        if q.id.startswith("checks::"):
            wanted = [str(v).strip().lower() for v in (val if isinstance(val, list) else re.split(r"\s*[;\n]\s*", str(val)))]
            # the legend's text runs its lines together ("seeking?(You may ...)"): the first line is enough to find it
            head = re.split(r"[(\n]", q.label)[0].strip()[:60]
            grp = page.locator("fieldset").filter(has=page.locator("legend", has_text=head)).first
            boxes = grp.locator("input[type=checkbox]")
            if boxes.count() == 0:
                raise DriverError("field not found on page", question=q.label, expected=q.id)
            names = boxes.evaluate_all("(els) => els.map((b) => ((b.labels && b.labels[0] && b.labels[0].innerText) || '').trim().toLowerCase())")
            if not any(n in wanted for n in names):
                raise DriverError("none of the choices is on the form", question=q.label, expected="; ".join(wanted), seen="; ".join(names))
            for i, n in enumerate(names):
                w.set_checkbox(boxes.nth(i), n in wanted)
            return
        if q.id.startswith("radio::"):
            grp = page.locator("fieldset").filter(has=page.locator("legend", has_text=q.label[:60])).first
            grp.locator("label").filter(has_text=re.compile(rf"^\s*{re.escape(str(val))}\s*$")).first.click(timeout=w.T)
            return
        loc = page.locator(f"[id='{q.id}']").first
        if loc.count() == 0:
            raise DriverError("field not found on page", question=q.label, expected=q.id)
        if q.locator.get("prompt"):
            cur = loc.locator("xpath=ancestor::*[@data-automation-id='multiSelectContainer' or @data-automation-id='formField'][1]").inner_text()
            path = [s.strip() for s in str(val).split(">")]
            if path[-1].lower() in cur.lower():
                return
            w.workday_prompt(page, loc, path)
            return
        tag = loc.evaluate("(e) => e.tagName.toLowerCase()")
        if tag == "button":
            if w.values_equal(val, loc.inner_text().strip()):
                return
            w.workday_listbox(page, loc, str(val))
            page.wait_for_timeout(500)  # dependent questions render after a choice
        elif q.type == "checkbox":
            w.set_checkbox(loc, bool(val))
        elif q.type == "date":
            w.workday_date(page, loc, str(val))
        else:
            if w.values_equal(val, loc.input_value()):
                return
            w.set_text(loc, str(val))

    def _upload(self, page: Page, paths: list[str]) -> None:
        """Replace the Resume/CV attachments with exactly ``paths``."""
        want = {Path(p).name for p in paths}
        for _ in range(8):  # delete attachments that should not be there (old résumé, old cover letter)
            dels = page.locator("button[aria-label^='Delete ']")
            victim = None
            for i in range(dels.count()):
                name = (dels.nth(i).get_attribute("aria-label") or "")[7:]
                if re.search(r"\.(pdf|docx?|txt|rtf)$", name, re.I) and name not in want:
                    victim = dels.nth(i)
                    break
            if victim is None:
                break
            victim.click(timeout=w.T)
            page.wait_for_timeout(1200)
        have = {(b.get_attribute("aria-label") or "")[7:] for b in page.locator("button[aria-label^='Delete ']").all()}
        todo = [p for p in paths if Path(p).name not in have]
        if todo:
            inp = page.locator("input[type=file]").first
            w.upload(inp, todo)
            for _ in range(30):
                page.wait_for_timeout(700)
                have = {(b.get_attribute("aria-label") or "")[7:] for b in page.locator("button[aria-label^='Delete ']").all()}
                if want <= have:
                    return
            raise DriverError("upload did not complete", expected=", ".join(sorted(want)), seen=", ".join(sorted(have)))

    def next_page(self, page: Page) -> bool:
        before = self._page_title(page)
        btn = page.get_by_role("button", name=re.compile(r"^(save and continue|next)$", re.I)).first
        if btn.count() == 0:
            return False
        btn.click(timeout=w.T)
        for _ in range(30):
            page.wait_for_timeout(500)
            if self.form_errors(page):
                return False
            if self._page_title(page) != before:
                self._wait_page(page)
                return True
        return False

    def form_errors(self, page: Page) -> list[str]:
        box = page.locator("[data-automation-id='errorHeading'], [data-automation-id='errorBanner'], [role=alert]:visible")
        if box.count() == 0:
            return []
        txt = page.locator("[data-automation-id='errorBanner'], [role=alert]:visible, [data-automation-id='inputAlert']").all_inner_texts()
        # an alert is how the page announces anything, good news included ("Resume.pdf successfully uploaded"): that is no error
        good = re.compile(r"success(fully)?|uploaded|saved", re.I)
        bad = re.compile(r"error|required|invalid|must|cannot|can't|failed|not (valid|allowed)", re.I)
        return [t.strip()[:300] for t in txt if t.strip() and (bad.search(t) or not good.search(t))][:20]

    def read_back(self, page: Page, schema: FormSchema, page_index: int | None = None) -> dict[str, Any]:
        """On the Review page everything is rendered as text: match by question label."""
        body = page.inner_text("main") if page.locator("main").count() else page.inner_text("body")
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        out: dict[str, Any] = {}
        for q in schema.questions:
            if q.type == "file":
                names = re.findall(r"[^\n/\\]+\.(?:pdf|docx?|txt|rtf)\b", body, re.I)
                out[q.id] = "|".join(dict.fromkeys(n.strip() for n in names))
                continue
            lab = q.label.rstrip("*").strip()
            for i, ln in enumerate(lines[:-1]):
                if ln.rstrip("*").strip() == lab:
                    out[q.id] = lines[i + 1]
                    break
        return out

    def submit(self, page: Page) -> None:
        page.get_by_role("button", name=re.compile(r"^submit$", re.I)).first.click(timeout=w.T)

    def confirmation(self, page: Page) -> dict[str, Any] | None:
        try:
            page.wait_for_function(
                "() => /jobTasks\\/completed|userHome/.test(location.href) || /application (has been )?submitted|thank you for applying|congratulations/i.test(document.body.innerText)",
                timeout=30000,
            )
        except PWTimeout:
            return None
        page.wait_for_timeout(1500)
        return {"url": page.url, "text": w.visible_text(page, 1500)}

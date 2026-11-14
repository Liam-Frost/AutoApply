"""A real Playwright driver for the local fixture form (tests/fixtures/form.html)."""

import re
from pathlib import Path

from autoapply.ats import widgets as w
from autoapply.ats.base import FormSchema, JobRef, PasswordPolicy, Question

FORM = Path(__file__).parent / "fixtures" / "form.html"


class FixtureDriver:
    ats = "fixture"
    requires_login = False
    password_policy = PasswordPolicy()

    def __init__(self):
        self.form_path = FORM
        self.corrupt = None  # question id whose value the "site" silently changes after fill
        self.submits = 0
        self.break_field = None  # question id the driver cannot handle (raises DriverError)
        self.extra = []  # questions the "site" added after the first reconnaissance

    def detect(self, url):
        return JobRef("fixture", "local", "1", url, "local") if "fixture" in url else None

    def get_schema(self, ref, page=None, answers=None):
        qs = [
            Question("first_name", "First Name", "text", True),
            Question("email", "Email", "text", True),
            Question("auth", "Are you legally authorized to work in Canada?", "select", True, ["Yes", "No"]),
            Question("sponsor", "Will you require sponsorship?", "select", True, ["Yes", "No"]),
            Question("resume", "Resume/CV", "file", True),
            Question("consent", "I agree to the privacy policy", "checkbox", False),
        ]
        return FormSchema(ats="fixture", tenant="local", job_ref="1", url=FORM.as_uri(), pages=["Application"], questions=qs + list(self.extra))

    def open_application(self, page, ref):
        page.goto(self.form_path.as_uri())

    def live_questions(self, page, i):
        out = []
        for c in w.describe_inputs(page):
            t = {"email": "text"}.get(c["type"], c["type"])
            out.append(Question(c["id"], c["label"], t, c["required"], c["options"][1:] if c["type"] == "select" else []))
        return out

    def fill_page(self, page, schema, i, answers):
        for q in schema.questions:
            v = answers.get(q.id)
            if v in (None, "", []):
                continue
            if q.id == self.break_field:
                from autoapply.ats.base import DriverError

                raise DriverError("unexpected widget", page=i, question=q.label, expected="listbox button", seen="native select #auth")
            loc = page.locator(f"#{q.id}")
            if q.type == "file":
                w.upload(loc, [v])
            elif q.type == "select":
                w.select_native(loc, v)
            elif q.type == "checkbox":
                w.set_checkbox(loc, bool(v))
            else:
                w.set_text(loc, v)
        if self.corrupt:
            page.evaluate("(id) => { document.getElementById(id).value = 'tampered'; }", self.corrupt)

    def next_page(self, page):
        return False

    def read_back(self, page, schema, i=None):
        out = {}
        for q in schema.questions:
            loc = page.locator(f"#{q.id}")
            if q.type == "file":
                out[q.id] = loc.evaluate("(e) => e.files.length ? e.files[0].name : ''")
            elif q.type == "select":
                out[q.id] = loc.evaluate("(e) => e.selectedIndex > 0 ? e.selectedOptions[0].text : ''")
            elif q.type == "checkbox":
                out[q.id] = loc.is_checked()
            else:
                out[q.id] = loc.input_value()
        return out

    def submit(self, page):
        self.submits += 1
        page.get_by_role("button", name=re.compile("submit", re.I)).click()

    def confirmation(self, page):
        if "Thank you" in page.inner_text("body"):
            return {"url": page.url, "text": page.inner_text("body")}
        return None

    def form_errors(self, page):
        t = page.locator("#err").inner_text() if page.locator("#err").count() else ""
        return [t] if t else []

    def already_applied(self, page, ref):
        return False

    def is_logged_in(self, page, ref, navigate=True):
        return True

    def login(self, *a):
        pass

    def register(self, *a):
        return "ok"

    def login_url(self, ref):
        return ""


LABEL_TO_ID = {"First Name": "first_name", "Email": "email", "Are you legally authorized to work in Canada?": "auth", "Will you require sponsorship?": "sponsor",
               "I agree to the privacy policy": "consent"}


def keys_in(prompt: str) -> dict[str, str]:
    """{key the model is asked to answer under: the test form's question id}, read from the question list in an answers prompt.
    (The model is given short keys, k1 k2 ..., never the form's own identifiers.)"""
    import ast
    import re

    out = {}
    for ln in str(prompt).split("Questions to answer:")[-1].splitlines():
        m = re.match(r"- id=(\S+) \|.*?\| label=(.+?)(?: \| (?:options|help)=.*)?$", ln)
        if not m:
            continue
        try:
            label = ast.literal_eval(m.group(2))
        except (ValueError, SyntaxError):
            continue
        if label in LABEL_TO_ID:
            out[m.group(1)] = LABEL_TO_ID[label]
    return out

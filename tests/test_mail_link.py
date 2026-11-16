"""An e-mail that does not say which application it is about."""
from datetime import datetime, timezone


def _two_sent_applications(s):
    from autoapply.models import Application, Job, MailEvent
    ids = []
    for n, title in enumerate(("Software Dev Engineer Intern", "Applied Scientist Intern")):
        job = Job(source="manual", source_id=f"A{n}", company="Amazon", title=title, apply_url=f"https://www.amazon.jobs/en/jobs/{n}/apply", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="confirmed", submitted_at=datetime(2026, 11, 1 + n, tzinfo=timezone.utc))
        s.add(a)
        s.flush()
        ids.append(a.id)
    draft = Job(source="manual", source_id="A9", company="Amazon", title="Not sent yet", apply_url="https://www.amazon.jobs/en/jobs/9/apply", channel="employer site", jd_text="x" * 300)
    s.add(draft)
    s.flush()
    s.add(Application(job_id=draft.id, status="draft_ready"))
    s.add(MailEvent(message_id="m1", sender="noreply@amazon.com", subject="Action Required for your Amazon Application", category="assessment",
                    company_guess="Amazon", summary="online assessment within two weeks", received_at=datetime(2026, 11, 15, tzinfo=timezone.utc)))
    s.flush()
    return ids


def _card():
    from autoapply import notify

    notify.add_todo("mail_unmatched", "Action Required for your Amazon Application", body="x", ref="mail:m1", payload={"message_id": "m1", "category": "assessment"}, push=False)


def test_the_applicant_says_which_application_an_email_is_about(app_env):
    """The card offers the applications that were sent to that employer; choosing one puts the e-mail on it."""
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app as api
    from autoapply.models import Application, MailEvent, Todo

    with db.session() as s:
        first, second = _two_sent_applications(s)
    _card()
    c = TestClient(api)
    card = next(t for t in c.get("/api/todos").json() if t["kind"] == "mail_unmatched")
    assert card["category"] == "answer" and card["urgency"] != 3      # something to do, not a notice
    assert [x["id"] for x in card["candidates"]] == [second, first] and card["candidates_near"]      # sent ones only, the latest first
    assert c.post(f"/api/todos/{card['id']}/link", json={}).status_code == 400
    assert c.post(f"/api/todos/{card['id']}/link", json={"application_id": first}).json() == {"updated": 1}
    with db.session() as s:
        assert s.get(Application, first).status == "assessment" and s.get(Application, second).status == "confirmed"
        assert s.query(MailEvent).one().application_id == first
        assert s.query(Todo).filter_by(kind="mail_unmatched").one().status != "open"


def test_the_employers_site_says_which_application_it_is(app_env, monkeypatch):
    """Before the applicant is asked, the applicant page of the employer's site is read with the saved sign-in: the e-mail
    goes to the application the site shows as waiting for the assessment, and what the site says is kept with each."""
    from autoapply import browser, db, llm, sitestatus
    from autoapply.models import Application, Todo

    with db.session() as s:
        first, second = _two_sent_applications(s)
    _card()
    assert sitestatus.resolve("m1") == {"skipped": "no saved sign-in for this employer's site"}      # nothing saved: the site is not opened
    monkeypatch.setattr(browser, "load_state", lambda key: {"cookies": [{"name": "s"}]})
    opened = []

    def site(key, start, run_dir):
        opened.append((key, start))
        return {"signed_in": True, "notes": "", "applications": [
            {"title": "Software Dev Engineer Intern", "job_id": "A0", "status": "Application submitted", "date": ""},
            {"title": "Applied Scientist Intern", "job_id": "A1", "status": "Assessment pending", "date": "Nov 15"}]}

    monkeypatch.setattr(sitestatus, "read", site)
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **k: {"application_ids": [second, 999], "reason": "the second one waits for an assessment"})
    out = sitestatus.resolve("m1")
    assert out["linked"] == [second] and opened == [("generic:www.amazon.jobs", "https://www.amazon.jobs/")]      # one visit for the site, not one per application
    with db.session() as s:
        assert s.get(Application, second).status == "assessment" and s.get(Application, first).status == "confirmed"
        assert s.get(Application, second).evidence["site_status"]["text"] == "Assessment pending"
        assert s.get(Application, first).evidence["site_status"]["text"] == "Application submitted"
        assert s.query(Todo).filter_by(kind="mail_unmatched").one().status != "open"
    assert sitestatus.resolve("m1") == {"skipped": "already linked"}


def test_a_site_that_does_not_settle_it_leaves_the_card_with_what_it_shows(app_env, monkeypatch):
    from autoapply import browser, db, llm, sitestatus
    from autoapply.models import Todo

    with db.session() as s:
        _two_sent_applications(s)
    _card()
    monkeypatch.setattr(browser, "load_state", lambda key: {"cookies": [{"name": "s"}]})
    monkeypatch.setattr(sitestatus, "read", lambda *a: {"signed_in": True, "notes": "", "applications": [{"title": "Software Dev Engineer Intern", "job_id": "", "status": "Under review", "date": ""}]})
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **k: {"application_ids": [], "reason": "both look the same"})
    assert sitestatus.resolve("m1")["linked"] == []
    with db.session() as s:
        t = s.query(Todo).filter_by(kind="mail_unmatched").one()
        assert t.status == "open" and t.payload["site"] == ["Software Dev Engineer Intern：Under review"]


def test_the_visit_to_the_site_only_reads(app_env, tmp_path):
    """On the applicant page the agent may look and move about the site; it is refused anything that changes an application."""
    import pytest
    from playwright.sync_api import sync_playwright

    from autoapply import sitestatus

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body='<main><h1>My applications</h1><p>SDE Intern - Assessment pending</p>'
                                               '<button id="w" onclick="document.title = \'gone\'">Withdraw application</button><button>Start assessment</button><a href="/more">Details</a></main>'))
        page.goto("https://www.amazon.jobs/applicant")
        tools = {t.name: t for t in sitestatus._tools(page, tmp_path, {}, "amazon.jobs")}
        assert set(tools) == {"read_page", "screenshot", "click", "goto", "report"}      # no filling, no uploading, no account tools
        for kw in ({"selector": "#w"}, {"text": "Start assessment"}):
            with pytest.raises(PermissionError):
                tools["click"].fn(**kw)
        assert page.title() != "gone"
        with pytest.raises(PermissionError):
            tools["goto"].fn(url="https://evil.example/")
        assert "amazon.jobs/account" in tools["goto"].fn(url="https://account.amazon.jobs/account")
        b.close()


def test_an_account_offered_only_after_the_submission_is_taken_up_there(app_env, tmp_path, monkeypatch):
    """A site that says "you can log in after submitting": the page that confirms the application offers the account.
    It is signed in to (or created) there - unless the account is already known to work, or the page offers none."""
    from playwright.sync_api import sync_playwright

    from autoapply import auth, db, executor, generic
    from autoapply.ats.base import JobRef

    db.set_setting("repair.enabled", True)
    ref = JobRef("generic", "www.careers.test", "", "https://www.careers.test/jobs/1", "www.careers.test")
    calls, steps = [], []
    monkeypatch.setattr(generic, "account_after_submit", lambda page, r, run_dir: calls.append(r.tenant_key) or {"ok": True, "notes": "signed in"})
    step = lambda op, **kw: steps.append(op)  # noqa: E731
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content("<main><h1>Thanks for applying</h1><p>Your application has been received.</p><h2>Sign up for a Career Profile</h2><a href='#'>Log in</a></main>")
        executor._finish_account(page, ref, step, tmp_path)
        assert calls == [ref.tenant_key] and steps == ["account_after_submit"]
        auth.upsert_account(ref.tenant_key, ats="generic", host=ref.host, status="ok")
        executor._finish_account(page, ref, step, tmp_path)      # an account that works needs nothing
        assert len(calls) == 1
        b.close()
    assert generic.ACCOUNT_OFFER.search("Already have a Career Profile? Log in") and not generic.ACCOUNT_OFFER.search("Thanks for applying. We will be in touch.")


def test_a_control_that_shows_less_than_it_holds_is_taken_from_the_agent_that_chose_it():
    """A phone-code list shows "+1" for "+1 / Canada". After the agent chose the approved entry there, "+1" is not a difference;
    without the agent's word, or with something that is not part of the approved entry, it still is."""
    from autoapply.executor import _not_vouched
    from autoapply.ats.base import FormSchema, Question

    schema = FormSchema(ats="generic", url="https://x", pages=["p"], questions=[
        Question(id="code", label="Code", type="select", options=["+1 / United States", "+1 / Canada"]), Question(id="city", label="City", type="text"),
        Question(id="name", label="Full name", type="text")])

    code = {"id": "code", "label": "Code", "expected": "+1\nCanada", "actual": "+1"}
    assert _not_vouched([code], ["code"], schema) == []
    assert _not_vouched([code], [], schema) == [code]
    wrong = {**code, "actual": "+44"}
    assert _not_vouched([wrong], ["code"], schema) == [wrong]
    empty = {**code, "actual": ""}
    assert _not_vouched([empty], ["code"], schema) == [empty]
    plain = {"id": "city", "label": "City", "expected": "Vancouver", "actual": "Van"}
    assert _not_vouched([plain], ["city"], schema) == [plain]
    # a text box that holds a part of the approved text holds something else, whoever says it was fixed
    name = {"id": "name", "label": "Full name", "expected": "John Smith", "actual": "John"}
    assert _not_vouched([name], ["name"], schema) == [name]


def test_nothing_the_server_starts_opens_a_console_window(monkeypatch):
    """On Windows every child process gets CREATE_NO_WINDOW, unless the caller asked for a console of its own."""
    import subprocess
    import sys

    import pytest

    if sys.platform != "win32":
        pytest.skip("console windows are a Windows matter")
    from autoapply import quiet

    quiet.install()
    seen = {}
    real = subprocess.Popen.__init__.__closure__      # the patched __init__ wraps the real one
    assert real is not None
    p = subprocess.Popen([sys.executable, "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"], stdout=subprocess.PIPE, text=True)
    seen["hwnd"] = p.communicate(timeout=30)[0].strip()
    assert seen["hwnd"] == "0"      # the child has no console window at all
    out = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "ok"


def test_the_interface_uses_its_own_drop_down_everywhere():
    """A browser's own <select> looks like nothing else in the interface; the project has <AaSelect> for it."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    native = [f"{p.relative_to(src).as_posix()}:{n}" for p in src.rglob("*.vue") if p.name != "Select.vue"
              for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if "<select" in line]
    assert native == []

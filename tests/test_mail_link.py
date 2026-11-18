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
    from autoapply import browser, db, sitestatus
    from autoapply.models import Application, Todo

    with db.session() as s:
        first, second = _two_sent_applications(s)
    _card()
    assert sitestatus.resolve("m1") == {"skipped": "no saved sign-in for this employer's site"}      # nothing saved: the site is not opened
    monkeypatch.setattr(browser, "load_state", lambda key: {"cookies": [{"name": "s"}]})
    opened = []

    def site(key, start, folder, question):
        opened.append((key, start))
        assert "Action Required for your Amazon Application" in question and f"id={second} | Applied Scientist Intern" in question
        return {"signed_in": True, "about": [second, 999], "reason": "the second one waits for an assessment", "applications": [
            {"title": "Software Dev Engineer Intern", "job_id": "A0", "status": "Application submitted", "date": ""},
            {"title": "Applied Scientist Intern", "job_id": "A1", "status": "Assessment pending", "date": "Nov 15"}]}

    monkeypatch.setattr(sitestatus, "read", site)
    out = sitestatus.resolve("m1")
    assert out["linked"] == [second] and opened == [("generic:www.amazon.jobs", "https://www.amazon.jobs/")]      # one visit for the site, not one per application
    with db.session() as s:
        assert s.get(Application, second).status == "assessment" and s.get(Application, first).status == "confirmed"
        assert s.get(Application, second).evidence["site_status"]["text"] == "Assessment pending"
        assert s.get(Application, first).evidence["site_status"]["text"] == "Application submitted"
        assert s.query(Todo).filter_by(kind="mail_unmatched").one().status != "open"
    assert sitestatus.resolve("m1") == {"skipped": "already linked"}


def test_a_site_that_does_not_settle_it_leaves_the_card_with_what_it_shows(app_env, monkeypatch):
    from autoapply import browser, db, sitestatus
    from autoapply.models import Todo

    with db.session() as s:
        _two_sent_applications(s)
    _card()
    monkeypatch.setattr(browser, "load_state", lambda key: {"cookies": [{"name": "s"}]})
    monkeypatch.setattr(sitestatus, "read", lambda *a: {"signed_in": True, "about": [], "reason": "both look the same",
                                                        "applications": [{"title": "Software Dev Engineer Intern", "job_id": "", "status": "Under review", "date": ""}]})
    assert sitestatus.resolve("m1")["linked"] == []
    with db.session() as s:
        t = s.query(Todo).filter_by(kind="mail_unmatched").one()
        assert t.status == "open" and t.payload["site"] == ["Software Dev Engineer Intern：Under review"]


def test_the_visit_to_the_site_only_reads(app_env, tmp_path, monkeypatch):
    """The agent that reads the applicant page is given the tools that look and move about the site, and none that
    type, choose, upload or run a script; what it reports is what resolve gets."""
    from contextlib import contextmanager

    from autoapply import browser, llm, sitestatus

    page = tmp_path / "applications.html"
    page.write_text("<main><h1>My applications</h1><p>SDE Intern - Assessment pending</p><button>Withdraw application</button></main>", encoding="utf-8")
    real = browser.open_page

    @contextmanager
    def open_page(site, **kw):
        with real(None) as p:
            yield p

    monkeypatch.setattr(browser, "open_page", open_page)
    given = {}

    def agent(goal, tools, *, system, kind="", on_step=None, budget=None):
        given.update(tools={t.name for t in tools}, goal=goal, kind=kind, read={t.name: t for t in tools}["read"].fn())
        {t.name: t for t in tools}["report"].fn(signed_in=True, about=[7], reason="it waits for an assessment",
                                                applications=[{"title": "SDE Intern", "status": "Assessment pending"}, {"status": "no title: not an application"}])

    monkeypatch.setattr(llm, "agent", agent)
    out = sitestatus.read("generic:www.amazon.jobs", page.as_uri(), tmp_path / "visit", "The e-mail: ...")
    assert given["tools"] == {*sitestatus.LOOKING, "report"} and not given["tools"] & {"type", "choose", "upload", "script"} and given["kind"] == "site_status"
    assert "Assessment pending" in given["read"] and "The e-mail: ..." in given["goal"]
    assert out == {"signed_in": True, "about": [7], "reason": "it waits for an assessment", "applications": [{"title": "SDE Intern", "job_id": "", "status": "Assessment pending", "date": ""}]}


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

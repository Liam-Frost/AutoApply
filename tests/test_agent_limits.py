"""The few things that are fixed for the application agent whatever it decides (agent/apply.md, "What is fixed").

Nothing here is about a form or a button: what a page is and which control does what is the agent's to judge. These
are the limits the program itself holds: a password never reaches the agent, a run that may not send is told so
by its own tools, an application is not called sent without its confirmation.
"""
from __future__ import annotations

import json

import pytest

from autoapply import db

LOGIN = """<!doctype html><title>Sign in</title>
<form onsubmit="window.sent = [user.value, pw.value]; return false">
<label for="user">E-mail</label><input id="user" type="text">
<label for="pw">Password</label><input id="pw" type="password">
<label for="pw2">Verify password</label><input id="pw2" type="password">
<button id="go" type="submit">Create account</button></form>"""


@pytest.fixture()
def desk(app_env, tmp_path):
    from autoapply import browser
    from autoapply.agent.hands import Hands
    from autoapply.agent.run import Desk

    form = tmp_path / "login.html"
    form.write_text(LOGIN, encoding="utf-8")
    with browser.open_page(None) as page:
        page.goto(form.as_uri())
        hands = Hands(page)

        def make(mode="auto"):
            return Desk(tmp_path / "app", hands, site="generic:careers.acme.example", mode=mode, login="alex@example.com")

        yield type("D", (), {"page": page, "hands": hands, "make": staticmethod(make), "folder": tmp_path / "app"})()


def _show(page, tmp_path, html):
    """Put a page in the window (by a file: both browsers can open one)."""
    import uuid

    f = tmp_path / f"{uuid.uuid4().hex}.html"
    f.write_text(html, encoding="utf-8")
    page.goto(f.as_uri())


def _ref(hands, pattern):
    import re

    m = re.search(r"\[(\d+)\] " + pattern, hands.controls())
    assert m, pattern
    return m.group(1)


def test_a_password_is_typed_by_the_program_and_is_nowhere_the_agent_can_read(desk):
    from autoapply import auth, secrets

    d = desk.make()
    pw, pw2, go = _ref(desk.hands, 'password "Password"'), _ref(desk.hands, 'password "Verify password"'), _ref(desk.hands, 'button "Create account"')
    # the agent's own typing does not go into a password box - by its number, or by focus
    with pytest.raises(PermissionError):
        desk.hands.type("hunter2", ref=pw)
    desk.hands.click(ref=pw)
    with pytest.raises(PermissionError):
        desk.hands.type("hunter2")
    assert desk.hands.type("", ref=pw).startswith("typed 0")                    # emptying one is not typing a password
    with pytest.raises(PermissionError):
        d.type_password(_ref(desk.hands, 'text "E-mail"'))                      # and the program types it into a password box only
    # registering: made up to the rules the agent read on the page, stored before it is sent, typed twice the same
    said = d.type_password(pw, new=True, length=14, symbols="!#")
    said += d.type_password(pw2, then_click=go)
    stored = secrets.get_password("generic:careers.acme.example")
    assert stored and len(stored) == 14 and all(c.isalnum() or c in "!#" for c in stored)
    assert desk.page.evaluate("window.sent") == ["", stored] and auth.account("generic:careers.acme.example")["has_password"]
    # what the tools said, what the journal holds, what the page still shows: none of it has the password
    written = (desk.folder / "journal.jsonl").read_text(encoding="utf-8")
    assert stored not in said and stored not in written and stored not in desk.hands.controls() and stored not in desk.hands.read()
    assert desk.page.evaluate("[...document.querySelectorAll('input[type=password]')].map((e) => e.value)") == ["", ""]      # the page did not move on: the boxes were emptied
    assert "filled (hidden)" not in desk.hands.controls()


def test_what_the_program_typed_is_in_no_answer_of_the_agents_tools(desk):
    """The agent has the whole page in its hands - a script, the list of controls, a picture - and a password typed into
    a box is on that page until the form is sent. The tools it is given answer without it."""
    from autoapply import secrets

    d = desk.make()
    tools = {t.name: t.fn for t in d.guard(desk.hands.tools() + d.tools())}
    pw = _ref(desk.hands, 'password "Password"')
    tools["type_password"](ref=pw, new=True, length=14, symbols="!#")      # the first of two boxes: nothing is sent yet, the box stays filled
    stored = secrets.get_password("generic:careers.acme.example")
    assert stored and desk.page.evaluate("document.getElementById('pw').value") == stored
    said = tools["script"](code="() => document.getElementById('pw').value")
    assert stored not in said and "(hidden)" in said
    # a page that shows the password in clear ("show password"): the box is still not one the agent reads, or types into
    desk.page.evaluate("document.getElementById('pw').type = 'text'")
    listed = tools["controls"]()
    assert stored not in listed and "filled (hidden)" in listed
    with pytest.raises(PermissionError):
        tools["type"](text="hunter2", ref=pw)
    # a picture is taken with that box covered, and the page is as it was afterwards
    covered = "getComputedStyle(document.getElementById('pw')).webkitTextSecurity"
    seen, real = [], desk.page.screenshot
    desk.page.screenshot = lambda **kw: (seen.append(desk.page.evaluate(covered)), real(**kw))[1]
    try:
        tools["look"]()
    finally:
        desk.page.screenshot = real
    assert seen == ["disc"] and desk.page.evaluate(covered) != "disc"
    # an error that carries it is told without it, and the journal holds nothing of it
    with pytest.raises(Exception) as e:  # noqa: PT011 - whatever the browser raises
        tools["script"](code="() => { throw new Error(document.getElementById('pw').value) }")
    assert stored not in str(e.value)
    d.step({"tool": "script", "input": {"code": f"'{stored}'"}, "ok": True, "output": f"it says {stored}"})      # (whatever reached the journal some other way)
    assert stored not in (desk.folder / "journal.jsonl").read_text(encoding="utf-8")
    # the password stored for the site before this run is known to the guard as well
    d2 = desk.make()
    d2.guard([])
    assert stored in d2.hidden
    # a password with a quote or a backslash in it reads differently inside JSON - which is what a script's answer and
    # the journal are - and is taken out of that too; a box in a frame of the same site is covered like any other
    odd = 'p"a\\ss wörd'
    d2.hidden = {odd}
    assert odd not in d2.clean(json.dumps({"password": odd}, ensure_ascii=False)) and "wörd" not in d2.clean(json.dumps({"password": odd}, ensure_ascii=False))
    assert "ss w" not in d2.clean(json.dumps([odd]))
    d2.write("log", text=odd)
    assert "ss w" not in (desk.folder / "journal.jsonl").read_text(encoding="utf-8")
    desk.page.evaluate("""() => { const f = document.createElement('iframe'); document.body.appendChild(f);
        f.contentDocument.body.innerHTML = '<input id="inner" type="password" value="x">'; }""")
    inner = "getComputedStyle(document.querySelector('iframe').contentDocument.getElementById('inner')).webkitTextSecurity"
    desk.page.evaluate(d2._COVER)                                       # (seen as a password box: marked)
    desk.page.evaluate("document.querySelector('iframe').contentDocument.getElementById('inner').type = 'text'")
    assert d2._picture(lambda: desk.page.evaluate(inner)) == "disc" and desk.page.evaluate(inner) != "disc"


def test_a_run_that_may_not_send_is_told_so_and_a_run_that_may_writes_it_down_first(desk):
    for mode in ("prepare", "hand_over", "verify"):
        d = desk.make(mode)
        assert "does not send" in d.sending("Submit application")
    assert not (desk.folder / "journal.jsonl").exists() or '"sending"' not in (desk.folder / "journal.jsonl").read_text(encoding="utf-8")
    for mode in ("auto", "send"):
        d = desk.make(mode)
        assert d.sending("Submit application").startswith("noted")
    lines = [json.loads(ln) for ln in (desk.folder / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(ln["kind"], ln["button"]) for ln in lines] == [("sending", "Submit application")] * 2


def test_an_application_is_not_reported_as_sent_without_its_confirmation(desk):
    d = desk.make()
    with pytest.raises(ValueError):
        d.report("submitted", "It went out.")
    with pytest.raises(ValueError):
        d.report("submitted", "It went out.", confirmation={"words": "Your profile was saved", "url": "https://x.example/profile"})      # nothing ties it to the posting
    with pytest.raises(ValueError):
        d.report("done", "Finished.")
    assert d.reported is None
    d.report("submitted", "It went out.", confirmation={"words": "Thank you, your application was received", "url": "https://x.example/done", "ties_to_posting": "reference AC-1 for Backend Intern"})
    assert d.reported["sent"] is True and json.loads((desk.folder / "record.json").read_text(encoding="utf-8"))["outcome"] == "submitted"
    # the page as it stood then is kept beside the words
    assert (desk.folder / "confirmation.png").read_bytes()[:4] == b"\x89PNG" and d.reported["shot"].endswith("confirmation.png")


def test_a_question_to_the_applicant_stays_with_this_application(desk):
    """An answer about this job ("I can start in January") is not a fact about the applicant from then on: what is
    asked says which it is, and nothing is written to the profile by the asking."""
    from autoapply import knowledge

    before = knowledge.read("profile")
    d = desk.make()
    said = d.ask("When can you start?", about="job", why="step 2, required")
    d.ask("What is your legal first name?", about="applicant", options=["Alex", "Alexander"])
    assert "no answer yet" in said and [q["about"] for q in d.asked] == ["job", "applicant"] and d.asked[1]["options"] == ["Alex", "Alexander"]
    assert knowledge.read("profile") == before
    # an answer on record is given back for the same question, whatever the spacing
    d2 = desk.make()
    d2.answers = {"When can  you start?": "2027-01-04"}
    assert "2027-01-04" in d2.ask("When can you start?") and d2.asked == []


def test_a_stored_password_is_typed_where_the_sites_sign_in_lives_and_nowhere_else(desk):
    """A page that only looks like the site's sign-in gets nothing: the agent decides what a page is, the program
    decides where a stored secret may go."""
    from autoapply import auth, secrets, sites

    key = "generic:careers.acme.example"
    auth.upsert_account(key, host="careers.acme.example", email="alex@example.com", password="the stored one", status="ok")
    d = desk.make()
    d.home = "careers.acme.example"
    pw = _ref(desk.hands, 'password "Password"')
    with pytest.raises(PermissionError, match="not where the password of this site belongs"):      # the test page is on no host at all
        d.type_password(pw)
    assert desk.page.evaluate("document.getElementById('pw').value") == ""
    # the site's own address, a subdomain of it, an address the applicant signed in on for it: these are home
    assert d._is_home("careers.acme.example") and d._is_home("login.careers.acme.example") and not d._is_home("careers.acme.example.evil.test") and not d._is_home("acme.example.co")
    sites.set_fact(key, "sign_in_hosts", ["sso.acme-login.example"])
    assert d._is_home("sso.acme-login.example")
    # an account being made somewhere is at home there from then on (the made-up password is that account's)
    d.type_password(pw, new=True)
    assert d._is_home(d._host()) and d._host() in sites.fact(key, "sign_in_hosts")
    assert secrets.get_password(key) != "the stored one"


def test_a_word_from_the_applicant_reaches_the_run_that_is_working(desk):
    """What the applicant says while the agent works comes with the answer to its next action - once, and not after the
    report: a word that comes that late is for the next run."""
    from autoapply.agent import run

    d = desk.make()
    tools = {t.name: t.fn for t in d.guard(desk.hands.tools() + d.tools())}
    assert "APPLICANT SAYS" not in tools["read"]()
    run.say(desk.folder, "Use my Vancouver address, not the Toronto one.")
    heard = tools["controls"]()
    assert "THE APPLICANT SAYS" in heard and "Use my Vancouver address" in heard
    assert "APPLICANT SAYS" not in tools["read"]() and d.words() == []                  # said once
    blocks = (run.say(desk.folder, "And skip the newsletter."), tools["look"]())[1]      # a picture's answer carries it as well
    assert any("skip the newsletter" in b.get("text", "") for b in blocks if isinstance(b, dict))
    run.say(desk.folder, "One more thing.")
    said = tools["report"](outcome="ready", summary="Everything is in.")
    assert "One more thing" not in said and d.words() == ["One more thing."]             # left for the next run
    lines = [json.loads(ln) for ln in (desk.folder / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [ln["text"] for ln in lines if ln["kind"] == "said"] == ["Use my Vancouver address, not the Toronto one.", "And skip the newsletter."]
    assert "THE APPLICANT SAID, while the run worked: Use my Vancouver" in run.journal_text(desk.folder)
    # a run that begins later has what was said in its brief: it does not hear it a second time
    assert desk.make().words() == []
    # ... counted from when its brief's words were read: one said after that, while the browser starts, is still heard
    from autoapply.agent.run import Desk

    late = Desk(desk.folder, desk.hands, site="generic:careers.acme.example", mode="auto", heard=2)
    assert late.words() == ["One more thing."]
    # an answer given by speaking closes the question it answers: the record does not ask it again
    d3 = desk.make()
    tools = {t.name: t.fn for t in d3.guard(desk.hands.tools() + d3.tools())}
    tools["ask"](question="When can you start?", about="job")
    run.say(desk.folder, "I can start on 4 January.")
    assert "call `answered`" in tools["read"]()
    assert "not one of the questions" in tools["answered"](question="What is your salary expectation?", answer="x")
    assert "closed" in tools["answered"](question="When can you start?", answer="2027-01-04")
    tools["report"](outcome="ready", summary="Everything is in.")
    assert d3.reported["asked"] == [] and d3.answers["When can you start?"] == "2027-01-04"


def test_a_resume_for_the_posting_is_written_when_the_agent_asks_and_the_applicants_setting_about_it_holds(desk, monkeypatch):
    """Whether an application is better with a résumé rewritten for the posting is the agent's to judge: it has a tool
    for it. The applicant's settings are theirs: switched off, none is written; and one written just now is looked at
    by them before it goes out, when they have set so."""
    from autoapply import tailor
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="manual", source_id="r1", company="Acme", title="Backend Intern", apply_url="https://careers.acme.example/jobs/1", jd_text="x" * 300, status="queued", online=1)
        s.add(j)
        s.flush()
        job_id = j.id
    made = []

    def make(job, *, instructions="", automatic=False):
        made.append(instructions)
        return {"id": 1, "name": "Alex_Resume_Acme.pdf", "path": str(desk.folder / "r.pdf"), "current": instructions != "worse", "tailor": {"problems": ["a number that is not in the original"] if instructions == "worse" else []}}

    monkeypatch.setattr(tailor, "make", make)
    d = desk.make("auto")
    d.job_id = job_id
    db.set_setting("tailor.mode", "off")
    assert "switched off" in d.tailor_resume() and made == []
    db.set_setting("tailor.mode", "select")
    monkeypatch.setattr(tailor, "base_doc", lambda: None)
    assert "no Word résumé" in d.tailor_resume() and made == []
    monkeypatch.setattr(tailor, "base_doc", lambda: {"id": 1, "name": "CV.docx", "path": "x"})
    assert "Nothing usable" in d.tailor_resume("worse") and "Alex_Resume_Acme.pdf" not in desk.hands.files and d.mode == "auto"
    db.set_setting("tailor.review", False)
    said = d.tailor_resume("lead with the backend work")
    assert "'Alex_Resume_Acme.pdf'" in said and desk.hands.files["Alex_Resume_Acme.pdf"] and d.mode == "auto" and "do not send" not in said
    db.set_setting("tailor.review", True)             # the applicant looks at a new one first: this run does not send
    said = d.tailor_resume()
    assert "do not send it in this run" in said and d.mode == "prepare" and "does not send" in d.sending("Submit")

def test_attachment_readback_survives_new_desk(desk, tmp_path):
    import hashlib
    path = tmp_path / "letter.pdf"
    path.write_bytes(b"attachment fixture")
    desk.hands.files[path.name] = str(path)
    _show(desk.page, tmp_path, '<div id="attachment">letter.pdf</div>')
    assert "Recorded" in desk.make().verify_attachment(path.name, "#attachment")
    entry = json.loads((desk.folder / "journal.jsonl").read_text("utf8").splitlines()[-1])
    assert entry["kind"] == "attachment_observed" and entry["local_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    _show(desk.page, tmp_path, '<input type="file" id="attachment">')
    assert "Unverified" in desk.make().verify_attachment(path.name, "#attachment")

def _answer_card(kind, **gives):
    """The applicant deals with the open card of this kind a moment from now, as they would on the to-do page."""
    import threading
    import time

    from autoapply.models import Todo, now

    def later():
        for _ in range(200):
            with db.session() as s:
                t = s.query(Todo).filter_by(kind=kind, status="open").first()
                if t is not None:
                    t.status, t.done_at, t.payload = gives.pop("status", "done"), now(), {**(t.payload or {}), **gives}
                    return
            time.sleep(0.05)

    threading.Thread(target=later, daemon=True).start()


def _carded(agent):
    from autoapply import notify

    agent.card = lambda kind, why, more: notify.add_todo(kind, "Acme", body=why, ref=f"application:1:{kind}", payload={"application_id": 1, "job_id": 1, **more})
    agent._idle = lambda seconds: __import__("time").sleep(0.05)
    return agent


def test_a_code_only_the_applicant_has_is_asked_for_while_the_run_waits_and_comes_back_to_the_agent(desk, monkeypatch):
    from autoapply import mailbox
    from autoapply.agent import run
    from autoapply.models import Todo

    agent = _carded(desk.make())
    # a mailbox that cannot be read does not end the run and does not send the applicant to a sign-in window
    monkeypatch.setattr(mailbox, "fetch", lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("timed out")))
    told = agent.mail(15)
    assert "ask_code" in told and "sign_in_by_hand" not in told and not agent.waiting
    # whatever words the agent finds for it, handing a sign-in over is not turned into something else
    names = {t.name for t in agent.tools()}
    assert {"ask_code", "wait_for_applicant", "change_browser", "sign_in_by_hand"} <= names

    _answer_card("code", code=" 482 913 ")
    got = agent.ask_code("六位数字，发到邮箱")
    assert "482913" in got and not agent.waiting and not agent.need
    with db.session() as s:
        card = s.query(Todo).filter_by(kind="code").one()
        assert card.status == "done" and "code" not in card.payload       # used once, not kept
    assert "482913" not in (desk.folder / "journal.jsonl").read_text(encoding="utf-8")
    agent.step({"tool": "ask_code", "input": {"what": "x"}, "ok": True, "output": got, "ms": 1})
    assert "482913" not in (desk.folder / "journal.jsonl").read_text(encoding="utf-8")

    # nobody there: the card is closed, and the run ends saying what kind of thing it stopped for
    monkeypatch.setattr(run, "WAIT_MINUTES", 0.004)
    assert "No code came" in agent.ask_code("发到手机") and agent.need == {"kind": "code", "why": "发到手机"}
    with db.session() as s:
        assert not s.query(Todo).filter_by(status="open").count()


def test_the_run_waits_for_what_the_applicant_does_on_their_phone_or_in_the_window(desk, monkeypatch):
    from autoapply import browser
    from autoapply.models import Todo

    agent = _carded(desk.make())
    _answer_card("confirm")
    assert "is done" in agent.wait_for_applicant("在手机上批准这次登录") and not agent.waiting
    with db.session() as s:
        assert s.query(Todo).filter_by(kind="confirm").one().payload["window"] is False
    # something to do in the window, and the window is hidden: nothing is waited for - the next run opens where they can see it
    monkeypatch.setattr(browser, "in_use", lambda: ("playwright", False))
    assert "hidden" in agent.wait_for_applicant("人机验证", window=True) and agent.need["kind"] == "window"
    # in a window they can see, the run waits there; a card they close ends the wait
    agent.need, agent.waiting = {}, ""
    monkeypatch.setattr(browser, "in_use", lambda: ("playwright", True))
    _answer_card("confirm", status="dismissed")
    assert "did not answer" in agent.wait_for_applicant("人机验证", window=True) and agent.need["kind"] == "window"


def test_the_agent_takes_an_application_to_the_other_browser_once(desk, monkeypatch):
    from autoapply import browser

    monkeypatch.setattr(browser, "in_use", lambda: ("playwright", False))
    agent = desk.make()
    db.set_setting("browser.nodriver_enabled", False)
    assert "switched off" in agent.change_browser("Access Forbidden") and not agent.other_browser
    db.set_setting("browser.nodriver_enabled", True)
    assert "ends here" in agent.change_browser("Access Forbidden") and agent.other_browser == "nodriver"
    again = desk.make()
    again.changed_browser = True          # the run that began after the change
    monkeypatch.setattr(browser, "in_use", lambda: ("nodriver", True))
    assert "both browsers" in again.change_browser("still forbidden") and not again.other_browser


SWALLOWED = """<!doctype html><title>Sign in</title>
<form id="f" onsubmit="window.sent = (window.sent || []).concat([[user.value, pw.value]]); document.title = 'Signed in'; return false">
<input id="user" type="text" aria-label="Login name" value="alex"><input id="pw" type="password" aria-label="Password">
<button id="go" type="submit">Login</button></form>
<script>/* the first two presses of the button are lost, as under a list the browser opened over the form */
let lost = %d; go.addEventListener('click', (e) => { if (lost-- > 0) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);</script>"""


def test_a_sign_in_whose_button_did_nothing_is_seen_through_by_the_program_and_never_sent_empty(desk, tmp_path):
    from autoapply import auth

    auth.upsert_account("generic:careers.acme.example", host="careers.acme.example", email="alex@example.com", password="s3cret-Pa55word", status="ok", created_by="user")
    d = desk.make()
    d._is_home = lambda host: True

    def page_with(lost):
        form = tmp_path / f"swallowed{lost}.html"
        form.write_text(SWALLOWED % lost, encoding="utf-8")
        desk.page.goto(form.as_uri())
        return _ref(desk.hands, 'password "Password"'), _ref(desk.hands, 'button "Login"')

    # the press was lost once: the program presses again, and the form goes out once, with the password in it
    pw, go = page_with(1)
    said = d.type_password(pw, then_click=go)
    assert "pressed again through the page" in said and desk.page.evaluate("() => window.sent") == [["alex", "s3cret-Pa55word"]]
    # lost every time the button is pressed: the form is sent directly - still once, still with the password
    pw, go = page_with(5)
    said = d.type_password(pw, then_click=go)
    assert "sent directly" in said and desk.page.evaluate("() => window.sent") == [["alex", "s3cret-Pa55word"]]
    # a page on which nothing sends it: the agent is told the box is empty again and that the form is not to be sent
    _show(desk.page, tmp_path, '<title>Sign in</title><input id="pw" type="password" aria-label="Password"><button id="go" type="button">Login</button>')
    pw, go = _ref(desk.hands, 'password "Password"'), _ref(desk.hands, 'button "Login"')
    said = d.type_password(pw, then_click=go)
    assert "NOT sent" in said and "emptied" in said and desk.page.evaluate("() => document.getElementById('pw').value") == ""

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

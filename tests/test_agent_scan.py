"""A portal the program cannot read by itself is given to the agent (agent/scan.py, sources/pdportal.py).

What is held here is the program's side of it: the postings the agent has collected go from the page to the program
without passing through the model, an applicant who was asked to sign in is not asked again by every scan, and a
sign-in that rings their phone is not started in the quiet hours. How the agent gets a page to give up its postings
is the agent's own business, and is not tested.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from autoapply import db

TEXT = "Job Title: {t}\nOrganization: Acme\nApplication Deadline: December 1, 2026 11:59 PM\nApplication Receipt Procedure: Online via system\nJob Description: Build things.\nAPPLICATION INFORMATION"
PORTAL = """<!doctype html><title>Co-op postings</title>
<form id="widgetSearch" onsubmit="return false"><input name="widget1Keyword"></form>
<table>__ROWS__</table>
<script>
  document.getElementById('widgetSearch').submit = () => {};
  window.texts = __TEXTS__;
</script>"""
ROW = """<tr><td><a href="#" onclick="openPosting({postingId: '%s'})">%s</a></td></tr>"""      # (not the markup the program's script was written for)
THEIRS = """async (known) => {
  const ids = [...document.querySelectorAll('[onclick*=postingId]')].map((e) => e.getAttribute('onclick').match(/\\d{5,7}/)[0]);
  return {ids, details: ids.filter((i) => !known.includes(i)).map((id) => ({id, text: window.texts[id]}))};
}"""


@pytest.fixture()
def portal(app_env, tmp_path, monkeypatch):
    from autoapply import browser, llm
    from autoapply.sources import pdportal

    posts = {"150001": "Backend Developer Co-op", "150002": "Data Engineer Co-op", "150003": "Firmware Co-op"}
    page = tmp_path / "postings.html"
    page.write_text(PORTAL.replace("__ROWS__", "".join(ROW % (i, t) for i, t in posts.items())).replace("__TEXTS__", json.dumps({i: TEXT.format(t=t) for i, t in posts.items()})), encoding="utf-8")
    db.set_setting("agent.pipeline", "agent")
    monkeypatch.setattr(pdportal, "POSTINGS", page.as_uri())
    monkeypatch.setattr(browser, "save_state", lambda *a, **k: None)
    seen = SimpleNamespace(runs=0, said=[], goal="", play=lambda tools: None)

    def agent(goal, tools, *, system, kind="", on_step=None, budget=None):      # (in place of the model: what it is given, and what a run of it does with its tools)
        seen.runs += 1
        seen.goal = goal
        seen.play({t.name: t.fn for t in tools})
        return SimpleNamespace(stopped="end_turn")

    monkeypatch.setattr(llm, "agent", agent)
    return seen


def test_what_the_agent_has_collected_goes_to_the_program_and_not_through_the_model(portal):
    from autoapply.sources import pdportal

    def play(t):
        portal.said.append(t["collect"](script=""))              # the program's own collection, on the page as it is: still fails
        portal.said.append(t["collect"](script=THEIRS))
        t["done"](ok=True, why="the rows no longer carry buildForm; read them by their onclick")

    portal.play = play
    rows = list(pdportal.scan({"150001"}))
    assert portal.runs == 1 and "collecting script failed" in portal.goal
    assert [r["source_id"] for r in rows] == ["150001", "150002", "150003"] and "title" not in rows[0]      # one the program has: kept online, not read again
    assert [r["title"] for r in rows[1:]] == ["Data Engineer Co-op", "Firmware Co-op"] and rows[1]["deadline"] == "2026-12-01 23:59" and rows[1]["channel"] == "PD Portal"
    assert portal.said[0].startswith("The collection failed") and "3 postings are listed; 2 are new" in portal.said[1]
    assert not any("Engineer" in s or "Build things" in s for s in portal.said)        # counts, not postings
    # a script that brings nothing the program can use is told so, and nothing is taken in from it
    portal.play = lambda t: (portal.said.append(t["collect"](script="async () => ({ids: ['150009'], details: [{id: '150009', text: 'hello'}]})")), t["done"](ok=False, why="could not"))
    with pytest.raises(RuntimeError, match="could not be read"):
        list(pdportal.scan(set()))
    assert "no new posting's text could be read" in portal.said[-1]


def test_an_applicant_who_was_asked_to_sign_in_is_not_asked_again_by_every_scan(portal, monkeypatch):
    from autoapply import notify
    from autoapply.ats.base import NeedsHuman
    from autoapply.models import Todo
    from autoapply.sources import pdportal

    monkeypatch.setattr(pdportal, "_signed_out", lambda page: True)
    monkeypatch.setattr(notify, "quiet_now", lambda at=None: True)
    with pytest.raises(NeedsHuman, match="quiet hours"):          # signing in rings their phone: not at night, unless they started the scan themselves
        list(pdportal.scan(set()))
    assert portal.runs == 0
    monkeypatch.setattr(notify, "quiet_now", lambda at=None: False)
    portal.play = lambda t: (t["sign_in_by_hand"](why="No password is stored for the university login."), t["done"](ok=False, why="needs the applicant"))
    with pytest.raises(NeedsHuman, match="No password is stored") as e:
        list(pdportal.scan(set()))
    assert portal.runs == 1 and "signed out" in portal.goal and e.value.waits_for == "account:pdportal:ubc"
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open")] == [("takeover", "account:pdportal:ubc")]
    with pytest.raises(NeedsHuman, match="still open"):
        list(pdportal.scan(set()))
    assert portal.runs == 1

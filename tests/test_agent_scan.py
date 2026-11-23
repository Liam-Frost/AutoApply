"""The co-op portal is read by the agent (agent/scan.py, sources/pdportal.py).

How the agent gets a page to give up its postings is the agent's business and is not tested here (the model is
replaced by a few calls of its tools). What is held is the program's side: what the agent is given, what becomes of
what it saves, and what it is shown of it.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from autoapply import db

TEXT = "Job Title: {t}\nOrganization: Acme\nApplication Deadline: December 1, 2026 11:59 PM\nApplication Receipt Procedure: Online via system\nJob Description: Build things.\nAPPLICATION INFORMATION"
PORTAL = """<!doctype html><title>Co-op postings</title>
<table>__ROWS__</table>
<script>window.texts = __TEXTS__;</script>"""
ROW = """<tr><td><a href="#" onclick="openPosting({postingId: '%s'})">%s</a></td></tr>"""
THEIRS = """async (known) => {
  const ids = [...document.querySelectorAll('[onclick*=postingId]')].map((e) => e.getAttribute('onclick').match(/\\d{5,7}/)[0]);
  return {listed: ids, postings: ids.filter((i) => !known.includes(i)).map((id) => ({id, text: window.texts[id]}))};
}"""


@pytest.fixture()
def portal(app_env, tmp_path, monkeypatch):
    from autoapply import browser, llm
    from autoapply.sources import pdportal

    posts = {"150001": "Backend Developer Co-op", "150002": "Data Engineer Co-op", "150003": "Firmware Co-op"}
    page = tmp_path / "postings.html"
    page.write_text(PORTAL.replace("__ROWS__", "".join(ROW % (i, t) for i, t in posts.items())).replace("__TEXTS__", json.dumps({i: TEXT.format(t=t) for i, t in posts.items()})), encoding="utf-8")
    monkeypatch.setattr(pdportal, "POSTINGS", page.as_uri())
    monkeypatch.setattr(browser, "save_state", lambda *a, **k: None)
    seen = SimpleNamespace(runs=0, said=[], goal="", tools=set(), play=lambda tools: None)

    def agent(goal, tools, *, system, kind="", on_step=None, budget=None):      # (in place of the model: what it is given, and what a run of it does with its tools)
        seen.runs += 1
        seen.goal, seen.tools = goal, {t.name for t in tools}
        seen.play({t.name: t.fn for t in tools})
        return SimpleNamespace(stopped="end_turn", steps=[])

    monkeypatch.setattr(llm, "agent", agent)
    return seen


def test_the_agent_reads_the_portal_and_is_shown_what_became_of_what_it_saved(portal):
    from autoapply.sources import pdportal

    def play(t):
        portal.said.append(t["save_postings"](script=THEIRS))
        t["done"](ok=True, why="read from the rows' onclick")

    portal.play = play
    rows = list(pdportal.scan({"150001"}))
    # the whole task is the agent's, with all its tools - and what was learned about this kind of portal, down to the script that worked
    assert portal.runs == 1 and {"look", "controls", "click", "type", "script", "goto", "account", "type_password", "mail", "note", "save_postings", "done"} <= portal.tools
    assert "loadPostingTable" in portal.goal and "text of 1 of its postings" in portal.goal
    assert [r["source_id"] for r in rows] == ["150001", "150002", "150003"] and "title" not in rows[0]      # one the program has: kept online, not read again
    assert [r["title"] for r in rows[1:]] == ["Data Engineer Co-op", "Firmware Co-op"] and rows[1]["deadline"] == "2026-12-01 23:59" and rows[1]["channel"] == "PD Portal"
    # the agent sees every posting that was stored, as it was stored
    assert "3 postings are listed" in portal.said[0] and "150002 | Data Engineer Co-op | Acme | deadline 2026-12-01 23:59 | applied for: PD Portal" in portal.said[0]
    assert "Nothing that is listed is missing" in portal.said[0]

    # what it read itself stands over what the program would make of the text; what the program could not use is said, for it to put right
    def by_hand(t):
        portal.said.append(t["save_postings"](listed=["150009"], postings=[{"id": "150009", "title": "Analyst Co-op", "company": "Beta", "deadline": "next Friday", "how_to_apply": "website",
                                                                             "apply_url": "https://beta.example/apply", "text": "Job Title: Something else\nJob Description: x"}]))
        t["done"](ok=True)

    portal.play = by_hand
    row = list(pdportal.scan(set()))[0]
    assert (row["title"], row["company"], row["channel"], row["apply_url"]) == ("Analyst Co-op", "Beta", "employer site", "https://beta.example/apply")
    assert "deadline 'next Friday' was not understood" in portal.said[-1]


def test_what_the_program_knows_about_signing_in_is_told_to_the_agent_and_a_scan_that_did_not_finish_takes_nothing_offline(portal, monkeypatch):
    from autoapply import notify, sites
    from autoapply.errors import NeedsHuman
    from autoapply.models import Todo
    from autoapply.sources import pdportal

    # only the applicant can sign in: a card, and the scan waits for it
    monkeypatch.setattr(notify, "quiet_now", lambda at=None: True)
    sites.set_fact("pdportal:ubc", "second_factor", True)
    portal.play = lambda t: (t["sign_in_by_hand"](why="No password is stored for the university login."), t["done"](ok=False, why="needs the applicant"))
    with pytest.raises(NeedsHuman, match="No password is stored") as e:
        list(pdportal.scan(set()))
    assert e.value.waits_for == "account:pdportal:ubc" and "quiet hours" in portal.goal and "approval on the applicant's phone" in portal.goal
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open")] == [("takeover", "account:pdportal:ubc")]
    # the next scan is the agent's again - it is told the card is still open, and decides
    portal.play = lambda t: (t["save_postings"](script=THEIRS.replace("listed: ids", "listed: ids.slice(0, 1)")), t["done"](ok=False, why="the list stopped loading after its first page"))
    rows = list(pdportal.scan({"150001", "140000"}))
    assert portal.runs == 2 and "has been open since" in portal.goal
    assert {r["source_id"] for r in rows} == {"150001", "140000", "150002", "150003"}      # what it got is kept; what it did not get to is not taken for gone


def test_the_agent_is_told_the_applicants_programme_and_to_read_the_list_for_it(portal):
    """The agent read all of a co-op portal's postings - every faculty's, some thousand - though the applicant's own
    notes said to filter the list to their programme first (Computer): the program's notes about the portal said to
    search with an empty keyword, "so that everything is listed", and the agent was never told the programme."""
    from autoapply import db, knowledge
    from autoapply.agent import brief
    from autoapply.sources import pdportal

    knowledge.write("profile", "# Profile\n\n## Education\n\n- University of British Columbia, Bachelor of Applied Science, Computer Engineering, Sept 2023 - May 2028\n")
    portal.play = lambda t: (t["save_postings"](script=THEIRS), t["done"](ok=True))
    list(pdportal.scan(set()))
    assert "The applicant's programme of study: Computer Engineering" in portal.goal and "narrow the list to that programme" in portal.goal
    assert "Filter by Program" in brief.about("orbis") and "so that\neverything is listed" not in brief.about("orbis")
    db.set_setting("intake.programs", ["Computer", "Electrical"])      # what they set themselves comes first
    list(pdportal.scan(set()))
    assert "programme of study: Computer, Electrical." in portal.goal

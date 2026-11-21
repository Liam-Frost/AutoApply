"""What the program says, by key (say.py): the same Chinese as before inside the program, the page's or the
notification's language where it leaves it; every key in the catalogs, with its note and its values."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "frontend" / "src" / "locales" / "server"


def _cat(name: str) -> dict:
    return json.loads((CAT / name).read_text(encoding="utf-8"))


def test_every_key_the_program_says_is_in_the_catalogs_with_its_note_and_values():
    en, zh, notes = _cat("en.json"), _cat("zh.json"), _cat("notes.json")
    used = set()
    for f in (ROOT / "backend" / "autoapply").rglob("*.py"):
        used |= set(re.findall(r'\bT\("(server\.[\w.]+)"', f.read_text(encoding="utf-8")))
    assert len(used) > 500
    assert sorted(used - set(en)) == [] and sorted(used - set(zh)) == []
    assert sorted(k for k in en if k not in notes) == []
    vals = lambda s: sorted(set(re.findall(r"\{(\w+)\}", s)))  # noqa: E731
    assert [k for k in en if k in zh and vals(en[k]) != vals(zh[k])] == []


def test_a_message_is_the_old_chinese_inside_and_its_language_outside(app_env):
    from autoapply import db, humanize, i18n, say

    m = humanize.APP_STATUS["draft_ready"]
    assert isinstance(m, str) and m == "等你审批"                       # what everything inside the program compares and stores
    assert m.in_lang("en") == "Awaiting your approval" and say.render({"x": [m]}, "en") == {"x": ["Awaiting your approval"]}
    db.set_setting("ui.lang", "en")
    assert i18n.tr(m) == "Awaiting your approval"                       # (notifications: the program's language)
    kept = say.from_data(m.data())
    assert kept == m and kept.in_lang("en") == "Awaiting your approval"
    assert say.say("server.no.such.key") == "server.no.such.key"        # a key no catalog has: said as it is
    # plural forms only in a message that counts
    assert say._fill("{n} day | {n} days", {"n": 1}, "en") == "1 day" and say._fill("{n} day | {n} days", {"n": 3}, "en") == "3 days"
    assert say._fill("a | b", {"p0": 1}, "en") == "a | b"


def test_the_api_answers_in_the_language_of_the_page_that_asks(app_env):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    zh = c.get("/api/calendar?start=2026-11-23&end=2027-11-23").json()
    en = c.get("/api/calendar?start=2026-11-23&end=2027-11-23", headers={"X-Lang": "en"}).json()
    assert re.search(r"[一-鿿]", zh["detail"]) and not re.search(r"[一-鿿]", en["detail"])    # a refusal, said in each


def test_what_the_program_keeps_is_read_in_the_language_it_is_shown_in(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db, notify
    from autoapply.api.main import app
    from autoapply.models import Todo
    from autoapply.say import say

    title = say("server.humanize.awaitingYourApproval") if "server.humanize.awaitingYourApproval" in _cat("en.json") else None
    key = next(k for k, v in _cat("zh.json").items() if v == "等你审批")
    tid = notify.add_todo("confirm", say(key)[:120], body="plain text, kept as it was", push=False)
    with db.session() as s:
        t = s.get(Todo, tid)
        assert t.title == "等你审批" and t.title.key == key and t.body == "plain text, kept as it was"      # read back: the message, the same text
    rows = {r["id"]: r for r in TestClient(app).get("/api/todos", headers={"X-Lang": "en"}).json()}
    assert rows[tid]["title"] == "Awaiting your approval"
    rows = {r["id"]: r for r in TestClient(app).get("/api/todos").json()}
    assert rows[tid]["title"] == "等你审批"
    del title


def test_a_message_kept_in_json_comes_back_with_its_key(app_env):
    from autoapply import db
    from autoapply.models import Task
    from autoapply.say import Msg, say

    key = next(k for k, v in _cat("zh.json").items() if v == "等你审批")
    db.set_setting("doctor.last", {"checks": [{"title": say(key), "n": 1}]})
    got = db.get_setting("doctor.last")["checks"][0]["title"]
    assert isinstance(got, Msg) and got == "等你审批" and got.in_lang("en") == "Awaiting your approval"
    with db.session() as s:
        s.add(Task(kind="score", ref="x", status="done", result={"summary": say(key), "plain": "text"}))
    with db.session() as s:
        r = s.query(Task).one().result
        assert isinstance(r["summary"], Msg) and r["plain"] == "text" and not isinstance(r["plain"], Msg)


def test_messages_put_together_stay_messages(app_env):
    from autoapply import humanize
    from autoapply.say import Msg, from_data, join

    s = humanize.result_summary("score", "done", {"scored": 4, "queued_for_draft": 2})
    assert isinstance(s, Msg) and "4" in s and "2" in s
    en = s.in_lang("en")
    assert "4" in en and "2" in en and not __import__("re").search(r"[一-鿿]", en)
    assert from_data(s.data()).in_lang("en") == en                                  # kept and read back
    j = join("；", [humanize.APP_STATUS["draft_ready"], "x"])
    assert j == "等你审批；x" and j.in_lang("en") == "Awaiting your approval；x"


def test_what_the_ai_writes_for_the_applicant_is_in_their_language(app_env):
    from autoapply import db, prompts
    from autoapply.agent import brief

    assert "in Simplified Chinese" in brief.reads()
    db.set_setting("ui.lang", "en")
    assert "in English" in brief.reads() and "write English instead" in prompts.get("mail_triage")
    db.set_setting("ui.lang", "fr")       # a language of the list (C4 adds French): the model is told its name
    import autoapply.say as s

    listed = s.language_name("fr")
    assert listed in ("French", "English")

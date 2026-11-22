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


def test_what_was_kept_before_messages_had_keys_is_found_as_the_message_it_is(app_env):
    """Cards and latest events written before 2.0.2 hold the Chinese the program wrote. Once, at the start, each that is one
    of the program's messages becomes that message - read in English or French from then on; what someone wrote stays."""
    from sqlalchemy import text

    from autoapply import db, say
    from autoapply.models import Todo

    budget = str(say.say("server.agent.work.thisApplicationsBudgetIs2", p0="Acme · Analyst"))      # (as it was stored: plain text)
    with db.session() as s:
        s.add(Todo(kind="failed", title="x", body="Recruiter said: call me back", payload={}))
    with db.get_engine().begin() as c:      # written as an earlier version wrote it, without a key
        c.execute(text("UPDATE todos SET title = :t"), {"t": budget})
    assert say.recognise_kept() == 1
    with db.session() as s:
        t = s.query(Todo).one()
        assert isinstance(t.title, say.Msg) and t.title.key == "server.agent.work.thisApplicationsBudgetIs2" and "Acme · Analyst" in t.title.in_lang("en")
        assert t.body == "Recruiter said: call me back"
    assert say.recognise("已投出").in_lang("en") == "Sent" and say.recognise("面试安排在下周") is None


def test_server_code_writes_no_text_for_people_but_by_key():
    """Every sentence the server shows has a key (say.py). Chinese left in the code is data - patterns that read what sites,
    mails and AI services write, words looked for, the tray's own two languages - and only in these files, each saying why."""
    import ast

    data = {
        "actions.py": "a field name of cards from before keys, compared",
        "agent/work.py": "a word looked for in the agent's own summary",
        "analytics.py": "patterns of error text",
        "humanize.py": "patterns of error text",
        "importer.py": "the words of the old tracking table being imported",
        "intake.py": "place names looked for in postings",
        "launcher.py": "the tray's own words, in Chinese and English",
        "lifecycle.py": "what employers' sites write",
        "llm.py": "what AI services answer",
        "mail.py": "a word looked for in a card's text",
        "mailbox.py": "words looked for in mails",
        "messages.py": "patterns of error text, a word looked for in a reason",
        "rules.py": "a heading of the applicant's scoring rules, looked for",
        "scoring.py": "headings the model is asked to write (in the applicant's language, by prompts.py)",
        "tailor.py": "section headings of résumés, looked for",
        "tasks.py": "words looked for in an error",
    }
    cjk = re.compile(r"[一-鿿]")
    root = Path(__file__).resolve().parents[1] / "backend" / "autoapply"
    found = set()
    for p in root.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and cjk.search(n.value) and id(n) not in docs for n in ast.walk(tree)):
            found.add(p.relative_to(root).as_posix())
    assert found - set(data) == set()       # a sentence for people: T("server.<module>.<key>") with its English and note in the catalogs


def test_a_third_language_is_only_its_catalogs():
    """French came as two files (and a line in the list of languages): the program says its messages in it, numbers
    pick their plural form the French way, and the AI is told the applicant reads French."""
    from autoapply import say

    msg = say.say("server.applications.questionsOpen", n=1)
    assert msg.in_lang("fr") == "1 question est encore en suspens" and say.say("server.applications.questionsOpen", n=3).in_lang("fr").startswith("3 questions sont")
    assert say.say("server.applications.questionsOpen", n=0).in_lang("fr").startswith("0 question est")      # (0 is singular in French)
    assert say.language_name("fr") == "French"

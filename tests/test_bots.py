"""The bots: a card goes out with the buttons that deal with it; a press, a reply, a command and anything else said come
back and do what the same press on the page does."""
from __future__ import annotations

import pytest

from autoapply import db


class FakeTelegram:
    """Telegram's API, as far as the bot uses it: what was sent, and the message ids it gave."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 100

    def post(self, url, json=None, timeout=None, **kw):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json or {}))
        if method == "sendMessage":
            self.next_id += 1
        result = {"message_id": self.next_id} if method == "sendMessage" else True
        return type("R", (), {"status_code": 200, "content": b"x", "text": "", "json": lambda self_: {"ok": True, "result": result}})()

    def sent(self, method="sendMessage"):
        return [b for m, b in self.calls if m == method]


@pytest.fixture()
def tg(app_env, monkeypatch):
    import httpx

    from autoapply import secrets

    fake = FakeTelegram()
    monkeypatch.setattr(httpx, "post", fake.post)
    secrets.put(secrets.TELEGRAM_TOKEN, "123:abc")
    db.set_setting("notify.telegram_chat_id", "42")
    return fake


def _posting(status="draft_ready", questions=()):
    from autoapply.models import Application, Draft, Job

    with db.session() as s:
        j = Job(source="manual", source_id="b1", company="Acme", title="Backend Intern", apply_url="https://careers.acme.example/jobs/1", jd_text="x" * 300, status="queued", online=1)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status=status)
        s.add(a)
        s.flush()
        answers = [{"id": "q1", "label": "First name", "value": "Alex", "source": "profile", "confidence": "high"},
                   {"id": "q2", "label": "Degree", "value": "BEng", "source": "agent", "confidence": "medium"}]
        answers += [{"id": f"o{i}", "label": q[0], "value": "", "source": "unresolved", "options": list(q[1]), "suggested": q[2] if len(q) > 2 else None}
                    for i, q in enumerate(questions)]
        d = Draft(application_id=a.id, version=1, review_status="pending", schema={}, answers=answers,
                  unresolved=[{"id": f"o{i}"} for i in range(len(questions))], materials=[{"name": "resume.pdf"}])
        s.add(d)
        s.flush()
        return j.id, a.id, d.id


def test_a_card_goes_out_with_its_buttons_and_a_press_does_what_the_page_does(tg):
    from autoapply import actions, bots, notify
    from autoapply.models import Notification, Todo

    job, app, _ = _posting()
    tid = notify.add_todo("confirm", "Acme：等你确认", body="在手机上点批准。", ref=f"application:{app}:confirm", payload={"application_id": app, "job_id": job})
    body = tg.sent()[-1]
    assert body["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"t:{tid}:done"
    with db.session() as s:
        n = s.query(Notification).order_by(Notification.id.desc()).first()
        assert n.pushed == {"telegram": "101"} and n.todo_id == tid
    # the press: the card is done, the chat is told, the buttons give way to what happened
    bots._tg_update("123:abc", "42", {"update_id": 1, "callback_query": {"id": "cq1", "data": f"t:{tid}:done", "message": {"message_id": 101, "chat": {"id": 42}}}})
    with db.session() as s:
        assert s.get(Todo, tid).status == "done"
    assert tg.sent("answerCallbackQuery")[-1]["text"] == "已继续"
    assert tg.sent("editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "-"
    # pressed again (an old message): nothing is done twice
    with pytest.raises(actions.Done):
        actions.run(f"t:{tid}:done")
    # a press from another chat is not the applicant's
    tid2 = notify.add_todo("confirm", "Acme：等你确认", ref=f"application:{app}:confirm", payload={"application_id": app, "job_id": job})
    bots._tg_update("123:abc", "42", {"update_id": 2, "callback_query": {"id": "cq2", "data": f"t:{tid2}:done", "message": {"message_id": 5, "chat": {"id": 7}}}})
    with db.session() as s:
        assert s.get(Todo, tid2).status == "open"


def test_a_question_is_answered_with_a_press_or_a_reply(tg):
    from autoapply import bots, notify
    from autoapply.models import Draft

    job, app, did = _posting("needs_input", questions=[("Are you legally entitled to work in Canada?", ["Yes", "No"], "Yes"), ("Notice period", [])])
    tid = notify.add_todo("answer", "Acme：有问题要你回答", ref=f"draft:{did}", payload={"draft_id": did})
    card = tg.sent()[-1]
    labels = [b["text"] for row in card["reply_markup"]["inline_keyboard"] for b in row]
    assert labels == ["就按建议：Yes", "Yes", "No"] and "Are you legally entitled" in card["text"]      # the question is on the card
    bots._tg_update("123:abc", "42", {"update_id": 3, "callback_query": {"id": "c", "data": f"t:{tid}:opt:1", "message": {"message_id": 101, "chat": {"id": 42}}}})
    with db.session() as s:
        got = {a["id"]: a["value"] for a in s.get(Draft, did).answers}
    assert got["o0"] == "No"
    # the next question has no options: the applicant replies to the card with the answer
    bots._tg_update("123:abc", "42", {"update_id": 4, "message": {"message_id": 300, "chat": {"id": 42}, "text": "Two weeks", "reply_to_message": {"message_id": 101}}})
    with db.session() as s:
        got = {a["id"]: a["value"] for a in s.get(Draft, did).answers}
    assert got["o1"] == "Two weeks" and "Two weeks" in tg.sent()[-1]["text"]


def test_a_record_waiting_for_approval_shows_what_the_agent_was_not_sure_of_and_can_be_approved(tg):
    from autoapply import actions, messages, notify
    from autoapply.models import Application, Draft

    job, app, did = _posting()
    notify.send("todo", messages.draft_ready("Acme · Backend Intern", did, answers=2, files=["resume.pdf"]), ref=f"draft:{did}")
    card = tg.sent()[-1]
    assert card["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"d:{did}:approve"
    assert "Degree：BEng" in card["text"] and "First name" not in card["text"] and "resume.pdf" in card["text"]
    assert actions.run(f"d:{did}:approve") == "已批准，正在提交"
    with db.session() as s:
        assert s.get(Draft, did).review_status == "approved" and s.get(Application, app).status == "approved"
    with pytest.raises(actions.Done):
        actions.run(f"d:{did}:approve")


def test_a_code_is_typed_as_a_reply_and_a_word_to_an_application_reaches_its_agent(tg, monkeypatch):
    from autoapply import bots, notify
    from autoapply.api import main as api

    job, app, _ = _posting("executing")
    tid = notify.add_todo("code", "Acme：请输入验证码", body="网站发了验证码。", ref=f"application:{app}:code", payload={"application_id": app, "job_id": job})
    given, said = [], []
    monkeypatch.setattr(api, "todo_code", lambda todo_id, body: given.append((todo_id, body["code"])) or {"given": True})
    monkeypatch.setattr(api, "say_to_the_agent", lambda application_id, body: said.append((application_id, body["text"])) or {"heard": "now"})
    # the button asks for the code as a reply ...
    bots._tg_update("123:abc", "42", {"update_id": 5, "callback_query": {"id": "c", "data": f"t:{tid}:code", "message": {"message_id": 101, "chat": {"id": 42}}}})
    prompt = tg.sent()[-1]
    assert prompt["reply_markup"] == {"force_reply": True}
    bots._tg_update("123:abc", "42", {"update_id": 6, "message": {"message_id": 301, "chat": {"id": 42}, "text": "482 913", "reply_to_message": {"message_id": 102}}})
    assert given == [(tid, "482 913")]
    # ... and a reply to the card itself does the same
    bots._tg_update("123:abc", "42", {"update_id": 7, "message": {"message_id": 302, "chat": {"id": 42}, "text": "111222", "reply_to_message": {"message_id": 101}}})
    assert given[-1] == (tid, "111222")
    # a reply to a card about the application (not a code): a word to its agent
    notify.send("status_update", "Acme：投递进展", ref=f"application:{app}")
    bots._tg_update("123:abc", "42", {"update_id": 8, "message": {"message_id": 303, "chat": {"id": 42}, "text": "Use my Vancouver address", "reply_to_message": {"message_id": tg.next_id}}})
    assert said == [(app, "Use my Vancouver address")]


def test_commands(tg):
    from autoapply import bots, notify
    from autoapply.models import Task

    bots._tg_update("123:abc", "42", {"update_id": 9, "message": {"message_id": 1, "chat": {"id": 42}, "text": "/pause"}})
    assert db.get_setting("schedule.paused") is True
    bots._tg_update("123:abc", "42", {"update_id": 10, "message": {"message_id": 2, "chat": {"id": 42}, "text": "/resume@AutoApplyBot"}})
    assert db.get_setting("schedule.paused") is False
    bots._tg_update("123:abc", "42", {"update_id": 11, "message": {"message_id": 3, "chat": {"id": 42}, "text": "/scan"}})
    with db.session() as s:
        assert s.query(Task).filter_by(kind="discover").count() == 1
    _posting("needs_human")
    tid = notify.add_todo("resume", "Acme：等你有空", ref="application:1:resume", payload={"application_id": 1, "job_id": 1})
    n = len(tg.sent())
    bots._tg_update("123:abc", "42", {"update_id": 12, "message": {"message_id": 4, "chat": {"id": 42}, "text": "/todo"}})
    out = tg.sent()[n:]
    assert "1 项" in out[0]["text"] and out[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"t:{tid}:done"
    bots._tg_update("123:abc", "42", {"update_id": 13, "message": {"message_id": 5, "chat": {"id": 42}, "text": "/app acme"}})
    assert "Acme · Backend Intern" in tg.sent()[-1]["text"]


def test_discord_binding_buttons_and_the_code_form(app_env, monkeypatch):
    from autoapply import bots, discord, notify, secrets
    from autoapply.api import main as api
    from autoapply.models import Todo

    secrets.put(discord.TOKEN, "bot-token")
    posted, answered, dm = [], [], []
    monkeypatch.setattr(discord, "_call", lambda method, path, body=None: posted.append((method, path, body)) or {"id": str(900 + len(posted))})
    monkeypatch.setattr(discord, "respond", lambda inter, kind, data=None: answered.append((kind, data)))
    monkeypatch.setattr(discord, "send_text", lambda text, buttons=None, channel="": dm.append(text) or "1")
    code = bots.bind_code()
    bots._discord_event("MESSAGE_CREATE", {"author": {"id": "555"}, "channel_id": "77", "content": "nope"})
    assert not db.get_setting("notify.discord_user_id")          # anyone else, anything else: not listened to
    bots._discord_event("MESSAGE_CREATE", {"author": {"id": "555"}, "channel_id": "77", "content": code.lower()})
    assert db.get_setting("notify.discord_user_id") == "555" and db.get_setting("notify.discord_dm") == {"user": "555", "channel": "77"}
    # a card goes to the direct message, with its buttons
    _, app, _ = _posting("executing")
    tid = notify.add_todo("code", "Acme：请输入验证码", ref=f"application:{app}:code", payload={"application_id": app, "job_id": 1})
    method, path, body = posted[-1]
    assert path == "/channels/77/messages" and body["components"][0]["components"][0]["custom_id"] == f"t:{tid}:code"
    # the press opens a form; what is typed in it is the code
    given = []
    monkeypatch.setattr(api, "todo_code", lambda todo_id, b: given.append(b["code"]) or {"given": True})
    press = {"id": "i1", "token": "t", "type": 3, "user": {"id": "555"}, "data": {"custom_id": f"t:{tid}:code"}, "message": {"id": "901"}}
    bots._discord_event("INTERACTION_CREATE", press)
    assert answered[-1][0] == 9
    bots._discord_event("INTERACTION_CREATE", {**press, "type": 5, "data": {"custom_id": f"t:{tid}:code", "components": [{"type": 1, "components": [{"custom_id": "value", "value": "7788"}]}]}})
    assert given == ["7788"] and answered[-1][0] == 7
    # someone else pressing: nothing
    bots._discord_event("INTERACTION_CREATE", {**press, "user": {"id": "666"}})
    assert len(answered) == 2
    with db.session() as s:
        assert s.get(Todo, tid).status == "open"      # (the code was handed on; the run closes the card when it uses it)


def test_the_assistant_does_one_thing_asked_and_asks_before_doing_several(app_env, monkeypatch):
    from autoapply import actions, chat, llm
    from autoapply.models import Job

    j1, _, _ = _posting("draft_ready")
    with db.session() as s:
        j2 = Job(source="manual", source_id="b2", company="Acme", title="Data Intern", apply_url="https://careers.acme.example/jobs/2", jd_text="x" * 300, status="scored", online=1)
        s.add(j2)
        s.flush()
        j2 = j2.id
    plan: list = []

    def agent(goal, tools, *, system, kind=""):
        by = {t.name: t.fn for t in tools}
        said = [by[name](**kw) for name, kw in plan.pop(0)]
        assert kind == "chat" and "approve" not in by and "send" not in by
        return llm.AgentResult(final_text=" | ".join(said))

    monkeypatch.setattr(llm, "agent", agent)
    plan.append([("look", {"query": "acme"})])
    reply, buttons = chat.reply("what is going on with Acme?")
    assert "Data Intern" in reply and buttons == []
    plan.append([("act", {"action": "not_applying", "ids": [j2]})])
    reply, buttons = chat.reply("don't apply to the data one")
    assert buttons == [] and "1 done" in reply
    with db.session() as s:
        assert s.get(Job, j2).status == "skipped"
    plan.append([("act", {"action": "pause", "ids": []}), ("act", {"action": "not_applying", "ids": [j1], "summary": "Acme 不投了"})])
    reply, buttons = chat.reply("pause, and drop Acme")
    assert db.get_setting("schedule.paused") is True and len(buttons) == 1 and buttons[0]["label"].endswith("Acme 不投了")
    with db.session() as s:
        assert s.get(Job, j1).status != "skipped"           # not until the press
    assert actions.run(buttons[0]["data"]) == "已照办"
    with db.session() as s:
        assert s.get(Job, j1).status == "skipped"
    with pytest.raises(actions.Done):
        actions.run(buttons[0]["data"])                    # once
    assert [h["who"] for h in db.get_setting(chat.HISTORY)] == ["me", "bot"] * 3


def test_the_assistant_enters_an_answer_the_applicant_gives(app_env, monkeypatch):
    from autoapply import chat, llm
    from autoapply.models import Draft

    _, _, did = _posting("needs_input", questions=[("Are you legally entitled to work in Canada?", ["Yes", "No"])])
    calls = [("cards", {}), ("answer", {"draft_id": did, "question_id": "o0", "value": "maybe"}), ("answer", {"draft_id": did, "question_id": "o0", "value": "yes"})]

    def agent(goal, tools, *, system, kind=""):
        by = {t.name: t.fn for t in tools}
        return llm.AgentResult(final_text=" | ".join(by[n](**kw) for n, kw in calls))

    monkeypatch.setattr(llm, "agent", agent)
    reply, _ = chat.reply("yes I can work in Canada")
    assert "must be one of" in reply and "entered" in reply
    with db.session() as s:
        assert {a["id"]: a["value"] for a in s.get(Draft, did).answers}["o0"] == "Yes"


def test_each_channel_takes_the_kinds_chosen_for_it(tg, monkeypatch):
    from autoapply import discord, notify, secrets

    secrets.put(discord.WEBHOOK, "https://discord.example/webhook")
    hooks = []
    monkeypatch.setattr(discord, "webhook_send", lambda card, base: hooks.append(card.heading))
    db.set_setting("notify.channel_categories", {"discord": ["todo"]})
    notify.send("status_update", "Acme：投递进展")
    assert hooks == [] and len(tg.sent()) == 1
    notify.add_todo("confirm", "Acme：等你确认", ref="application:9:confirm")
    assert len(hooks) == 1 and len(tg.sent()) == 2


def test_a_revised_record_lists_what_changed_and_one_with_too_much_to_look_at_has_only_its_link(tg):
    from autoapply import actions, messages, notify
    from autoapply.models import Draft

    _, app, first = _posting()
    with db.session() as s:
        s.get(Draft, first).review_status = "superseded"
        d = Draft(application_id=app, version=2, review_status="pending", schema={}, unresolved=[], materials=[{"name": "resume.pdf"}],
                  answers=[{"id": "q1", "label": "First name", "value": "Alex", "source": "profile", "confidence": "high"},
                           {"id": "q2", "label": "Degree", "value": "BASc", "source": "user", "confidence": "high"}])
        s.add(d)
        s.flush()
        second = d.id
    notify.send("todo", messages.draft_ready("Acme · Backend Intern", second, answers=2, files=["resume.pdf"]), ref=f"draft:{second}")
    card = tg.sent()[-1]
    assert "Degree：BEng → BASc" in card["text"] and "First name" not in card["text"] and card["text"].count("resume.pdf") == 1
    assert card["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"d:{second}:approve"
    with db.session() as s:
        s.get(Draft, second).answers = [{"id": f"x{i}", "label": f"Q{i}", "value": "a", "source": "agent", "confidence": "low"} for i in range(13)]
    assert actions.for_record(second) == []          # thirteen to look at: on the page


def test_what_the_applicant_told_a_bot_is_in_the_activity_record_without_the_code(tg, monkeypatch):
    from autoapply import bots, notify
    from autoapply.api import main as api
    from autoapply.models import Notification

    _, app, _ = _posting("executing")
    tid = notify.add_todo("code", "Acme：请输入验证码", ref=f"application:{app}:code", payload={"application_id": app, "job_id": 1})
    monkeypatch.setattr(api, "todo_code", lambda todo_id, body: {"given": True})
    bots._tg_update("123:abc", "42", {"update_id": 20, "message": {"message_id": 400, "chat": {"id": 42}, "text": "553311", "reply_to_message": {"message_id": 101}}})
    bots.press("discord", f"t:{tid}:code", "778899")
    bots._tg_update("123:abc", "42", {"update_id": 21, "message": {"message_id": 401, "chat": {"id": 42}, "text": "/pause"}})
    with db.session() as s:
        said = [n.text for n in s.query(Notification).filter_by(category="heard").order_by(Notification.id)]
    assert said[0].startswith("Telegram：回复了验证码") and said[1].startswith("Discord：Acme：请输入验证码") and said[2].startswith("Telegram：/pause")
    assert not any(c in " ".join(said) for c in ("553311", "778899"))


def test_the_assistant_narrows_looks_ahead_and_remembers_what_it_talked_about(app_env, monkeypatch):
    from datetime import date, timedelta

    from autoapply import chat, llm

    soon = (date.today() + timedelta(days=3)).isoformat()
    later = (date.today() + timedelta(days=30)).isoformat()
    j1, _, _ = _posting("draft_ready")
    from autoapply.models import Job

    with db.session() as s:
        s.get(Job, j1).deadline, s.get(Job, j1).score = soon, 8.0
        s.add(Job(source="manual", source_id="b2", company="Globex", title="Data Intern", apply_url="https://x/2", jd_text="x" * 300, status="scored", online=1, score=6.0, deadline=later))
    assert [r["company"] for r in chat.look(due_within_days=7)] == ["Acme"]
    assert [r["company"] for r in chat.look(state="unapplied")] == ["Globex"]
    assert [r["company"] for r in chat.look(min_score=7)] == ["Acme"]
    assert [(x["kind"], x["subject"]) for x in chat.upcoming(7)] == [("deadline", "Acme · Backend Intern")]
    goals = []

    def agent(goal, tools, *, system, kind=""):
        goals.append(goal)
        by = {t.name: t.fn for t in tools}
        if len(goals) == 1:
            by["look"](query="acme")
        return llm.AgentResult(final_text="Acme is waiting for your approval.")

    monkeypatch.setattr(llm, "agent", agent)
    chat.reply("how is Acme?")
    chat.reply("and the other one?")
    assert "that answer was about: Acme · Backend Intern (job" in goals[1]          # "the other one" can be worked out


def test_a_summary_each_morning_once_when_asked_for(app_env, monkeypatch):
    from datetime import datetime

    from autoapply import chat, notify

    sent = []
    monkeypatch.setattr(notify, "send", lambda category, card, **k: sent.append((category, card.heading, k.get("tag"))) or True)
    _posting("needs_input")
    assert chat.morning(datetime(2026, 11, 24, 9, 0)) is False                         # off unless switched on
    db.set_setting("bot.daily_summary", {"on": True, "at": "08:30"})
    assert chat.morning(datetime(2026, 11, 24, 8, 0)) is False                         # not before its hour
    assert chat.morning(datetime(2026, 11, 24, 8, 31)) is True
    assert chat.morning(datetime(2026, 11, 24, 12, 0)) is False                        # once a day
    assert chat.morning(datetime(2026, 11, 25, 8, 30)) is True
    assert sent[0] == ("status_update", "早上好：今天的情况", "summary")

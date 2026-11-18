"""One run of the agent on one application.

What outlives the run is kept in the application's folder (phase 0; the database in phase 1), so that a run can be
followed by another that knows what this one did - whatever became of the browser and of the model's session:

    journal.jsonl   every tool call, and the lines the agent logged itself
    record.json     what the agent reported: how it ended, every question with what was entered and why, the files
                    given, what is open, the confirmation
    questions.json  what it asked the applicant, and what they answered when they have
    shots/          the pictures it took
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import llm
from . import brief
from .hands import Hands

OUTCOMES = ("ready", "submitted", "needs_you", "cannot")


@dataclass
class Result:
    outcome: str = ""                    # ready | submitted | needs_you | cannot | "" (the run ended without a report)
    record: dict[str, Any] = field(default_factory=dict)
    stopped: str = ""                    # how the model's run ended: end_turn | max_steps | timeout | error text
    steps: int = 0
    seconds: float = 0.0
    said: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class Desk:
    """What the agent has besides the browser: the applicant's side (accounts, questions) and its own notes."""

    def __init__(self, folder: Path, hands: Hands, *, site: str, mode: str, login: str = "", answers: dict[str, str] | None = None) -> None:
        self.folder, self.hands, self.site, self.mode, self.login = folder, hands, site, mode, login
        self.answers = dict(answers or {})
        self.asked: list[dict[str, Any]] = []
        self.reported: dict[str, Any] | None = None
        self.waiting = ""                # what the run stopped for, when it handed the window to the applicant
        folder.mkdir(parents=True, exist_ok=True)

    # --- the journal ---------------------------------------------------------------------------------------------
    def write(self, kind: str, **what: Any) -> None:
        with open(self.folder / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, **what}, ensure_ascii=False, default=str) + "\n")

    def step(self, step: dict[str, Any]) -> None:
        """A tool call, as the model's run reports it."""
        inp = {k: (v if len(str(v)) < 300 else str(v)[:300] + "…") for k, v in (step.get("input") or {}).items()}
        self.write("tool", tool=step.get("tool"), input=inp, ok=step.get("ok"), output=str(step.get("output") or "")[:600], ms=step.get("ms"))

    def log(self, text: str) -> str:
        self.write("log", text=str(text)[:1000])
        return "written down."

    # --- the site's notes ----------------------------------------------------------------------------------------
    def note(self, text: str, about: str = "") -> str:
        from .. import sites

        key = f"system:{about.strip().lower()}" if about.strip() else self.site
        sites.note(key, str(text)[:1200])
        self.write("note", about=key, text=str(text)[:1200])
        return f"noted for {key}."

    def notes(self, about: str) -> str:
        from .. import sites

        return sites.notes(f"system:{about.strip().lower()}") or f"nothing is written down about {about!r}."

    # --- the applicant ---------------------------------------------------------------------------------------------
    def ask(self, question: str, about: str = "applicant", options: list[str] | None = None, why: str = "") -> str:
        q = " ".join(str(question).split())
        for known, answer in self.answers.items():
            if " ".join(known.split()).lower() == q.lower():
                return f"The applicant answered this before: {answer}"
        self.asked.append({"question": q, "about": "job" if str(about).lower().startswith("job") else "applicant", "options": list(options or []), "why": str(why)[:400]})
        (self.folder / "questions.json").write_text(json.dumps(self.asked, ensure_ascii=False, indent=1), encoding="utf-8")
        self.write("ask", question=q, about=about)
        return ("The question is on the record for the applicant; there is no answer yet. Leave what it is for as it is (empty, or the form's own default), "
                "go on with everything else, and list it as open in your report. Do not send the application while it is open.")

    def account(self) -> str:
        from .. import auth

        acct = auth.account(self.site)
        if not acct:
            return f"No account is on record for this site. The e-mail address to register or sign in with: {self.login or '(none on record: ask)'}."
        return (f"Account on record: login name {acct['login_email'] or self.login or '(not recorded)'}; password {'stored' if acct['has_password'] else 'NOT stored'}; "
                f"status {acct['status']}.")

    def type_password(self, ref: str, then_click: str = "", new: bool = False) -> str:
        """The applicant's password for this site, typed by the program into the box ``ref``; then ``then_click`` is
        pressed. The agent never has the password: the box is emptied again before control goes back, unless the
        page has moved on. ``new``: a password is made up and stored first (registering an account)."""
        from .. import auth, secrets

        at = self.hands._at(ref)
        if at["type"] != "password":
            raise PermissionError(f"[{ref}] is not a password box")
        if new:
            pw = secrets.generate_password(20)
            auth.upsert_account(self.site, host=self.site.split(":", 1)[-1], email=self.login, password=pw, status="pending", created_by="agent")      # kept before it is sent
        else:
            pw = secrets.get_password(self.site) or ""
            if not pw:
                return "No password is stored for this site. Register with new=true if the applicant has no account here, or use sign_in_by_hand."
        page = self.hands.page
        page.mouse.click(at["x"], at["y"])
        time.sleep(0.15)
        page.evaluate("() => { const e = window.__aaAt; if (e && e.select) e.select(); }")
        page.keyboard.insert_text(pw)
        if not then_click:
            return ("typed (hidden). If the form wants it a second time (verify password), call this again for that box - without new, so that it is the same password - "
                    "and give then_click there, so that the boxes do not stay filled.")
        said = self.hands.click(ref=then_click)
        time.sleep(1.5)
        try:        # a sign-in that did not go through leaves the box filled: emptied, so that nothing on the page holds the password
            page.evaluate("""() => { for (const e of document.querySelectorAll('input[type=password]')) { if (e.value) {
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, ''); e.dispatchEvent(new Event('input', {bubbles: true})); } } }""")
        except Exception:  # noqa: BLE001 - the page moved on: there is no box left
            pass
        self.write("password", new=bool(new))
        return "typed (hidden) and " + said

    def sign_in_by_hand(self, why: str) -> str:
        self.waiting = str(why)[:600]
        self.write("needs_applicant", why=self.waiting, url=self.hands.page.url)
        return "The window is the applicant's from here. This run is over: call report with outcome needs_you, saying what you had done up to here."

    # --- the end ---------------------------------------------------------------------------------------------------
    def report(self, outcome: str, summary: str, answers: list[dict[str, Any]] | None = None, files: list[dict[str, Any]] | None = None,
               open: list[str] | None = None, confirmation: dict[str, Any] | None = None, sent: bool = False) -> str:  # noqa: A002
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome is one of {OUTCOMES}")
        if outcome == "submitted" and not (confirmation and str(confirmation.get('words') or '').strip() and str(confirmation.get('ties_to_posting') or '').strip()):
            raise ValueError("an application that went out is reported with its confirmation: the page's own words, its address, and what ties it to this posting")
        self.reported = {"outcome": outcome, "summary": str(summary)[:3000], "answers": list(answers or []), "files": list(files or []), "open": [str(x) for x in (open or [])],
                         "confirmation": dict(confirmation or {}), "sent": bool(sent or outcome == "submitted"), "asked": list(self.asked),
                         "at": datetime.now().isoformat(timespec="seconds"), "mode": self.mode}
        (self.folder / "record.json").write_text(json.dumps(self.reported, ensure_ascii=False, indent=1), encoding="utf-8")
        self.write("report", outcome=outcome, summary=str(summary)[:600], open=len(open or []), sent=self.reported["sent"])
        return "recorded. The run is over: stop here."

    def tools(self) -> list[llm.Tool]:
        s, b = {"type": "string"}, {"type": "boolean"}
        arr = {"type": "array", "items": s}
        answer = {"type": "object", "properties": {"question": s, "entered": s, "from": {"type": "string", "description": "where the answer comes from: the profile's own line, the résumé, "
                  "an answer the applicant gave, or 'the form's default, left as it was'"}, "sure": {"type": "string", "enum": ["yes", "fairly", "no"]}}, "required": ["question", "entered", "from"]}
        gave = {"type": "object", "properties": {"field": s, "file": s}, "required": ["field", "file"]}
        conf = {"type": "object", "properties": {"words": s, "url": s, "ties_to_posting": s}}

        def spec(required: list[str] | None = None, **props: Any) -> dict[str, Any]:
            return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}

        return [
            llm.Tool("log", "Write a line in this application's journal: a milestone, what you worked around, that you are about to send.", spec(["text"], text=s), self.log),
            llm.Tool("note", "Write down something that is true of this site for whoever applies here next. `about`: a recruiting system's name (workday, greenhouse ...) when it is "
                             "true of that system on every employer's site; empty for this site.", spec(["text"], text=s, about=s), self.note),
            llm.Tool("notes", "Read what is written down about a recruiting system.", spec(["about"], about=s), self.notes),
            llm.Tool("ask", "Put a question to the applicant: something the form needs and you were not given. `about`: 'applicant' when it is about them in general, 'job' when it "
                            "is about this job only. `options`: the form's choices, when it has them. `why`: where the form asks it.", spec(["question"], question=s, about=s, options=arr, why=s), self.ask),
            llm.Tool("account", "What the program has on record for this site: the login name, whether a password is stored.", spec(), self.account),
            llm.Tool("type_password", "Have the applicant's password for this site typed into the password box `ref` (you do not see it), then press `then_click` (the sign-in or "
                                      "create-account button). `new`: make up and store a password first - for registering an account; a second box that wants the same "
                                      "password again is filled by a second call without `new`.", spec(["ref"], ref=s, then_click=s, new=b), self.type_password),
            llm.Tool("sign_in_by_hand", "Hand the window to the applicant for something only they can do: a sign-in without a stored password, a code on their phone, a CAPTCHA. "
                                        "Ends this run; the next one goes on from here.", spec(["why"], why=s), self.sign_in_by_hand),
            llm.Tool("report", "End the run. outcome: ready (everything is in, one press from sending, not sent) | submitted (it went out: give the confirmation) | "
                               "needs_you (only the applicant can go on) | cannot (say why, and what the page shows).",
                     spec(["outcome", "summary"], outcome={"type": "string", "enum": list(OUTCOMES)}, summary=s, answers={"type": "array", "items": answer},
                          files={"type": "array", "items": gave}, open=arr, confirmation=conf, sent=b), self.report),
        ]


def journal_text(folder: Path) -> str:
    """What earlier runs wrote down, for the next one: the agent's own lines, what it asked, how each run ended."""
    p = folder / "journal.jsonl"
    if not p.exists():
        return ""
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("kind") == "log":
            out.append(f"{e['at']} {e['text']}")
        elif e.get("kind") == "report":
            out.append(f"{e['at']} RUN ENDED: {e.get('outcome')} - {e.get('summary')}")
        elif e.get("kind") == "ended":
            out.append(f"{e['at']} RUN ENDED WITHOUT A REPORT ({e.get('why')}), after {e.get('steps')} tool calls")
        elif e.get("kind") == "needs_applicant":
            out.append(f"{e['at']} WAITED FOR THE APPLICANT: {e.get('why')}")
        elif e.get("kind") == "ask":
            out.append(f"{e['at']} asked the applicant: {e.get('question')}")
    return "\n".join(out)


def apply(page: Any, posting: brief.Posting, applicant: brief.Applicant, folder: Path, *, mode: str = "prepare", answers: dict[str, str] | None = None) -> Result:
    """Run the agent on one application, on ``page``. Everything it leaves behind is in ``folder``."""
    from .. import agentbudget, sites

    site = brief.site_key(posting.url)
    hands = Hands(page, files=applicant.files, shots=folder / "shots")
    desk = Desk(folder, hands, site=site, mode=mode, login=applicant.login, answers=answers)
    record = None
    if (folder / "record.json").exists():
        try:
            record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        except ValueError:
            record = None
    budget = agentbudget.for_kind("apply")
    systems = sorted(k.split(":", 1)[1] for k in _keys_with_notes() if k.startswith("system:"))
    goal = brief.goal(posting, applicant, mode=mode, site_notes=sites.notes(site), systems=systems, journal=journal_text(folder), record=record, answers=answers,
                      account=desk.account(), budget=f"About {budget.steps} tool calls and {int(budget.seconds // 60)} minutes for this run. Log where you are before it runs out.")
    (folder / "brief.md").write_text(goal, encoding="utf-8")
    desk.write("run", mode=mode, url=posting.url)
    began, res = time.monotonic(), Result()
    try:
        page.goto(posting.url, wait_until="domcontentloaded")
    except Exception as e:  # noqa: BLE001 - the agent sees what the window shows and decides
        desk.write("log", text=f"(the program could not open the posting's address by itself: {type(e).__name__})")
    try:
        out = llm.agent(goal, hands.tools() + desk.tools(), system=brief.manual(), kind="apply", on_step=desk.step, budget=budget)
        res.stopped, res.steps, res.said = out.stopped or "end_turn", len(out.steps), (out.final_text or "")[:2000]
        res.usage = dict(out.budget or {})
    except llm.LLMError as e:
        res.stopped = f"{type(e).__name__}: {str(e)[:300]}"
    if desk.reported is not None:
        res.outcome, res.record = desk.reported["outcome"], desk.reported
    elif desk.waiting:
        res.outcome, res.record = "needs_you", {"outcome": "needs_you", "summary": desk.waiting, "asked": list(desk.asked)}
    else:
        desk.write("ended", why=res.stopped, steps=res.steps)
    res.seconds = round(time.monotonic() - began, 1)
    return res


def _keys_with_notes() -> list[str]:
    from .. import db
    from ..models import Site

    try:
        with db.session() as s:
            return [r.key for r in s.query(Site) if (r.notes or "").strip()]
    except Exception:  # noqa: BLE001 - how notes are stored is not this module's to depend on
        return []

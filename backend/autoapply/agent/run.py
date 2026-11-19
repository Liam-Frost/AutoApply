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
from ..errors import tolerated
from . import brief
from .hands import Hands

OUTCOMES = ("ready", "submitted", "needs_you", "cannot")
STOP = "stop"       # a file of this name in the application's folder: the applicant says "stop" (work.stop)


class _Budget:
    """What one run may spend - and the applicant's word: with ``stop`` in the application's folder, the next action
    is not carried out and the run ends ("stopped")."""

    def __new__(cls, steps: int, seconds: float, folder: Path):  # noqa: ANN204
        from .. import agentbudget

        class Stoppable(agentbudget.Budget):
            def spend(self) -> None:
                if (folder / STOP).exists():
                    self.ended = "stopped"
                    raise agentbudget.Spent("stopped")
                super().spend()

        return Stoppable(steps, seconds, "apply")


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

    def __init__(self, folder: Path, hands: Hands, *, site: str, mode: str, login: str = "", answers: dict[str, str] | None = None, job_id: int | None = None,
                 home: str = "", on_hand: Any = None) -> None:
        self.folder, self.hands, self.site, self.mode, self.login, self.job_id = folder, hands, site, mode, login, job_id
        self.on_hand = on_hand           # called when the window is given to the applicant: the program tells them
        self.home = home.lower()         # the host of the posting: where this site is
        self.answers = dict(answers or {})
        self.asked: list[dict[str, Any]] = []
        self.reported: dict[str, Any] | None = None
        self.waiting = ""                # what the run stopped for, when it handed the window to the applicant
        self.hidden: set[str] = set()    # the passwords of this site: never in what a tool answers or the journal holds (guard)
        folder.mkdir(parents=True, exist_ok=True)

    # --- the journal ---------------------------------------------------------------------------------------------
    def write(self, kind: str, **what: Any) -> None:
        with open(self.folder / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(self._clean(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, **what}, ensure_ascii=False, default=str)) + "\n")

    # --- what the program types for the applicant stays out of what the agent reads ----------------------------------
    # The agent has the whole page in its hands - a script, the list of controls, a picture. A password the program
    # typed into a box is on that page until the form is sent (a registration asks for it twice), and a page can show
    # it in clear. So the limit is held where the tools answer: the passwords of this site are taken out of every
    # answer and of the journal, and a box that holds one is covered while a picture is taken. (A password that only
    # the browser knows - filled in by its own password manager - is hidden in the list of controls and in pictures;
    # the program cannot take out of a script's answer what it does not know.)
    def _clean(self, text: str) -> str:
        for pw in self.hidden:
            if pw in text:
                text = text.replace(pw, "(hidden)")
        return text

    def clean(self, out: Any) -> Any:
        if isinstance(out, str):
            return self._clean(out)
        if isinstance(out, list):
            return [{**b, "text": self._clean(b["text"])} if isinstance(b, dict) and isinstance(b.get("text"), str) else b for b in out]
        return out

    _COVER = """() => { const walk = (root) => { for (const e of root.querySelectorAll('*')) {
        if (e.tagName === 'INPUT' && (e.getAttribute('type') || '').toLowerCase() === 'password') e.setAttribute('data-aa-secret', '');
        else if (e.hasAttribute && e.hasAttribute('data-aa-secret') && !e.hasAttribute('data-aa-covered')) { e.setAttribute('data-aa-covered', e.style.webkitTextSecurity || ''); e.style.webkitTextSecurity = 'disc'; }
        if (e.shadowRoot) walk(e.shadowRoot); } }; walk(document); }"""
    _UNCOVER = """() => { const walk = (root) => { for (const e of root.querySelectorAll('*')) {
        if (e.hasAttribute && e.hasAttribute('data-aa-covered')) { e.style.webkitTextSecurity = e.getAttribute('data-aa-covered'); e.removeAttribute('data-aa-covered'); }
        if (e.shadowRoot) walk(e.shadowRoot); } }; walk(document); }"""

    def _picture(self, take: Any) -> Any:
        """Take a picture with every box that holds (or held) a password covered."""
        try:
            self.hands.page.evaluate(self._COVER)
        except Exception:  # noqa: BLE001 - between two pages: there is no box to cover
            pass
        try:
            return take()
        finally:
            try:
                self.hands.page.evaluate(self._UNCOVER)
            except Exception:  # noqa: BLE001
                pass

    def guard(self, tools: list[llm.Tool]) -> list[llm.Tool]:
        """The same tools, answering without the passwords of this site in what they say."""
        from .. import secrets

        try:
            stored = secrets.get_password(self.site) or ""
        except Exception:  # noqa: BLE001 - no store to ask: what is typed in this run is still known
            stored = ""
        if len(stored) >= 6:
            self.hidden.add(stored)

        def kept(t: llm.Tool) -> llm.Tool:
            def run(**kw: Any) -> Any:
                try:
                    return self.clean(self._picture(lambda: t.fn(**kw)) if t.name == "look" else t.fn(**kw))
                except Exception as e:  # noqa: BLE001 - told to the agent as it is, without what is hidden
                    if any(pw in str(e) for pw in self.hidden):
                        raise RuntimeError(self._clean(f"{type(e).__name__}: {e}")) from None
                    raise
            return llm.Tool(t.name, t.description, t.input_schema, run)

        return [kept(t) for t in tools]

    def step(self, step: dict[str, Any]) -> None:
        """A tool call, as the model's run reports it."""
        if step.get("event") == "summarized":      # not a tool call: the conversation grew long and its older part was summarized
            n = step.get("tokens_before")
            self.write("log", text="(the conversation grew long" + (f", about {int(n):,} tokens" if n else "") + ": the model's program summarized its older part here. "
                                   "What the run was told at its start is unchanged; what pages showed earlier may need to be looked at again.)")
            return
        inp = {k: (v if len(str(v)) < 300 else str(v)[:300] + "…") for k, v in (step.get("input") or {}).items()}
        self.write("tool", tool=step.get("tool"), input=inp, ok=step.get("ok"), output=str(step.get("output") or "")[:600], ms=step.get("ms"))

    def log(self, text: str) -> str:
        self.write("log", text=str(text)[:1000])
        return "written down."

    def sending(self, button: str = "") -> str:
        """Called immediately before the press that sends the application. If the run is cut off after this and
        before its report, the application may be out: the program then finds that out before anything is pressed
        again (work.py)."""
        if self.mode in ("prepare", "hand_over", "verify"):
            return "This run does not send the application (see Mode). Do not press it."
        self.write("sending", button=str(button)[:120], url=self.hands.page.url)
        return "noted. Press it now, then report what the site answers."

    def hand_window(self, minutes: float = 20) -> str:
        """The window is the applicant's: they look the application over and press the last button themselves. Waits
        until they close the window or the time is up, then gives it back."""
        self.write("handed", url=self.hands.page.url)
        if self.on_hand is not None:
            try:
                self.on_hand()
            except Exception:  # noqa: BLE001 - the window is theirs whether or not they could be told
                pass
        until = time.monotonic() + max(1.0, min(float(minutes or 20), 60.0)) * 60
        while time.monotonic() < until:
            try:
                if not [p for p in self.hands.page.context.pages if not p.is_closed()]:
                    return "The applicant closed the window. Nothing more can be seen in it: report what you know (ready, unless you saw it go out)."
            except Exception:  # noqa: BLE001 - the window is gone
                return "The window is gone. Report what you know (ready, unless you saw it go out)."
            if self.hands.page.evaluate("() => !!window.__aaDone"):
                break
            time.sleep(2)
        return "The window is yours again. Look at what it shows now and at the site's list of applications, and report what the applicant did."

    # --- the site's notes ----------------------------------------------------------------------------------------
    def note(self, text: str, about: str = "") -> str:
        from .. import sites

        key = f"system:{about.strip().lower()}" if about.strip() else self.site
        sites.note(key, str(text)[:1200])
        self.write("note", about=key, text=str(text)[:1200])
        return f"noted for {key}."

    def notes(self, about: str) -> str:
        return brief.about(about) or f"nothing is written down about {about!r}."

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

    def type_password(self, ref: str, then_click: str = "", new: bool = False, length: int = 20, symbols: str = "!@#$%^&*") -> str:
        """The applicant's password for this site, typed by the program into the box ``ref``; then ``then_click`` is
        pressed. The agent never has the password: the box is emptied again before control goes back, unless the
        page has moved on. ``new``: a password is made up and stored first (registering an account) - to the rules
        the agent read on the page: ``length``, and which punctuation it may hold (``symbols``, empty for none).
        (It was always twenty characters; a site that takes eighteen at most refused it, and the agent, who could read
        the rule and not the password, had no way to say so.)"""
        from .. import auth, secrets

        at = self.hands._at(ref)
        if at["type"] != "password" and not at.get("secret"):
            raise PermissionError(f"[{ref}] is not a password box")
        here = self._host()
        if new:
            pw = secrets.generate_password(max(8, min(int(length or 20), 64)), symbols="".join(c for c in str(symbols) if not c.isalnum() and not c.isspace())[:16])
            self._belongs_here(here)      # an account is being made on this address: its password belongs here from now on
            auth.upsert_account(self.site, host=self.site.split(":", 1)[-1], email=self.login, password=pw, status="pending", created_by="agent")      # kept before it is sent
        else:
            pw = secrets.get_password(self.site) or ""
            if not pw:
                return "No password is stored for this site. Register with new=true if the applicant has no account here, or use sign_in_by_hand."
            if not self._is_home(here):
                # The stored password is typed where this site's sign-in lives - the site itself, or an address the
                # applicant signed in on for it - and nowhere else: a page that only looks like it gets nothing.
                raise PermissionError(f"this page is on {here or 'no site'}, which is not where the password of this site belongs ({', '.join(sorted(self._homes())) or 'no address on record'}). "
                                      "If the site's sign-in really lives here, the applicant signs in by hand once (sign_in_by_hand); it is known from then on.")
        if len(pw) >= 6:
            self.hidden.add(pw)
        page = self.hands.page
        page.mouse.click(at["x"], at["y"])
        time.sleep(0.15)
        page.evaluate("() => { const e = window.__aaAt; if (e) { e.setAttribute('data-aa-secret', ''); if (e.select) e.select(); } }")
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

    def cover_letter(self, instructions: str = "") -> str:
        """Write a cover letter for this posting from the applicant's profile and résumé (the program's own letter
        writer, with its checks) and add it to the files that may be uploaded."""
        from .. import db, materials
        from ..models import Job

        if not self.job_id:
            return "No cover letter can be written here (this application is not one of the program's postings)."
        got = materials.existing_cover_letter(self.job_id) if not instructions.strip() else None
        if got is None:
            with db.session() as s:
                job = s.get(Job, self.job_id)
                s.expunge(job)
            got = materials.make_cover_letter(job, instructions=str(instructions)[:1000])
        self.hands.files[got["name"]] = got["path"]
        self.write("cover_letter", name=got["name"], problems=got.get("problems") or [])
        return (f"The cover letter is the file {got['name']!r}: upload it by that name."
                + (f" The program's checks still object to: {'; '.join(got['problems'])[:400]}. Say so in your report." if got.get("problems") else ""))

    def mail(self, minutes: int = 15, about: str = "") -> str:
        """What arrived in the applicant's mailbox in the last minutes from this site: a code, a confirmation link.
        Only mail that names the site or the employer; the mailbox is read, never written to."""
        from datetime import timedelta, timezone

        from .. import mailbox

        try:
            got = mailbox.fetch(datetime.now(timezone.utc) - timedelta(minutes=max(1, min(int(minutes or 15), 120))), limit=25)
        except Exception as e:  # noqa: BLE001 - no mailbox connected: the applicant reads it
            return f"The applicant's mailbox cannot be read from here ({type(e).__name__}). If the site waits for a code or a link from a mail, hand over with sign_in_by_hand."
        host = self.hands.page.url.split("/")[2].lower() if "//" in self.hands.page.url else ""
        words = {w for w in [*host.replace("www.", "").split(".")[:-1], *self.site.split(":", 1)[-1].replace("www.", "").split(".")[:-1], *str(about).lower().split()] if len(w) > 2}
        hits = [m for m in got if any(w in f"{m.sender} {m.subject} {m.body[:3000]}".lower() for w in words)]
        self.write("mail", found=len(hits))
        if not hits:
            return f"No mail about this site has arrived in the last {minutes} minutes (looked for: {', '.join(sorted(words)) or 'nothing to look for'}). It can take a minute: wait and ask again."
        return "\n\n".join(f"From: {m.sender}\nSubject: {m.subject}\nReceived: {m.date}\n{m.body[:2500]}" for m in hits[:3])

    def _host(self) -> str:
        from urllib.parse import urlparse

        try:
            return (urlparse(self.hands.page.url).hostname or "a-local-file").lower()      # (a page that is on no host is still a place)
        except Exception:  # noqa: BLE001
            return "a-local-file"

    def _homes(self) -> set[str]:
        from .. import auth, sites

        acct = auth.account(self.site) or {}
        return {h.lower() for h in [self.home, str(acct.get("host") or ""), *(sites.fact(self.site, "sign_in_hosts") or [])] if h}

    def _is_home(self, host: str) -> bool:
        from .. import auth

        homes = self._homes()
        return host in homes or (bool(host) and any(auth._site(host) == auth._site(h) and host.endswith(auth._site(h)) for h in homes))

    def _belongs_here(self, host: str) -> None:
        from .. import sites

        if not self._is_home(host):
            sites.set_fact(self.site, "sign_in_hosts", sorted({*(sites.fact(self.site, "sign_in_hosts") or []), host}))

    def sign_in_by_hand(self, why: str) -> str:
        self.waiting = str(why)[:600]
        self.write("needs_applicant", why=self.waiting, url=self.hands.page.url)
        return "The window is the applicant's from here. This run is over: call report with outcome needs_you, saying what you had done up to here."

    # --- the end ---------------------------------------------------------------------------------------------------
    def report(self, outcome: str, summary: str, answers: list[dict[str, Any]] | None = None, files: list[dict[str, Any]] | None = None,
               open: list[str] | None = None, confirmation: dict[str, Any] | None = None, sent: bool = False, not_sent: str = "") -> str:  # noqa: A002
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome is one of {OUTCOMES}")
        if outcome == "submitted" and not (confirmation and str(confirmation.get('words') or '').strip() and str(confirmation.get('ties_to_posting') or '').strip()):
            raise ValueError("an application that went out is reported with its confirmation: the page's own words, its address, and what ties it to this posting")
        try:
            at = str(self.hands.page.url)
        except Exception:  # noqa: BLE001
            at = ""
        shot = ""
        if outcome == "submitted":      # the page as it stands when the agent says the application is out: kept with the evidence
            try:
                (self.folder / "confirmation.png").write_bytes(self._picture(lambda: self.hands.page.screenshot(full_page=True)))
                shot = str(self.folder / "confirmation.png")
            except Exception:  # noqa: BLE001 - the words and the address are the evidence; the picture is beside them when there is one
                pass
        self.reported = {"outcome": outcome, "summary": str(summary)[:3000], "url": at, "answers": list(answers or []), "files": list(files or []), "open": [str(x) for x in (open or [])],
                         "confirmation": dict(confirmation or {}), "sent": bool(sent or outcome == "submitted"), "asked": list(self.asked),
                         "at": datetime.now().isoformat(timespec="seconds"), "mode": self.mode}
        (self.folder / "record.json").write_text(json.dumps(self.reported, ensure_ascii=False, indent=1), encoding="utf-8")
        self.reported["not_sent"], self.reported["shot"] = str(not_sent)[:600], shot
        self.write("report", outcome=outcome, summary=str(summary)[:600], open=len(open or []), sent=self.reported["sent"], not_sent=str(not_sent)[:600])
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
            llm.Tool("log", "Write a line in this application's journal: a milestone, what you worked around.", spec(["text"], text=s), self.log),
            llm.Tool("sending", "Call this immediately BEFORE the one press that sends the application to the employer - every time, and only then. `button`: what that button is called.",
                     spec(button=s), self.sending),
            llm.Tool("hand_window", "Give the window to the applicant, who looks the application over and presses the last button themselves (a run told to stop at the last step). "
                                    "Comes back when they are done.", spec(minutes={"type": "number"}), self.hand_window),
            llm.Tool("note", "Write down something that is true of this site for whoever applies here next. `about`: a recruiting system's name (workday, greenhouse ...) when it is "
                             "true of that system on every employer's site; empty for this site.", spec(["text"], text=s, about=s), self.note),
            llm.Tool("notes", "Read what is written down about a recruiting system.", spec(["about"], about=s), self.notes),
            llm.Tool("ask", "Put a question to the applicant: something the form needs and you were not given. `about`: 'applicant' when it is about them in general, 'job' when it "
                            "is about this job only. `options`: the form's choices, when it has them. `why`: where the form asks it.", spec(["question"], question=s, about=s, options=arr, why=s), self.ask),
            llm.Tool("account", "What the program has on record for this site: the login name, whether a password is stored.", spec(), self.account),
            llm.Tool("type_password", "Have the applicant's password for this site typed into the password box `ref` (you do not see it), then press `then_click` (the sign-in or "
                                      "create-account button). `new`: make up and store a password first - for registering an account; a second box that wants the same "
                                      "password again is filled by a second call without `new`. Read the site's password rules first and pass them on: `length` "
                                      "(default 20) and `symbols`, the punctuation the site allows (default !@#$%^&*; empty for none).",
                     spec(["ref"], ref=s, then_click=s, new=b, length={"type": "number"}, symbols=s), self.type_password),
            llm.Tool("mail", "Read what this site has just sent to the applicant's mailbox: a verification code, a confirmation link (open the link with goto; type the code "
                             "into its box). `minutes`: how far back; `about`: the employer's or the system's name, to find the mail by.", spec(minutes={"type": "number"}, about=s), self.mail),
            llm.Tool("cover_letter", "Have a cover letter written for this posting, when the posting or the form asks for one and none is among the files. It becomes a file you can "
                                     "upload. `instructions`: anything the letter must take into account.", spec(instructions=s), self.cover_letter),
            llm.Tool("sign_in_by_hand", "Hand the window to the applicant for something only they can do: a sign-in without a stored password, a code on their phone, a CAPTCHA. "
                                        "Ends this run; the next one goes on from here.", spec(["why"], why=s), self.sign_in_by_hand),
            llm.Tool("report", "End the run. outcome: ready (everything is in, one press from sending, not sent) | submitted (it went out: give the confirmation) | "
                               "needs_you (only the applicant can go on) | cannot (say why, and what the page shows). `not_sent`: if you called `sending` in this run and the "
                               "application did not go out, what shows that it did not.",
                     spec(["outcome", "summary"], outcome={"type": "string", "enum": list(OUTCOMES)}, summary=s, answers={"type": "array", "items": answer},
                          files={"type": "array", "items": gave}, open=arr, confirmation=conf, sent=b, not_sent=s), self.report),
        ]


def journal_text(folder: Path) -> str:
    """What earlier runs wrote down, for the next one: the agent's own lines, what it asked, how each run ended."""
    p = folder / "journal.jsonl"
    if not p.exists():
        return ""
    out: list[str] = []
    tools: list[str] = []        # the tool calls of the run being read, for a run that was cut off without a word
    ended = True

    def cut_off() -> None:
        if not ended:
            out.append("THE RUN WAS CUT OFF HERE WITHOUT A REPORT (the program or the browser stopped). Its last actions were:\n  " + "\n  ".join(tools[-14:]))

    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        kind = e.get("kind")
        if kind == "run":
            cut_off()
            ended, tools = False, []
            out.append(f"{e['at']} A RUN BEGAN (mode: {e.get('mode')})")
        elif kind == "tool":
            tools.append(f"{e.get('tool')} {json.dumps(e.get('input') or {}, ensure_ascii=False)[:160]} -> {str(e.get('output') or '')[:140]}")
        elif kind == "log":
            out.append(f"{e['at']} {e['text']}")
        elif kind == "report":
            ended = True
            out.append(f"{e['at']} RUN ENDED: {e.get('outcome')} - {e.get('summary')}")
        elif kind == "ended":
            ended = True
            out.append(f"{e['at']} RUN ENDED WITHOUT A REPORT ({e.get('why')}), after {e.get('steps')} tool calls")
        elif kind == "needs_applicant":
            out.append(f"{e['at']} WAITED FOR THE APPLICANT: {e.get('why')}")
        elif kind == "ask":
            out.append(f"{e['at']} asked the applicant: {e.get('question')}")
    cut_off()
    return "\n".join(out)


def apply(page: Any, posting: brief.Posting, applicant: brief.Applicant, folder: Path, *, mode: str = "prepare", answers: dict[str, str] | None = None,
          job_id: int | None = None, record: dict[str, Any] | None = None, budget: dict[str, float] | None = None, on_hand: Any = None) -> Result:
    """Run the agent on one application, on ``page``. Everything it leaves behind is in ``folder``."""
    from .. import agentbudget, sites

    site = brief.site_key(posting.url)
    hands = Hands(page, files=applicant.files, shots=folder / "shots")
    from urllib.parse import urlparse as _urlparse

    desk = Desk(folder, hands, site=site, mode=mode, login=applicant.login, answers=answers, job_id=job_id, home=_urlparse(posting.url).hostname or "", on_hand=on_hand)
    if record is None and (folder / "record.json").exists():
        try:
            record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        except ValueError:
            record = None
    per_run = agentbudget.for_kind("apply")
    left = budget or {"steps": per_run.steps, "seconds": per_run.seconds}      # what this application has left over all its runs, when that is less than a run's share
    (folder / STOP).unlink(missing_ok=True)       # (a word of "stop" is for the run it was said to)
    budget = _Budget(int(max(1, min(per_run.steps, left["steps"]))), max(60.0, min(per_run.seconds, left["seconds"])), folder)
    system, book = brief.playbook_for(posting.url)
    systems = sorted({*brief.playbooks(), *(k.split(":", 1)[1] for k in _keys_with_notes() if k.startswith("system:"))} - {system})
    known = "\n\n".join(x for x in ((f"About {system} (the system this site runs on):\n" + brief.about(system)) if system else "", sites.notes(site)) if x)
    goal = brief.goal(posting, applicant, mode=mode, site_notes=known, systems=systems, journal=journal_text(folder), record=record, answers=answers,
                      account=desk.account(), budget=f"About {budget.steps} tool calls and {int(budget.seconds // 60)} minutes for this run. Log where you are before it runs out.")
    (folder / "brief.md").write_text(goal, encoding="utf-8")
    desk.write("run", mode=mode, url=posting.url)
    began, res = time.monotonic(), Result()
    try:
        page.goto(posting.url, wait_until="domcontentloaded")
    except Exception as e:  # noqa: BLE001 - the agent sees what the window shows and decides
        desk.write("log", text=f"(the program could not open the posting's address by itself: {type(e).__name__})")
    try:
        out = llm.agent(goal, desk.guard(hands.tools() + desk.tools()), system=brief.manual(), kind="apply", on_step=desk.step, budget=budget)
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
            return [r.key for r in s.query(Site) if r.notes]
    except Exception as e:  # noqa: BLE001 - a brief without the list of systems is still a brief
        tolerated(e)
        return []

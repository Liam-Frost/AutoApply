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
SAID = "said.jsonl"
WINDOW = "window"            # in an application's folder: its next run opens in a window the applicant can see
WAIT_MINUTES = 10            # how long a run waits for the applicant's code or confirmation before it ends
BROWSERS = {"playwright": "the automated browser (a Chromium this program starts and drives; some sites recognise and refuse it)",
            "nodriver": "the applicant's ordinary browser (a plain Chrome window driven from outside; a site sees an ordinary visitor)"}     # what the applicant said to the agent about this application, a line each (work.say)


def said_so_far(folder: Path) -> int:
    """How many words the applicant has said to the runs of this application."""
    try:
        return sum(1 for ln in (folder / SAID).read_text(encoding="utf-8").splitlines() if ln.strip())
    except OSError:
        return 0


def say(folder: Path, text: str) -> None:
    """A word from the applicant: the run that is working this application hears it with the answer to its next action."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / SAID, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "text": str(text)[:2000]}, ensure_ascii=False) + "\n")


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
    unheard: list[str] = field(default_factory=list)      # what the applicant said too late for this run to hear
    need: dict[str, str] = field(default_factory=dict)    # what the applicant is needed for, when not a sign-in (Desk.need)


class Desk:
    """What the agent has besides the browser: the applicant's side (accounts, questions) and its own notes."""

    def __init__(self, folder: Path, hands: Hands, *, site: str, mode: str, login: str = "", answers: dict[str, str] | None = None, job_id: int | None = None,
                 home: str = "", on_hand: Any = None, heard: int | None = None) -> None:
        self.folder, self.hands, self.site, self.mode, self.login, self.job_id = folder, hands, site, mode, login, job_id
        self.on_hand = on_hand           # called when the window is given to the applicant: the program tells them
        self.home = home.lower()         # the host of the posting: where this site is
        self.answers = dict(answers or {})
        self.asked: list[dict[str, Any]] = []
        self.reported: dict[str, Any] | None = None
        self.human_seconds = 0.0
        self.upgrade_checkpoint = False
        self.sending_started = False
        self.on_checkpoint = None
        self.email_delivery = False
        self.mail_checked = False
        self.mail_reconnect = False
        self.material_task = 0
        self.waiting = ""                # what the run stopped for, when it handed the window to the applicant
        self.need: dict[str, str] = {}   # ... and which kind of thing it is, when not a sign-in: code | confirm | window
        self.card: Any = None            # (kind, why, payload) -> the id of a card on the applicant's to-do page (work.py)
        self.budget: Any = None          # this run's budget: time spent waiting for the applicant is given back to it
        self.other_browser = ""          # the browser the application is to be taken up in again (change_browser)
        self.changed_browser = False     # this run is itself the result of such a change
        self.hidden: set[str] = set()    # the passwords of this site: never in what a tool answers or the journal holds (guard)
        # How much of what the applicant said is in this run's brief already (``heard``: counted when the brief's
        # words were read - what comes after that, while the browser starts, is heard with the first action).
        self.heard = len(self._said()) if heard is None else int(heard)
        folder.mkdir(parents=True, exist_ok=True)

    # --- the journal ---------------------------------------------------------------------------------------------
    def write(self, kind: str, **what: Any) -> None:
        with open(self.folder / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(self._clean(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, **what}, ensure_ascii=False, default=str)) + "\n")
            if kind == "sending":
                import os

                f.flush()
                os.fsync(f.fileno())

    # --- what the program types for the applicant stays out of what the agent reads ----------------------------------
    # The agent has the whole page in its hands - a script, the list of controls, a picture. A password the program
    # typed into a box is on that page until the form is sent (a registration asks for it twice), and a page can show
    # it in clear. So the limit is held where the tools answer: the passwords of this site are taken out of every
    # answer and of the journal, and a box that holds one is covered while a picture is taken. (A password that only
    # the browser knows - filled in by its own password manager - is hidden in the list of controls and in pictures;
    # the program cannot take out of a script's answer what it does not know.)
    def _clean(self, text: str) -> str:
        for pw in self.hidden:
            # as it is, and as it reads inside JSON (a script's answer and the journal are JSON: a quote or a backslash
            # in a password is written with a backslash before it there, a letter outside ASCII may be written as \uXXXX)
            for form in sorted({pw, json.dumps(pw, ensure_ascii=False)[1:-1], json.dumps(pw)[1:-1]}, key=len, reverse=True):
                if form in text:
                    text = text.replace(form, "(hidden)")
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
        if (e.shadowRoot) walk(e.shadowRoot);
        if (e.tagName === 'IFRAME') { try { if (e.contentDocument) walk(e.contentDocument); } catch (err) {} } } }; walk(document); }"""
    _UNCOVER = """() => { const walk = (root) => { for (const e of root.querySelectorAll('*')) {
        if (e.hasAttribute && e.hasAttribute('data-aa-covered')) { e.style.webkitTextSecurity = e.getAttribute('data-aa-covered'); e.removeAttribute('data-aa-covered'); }
        if (e.shadowRoot) walk(e.shadowRoot);
        if (e.tagName === 'IFRAME') { try { if (e.contentDocument) walk(e.contentDocument); } catch (err) {} } } }; walk(document); }"""

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

    # --- a word from the applicant while the run is working ----------------------------------------------------------
    def _said(self) -> list[str]:
        try:
            return [json.loads(ln)["text"] for ln in (self.folder / SAID).read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, ValueError, KeyError):
            return []

    def words(self) -> list[str]:
        """What the applicant has said since this run last heard. Given once."""
        said = self._said()
        new, self.heard = said[self.heard:], len(said)
        return new

    def _with_words(self, out: Any) -> Any:
        new = self.words()
        if not new:
            return out
        for w in new:
            self.write("said", text=w)
        told = ("\n\n[THE APPLICANT SAYS, while you work - their word on this application, to weigh like anything else they told you:\n"
                + "\n".join(f"- {w}" for w in new) + ("\nIf this answers a question you asked, enter it and call `answered` for that question." if self.asked else "") + "]")
        return out + [{"type": "text", "text": told}] if isinstance(out, list) else str(out) + told

    def guard(self, tools: list[llm.Tool]) -> list[llm.Tool]:
        """The same tools, answering without the passwords of this site in what they say - and with what the applicant
        said in the meantime after it (not after `report`: a word that comes that late is for the next run)."""
        from .. import secrets

        try:
            stored = secrets.get_password(self.site) or ""
        except Exception:  # noqa: BLE001 - no store to ask: what is typed in this run is still known
            stored = ""
        if len(stored) >= 6:
            self.hidden.add(stored)

        def kept(t: llm.Tool) -> llm.Tool:
            def run(**kw: Any) -> Any:
                if self.email_delivery and t.name == "goto":
                    from ..errors import url_host

                    if url_host(str(kw.get("url") or "")) == "mail.google.com":
                        return "This is an email application. Prepare the recipient, subject, body and attachments for the applicant's review."
                if self.on_checkpoint is not None and not self.on_checkpoint(t.name):
                    raise RuntimeError("This worker no longer owns the task")
                if self.on_checkpoint is not None and not self.sending_started:
                    from .. import db, tasks
                    if tasks.retiring() or db.get_setting("runtime.upgrade_requested"):
                        self.upgrade_checkpoint = True
                        raise RuntimeError("Upgrade checkpoint reached; stop this run")
                try:
                    out = self.clean(self._picture(lambda: t.fn(**kw)) if t.name == "look" else t.fn(**kw))
                    return out if t.name in ("report", "done") else self._with_words(out)
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
        if step.get("tool") in ("mail", "sign_in_by_hand", "ask_code"):      # (what these answer is a code, or a mail)
            self.write("tool", tool=step.get("tool"), ok=step.get("ok"), ms=step.get("ms"))
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
        if self.material_task:
            return "The required cover letter is pending. Do not submit."
        if self.mode in ("prepare", "hand_over", "verify"):
            return "This run does not send the application (see Mode). Do not press it."
        self.sending_started = True
        self.write("sending", button=str(button)[:120], url=self.hands.page.url)
        return "noted. Press it now, then report what the site answers."

    def hand_window(self, minutes: float = 20) -> str:
        """The window is the applicant's: they look the application over and press the last button themselves. Waits
        until they close the window or the time is up, then gives it back."""
        start = time.monotonic()
        try:
            return self._hand_window(minutes)
        finally:
            self.human_seconds += time.monotonic() - start

    def _hand_window(self, minutes: float) -> str:
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
            self._idle(2)
        return "The window is yours again. Look at what it shows now and at the site's list of applications, and report what the applicant did."

    def _idle(self, seconds: float) -> None:
        """Wait for the applicant at the window: through the page, so that a window shown in the web page (a server
        without a screen) is served while waiting."""
        try:
            from .. import browser

            browser.idle(self.hands.page, seconds)
        except Exception:  # noqa: BLE001 - a page that cannot wait that way is waited for by the clock
            time.sleep(seconds)

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

    def answered(self, question: str, answer: str) -> str:
        """The applicant answered a question of this run by speaking to it: it is not open any more."""
        want = " ".join(str(question).split()).lower()
        hit = [q for q in self.asked if q["question"].lower() == want] or [q for q in self.asked if want and (want in q["question"].lower() or q["question"].lower() in want)]
        if len(hit) != 1:
            return ("That is not one of the questions open in this run: " + "; ".join(repr(q["question"]) for q in self.asked) if self.asked else "No question is open in this run.")
        self.asked.remove(hit[0])
        self.answers[hit[0]["question"]] = str(answer)[:1000]
        (self.folder / "questions.json").write_text(json.dumps(self.asked, ensure_ascii=False, indent=1), encoding="utf-8")
        self.write("answered", question=hit[0]["question"], answer=str(answer)[:300])
        return "The question is closed. In your report, give what you entered for it and say that it is the applicant's answer."

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
        # The press is the program's to see through. The box is emptied before control goes back, so a press that did
        # nothing cannot be left to the agent: whatever it sent afterwards would go out with an empty password and
        # count, at the site, as a wrong one. (An ordinary browser that knows a password for the page opens its own
        # list over the form when the box is clicked; the first click after that closes the list and presses nothing.)
        before = self._face(page)
        said = self.hands.click(ref=then_click)
        went = self._moved(page, before)
        how = ""
        if not went:
            try:
                page.keyboard.press("Escape")
                self.hands._at(then_click)
                page.evaluate("() => { if (window.__aaAt) window.__aaAt.click(); }")
                how = " The press did nothing at first; pressed again through the page."
            except Exception:  # noqa: BLE001 - the control is gone: the page did move
                went = True
            went = went or self._moved(page, before)
        if not went:
            try:
                page.evaluate("""() => { const b = document.querySelector('input[data-aa-secret]'); const f = b && b.form; if (!f) return;
                    const s = window.__aaAt && window.__aaAt.form === f && /^(submit|image)$/.test(window.__aaAt.type || '') ? window.__aaAt : undefined;
                    f.requestSubmit(s); }""")
                how = " Pressing the button did nothing, also through the page; the form was sent directly."
            except Exception:  # noqa: BLE001
                pass
            went = self._moved(page, before)
        left = False
        try:        # a sign-in that did not go through leaves the box filled: emptied, so that nothing on the page holds the password
            left = bool(page.evaluate("""() => { let n = 0; for (const e of document.querySelectorAll('input[type=password], input[data-aa-secret]')) { if (e.value) { n++;
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, ''); e.dispatchEvent(new Event('input', {bubbles: true})); } } return n; }"""))
        except Exception:  # noqa: BLE001 - the page moved on: there is no box left
            pass
        self.write("password", new=bool(new), sent=bool(went))
        if not went:
            return ("typed (hidden), but the form was NOT sent: pressing [" + str(then_click).strip("[]") + "] did nothing, in three ways. The password box has been emptied again. Do not send the "
                    "form yourself - it would go out with an empty password, and the site would count a failed sign-in. Look at the page (`look`) for what is in the way, "
                    "or hand the sign-in to the applicant.")
        return ("typed (hidden) and " + said + how
                + (" The password box was still filled and has been emptied again: if the page shows an error, that is the site's answer to the password that was sent - "
                   "do not send the form again yourself." if left else ""))

    @staticmethod
    def _face(page: Any) -> tuple[str, str]:
        try:
            return str(page.url), str(page.evaluate("() => document.title + '|' + (document.body ? document.body.innerText.length + '|' + document.body.innerText.slice(-400) : '')"))
        except Exception:  # noqa: BLE001
            return "", ""

    def _moved(self, page: Any, before: tuple[str, str], seconds: float = 4.0) -> bool:
        """Did anything at all happen after the press - another address, other words on the page, the box gone?"""
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            time.sleep(0.3)
            try:
                if self._face(page) != before or not page.evaluate("() => [...document.querySelectorAll('input[data-aa-secret]')].some(e => e.isConnected)"):
                    return True
            except Exception:  # noqa: BLE001 - the page is on its way somewhere else
                return True
        return False

    def cover_letter(self, instructions: str = "") -> str:
        """Write a cover letter for this posting from the applicant's profile and résumé (the program's own letter
        writer, with its checks) and add it to the files that may be uploaded."""
        from .. import db, materials
        from ..models import Job

        if not self.job_id:
            return "No cover letter can be written here (this application is not one of the program's postings)."
        from .. import tasks

        got = materials.existing_cover_letter(self.job_id)
        with db.session() as session:
            key = materials.letter_request_key(session.get(Job, self.job_id), instructions[:1000])
        if got is None or (got.get("request_key") and got["request_key"] != key):
            self.material_task = tasks.enqueue("cover_letter", ref=f"letter:{self.job_id}:{key}", payload={"job_id": self.job_id, "request_key": key, "instructions": instructions[:1000]}, priority=20)
            self.write("material_requested", task_id=self.material_task)
            return f"Cover letter task {self.material_task} is queued. Finish other fields, then stop without sending. The application resumes when the PDF is ready."
        self.hands.files[got["name"]] = got["path"]
        self.write("cover_letter", name=got["name"], problems=got.get("problems") or [])
        return (f"The cover letter is the file {got['name']!r}: upload it by that name."
                + (f" The program's checks still object to: {'; '.join(got['problems'])[:400]}. Say so in your report." if got.get("problems") else ""))

    def verify_attachment(self, file: str, selector: str) -> str:
        """Read a single visible attachment row on the current site after upload or recovery."""
        from pathlib import Path
        from urllib.parse import urlsplit
        import hashlib

        if file not in self.hands.files or not selector.strip():
            raise ValueError("Choose an available file and its attachment row.")
        row = self.hands.page.evaluate("""(selector) => {
            const rows = [...document.querySelectorAll(selector)].filter(e => e.getClientRects().length);
            if (rows.length !== 1 || rows[0].matches('html, body, input, textarea')) return '';
            return (rows[0].innerText || '').trim();
        }""", selector)
        local = Path(self.hands.files[file])
        if not row or len(row) > 500 or local.name.casefold() not in row.casefold():
            return "Unverified: the named file was not read back in a single visible attachment row."
        url = urlsplit(self.hands.page.url)
        self.write("attachment_observed", file=file, local_sha256=hashlib.sha256(local.read_bytes()).hexdigest(),
                   url=url._replace(query="", fragment="").geturl(), evidence=self._clean(row))
        return "Recorded the filename shown in the site's attachment row. Check the site for pending uploads or errors."

    def tailor_resume(self, instructions: str = "") -> str:
        """Have the applicant's résumé rewritten for this posting (the program's own writer: within what the applicant's
        settings allow, checked against the original) and add it to the files that may be uploaded."""
        from .. import db, tailor
        from ..models import Job

        if not self.job_id:
            return "No résumé can be rewritten here (this application is not one of the program's postings): use the résumé as it is."
        if (tailor.settings().get("mode") or "off") == "off":
            return "The applicant has switched off rewriting their résumé for postings: use the résumé as it is."
        if tailor.base_doc() is None:
            return "There is no Word résumé of the applicant's to rewrite (only a Word file can be): use the résumé as it is."
        with db.session() as s:
            job = s.get(Job, self.job_id)
            s.expunge(job)
        try:
            doc = tailor.make(job, instructions=str(instructions)[:1000], automatic=True)
        except Exception as e:  # noqa: BLE001 - told to the agent: the application goes on with the résumé as it is
            self.write("resume", failed=f"{type(e).__name__}: {str(e)[:200]}")
            return f"The résumé could not be rewritten ({type(e).__name__}: {str(e)[:200]}): use the résumé as it is."
        info = doc.get("tailor") or {}
        if not doc.get("current"):
            why = "; ".join(map(str, info.get("problems") or [])) or "it came out the same as the original"
            self.write("resume", failed=why[:300])
            return f"Nothing usable came of rewriting it ({why[:400]}): use the résumé as it is."
        self.hands.files[doc["name"]] = doc["path"]
        self.write("resume", name=doc["name"])
        said = (f"The rewritten résumé is the file {doc['name']!r}: upload it wherever the form takes a résumé, in place of the general one "
                "(also where the general one was uploaded before).")
        if self.mode == "auto" and db.get_setting("tailor.review"):
            # the applicant's setting: a résumé written just now is looked at by them before it goes out
            self.mode = "prepare"
            said += (" The applicant has set that they look at a résumé written just now before it goes out: finish the application with it, "
                     "do not send it in this run, and report `ready`.")
        return said

    def mail(self, minutes: int = 15, about: str = "") -> str:
        """What arrived in the applicant's mailbox in the last minutes from this site: a code, a confirmation link.
        Only mail that names the site or the employer; the mailbox is read, never written to."""
        from datetime import timedelta, timezone

        from .. import mail, mailbox

        self.mail_checked = True
        self.write("mail_attempt")
        try:
            got = mailbox.fetch(datetime.now(timezone.utc) - timedelta(minutes=max(1, min(int(minutes or 15), 120))), limit=25)
        except mail.GmailReconnect:
            self.mail_reconnect = True
            self.write("mail_unavailable", reason="reconnect")
            return ("The mailbox's authorization has run out; the applicant is told to renew it in the settings. For a code the site waits for now: ask_code. "
                    "For a link to open in a mail: tell them which mail and wait (wait_for_applicant). The employer account does not need registering again.")
        except Exception as e:  # noqa: BLE001 - no mailbox connected: the applicant reads it
            self.write("mail_unavailable", reason=type(e).__name__)
            return (f"The applicant's mailbox cannot be read right now ({type(e).__name__}). It may be a moment's trouble: try once more. If it still cannot be read and "
                    "the site waits for a code from a mail: ask_code. For a link in a mail: tell them which mail to open and wait (wait_for_applicant).")
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

    # --- what only the applicant can give, asked for while the run waits -------------------------------------------
    # A code runs out in minutes and an approved sign-in not much later: a run that ends there and is taken up again
    # tomorrow finds neither. So the run stays where it is, in the same window and session, the applicant is asked on
    # their to-do page (and on their phone), and what they give comes back to the agent as the tool's answer.
    def _wait_for_card(self, todo_id: int) -> dict[str, Any] | None:
        """The card's payload once the applicant has dealt with it; None when they closed it, stopped the run, or the
        time is up. The time waited is theirs, not the run's."""
        from .. import db
        from ..models import Todo

        start = time.monotonic()
        try:
            while time.monotonic() - start < WAIT_MINUTES * 60:
                if (self.folder / STOP).exists():
                    return None
                with db.session() as s:
                    t = s.get(Todo, todo_id)
                    if t is None or t.status == "dismissed":
                        return None
                    if t.status == "done":
                        got = dict(t.payload or {})
                        t.payload = {k: v for k, v in got.items() if k != "code"}      # (a code is used once: not kept)
                        return got
                self._idle(2)
            return None
        finally:
            waited = time.monotonic() - start
            self.human_seconds += waited
            if self.budget is not None:
                self.budget.deadline += waited

    def _close_card(self, todo_id: int) -> None:
        from .. import db
        from ..models import Todo, now

        with db.session() as s:
            t = s.get(Todo, todo_id)
            if t is not None and t.status == "open":
                t.status, t.done_at = "dismissed", now()

    def _stops_for(self, kind: str, why: str) -> None:
        self.need, self.waiting = {"kind": kind, "why": str(why)[:600]}, str(why)[:600]

    def ask_code(self, what: str) -> str:
        what = " ".join(str(what).split())[:400]
        self.write("needs_applicant", need="code", why=what, url=self.hands.page.url)
        if self.card is None:
            self._stops_for("code", what)
            return "The applicant cannot be asked from here. This run is over: call report with outcome needs_you."
        todo = self.card("code", what, {})
        got = self._wait_for_card(todo)
        code = "".join(str((got or {}).get("code") or "").split())
        if code:
            self.write("code_given")
            return f"The applicant gives the code: {code}\nType it into the site now - a code runs out within minutes."
        self._close_card(todo)
        self._stops_for("code", what)
        return (f"No code came from the applicant in {WAIT_MINUTES} minutes. This run is over: call report with outcome needs_you, saying what you had done up to "
                "here. When they are back, the application is taken up again at once; have the site send a fresh code then and ask again.")

    def wait_for_applicant(self, why: str, window: bool = False) -> str:
        from .. import browser

        why = " ".join(str(why).split())[:400]
        self.write("needs_applicant", need="window" if window else "confirm", why=why, url=self.hands.page.url)
        if window and not browser.in_use()[1]:
            self._stops_for("window", why)
            return ("The applicant cannot see this window: it is hidden. This run is over: call report with outcome needs_you. When they are ready, the application is "
                    "taken up again in a window they can see; get back to this point and call wait_for_applicant again.")
        if self.card is None:
            self._stops_for("window" if window else "confirm", why)
            return "The applicant cannot be asked from here. This run is over: call report with outcome needs_you."
        todo = self.card("confirm", why, {"window": bool(window)})
        got = self._wait_for_card(todo)
        if got is not None:
            self.write("applicant_done")
            return "The applicant says it is done. The window is yours again: look at what it shows now and go on."
        self._close_card(todo)
        self._stops_for("window" if window else "confirm", why)
        return (f"The applicant did not answer in {WAIT_MINUTES} minutes. This run is over: call report with outcome needs_you, saying what you had done up to here. "
                "When they are back, the application is taken up again at once" + (", in a window they can see." if window else "."))

    # --- the browser -----------------------------------------------------------------------------------------------
    def change_browser(self, why: str) -> str:
        from .. import browser, db

        now = browser.in_use()[0] or "playwright"
        other = "playwright" if now == "nodriver" else "nodriver"
        if self.changed_browser:
            return ("This application has been tried in both browsers already (this run began after such a change). If the site refuses this one too, "
                    "report cannot and say what each of them showed.")
        if other == "nodriver" and not db.get_setting("browser.nodriver_enabled"):
            return ("The ordinary browser is switched off in the applicant's settings. Report cannot: say that the site refuses the automated browser and that "
                    "switching the ordinary browser on (Settings, browser) would let the application be tried in it.")
        self.other_browser = other
        self.write("browser", was=now, to=other, why=str(why)[:400])
        return (f"This run ends here. The application is taken up again at once in {BROWSERS[other].split(' (')[0]}; what you wrote down is in that run's "
                "brief. Stop now: no report is needed.")

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
            llm.Tool("answered", "The applicant answered a question you asked in this run by speaking to you while you worked: close it. `question`: as you asked it; "
                                 "`answer`: what they said.", spec(["question", "answer"], question=s, answer=s), self.answered),
            llm.Tool("account", "What the program has on record for this site: the login name, whether a password is stored.", spec(), self.account),
            llm.Tool("type_password", "Have the applicant's password for this site typed into the password box `ref` (you do not see it), then press `then_click` (the sign-in or "
                                      "create-account button). `new`: make up and store a password first - for registering an account; a second box that wants the same "
                                      "password again is filled by a second call without `new`. The press is seen through for you: the answer says whether the "
                                      "form was sent, and the box is emptied afterwards - never send a sign-in form yourself after this tool. In the ordinary "
                                      "browser a sign-in form may already be filled in by the browser itself (the box shows 'filled (hidden)'): pressing its "
                                      "button sends what the browser has saved, which is another way in. Read the site's password rules first and pass them on: `length` "
                                      "(default 20) and `symbols`, the punctuation the site allows (default !@#$%^&*; empty for none).",
                     spec(["ref"], ref=s, then_click=s, new=b, length={"type": "number"}, symbols=s), self.type_password),
            llm.Tool("mail", "Read what this site has just sent to the applicant's mailbox: a verification code, a confirmation link (open the link with goto; type the code "
                             "into its box). `minutes`: how far back; `about`: the employer's or the system's name, to find the mail by.", spec(minutes={"type": "number"}, about=s), self.mail),
            llm.Tool("verify_attachment", "Read back the filename from one visible employer attachment row. After upload, wait for completion and call this with the row selector. On resume check existing attachments before uploading again.", spec(["file", "selector"], file=s, selector=s), self.verify_attachment),
            llm.Tool("cover_letter", "Have a cover letter written for this posting, when the posting or the form asks for one and none is among the files. It becomes a file you can "
                                     "upload. `instructions`: anything the letter must take into account.", spec(instructions=s), self.cover_letter),
            llm.Tool("tailor_resume", "Have the applicant's résumé rewritten for this posting - reordered, and reworded where their settings allow, checked against the "
                                      "original. It becomes a file you can upload. Whether this application is better with one is yours to judge, from the posting and from "
                                      "what the brief says the applicant wants. `instructions`: anything the rewriting must take into account.", spec(instructions=s), self.tailor_resume),
            llm.Tool("ask_code", "Ask the applicant for a one-time code that the site sent them and that you cannot read yourself: it went to their phone, or `mail` could "
                                 "not read the mailbox. They type it on their to-do page; you get it back as this tool's answer and type it into the site. Waits up to "
                                 f"{WAIT_MINUTES} minutes, in this window and session. `what`: where the site says it sent the code and what it looks like, in the "
                                 "applicant's language (six digits, to the phone ending in 42).", spec(["what"], what=s), self.ask_code),
            llm.Tool("wait_for_applicant", "Wait while the applicant does something only they can do, then go on in the same window and session. `window` false: it happens "
                                           "away from this window - they approve a sign-in on their phone, tap a number in an authenticator app. `window` true: they must "
                                           "act in this browser window - a CAPTCHA, a puzzle, a passkey prompt. `why`: what they are to do, in their language. Comes back "
                                           f"when they say they are done (up to {WAIT_MINUTES} minutes).", spec(["why"], why=s, window=b), self.wait_for_applicant),
            llm.Tool("change_browser", "Take this application up again in the other of the program's two browsers (the brief says which one this run is in). For a site "
                                       "that refuses or breaks in this one: a page that says access is forbidden or restricted, an endless check, a form that will not "
                                       "load - while nothing says the posting itself is gone. Ends this run; the next begins at once.", spec(["why"], why=s), self.change_browser),
            llm.Tool("sign_in_by_hand", "Hand the sign-in to the applicant: a site whose password is not stored and that you cannot register on, a sign-in that is another "
                                        "service's own. They sign in once in a window of their own and the session is kept. Ends this run; the next one goes on from "
                                        "here. (A code, a CAPTCHA, a confirmation on their phone are not this: ask_code, wait_for_applicant.)", spec(["why"], why=s), self.sign_in_by_hand),
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
        elif kind == "attachment_observed":
            out.append(f"{e['at']} The site showed attachment {e.get('file')!r} at {e.get('url')}. Check the current row before uploading again.")
        elif kind == "needs_applicant":
            out.append(f"{e['at']} WAITED FOR THE APPLICANT: {e.get('why')}")
        elif kind == "ask":
            out.append(f"{e['at']} asked the applicant: {e.get('question')}")
        elif kind == "said":
            out.append(f"{e['at']} THE APPLICANT SAID, while the run worked: {e.get('text')}")
    cut_off()
    return "\n".join(out)


def apply(page: Any, posting: brief.Posting, applicant: brief.Applicant, folder: Path, *, mode: str = "prepare", answers: dict[str, str] | None = None,
          job_id: int | None = None, record: dict[str, Any] | None = None, budget: dict[str, float] | None = None, on_hand: Any = None, heard: int | None = None, on_checkpoint: Any = None, email_delivery: bool = False, card: Any = None,
          changed_browser: bool = False) -> Result:      # noqa: PLR0913
    """Run the agent on one application, on ``page``. Everything it leaves behind is in ``folder``."""
    from .. import agentbudget, sites

    site = brief.site_key(posting.url)
    hands = Hands(page, files=applicant.files, shots=folder / "shots")
    from urllib.parse import urlparse as _urlparse

    desk = Desk(folder, hands, site=site, mode=mode, login=applicant.login, answers=answers, job_id=job_id, home=_urlparse(posting.url).hostname or "", on_hand=on_hand, heard=heard)
    desk.on_checkpoint = on_checkpoint
    desk.card, desk.changed_browser = card, changed_browser
    desk.email_delivery = email_delivery
    if record is None and (folder / "record.json").exists():
        try:
            record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        except ValueError:
            record = None
    per_run = agentbudget.for_kind("apply")
    left = budget or {"steps": per_run.steps, "seconds": per_run.seconds}      # what this application has left over all its runs, when that is less than a run's share
    (folder / STOP).unlink(missing_ok=True)       # (a word of "stop" is for the run it was said to)
    budget = _Budget(int(max(1, min(per_run.steps, left["steps"]))), max(60.0, min(per_run.seconds, left["seconds"])), folder)
    desk.budget = budget
    system, book = brief.playbook_for(posting.url)
    systems = sorted({*brief.playbooks(), *(k.split(":", 1)[1] for k in _keys_with_notes() if k.startswith("system:"))} - {system})
    known = "\n\n".join(x for x in ((f"About {system} (the system this site runs on):\n" + brief.about(system)) if system else "", sites.notes(site)) if x)
    from .. import browser as _browser

    used, seen = _browser.in_use()
    where = (f"This run works in {BROWSERS.get(used or 'playwright', used)}. Its window is "
             + ("on the applicant's screen." if seen else "hidden from the applicant.")
             + (" The application was moved here from the other browser by the run before this one." if changed_browser else ""))
    goal = brief.goal(posting, applicant, mode=mode, site_notes=known, systems=systems, journal=journal_text(folder), record=record, answers=answers, browser=where,
                      account=desk.account(), budget=f"About {budget.steps} tool calls and {int(budget.seconds // 60)} minutes for this run. Log where you are before it runs out.")
    (folder / "brief.md").write_text(goal, encoding="utf-8")
    desk.write("run", mode=mode, url=posting.url)
    began, res = time.monotonic(), Result()
    navigation_limit = min(60.0, budget.seconds)
    try:
        page.goto(posting.url, wait_until="domcontentloaded", timeout=int(navigation_limit * 1000))
    except Exception as e:  # noqa: BLE001 - the agent sees what the window shows and decides
        from ..errors import SiteDown, unreachable
        if (unreachable(e) or type(e).__name__ == "TimeoutError") and str(page.url or "") in ("", "about:blank", "chrome-error://chromewebdata/"):
            raise SiteDown(f"{posting.url}: {type(e).__name__}") from e
        desk.write("log", text=f"(the program could not open the posting's address by itself: {type(e).__name__})")
    navigation = time.monotonic() - began
    try:
        out = llm.agent(goal, desk.guard(hands.tools() + desk.tools()), system=brief.manual(), kind="apply", on_step=desk.step, budget=budget)
        res.stopped, res.steps, res.said = out.stopped or "end_turn", len(out.steps), (out.final_text or "")[:2000]
        res.usage = dict(out.budget or {})
    except llm.LLMError as e:
        res.stopped = f"{type(e).__name__}: {str(e)[:300]}"
    res.need = dict(desk.need)
    if desk.other_browser and (desk.reported is None or desk.reported["outcome"] != "submitted"):
        res.outcome, res.record = "other_browser", {"outcome": "other_browser", "browser": desk.other_browser, "asked": list(desk.asked)}
    elif desk.reported is not None:
        res.outcome, res.record = desk.reported["outcome"], desk.reported
    elif desk.waiting:
        res.outcome, res.record = "needs_you", {"outcome": "needs_you", "summary": desk.waiting, "asked": list(desk.asked)}
    else:
        desk.write("ended", why=res.stopped, steps=res.steps)
    if desk.material_task and not desk.waiting and not desk.asked and res.outcome != "submitted":
        res.outcome = "material_pending"
        res.record["material_task"] = desk.material_task
    if desk.mail_reconnect and res.outcome in ("needs_you", "cannot", ""):
        res.outcome = "mail_reconnect"
    if desk.upgrade_checkpoint and res.outcome not in ("submitted", "material_pending", "mail_reconnect", "needs_you", "ready"):
        res.outcome = "upgrade_checkpoint"
    res.unheard = desk.words()
    for w in res.unheard:      # said too late for this run: on the journal all the same, for the applicant and for the next run
        desk.write("said", text=w, late=True)
    elapsed = time.monotonic() - began
    active = max(0, elapsed - desk.human_seconds - max(0, navigation - navigation_limit))
    res.seconds = round(min(budget.seconds, active), 1)
    res.usage.update(navigation_seconds=round(navigation, 1), human_seconds=round(desk.human_seconds, 1), elapsed_seconds=round(time.monotonic() - began, 1))
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

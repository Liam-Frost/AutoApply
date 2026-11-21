"""Notification templates: one function per event, each returning a ``Card``.

A card renders two ways: Telegram HTML (bold heading, quoted detail, tappable
link) and plain text (stored in the notification log and shown in the UI).

Layout, top to bottom:
    icon + heading        what happened, in a few words
    subject               which job / account it is about
    fields                short "label: value" facts
    items                 a bulleted list
    detail                longer text, quoted (collapsed in Telegram when long)
    hint                  what, if anything, the user should do
    link                  where to look in the app

Cards never carry passwords, verification codes, or profile data.
"""

from __future__ import annotations

from .say import say as T

import re
from dataclasses import dataclass, field, replace
from html import escape
from typing import Any


@dataclass
class Card:
    icon: str
    heading: str
    subject: str = ""  # "Company · Title" (the company part is emphasised) or any one-line subject
    fields: list[tuple[str, str]] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    items_title: str = ""
    inline: bool = False  # fields on one line, "a 1 · b 2"
    detail: str = ""
    hint: str = ""
    path: str = ""  # app path, e.g. /drafts/12
    link: str = T("server.messages.open")
    open_url: str = ""  # where the thing itself is (an interview's meeting): a button of its own on the phone

    def _blocks(self, html: bool, base_url: str) -> str:
        e = escape if html else (lambda x: x)
        b = (lambda x: f"<b>{x}</b>") if html else (lambda x: x)
        out = [f"{self.icon} {b(e(self.heading))}"]
        if self.subject:
            head, sep, rest = self.subject.partition(" · ")
            out.append(b(e(head)) + (e(sep + rest) if sep else ""))
        body: list[str] = []
        fs = [(k, v) for k, v in self.fields if v not in ("", None)]
        colon = "：" if re.search(r"[\u4e00-\u9fff]", self.heading + "".join(k for k, _ in fs)) else ": "
        if self.inline and fs:
            body.append(" · ".join(f"{e(k)} {b(e(str(v)))}" for k, v in fs))
        else:
            body += [f"{e(k)}{colon}{e(str(v))}" for k, v in fs]
        if self.items and self.items_title:
            body.append(e(self.items_title))
        body += [f"• {e(i)}" for i in self.items]
        if self.detail:
            d = self.detail.strip()
            if html:
                body.append(f"<blockquote{' expandable' if len(d) > 240 or d.count(chr(10)) > 3 else ''}>{e(d)}</blockquote>")
            else:
                body.append("\n".join("> " + ln for ln in d.splitlines()))
        if self.hint:
            body.append(f"<i>{e(self.hint)}</i>" if html else self.hint)
        if body:
            out.append("")
            out += body
        if self.path:
            url = base_url.rstrip("/") + self.path
            out.append("")
            out.append(f'👉 <a href="{escape(url, quote=True)}">{e(self.link)}</a>' if html else f"{self.link}{colon}{url}")
        return "\n".join(out)

    def localized(self) -> "Card":
        """This card in the interface language (the card itself when that is Chinese). Names of companies and postings, and
        anything a website or the AI wrote, stay as they are: only the program's own wording is translated."""
        from . import i18n

        to = i18n.lang()
        if to == "zh":
            return self
        t = lambda x: i18n.tr(x, to)  # noqa: E731
        return replace(self, heading=t(self.heading), fields=[(t(k), t(v) if isinstance(v, str) else v) for k, v in self.fields], items=[t(i) for i in self.items],
                       items_title=t(self.items_title), detail=i18n.tr_lines(self.detail, to), hint=t(self.hint), link=t(self.link))

    def html(self, base_url: str) -> str:
        return self._blocks(True, base_url)

    def plain(self, base_url: str) -> str:
        return self._blocks(False, base_url)


def _cut(s: str, n: int) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --- task started ------------------------------------------------------------------------

def discover_started(sources: int) -> Card:
    return Card("🔎", T("server.messages.startScanningJobs"), fields=[(T("server.messages.source"), T("server.messages.text", p0=sources))])


# --- task result -------------------------------------------------------------------------

def discover_done(total: dict[str, int], new_by_source: dict[str, int], errors: dict[str, str]) -> Card:
    c = Card("🔎", T("server.messages.jobScanComplete"), path="/jobs", link=T("server.messages.viewJobList"), inline=True)
    c.fields = [(T("server.messages.read"), str(total["read"]) if total.get("read") else ""), (T("server.messages.eligible"), str(total["seen"])), (T("server.messages.add"), str(total["new"])), (T("server.messages.reposted"), str(total["back"]) if total["back"] else ""), (T("server.messages.takenDown"), str(total["offline"]) if total["offline"] else "")]
    c.items = [f"{name}　+{n}" for name, n in sorted(new_by_source.items(), key=lambda x: -x[1])[:8] if n]
    if errors:
        # sources that failed for the same reason are named together: eight boards of one service turned away by its
        # security check are one thing to know, not eight
        said: dict[str, list[str]] = {}
        for k, v in errors.items():
            why = T("server.messages.needsYouToSign") if v.startswith("needs login") else T("server.messages.theSiteRefusesAutomated") if "blocked by the site" in v else _cut(v, 80)
            said.setdefault(why, []).append(k)
        c.detail = "未能读取的来源：\n" + "\n".join(f"{'、'.join(names)}：{why}" for why, names in said.items())
        if any("安全检查拒绝" in why for why in said):
            c.hint = T("server.messages.sourcesTurnedAwayBy")
    if not total["new"] and not errors:
        c.hint = T("server.messages.noNewPostings")
    return c


def submitted(title: str, *, evidence: str, auto: bool = False, note: str = "") -> Card:
    c = Card("✅", T("server.messages.applicationSubmitted"), title, path="/jobs", link=T("server.messages.viewJob"))
    c.fields = [(T("server.messages.method"), T("server.messages.autoApproveAndSubmit") if auto else ""), (T("server.messages.notes"), T("server.messages.siteSaysYouveAlready") if note == "already applied" else "")]
    if evidence:
        c.detail = T("server.messages.confirmationPage") + _cut(evidence, 220)
    return c


def submit_unknown(title: str, *, said: str = "") -> Card:
    return Card("❓", T("server.messages.outcomeOfTheSubmission"), title, detail=_cut(said, 300), hint=T("server.messages.submitWasPressedAnd"),
                path="/todos", link=T("server.messages.openToDo"))


def failed(title: str, *, error: str) -> Card:
    return Card("❌", T("server.messages.applicationNotSubmitted"), title, detail=_cut(error, 400), hint=T("server.messages.nothingWasSubmittedSee"), path="/todos", link=T("server.messages.openToDo"))


def task_failed(kind: str, error: str) -> Card:
    what = {"apply": T("server.messages.thisApplication")}.get(kind, kind)
    return Card("⚠️", T("server.messages.notCompleted", p0=what), detail=_cut(error, 400), hint=T("server.messages.nothingWasSubmitted"), path="/runs", link=T("server.messages.viewTaskLog"))


def second_factor(site: str, method: str) -> Card:
    return Card("📱", T("server.messages.approveOnYourPhone", p0=method), site, hint=T("server.messages.theProgramIsSigning", p0=site))


def reminder(title: str, which: str, due: Any = None, date_only: bool = False) -> Card:
    """A card with a date coming up ("day_before", "day"), or one the applicant put off until now ("again")."""
    when = "" if due is None else (due.strftime("%Y-%m-%d") if date_only else due.strftime("%Y-%m-%d %H:%M"))
    heading = {"day_before": T("server.messages.dueTomorrow"), "day": T("server.messages.dueToday"), "again": T("server.messages.theTimeYouAsked")}[which]
    return Card("⏰", heading, title, fields=[(T("server.messages.time"), when)], path="/todos", link=T("server.messages.openToDo"))


ITEM_KINDS = {"deadline": T("server.messages.due"), "interview": T("server.messages.interview"), "assessment": T("server.messages.assessment"), "offer": T("server.messages.offerReply"), "info_request": T("server.messages.informationAsked"), "contact": T("server.messages.getBackTo"), "own": T("server.messages.yourItem")}


def ahead(before: int, all_day: bool) -> str:
    """How long before, in words: "30 分钟前", "1 天前", "当天"."""
    if all_day or before % 1440 == 0:
        days = before // 1440 + (1 if before % 1440 else 0)
        return T("server.messages.sameDay") if days == 0 else T("server.messages.daySBefore", p0=days)
    if before % 60 == 0:
        return T("server.messages.hrBefore", p0=before // 60)
    return T("server.messages.minBefore", p0=before) if before else T("server.messages.now")


def alarm(title: str, subject: str, start: Any, all_day: bool, kind: str, before: int, link: str = "") -> Card:
    """A reminder the applicant set (or the one of its kind): what, when, and the way to it."""
    when = start.strftime("%Y-%m-%d") if all_day else start.strftime("%Y-%m-%d %H:%M")
    return Card("⏰", T("server.messages.reminder", p0=ITEM_KINDS.get(kind, '日程')), subject or title, fields=[(T("server.messages.item"), title if subject else ""), (T("server.messages.time"), when), (T("server.messages.ahead"), ahead(before, all_day))],
                path=f"/calendar?view=day&date={start.strftime('%Y-%m-%d')}", link=T("server.messages.openTheCalendar"), open_url=link)


def morning(waiting: list[str], today: list[tuple[str, str, str]], *, sent: int, replies: int) -> Card:
    """The summary each morning (chat.morning)."""
    items = [f"{t} {k}：{s}".strip() for t, k, s in today[:8]]
    return Card("☀️", T("server.messages.goodMorningToday"), fields=[(T("server.messages.needsYou"), T("server.messages.items2", p0=len(waiting))), (T("server.messages.sentYesterday"), T("server.messages.text2", p0=sent)), (T("server.messages.repliesYesterday"), T("server.messages.text3", p0=replies))],
                inline=True, items_title=T("server.messages.today") if items else "", items=items,
                detail="\n".join(f"• {w}" for w in waiting[:5]), path="/todos", link=T("server.messages.openToDo"))


def drained() -> Card:
    return Card("⏹️", T("server.messages.whatWasBeingDone"), hint=T("server.messages.noNewTaskWill"), path="/runs", link=T("server.messages.openThePlan"))


def session_saved(key: str, *, credentials: bool) -> Card:
    return Card("🔑", T("server.messages.signInSaved"), key, fields=[(T("server.messages.password"), T("server.messages.savedAsWell") if credentials else "")], path="/accounts", link=T("server.messages.viewAccount"))


def tailored(title: str, *, focus: str, problems: list[str]) -> Card:
    if problems:
        return Card("📄", T("server.messages.tailoredRSumFailed"), title, hint="；".join(problems)[:300] + T("server.messages.applicationsWillUseThe"), path="/files", link=T("server.messages.openTheLibrary"))
    return Card("📄", T("server.messages.tailoredRSumIs"), title, hint=focus[:300], path="/files", link=T("server.messages.openTheLibrary"))


def gmail_authorized() -> Card:
    from . import mail

    if mail.can_send():
        return Card("📧", T("server.messages.gmailAuthorizedReadingAnd"), hint=T("server.messages.mailAboutYourApplications2"))
    return Card("📧", T("server.messages.gmailAuthorizedReadingOnly"), hint=T("server.messages.mailAboutYourApplications"))


# --- status update -----------------------------------------------------------------------

def high_scores(rows: list[dict[str, Any]]) -> Card:
    """rows: {score, company, title, deadline}"""
    c = Card("⭐", T("server.messages.newHighScoringPostings", p0=len(rows)), path="/jobs", link=T("server.messages.viewJobList"), hint=T("server.messages.queuedTheAgentWill"))
    for r in rows[:12]:
        dl = f"　截止 {r['deadline']}" if r.get("deadline") else ""
        c.items.append(f"{r['score']:g}　{r['company']} · {_cut(r['title'], 60)}{dl}")
    if len(rows) > 12:
        c.items.append(T("server.messages.andMore", p0=len(rows) - 12))
    return c


MAIL = {
    "confirmation": ("📬", T("server.messages.applicationConfirmationReceived")),
    "rejection": ("📭", T("server.messages.applicationUnsuccessful")),
    "interview": ("🎉", T("server.messages.interviewInvitation")),
    "assessment": ("🧪", T("server.messages.onlineAssessment")),
    "offer": ("🏆", T("server.messages.jobOffer")),
    "info_request": ("❓", T("server.messages.employerNeedsMoreInformation")),
}


# What an e-mail says ABOUT an interview, an assessment or an offer when it does not announce one (mail.EVENTS).
MAIL_EVENT = {
    ("interview", "cancelled"): ("⚠️", T("server.messages.interviewCancelled")), ("interview", "changed"): ("🗓️", T("server.messages.interviewArrangementsChanged")), ("interview", "reminder"): ("⏰", T("server.messages.interviewReminder")),
    ("assessment", "cancelled"): ("⚠️", T("server.messages.assessmentCancelled")), ("assessment", "changed"): ("🗓️", T("server.messages.assessmentChanged")), ("assessment", "reminder"): ("⏰", T("server.messages.assessmentReminder")),
    ("offer", "cancelled"): ("⚠️", T("server.messages.offerWithdrawn")), ("offer", "changed"): ("📝", T("server.messages.offerUpdated")), ("offer", "reminder"): ("⏰", T("server.messages.offerWaitingForYour")),
}


def mail_label(category: str, event: str = "new") -> tuple[str, str]:
    """(icon, heading) for an e-mail: by what it is about and what it says about it."""
    return MAIL_EVENT.get((category, event)) or MAIL.get(category, ("✉️", category or T("server.messages.newEmailReceived")))


def mail_update(category: str, title: str, summary: str, *, new_status: str = "", event: str = "new") -> Card:
    icon, heading = MAIL_EVENT.get((category, event)) or MAIL.get(category, ("✉️", T("server.messages.newEmailReceived")))
    hint = (T("server.messages.readTheEMail") if event == "cancelled" and (category, event) in MAIL_EVENT
            else T("server.messages.checkTheOriginalEmail") if category in ("interview", "assessment", "offer", "info_request") else "")
    return Card(icon, heading, title, fields=[(T("server.messages.statusChangedTo"), new_status)], detail=_cut(summary, 300), hint=hint, path="/jobs", link=T("server.messages.viewJob"))


def quota_low(name: str, lines: list[tuple[str, str]], *, out: bool, backup: str, primary: bool) -> Card:
    if backup:
        hint = (T("server.messages.willSwitchToThe", p0=backup) if out else T("server.messages.whenItRunsOut", p0=backup)) if primary else T("server.messages.thisIsABackup")
    else:
        hint = T("server.messages.noBackupServiceSet")
    return Card("⛔" if out else "⚠️", T("server.messages.aiUsageLimitReached") if out else T("server.messages.aiUsageAlmostUsed"), fields=[(T("server.messages.service"), name), *lines], hint=hint, path="/settings/accounts/ai", link=T("server.messages.openSettings"))


def llm_switched(frm: str, to: str, why: str, until: str) -> Card:
    reason = (T("server.messages.usageLimitReached") if re.search(r"usage limit|limit reached|额度|quota|欠费|billing", why, re.I) else T("server.messages.tooManyRequestsRate") if re.search(r"rate.?limit|429", why, re.I)
              else T("server.messages.signInOrKey") if re.search(r"login|key|authenticat|拒绝", why, re.I) else T("server.messages.cantConnectRightNow"))
    return Card("🔁", T("server.messages.switchedToBackupAi"), fields=[(T("server.messages.previouslyUsed"), frm), (T("server.messages.nowUsing"), to), (T("server.messages.reason"), reason)],
                hint=(T("server.messages.willRetryTheOriginal", p0=until) if until else "") + T("server.messages.switchesBackAutomaticallyOnce"), path="/settings/accounts/ai", link=T("server.messages.openSettings"))



# --- to-do -------------------------------------------------------------------------------

# kind -> (icon, heading, hint)
TODO = {
    "answer": ("✍️", T("server.messages.someQuestionsNeedYour"), T("server.messages.theFormNeedsThis")),
    "review": ("📝", T("server.messages.theRecordOfThe"), T("server.messages.lookOverWhatThe")),
    "takeover": ("🔐", T("server.messages.youNeedToSign"), T("server.messages.inYourToDos")),
    "blocked": ("🚧", T("server.messages.thisSiteCantBe"), T("server.messages.theApplicationPageWont")),
    "login": ("🔐", T("server.messages.youNeedToSign"), T("server.messages.inYourToDos2")),
    "captcha": ("🤖", T("server.messages.manualVerificationNeeded"), T("server.messages.theSiteWantsA")),
    "code": ("🔢", T("server.messages.theAgentIsWaiting"), T("server.messages.theSiteSentYou")),
    "confirm": ("📲", T("server.messages.theAgentIsWaiting2"), T("server.messages.whenYouHaveDone")),
    "resume": ("⏸️", T("server.messages.theApplicationStoppedAt"), T("server.messages.whenItSuitsYou")),
    "submit": ("👆", T("server.messages.filledInUpTo"), T("server.messages.checkEverythingInThe")),
    "failed": ("❌", T("server.messages.applicationNotSubmitted"), T("server.messages.nothingWasSubmitted")),
    "facts_changed": ("🔁", T("server.messages.yourProfileChangedSome"), T("server.messages.theseApplicationsHaveBeen")),
    "mail_out": ("✉️", T("server.messages.anEMailIs"), T("server.messages.openItInThe")),
    "gone": ("📭", T("server.messages.thePostingHasBeen"), T("server.messages.nothingWasSubmittedThe")),
    "config": ("⚙️", T("server.messages.settingsNeedAttention"), ""),
    "mail_unmatched": ("📨", T("server.messages.couldntMatchEmailTo"), T("server.messages.theProgramFirstLooks")),
}


def todo(kind: str, title: str, body: str = "", *, payload: dict[str, Any] | None = None) -> Card:
    icon, heading, hint = TODO.get(kind, ("🔔", T("server.messages.needsYourAction"), ""))
    did = (payload or {}).get("draft_id")
    path, link = (f"/drafts/{did}", T("server.messages.openDraft")) if kind in ("answer", "review") and did else ("/todos", T("server.messages.openToDo"))
    return Card(icon, heading, title, detail=_cut(body, 500) if body else "", hint=hint, path=path, link=link)


def draft_ready(title: str, draft_id: int, *, answers: int, files: list[str]) -> Card:
    c = todo("review", title, payload={"draft_id": draft_id})
    c.fields = [(T("server.messages.entered"), T("server.messages.items", p0=answers)), (T("server.messages.uploaded"), "、".join(files))]
    return c


def test() -> Card:
    return Card("✅", T("server.messages.autoapplyNotificationsAreConnected"), hint=T("server.messages.taskProgressToDos"))

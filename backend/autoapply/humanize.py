"""User-facing wording for things the engine tracks with internal names.

The engine keeps tenant keys ("workday:tmx.wd3"), task kinds ("recon"), refs ("job:669") and raw
exception text. None of that belongs on screen. The API passes those through here so every page
shows a site by its employer's name, a task by what it does, and an error as one plain sentence -
with the raw text kept as collapsible "technical details" for debugging.
"""

from __future__ import annotations

from .say import say as T

import re
from collections import Counter
from typing import Any

from . import db
from .models import Application, Draft, Job

ATS = {
    "workday": "Workday", "greenhouse": "Greenhouse", "ashby": "Ashby", "lever": "Lever", "pdportal": "UBC PD Portal",
    "generic": T("server.humanize.companyWebsite"), "oracle": "Oracle", "eightfold": "Eightfold", "workable": "Workable", "smartrecruiters": "SmartRecruiters",
    "icims": "iCIMS", "successfactors": "SAP SuccessFactors", "jazzhr": "JazzHR", "": "",
}
TASK = {
    "discover": T("server.humanize.scanForNewJobs"), "score": T("server.humanize.scoreJobs"), "apply": T("server.humanize.workingThisApplication"), "recon": T("server.humanize.readApplicationFormsCreate"), "scout": T("server.humanize.readingTheLaterSteps"), "tailor": T("server.humanize.tailorRSumTo"), "revise": T("server.humanize.reviseDraftWithYour"), "reanswer": T("server.humanize.reAnswerTheDrafts"),
    "execute": T("server.humanize.fillInAndSubmit"), "mail": T("server.humanize.checkYourEmail"), "canary": T("server.humanize.selfCheck"), "site_status": T("server.humanize.checkApplicationStatusOn"), "profile_init": T("server.humanize.createProfileFromR"), "mail_reply": T("server.humanize.writeAReply"), "cover_letter": T("server.humanize.writeCoverLetter"),
    "directions": T("server.humanize.sortPostingsIntoFields"),
}
TASK_STATUS = {"queued": (T("server.humanize.queued"), ""), "running": (T("server.humanize.inProgress"), "info"), "done": (T("server.humanize.done"), "ok"), "failed": (T("server.humanize.unfinished"), "bad"), "waiting_human": (T("server.humanize.needsYou"), "warn"),
               "held": (T("server.humanize.setAside"), ""), "cancelled": (T("server.humanize.cancelled"), "")}


def ats_name(ats: str) -> str:
    return ATS.get(ats or "", (ats or "").capitalize())


def site(tenant_key: str) -> dict[str, str]:
    """{"name": employer (or host), "system": ATS label} for a tenant key such as "workday:tmx.wd3"."""
    ats, _, tenant = (tenant_key or "").partition(":")
    name = ""
    with db.session() as s:
        if ats == "generic":
            rows = s.query(Job.company).filter(Job.apply_url.like(f"%{tenant}%")).all()
        elif ats == "pdportal":
            rows = []
            name = "UBC PD Portal"
        else:
            rows = s.query(Job.company).filter(Job.ats == ats, Job.tenant == tenant).all()
            if not rows:  # tenant "tmx.wd3" vs stored "tmx"
                rows = s.query(Job.company).filter(Job.ats == ats, Job.tenant == tenant.split(".")[0]).all()
        if rows:
            name = Counter(r[0] for r in rows if r[0]).most_common(1)[0][0]
    if not name:
        name = tenant.split(".")[0].upper() if ats == "workday" else tenant
    return {"name": name, "system": "" if ats == "pdportal" else ats_name(ats)}


_CJK = re.compile(r"[一-鿿]")
_RULES: list[tuple[str, str]] = [
    (r"ChatGPT.*(usage limit|额度已用完)|hit your usage limit", T("server.humanize.yourChatgptSubscriptionHit")),
    (r"Claude subscription usage limit", T("server.humanize.yourClaudeSubscriptionHit")),
    (r"usage limit", T("server.humanize.thisAiServiceHit")),
    (T("server.humanize.chatgptConnectorNotInstalled"), T("server.humanize.theChatgptConnectorIsnt")),
    (T("server.humanize.aiServiceLimitReached"), T("server.humanize.thisAiServiceIs")),
    (r"拒绝了这个 API key|API key is missing or invalid", T("server.humanize.theApiKeyIs")),
    (r"连不上 AI 服务|cannot reach the Claude API", T("server.humanize.cantReachThisAi")),
    (T("server.humanize.noModelSelectedYet"), T("server.humanize.noModelSelectedFor")),
    (r"subscription login is not usable|not logged in", T("server.humanize.signInExpiredPlease")),
    (r"cannot reach Gmail", T("server.humanize.cantReachGmail")),
    (r"网站暂时打不开|SiteDown|HTTP 5\d\d|Server error '5\d\d|error page|empty page|could not open the posting|net::ERR|Page\.goto: Timeout|Site Maintenance|ConnectTimeout|ReadTimeout|ConnectError|ReadError|RemoteProtocolError|timed out|getaddrinfo failed|Name or service not known|Connection (reset|refused|aborted)",
     T("server.humanize.theSiteCantBe")),
    (T("server.humanize.windowClosedOrTimed"), T("server.humanize.theWindowClosedBefore")),
    (r"岗位.{0,12}已关闭|找不到这个岗位|posting not found|no longer (open|accepting|available)|job_unavailable|not found on Ashby", T("server.humanize.thisPostingHasBeen")),
    (r"captcha|human verification|人机验证", T("server.humanize.theSiteWantsA")),
    (r"already exists|already registered|已经注册过", T("server.humanize.thisEmailIsAlready")),
    (T("server.humanize.shouldAlreadyHaveAn"), T("server.humanize.youVeAppliedTo")),
    (r"Registration did not complete|registration failed|Registered, but signing in failed", T("server.humanize.automaticSignUpDidnt")),
    (r"verification e-?mail did not arrive|没有等到这封邮件|no verification e-mail", T("server.humanize.noVerificationEmailArrived")),
    (T("server.humanize.noEmailVerificationCode"), T("server.humanize.theSiteDidntAccept")),
    (r"Automatic login failed|Login did not succeed|Login failed twice|sign-in rejected", T("server.humanize.couldntSignInAutomatically")),
    (r"session has expired|session expired", T("server.humanize.yourSignInExpired")),
    (r"login required|No stored login|needs you to sign in|sign in yourself|This account needs", T("server.humanize.thisSiteNeedsYou")),
    (r"differ from the draft|mismatch", T("server.humanize.afterFillingItIn")),
    (r"form changed|drift", T("server.humanize.theApplicationFormChanged")),
    (r"no confirmation after submit", T("server.humanize.submitWasClickedBut")),
    (r"could not determine the form structure", T("server.humanize.couldntUnderstandThisSites")),
    (r"no résumé|No résumé", T("server.humanize.noRSumUploaded")),
    (r"cover-letter|cover letter", T("server.humanize.theCoverLetterCouldnt")),
    (r"interrupted|superseded", T("server.humanize.thisRunWasInterrupted")),
    (r"Locator\.|waiting for locator|TimeoutError|Timeout \d+ms|strict mode violation|is not an? <", T("server.humanize.thePageDidnT")),
    (r"KeyError|TypeError|AttributeError|ValueError|AssertionError|Traceback", T("server.humanize.somethingWentWrongInside")),
]


def explain(text: str | None) -> dict[str, str]:
    """One plain sentence for an error or status text, plus the raw text as detail when it adds anything."""
    raw = (text or "").strip()
    if not raw:
        return {"message": "", "detail": ""}
    m = re.match(r"^(confirmation|rejection|interview|assessment|offer|info_request): (.*)$", raw, re.S)
    if m:  # the latest e-mail about this application
        from .messages import MAIL

        return {"message": f"{MAIL[m.group(1)][1]}：{m.group(2)}", "detail": ""}
    if re.search(r"not on the last step of the form|could not tell which button submits", raw):
        return {"message": T("server.humanize.theFormIsFilled"), "detail": raw}
    for pat, msg in _RULES:
        if re.search(pat, raw, re.I):
            return {"message": msg, "detail": "" if raw == msg else raw}
    cjk = len(_CJK.findall(raw))
    if cjk >= 6 and not re.search(r"Error:|Exception|Locator|Call log", raw):
        return {"message": raw, "detail": ""}
    if not re.search(r"Error|Exception|Traceback|Timeout|failed|Locator|refused|invalid", raw, re.I):
        return {"message": raw, "detail": ""}  # a plain status note, not a failure
    return {"message": T("server.humanize.thisStepDidntFinish"), "detail": raw}


_NOTES: list[tuple[str, str]] = [
    (r"^This form was read up to its step \"(.*?)\"; that step did not let the program go on \(the form said: (.*?)\)\. Not read yet: (.*?)\. Answer the open questions and the reading goes on from there by itself\.$",
     T("server.humanize.thisFormWasRead")),
    (r"^While reading the form, the field \"(.*?)\" could not be filled in \((.*)\)\.$", T("server.humanize.whileReadingTheForm")),
    (r"^Proposed rule \(confirm to save to profile\): (.*)$", T("server.humanize.suggestedRuleToRemember")),
    (r"^Form changed since the approved draft v(\d+): (\d+) new or changed question\(s\) need review; the other answers are carried over\.$",
     T("server.humanize.theApplicationFormHas")),
    (r"^(?:Required file|File) '(.+?)' has no matching document\.( No résumé has been uploaded yet.*)?$", T("server.humanize.theresNoFileTo")),
    (r"^The form has no transcript field; the transcript goes in the Cover Letter slot\.$", T("server.humanize.theFormHasNo")),
    (r"^Cover letter still has open issues: (.*)$", T("server.humanize.theCoverLetterStill")),
    (r"^The later steps of this form were read by filling in this draft's answers step by step, up to the review page; nothing was submitted\. (\d+) answer\(s\) were added from your profile; "
     r"(\d+) answer\(s\) the employer's site already holds were read into the draft; (\d+) question\(s\) need your answer\.$",
     T("server.humanize.theLaterStepsHave")),
    (r"^The later steps of this form were read by filling in this draft's answers step by step, up to the review page; nothing was submitted\. (\d+) answer\(s\) were added from your profile; (\d+) question\(s\) need your answer\.$",
     T("server.humanize.theLaterStepsHave2")),
    (r"^Reading the later steps stopped at \"(.*)\": (\d+) question\(s\) there need your answer\. Answer them and the reading goes on from there; nothing was submitted\.$",
     T("server.humanize.readingTheLaterSteps2")),
    (r"^Still open: (.*)$", T("server.humanize.stillOpen")),
    (r"^Reading the later steps did not work this time; .*$", T("server.humanize.theLaterStepsCould")),
    (r"^Steps of this form that could not be read yet: (.*?)\. The form shows them only after the earlier steps are filled; .*$",
     T("server.humanize.someStepsOfThis")),
]
_BASIS: list[tuple[str, str]] = [
    (r"^carried over from approved draft v(\d+)$", T("server.humanize.usingDraftVersionYou")),
    (r"^revised per comment: (.*)$", T("server.humanize.basedOnYourFeedback")),
    (r"^materials list$", T("server.humanize.pickedFromYourUploaded")),
    (r"^no document for this slot$", T("server.humanize.noMatchingFile")),
    (r"^edited by the user$|^user edit$", T("server.humanize.enteredByYou")),
    (r"^answer cache.*$|^cache.*$", T("server.humanize.youveAnsweredThisQuestion")),
]


def _map(text: str, table: list[tuple[str, str]]) -> str:
    for pat, rep in table:
        if re.search(pat, text or "", re.S):
            out = re.sub(pat, rep, text, flags=re.S)
            if "No résumé has been uploaded" in (text or ""):
                out += T("server.humanize.noRSumUploaded2")
            return out
    return text or ""


def note(text: str) -> str:
    """A draft note in the user's language (the stored text stays as the engine wrote it)."""
    return _map(text, _NOTES)


def basis(text: str) -> str:
    return _map(text, _BASIS)


APP_STATUS = {
    "recon": T("server.humanize.readingTheApplicationForm"), "revising": T("server.humanize.revisingWithYourFeedback"), "needs_input": T("server.humanize.questionsWaitingForYour"), "draft_ready": T("server.humanize.awaitingYourApproval"),
    "approved": T("server.humanize.approvedQueuedForFilling"), "executing": T("server.humanize.fillingIn"), "drifted": T("server.humanize.applicationFormChangedRe"), "ready_to_submit": T("server.humanize.filledInNotSubmitted"),
    "submit_unknown": T("server.humanize.outcomeOfTheSubmission"), "needs_human": T("server.humanize.needsYourAction"), "failed": T("server.humanize.submissionFailed"), "submitted": T("server.humanize.submitted"), "confirmed": T("server.humanize.confirmationEmailReceived"), "assessment": T("server.humanize.writtenTestOaVa"),
    "interview": T("server.humanize.interview"), "offer": T("server.humanize.offerReceived"), "rejected": T("server.humanize.rejected"), "withdrawn": T("server.humanize.skipIt"), "returned": T("server.humanize.draftSentBack"),
}
REVIEW = {"pending": T("server.humanize.awaitingYourApproval"), "approved": T("server.humanize.approved"), "superseded": T("server.humanize.replacedByANewer"), "rejected": T("server.humanize.sentBack"), "closed": T("server.humanize.closedTheApplicationHas")}


def subject(ref: str) -> str:
    """What a task or run is about, in words: "job:669" -> "Bombardier · Intern, Software Developer"."""
    kind, _, rest = (ref or "").partition(":")
    ident = rest.split(":")[0]
    if kind in ("schedule", "manual", "unscored", ""):
        return {"schedule": T("server.humanize.scheduledRuns"), "manual": T("server.humanize.runManually"), "unscored": T("server.humanize.newlyAddedPostings")}.get(kind, "")
    if kind == "account":
        st = site(rest)
        return T("server.humanize.account", p0=st['name'])
    if kind == "config":
        return T("server.humanize.settings")
    if not ident.isdigit():
        return ""
    with db.session() as s:
        job = None
        if kind == "job":
            job = s.get(Job, int(ident))
        elif kind in ("application", "confirm"):
            a = s.get(Application, int(ident))
            job = a.job if a else None
        elif kind == "draft":
            d = s.get(Draft, int(ident))
            job = d.application.job if d else None
        return f"{job.company} · {job.title}" if job else ""


def result_summary(kind: str, status: str, result: dict[str, Any] | None) -> str:
    r = result or {}
    if status != "done":
        return ""
    if kind == "discover":
        t = r.get("total") or {}
        errs = r.get("errors") or {}
        base = (T("server.humanize.found", p0=t['read']) if t.get("read") else "") + T("server.humanize.matchedNew", p0=t.get('seen', 0), p1=t.get('new', 0)) + (T("server.humanize.takenDown", p0=t['offline']) if t.get("offline") else "")
        return base + (T("server.humanize.couldntReadSources", p0=len(errs)) if errs else "")
    if kind == "mail":
        if r.get("skipped"):
            return T("server.humanize.gmailIsntAuthorizedYet")
        return T("server.humanize.newEmailsApplicationsUpdated", p0=r.get('new_mail', 0), p1=r.get('status_updates', 0)) + (T("server.humanize.emailsDidntMatchA", p0=r['unmatched']) if r.get("unmatched") else "")
    if kind == "profile_init":
        n = int(r.get("todos") or 0)
        if r.get("applied"):
            return T("server.humanize.generatedAndSavedAs", p0=n) if n else T("server.humanize.generatedAndSavedAs2")
        if r.get("settled"):
            return T("server.humanize.theGeneratedDraftWas") if r["settled"] == "adopted" else T("server.humanize.theGeneratedDraftWas2")
        return T("server.humanize.draftGeneratedWithItem", p0=n) if n else T("server.humanize.draftGeneratedItIs")
    if kind == "score" and r.get("waits_for_profile"):
        return T("server.humanize.yourProfileIsStill")
    if kind == "score":
        return (T("server.humanize.scoredPostings", p0=r.get('scored', 0)) + (T("server.humanize.highScoringPostingsQueued", p0=r['queued_for_draft']) if r.get("queued_for_draft") else "")
                + (T("server.humanize.stillUnscoredScoringResumes", p0=r['remaining']) if r.get("remaining") else "")) if "scored" in r else T("server.humanize.scored")
    if kind == "apply":
        if r.get("already_applied"):
            return T("server.humanize.thisApplicationHasAlready")
        if r.get("skipped"):
            return T("server.humanize.notWorkedYouDecided")
        return {"submitted": T("server.humanize.sentTheConfirmationIs"), "ready": T("server.humanize.filledInUpTo"), "needs_input": T("server.humanize.aQuestionNeedsYour"), "submit_unknown": T("server.humanize.submitWasPressedThe"),
                "not_sent": T("server.humanize.checkedOnTheSite"), "goes_on": T("server.humanize.thisRunsShareOf"), "cannot": T("server.humanize.itDidNotGet"), "gone": T("server.humanize.thePostingWasTaken"), "mail_ready": T("server.humanize.theApplicationEMail"), "stuck": T("server.humanize.itStoppedAtThe"),
                "budget_used": T("server.humanize.thisApplicationsBudgetIs"), "stopped": T("server.humanize.stoppedAsYouAsked")}.get(str(r.get("status")), "")
    if kind == "recon":      # (and below: what earlier versions ran, in the history)
        if r.get("status") == "submit_unknown":
            return T("server.humanize.noDraftWasMade")
        return T("server.humanize.draftCreatedAwaitingYour") if r.get("draft_id") else ""
    if kind == "revise":
        return T("server.humanize.newVersionCreatedFrom")
    if kind == "execute":
        return {"submitted": T("server.humanize.submitted"), "ready_to_submit": T("server.humanize.filledInNotSubmitted2"), "submit_unknown": T("server.humanize.submitWasPressedThe"), "drifted": T("server.humanize.applicationFormChangedRe2"), "failed": T("server.humanize.notSubmitted"),
                "needs_human": T("server.humanize.needsYourAction"), "approved": T("server.humanize.rerunInAVisible")}.get(str(r.get("status")), "")
    if kind == "site_status":
        r = result or {}
        if r.get("linked"):
            return T("server.humanize.foundOnTheEmployers", p0=len(r['linked']))
        return {"already linked": T("server.humanize.theEmailWasAlready"), "no saved sign-in for this employer's site": T("server.humanize.noSavedSignIn"),
                "no address of the employer's site": T("server.humanize.theAddressOfThis")}.get(
            r.get("skipped", ""), T("server.humanize.readApplicationSOn", p0=r.get('read', 0)))
    if kind == "canary":
        n = int(((result or {}).get("fixtures") or {}).get("failed") or 0)
        return T("server.humanize.selfCheckDoneSaved", p0=n) if n else T("server.humanize.selfCheckComplete")
    return ""


_BROWSER = re.compile(r"^browser:(\w+) \((.*)\)$")


def browser_stage(stage: str) -> str:
    """Which browser a task worked in, as a sentence - '' for the usual one, which is not worth a line.

    The stage is written for the record ("browser:nodriver (tenant: pdportal:ubc)"); the activity page showed it as it
    stood."""
    m = _BROWSER.match(stage or "")
    if not m:
        return ""
    backend, why = m.group(1), m.group(2)
    if backend == "playwright" and why == "default":
        return ""
    name = T("server.humanize.theOrdinaryBrowser") if backend == "nodriver" else T("server.humanize.theProgramsOwnBrowser")
    if why == "task override":
        return T("server.humanize.thisTimeInYou", p0=name)
    if why == "default":
        return T("server.humanize.in", p0=name)
    if why.startswith("tenant: "):
        return T("server.humanize.inThisSitesAccount", p0=name, p1=why[8:])
    if why.startswith("domain: "):
        return T("server.humanize.inASiteRule", p0=name, p1=why[8:])
    if why.startswith("where the sign-in for "):
        return T("server.humanize.inThisSitesSign", p0=name)
    if why.startswith("signs in through "):
        return T("server.humanize.inThisSiteIs", p0=name)
    return T("server.humanize.in", p0=name)


def reused(r: dict[str, Any] | None, ats: str = "") -> str:
    """Where an answer that is used again came from, as a sentence for the draft: whose form it was given on, when, and
    whether the applicant confirmed it for this employer. '' for an answer that is not a reused one (or a draft from
    before this was kept)."""
    if not isinstance(r, dict):
        return ""
    day = str(r.get("at") or "")[:10]
    if r.get("own"):
        if r.get("confirmed"):
            return T("server.humanize.youConfirmedThisAnswer", p0=day) if day else T("server.humanize.youConfirmedThisAnswer2")
        return T("server.humanize.thisIsTheAnswer", p0=day) if day else T("server.humanize.thisIsTheAnswer2")
    who = site(f"{ats}:{r['employer']}")["name"] if r.get("employer") and ats else str(r.get("employer") or "")
    if who:
        return (T("server.humanize.thisAnswerWasLast", p0=who, p1=day) if day
                else T("server.humanize.thisAnswerWasLast2", p0=who))
    return (T("server.humanize.thisAnswerComesFrom", p0=day) if day
            else T("server.humanize.thisAnswerComesFrom2"))

"""What the settings come to, in words.

The settings are many, in several places, and what they add up to had to be worked out by the applicant: which postings
get in at all, which of the remaining ones get a draft, and how far the program then goes by itself. This reads the
rules where the program reads them - the intake filter, the thresholds of the scoring, how applications are sent
(``agent/work.py: policy``), what an application may spend - and says them, each
with the place where it is changed. Nothing is decided here: a statement that differs from what the program does is a
mistake in this file (tests/test_rules.py holds the two against each other).

``what_i_apply_to``: every line is a fact the applicant gave, a hard filter (what fails it is not taken in), a
preference (it moves the score), or a threshold. ``what_the_program_may_do``: every step, with who does it now.
"""
from __future__ import annotations

from .say import say as T

from typing import Any

from . import db

KINDS = {"fact": T("server.rules.whatYouToldThe"), "filter": T("server.rules.hardCondition"), "preference": T("server.rules.scoringPreference"), "threshold": T("server.rules.threshold"), "source": T("server.rules.source")}

SUBMIT, PREPARE, LOGINS, FILTERS = "/settings/automation/submit", "/settings/automation/prepare", "/settings/accounts/logins", "/settings/goals/filters"


def _line(kind: str, text: str, where: str, note: str = "") -> dict[str, str]:
    return {"kind": kind, "label": KINDS[kind], "text": text, "where": where, "note": note}


def _words(xs: Any) -> str:
    return "、".join(str(x) for x in (xs or []) if str(x).strip())


def what_i_apply_to() -> list[dict[str, str]]:
    from . import employers, intake, knowledge, persona

    st = db.all_settings()
    out: list[dict[str, str]] = []
    said = persona.describe(persona.get())
    out.append(_line("fact", said or T("server.rules.noSearchProfileYet"), "/settings/goals/profile"))

    r = intake.rules()
    if not r["enabled"]:
        out.append(_line("filter", T("server.rules.theHardConditionsBefore"), FILTERS))
    else:
        if r["title_any"]:
            out.append(_line("filter", T("server.rules.theTitleMustContain", p0=_words(r['title_any'])), FILTERS))
        if r["title_role_any"]:
            out.append(_line("filter", T("server.rules.andOneOfThese", p0=_words(r['title_role_any'])), FILTERS))
        if r["title_none"]:
            out.append(_line("filter", T("server.rules.theTitleMustNot", p0=_words(r['title_none'])), FILTERS))
        if r["countries"]:
            out.append(_line("filter", T("server.rules.thePlaceOfWork", p0=_words(r['countries'])), FILTERS, T("server.rules.aPostingThatNames")))
        if int(r["max_age_days"] or 0) > 0:
            out.append(_line("filter", T("server.rules.onlyPostingsFromThe", p0=int(r['max_age_days'])), FILTERS, T("server.rules.aPostingWithoutA")))
        if not any((r["title_any"], r["title_role_any"], r["title_none"], r["countries"], int(r["max_age_days"] or 0) > 0)):
            out.append(_line("filter", T("server.rules.theHardConditionsBefore2"), FILTERS))
        if r.get("exempt_sources"):
            out.append(_line("filter", T("server.rules.theSchoolPortalAnd"), FILTERS))
    fields = sorted(intake.my_fields())
    given = bool([x for x in (st["intake.programs"] or []) if str(x).strip()])
    if fields:
        out.append(_line("filter", T("server.rules.whereAPostingSays", p0=_words(fields)), FILTERS,
                         T("server.rules.fromTheFieldOf") if given else T("server.rules.fromTheFirstEntry")))

    lines = [ln.strip().lstrip("-*# ").strip() for ln in (knowledge.read("scoring") or "").splitlines()]
    lines = [ln for ln in lines if ln and not ln.lower().startswith(("scoring", "评分规则"))]
    if lines:
        for ln in lines[:8]:
            out.append(_line("preference", ln[:160], "/profile?tab=scoring"))
        if len(lines) > 8:
            out.append(_line("preference", T("server.rules.andMoreLineS", p0=len(lines) - 8), "/profile?tab=scoring"))
    else:
        out.append(_line("preference", T("server.rules.noScoringRulesYet"), "/profile?tab=scoring"))

    prio = [e for e in employers.listing() if e.get("priority") and e.get("enabled", True)]
    out.append(_line("threshold", T("server.rules.postingsScoringOrMore", p0=format(float(st['queue.min_score_for_draft']), 'g')), PREPARE))
    if prio:
        out.append(_line("threshold", T("server.rules.postingsOfPriorityEmployers", p0=len(prio), p1=format(float(st['employers.priority_min_score'] or 7.0), 'g')), PREPARE))
    watched = [e for e in employers.listing() if e.get("enabled", True)]
    # (whole sentences, not pieces put together: each of them is a text of the interface, and is translated as one)
    out.append(_line("source", T("server.rules.employerSWatchedOf", p0=len(watched), p1=len(prio)) if prio else T("server.rules.employerSWatched", p0=len(watched)), "/jobs/sources"))
    if st["sources.pdportal"]:
        out.append(_line("source", T("server.rules.theSchoolPortalIs"), "/jobs/sources"))
    if st["sources.search_terms"]:
        out.append(_line("source", T("server.rules.searchedForOnLarge", p0=_words(st['sources.search_terms'])), "/settings/goals/search"))
    return out


def _step(key: str, name: str, who: str, text: str, where: str, more: list[str] | None = None) -> dict[str, Any]:
    """``who``: "auto" the program does it by itself, "you" it waits for the applicant, "mixed" it depends (see more), "off"."""
    return {"key": key, "name": name, "who": who, "text": text, "where": where, "more": more or []}


def what_the_program_may_do() -> list[dict[str, Any]]:
    from .agent import work

    st = db.all_settings()
    out: list[dict[str, Any]] = []
    paused = bool(st["schedule.paused"])

    every = int(st["schedule.discover_minutes"] or 0)
    out.append(_step("discover", T("server.rules.findingPostings"), "off" if (paused or not every) else "auto",
                     T("server.rules.automaticRunsArePaused") if paused else T("server.rules.itScansForNew", p0=every) if every else T("server.rules.scheduledScansAreOff"),
                     "/settings/automation/schedule", [T("server.rules.newPostingsAreScored", p0=int(st['scoring.max_per_run']))]))

    cap = int(st["drafts.max_pending"] or 0)
    out.append(_step("prepare", T("server.rules.startingAnApplication"), "off" if paused else "auto",
                     T("server.rules.automaticRunningIsPaused") if paused else T("server.rules.theAgentAppliesBy"), PREPARE,
                     [T("server.rules.atMostApplicationsWait", p0=cap) if cap else T("server.rules.noLimitOnThe"), T("server.rules.applicationsYouStartYourself")]))

    policy = work.policy()
    more = []
    if st["policy.manual_companies"]:
        more.append(T("server.rules.forTheseCompaniesIt", p0=_words(st['policy.manual_companies'])))
    if policy == "auto" and st["tailor.review"] and str(st["tailor.mode"]) != "off":
        more.append(T("server.rules.whenARSum"))
    more.append(T("server.rules.whatTheFormNeeds"))
    text = {"auto": T("server.rules.whenThereIsNothing"), "approve": T("server.rules.theAgentFillsIn"),
            "hand_over": T("server.rules.theAgentStopsAt")}[policy]
    out.append(_step("submit", T("server.rules.sendingTheApplication"), {"auto": "auto", "approve": "mixed", "hand_over": "you"}[policy], text, SUBMIT, more))

    out.append(_step("accounts", T("server.rules.accountsAndSignIn"), "auto", T("server.rules.whenASiteNeeds"), LOGINS,
                     [T("server.rules.verificationCodesASecond"), T("server.rules.aSavedPasswordIs")]))
    b = (st["agent.budgets"] or {}).get("apply") or {}
    out.append(_step("budget", T("server.rules.theBudgetOfAn"), "auto", T("server.rules.anApplicationGetsAt", p0=int(b.get('steps') or 400), p1=int(b.get('minutes') or 45)),
                     "/settings/automation/permissions"))
    for s in out:
        s["more"] = [m for m in s["more"] if m]
    return out


def summary() -> dict[str, Any]:
    return {"apply": what_i_apply_to(), "allowed": what_the_program_may_do(), "paused": bool(db.get_setting("schedule.paused"))}

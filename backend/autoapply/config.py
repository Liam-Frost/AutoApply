"""Paths and runtime settings.

Everything user-specific lives under ``data/`` (git-ignored) or ``knowledge/``
(Markdown the agent and the user both edit). Secrets never live here; see
``secrets.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("AUTOAPPLY_ROOT", Path(__file__).resolve().parents[2]))
DATA = Path(os.environ.get("AUTOAPPLY_DATA", ROOT / "data"))
KNOWLEDGE = Path(os.environ.get("AUTOAPPLY_KNOWLEDGE", ROOT / "knowledge"))

DB_PATH = DATA / "app.db"
FILES = DATA / "files"  # uploaded source documents, résumés, transcripts
MATERIALS = DATA / "materials"  # generated cover letters, merged PDFs
RUNS = DATA / "runs"  # screenshots and evidence of runs (the agent's own folders are under data/agent)
SESSIONS = DATA / "sessions"  # encrypted Playwright storage states
FRONTEND_DIST = ROOT / "frontend" / "dist"

PROFILE_MD = KNOWLEDGE / "profile.md"
SCORING_MD = KNOWLEDGE / "scoring.md"
STORIES_MD = KNOWLEDGE / "stories.md"
PLAYBOOKS = KNOWLEDGE / "playbooks"

for _p in (DATA, FILES, MATERIALS, RUNS, SESSIONS, KNOWLEDGE, PLAYBOOKS):
    _p.mkdir(parents=True, exist_ok=True)

# Defaults for the key/value ``settings`` table. Anything here can be changed
# from the Settings page; secrets (tokens, passwords) are NOT stored there.
# Kept in the settings table, but the program's own record of what it found out - not something the settings page
# shows or saves. The page used to get these and send them back with everything else: a page left open wrote an older
# copy over what the program had recorded since (which browser a sign-in lives in, which site signs in on which).
STATE = frozenset({"mail.gmail_history", "schedule.draining", "schedule.drain_told", "sources.history"})
# Settings of earlier versions that are no longer settings: what the program found out about sites lives in sites.py now.
# A settings page loaded before sends them back; they are ignored.
RETIRED = frozenset({"accounts.alias", "sso.offered", "browser.visible_sites", "browser.session_made_in", "learned.drivers_written",
                     "schedule.execute_minutes", "executor.concurrency",
                     # 2.0: one agent works an application (agent/). What steered the pipeline before it - who reads a form,
                     # when a draft passes without the applicant, what a driver may do, what is learned from a run - is gone;
                     # how forms are filled is in the agent's manual and the applicant's profile.
                     "agent.pipeline", "agent.reads", "recon.provisional", "recon.walk", "fill.optional", "repair.enabled", "policy.default", "policy.per_ats",
                     "policy.manual_confidence", "auto_approve.enabled", "auto_approve.per_ats", "auto_approve.min_score", "auto_approve.min_driver_successes",
                     "auto_approve.allow_new_cover_letter", "learned.enabled", "learned.mode", "learned.share", "register.auto", "register.per_ats", "register.allow_keys",
                     "schedule.canary_minutes", "consent.acknowledge_notices", "sso.mode", "sso.sites"})

DEFAULT_SETTINGS: dict[str, object] = {
    # models
    "llm.auth": "subscription",  # older installs: "subscription" | "api_key" (Anthropic); used only while llm.provider is empty
    # which AI service: claude_subscription | anthropic | chatgpt (Codex CLI login) | openai | gemini | deepseek | qwen | openrouter | custom
    "llm.provider": "",
    # per service, for the OpenAI-compatible ones and chatgpt: {"openai": {"base_url": "", "model": "", "small_model": ""}}; keys are kept with the secrets
    "llm.providers": {},
    # What an agent may spend on one piece of work, by kind: tool calls, and minutes on the clock (agentbudget.py).
    # "apply" is one run on an application; an application has one such budget over all its runs, and the applicant
    # can give it another (agent/work.py).
    "agent.budgets": {"apply": {"steps": 400, "minutes": 45},
                      # reading the postings of a source that needs a sign-in - a school's portal (agent/scan.py)
                      "scan": {"steps": 150, "minutes": 30},
                      # reading the applicant's list of applications on an employer's site (sitestatus.py)
                      "site_status": {"steps": 60, "minutes": 15},
                      # what the applicant says to the Telegram or Discord bot (chat.py)
                      "chat": {"steps": 12, "minutes": 3}},
    # How an application is sent (the application agent): "auto" - when nothing is open, without asking; "approve" -
    # once the applicant has approved its record; "hand_over" - the agent stops at the last step and gives the window
    # to the applicant (an instruction to the agent, not a lock: see agent/apply.md).
    "submit.policy": "auto",
    "agent.parallel": 3,          # how many applications are worked at the same time (1-6); never two on one site
    "mail.send": "review",        # a mail the program wrote for the applicant: "review" - they look at it and send it; "auto" - sent when nothing is missing from it
    "agent.keep_window_minutes": 10,  # a record waiting for approval keeps its window this long: approved meanwhile, it is sent from it (0: off)
    "agent.keep_window_most": 3,      # at most this many such windows at once (they do not count among the applications worked at once)
    "agent.show_window": False,   # show the browser window while the agent works an application (to watch, to take over); hidden otherwise
    # An e-mail that does not say which application it is about: read the applicant page of the employer's site (with
    # the sign-in already saved for it) to find out, before asking the applicant.
    "mail.site_lookup": True,
    "llm.model": "claude-opus-5-5",
    "llm.small_model": "claude-haiku-5-5",
    "llm.effort": "high",
    "llm.fallbacks": True,
    # Backup AI services, tried in this order when the one in use runs out or cannot be reached:
    # [{"provider": "chatgpt", "model": "", "small_model": ""}, ...]; an empty model means "the one saved for that service".
    "llm.failover": [],
    # conventions of the user's own Word cover-letter template, applied when a letter is generated from it
    "cover_letter.bold_terms": [],   # names set in bold on first mention in a paragraph (project or employer names)
    "cover_letter.links": [],        # [{"text": "careers@school.example", "url": "mailto:careers@school.example"}] restored in the closing paragraph
    "cover_letter.replace": [],      # [{"find": "...", "with": "..."}] fixed text of the template to correct
    # allowance of the AI services that report one (quota.py): checked on a timer, warned about once per window
    "llm.quota_check_minutes": 30,
    "llm.prices": [],   # the user's own prices per million tokens: [{model, provider?, input, output, cache_read?, cache_write?}] in US dollars
    "llm.quota_warn_percent": 80,      # a usage window counts as running low from this share used
    "llm.quota_warn_balance": 1.0,     # a prepaid balance counts as running low below this amount (in the service's currency)
    "llm.quota_notify": True,
    "llm.quota": {},                   # the last figures read, per service
    "llm.quota_alerts": {},            # which warnings were already sent
    "mail.confirm_check_minutes": [5, 30],  # after a submission, look for the confirmation e-mail at these delays
    "policy.manual_companies": [],  # company names (substring match) whose applications the applicant always sends themselves
    # scheduler (minutes; 0 disables)
    "schedule.discover_minutes": 720,
    "schedule.mail_minutes": 60,
    "schedule.mail_new_minutes": 2,     # Gmail only: ask what arrived since the last look (0: off)
    "schedule.paused": False,
    # "finish what is being done, start nothing new, and tell me": for closing or restarting the program. Not a setting -
    # it is over when the program is started again.
    "schedule.draining": False,
    "schedule.drain_told": False,
    # how many applications may wait for the applicant at once (being drafted, or drafted and not yet approved) before the
    # program stops starting new drafts by itself. 0: no limit. Drafts asked for by hand are not counted against it.
    "drafts.max_pending": 20,
    # queueing
    "queue.min_score_for_draft": 8.0,
    # notifications: per-category switches
    "notify.task_started": True,
    "notify.todo": True,
    "notify.status_update": True,
    "notify.task_result": True,
    "notify.telegram_chat_id": "",
    "notify.discord_user_id": "",       # the applicant's Discord user, bound with a code from the settings page
    "notify.channel_categories": {},    # per channel, which kinds of notification it takes (a channel not named takes all)
    # the calendar's reminders (alarms.py): what each kind of item gets when it appears - minutes before it; for a whole
    # day, days before (1440 = 1 day) at the morning hour below
    "calendar.reminders": {"interview": [1440, 30], "assessment": [1440, 120], "offer": [1440], "info_request": [1440], "contact": [0], "own": [0], "deadline": []},
    "calendar.allday_at": "09:00",
    "calendar.reminders_quiet": False,     # True: a reminder that falls in the quiet hours waits for them to end
    "bot.listen": True,                 # the bots take presses, replies and commands (off: they only send)
    "bot.chat": True,                   # what is said to a bot that is not a command or a reply goes to the assistant
    # Hours in which nothing is pushed to the phone ({"on", "from", "to"}, local time; "to" may be on the next day).
    # What comes in then is kept and goes out as one message when the hours end. Off by default.
    "notify.quiet": {"on": False, "from": "22:00", "to": "08:00"},
    "app.base_url": "http://127.0.0.1:8000",
    # discovery
    "sources.greenhouse": [],  # board tokens
    "sources.lever": [],
    "sources.ashby": [],
    "sources.workday": [],  # [{"host": "altera.wd1.myworkdayjobs.com", "site": "Altera", "tenant": "altera"}]
    "sources.pdportal": False,  # the school's co-op portal, read by the agent with the applicant's sign-in (agent/scan.py)
    # the large tech employers' own career sites (sources/bigtech.py); always watched unless switched off
    "sources.bigtech": {"amazon": False, "apple": False, "google": False, "microsoft": False, "meta": False, "nvidia": False, "amd": False, "intel": False},
    "sources.search_terms": [],  # what to type into a career site's search box
    # What each source gave the last time it was read and when it last could be read (discover.remember): counts by
    # reason, never the postings that were dropped. Not a setting.
    "sources.history": {},
    # intake rules (intake.py): what gets stored at all. Empty lists = no restriction; the first-run guide fills these in from the persona.
    "intake.enabled": True,
    "intake.title_any": [],
    "intake.title_role_any": [],
    "intake.title_none": [],
    "intake.countries": [],
    "intake.max_age_days": 90,
    "intake.exempt_sources": ["pdportal", "manual"],
    # Postings that say which programmes of study they are for (a university co-op portal does): yours, as words that
    # occur in the programme's name ("Computer"). Empty: taken from the Education section of your profile.
    "intake.programs": [],
    "scoring.max_per_run": 60,
    "scoring.parallel": 4,           # postings read by the model at the same time
    "scoring.brief_min_score": 6.0,  # the long overview of a posting is written only from this score up (and on request for the rest)
    "sources.parallel": 4,           # employers' listings fetched at the same time
    # lifecycle (discover.archive_old): when a posting leaves the working lists
    "archive.closed_after_days": 30,   # offline / expired / skipped / rejected for this long
    "archive.silent_after_days": 150,  # applied, no reply for this long
    "dedupe.window_days": 150,         # two listings further apart than this are different postings (next year's posting with the same title)  # model quota guard: the rest is scored on the next run
    # identity used for registration/login forms
    "account.email": "",
    # mailbox (mailbox.py): gmail_api (Google OAuth, the original way) | imap (any mailbox with an app password)
    "mail.kind": "gmail_api",
    "mail.outlook": {},   # {"client_id": "<the user's own app registration>", "user": "me@outlook.com"}
    "mail.imap": {},   # {"preset": "qq", "host": "", "port": 993, "user": "me@example.com"}; the password is kept with the secrets
    # employers the user wants watched (employers.py)
    "employers": [],
    "employers.migrated": False,
    "employers.priority_min_score": 7.0,   # a priority employer's posting gets a draft from this score
    "update.repo": "Liam-Frost/AutoApply",   # where releases are published; looked at only when the user clicks "check for updates"
    "ui.lang": "zh",   # interface language: zh | en. Text the AI writes for the user (reasons, summaries, replies) follows it.
    # who is using the program (persona.py); filled in by the first-run guide
    "persona": {},
    "onboarding.done": False,
    "browser.nodriver_enabled": False,
    "browser.executable": "",
    "browser.rules": [
        {"tenant": "pdportal:ubc", "backend": "nodriver", "operations": []},
        {"tenant": "idp:google", "backend": "nodriver", "operations": []},
        {"domain": "accounts.google.com", "backend": "nodriver", "operations": ["login"]},
    ],
    # network (net.py)
    "proxy.mode": "system",   # system: whatever this computer is set to use | none: connect directly | custom: proxy.url
    "proxy.url": "",          # http://127.0.0.1:7890, socks5://127.0.0.1:1080
    "proxy.username": "",     # the password is kept with the other secrets
    "proxy.bypass": "",       # extra hosts that never go through the proxy, comma separated
    "identity.share": True,
    "identity.emails": {},    # provider -> the e-mail of the user's account there, when it is not the application e-mail
    "identity.custom": [],    # sign-in providers the user added: [{"name": "…", "url": "sign-in page", "domains": ["example.com"]}]
    "sso.order": ["microsoft", "linkedin", "google", "apple", "github", "facebook", "indeed", "seek", "xing"],
    # per-job résumé tailoring (tailor.py)
    "tailor.mode": "select",            # off | select (reorder / choose only, no wording changes) | rephrase (may reword bullets; checked against the original)
    "tailor.auto": True,                # write one when the application is begun; False = only when asked
    "tailor.min_score": 8.0,            # jobs below this use the résumé as uploaded
    "tailor.reorder_entries": "projects",  # none | projects | all
    "tailor.reorder_skills": True,
    "tailor.allow_drop": False,         # leave out bullets that do not matter for the posting
    "tailor.min_bullets": 2,            # never fewer than this per entry
    "tailor.target_pages": 0,           # 0 = as many pages as the original
    "tailor.review": True,              # an application with a résumé rewritten just now waits for the applicant's approval
}

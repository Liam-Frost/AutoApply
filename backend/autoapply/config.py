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
RUNS = DATA / "runs"  # per-run screenshots, DOM fixtures, evidence
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
DEFAULT_SETTINGS: dict[str, object] = {
    # models
    "llm.auth": "subscription",  # older installs: "subscription" | "api_key" (Anthropic); used only while llm.provider is empty
    # which AI service: claude_subscription | anthropic | chatgpt (Codex CLI login) | openai | gemini | deepseek | qwen | openrouter | custom
    "llm.provider": "",
    # per service, for the OpenAI-compatible ones and chatgpt: {"openai": {"base_url": "", "model": "", "small_model": ""}}; keys are kept with the secrets
    "llm.providers": {},
    "repair.enabled": True,  # let the agent take over a page the driver could not fill (it can never submit)
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
    "llm.quota_warn_percent": 80,      # a usage window counts as running low from this share used
    "llm.quota_warn_balance": 1.0,     # a prepaid balance counts as running low below this amount (in the service's currency)
    "llm.quota_notify": True,
    "llm.quota": {},                   # the last figures read, per service
    "llm.quota_alerts": {},            # which warnings were already sent
    # submit policy: manual | approve_then_submit | auto_approve
    "policy.default": "approve_then_submit",
    "policy.per_ats": {},  # {"workday": "manual", ...}
    "mail.confirm_check_minutes": [5, 30],  # after a submission, look for the confirmation e-mail at these delays
    "policy.manual_companies": [],  # company names (substring match) the user always submits by hand
    "policy.manual_confidence": "low",  # "none" | "low" | "medium": answers at or below this level make the run manual
    "auto_approve.enabled": False,
    "auto_approve.per_ats": {},  # {"greenhouse": true}
    "auto_approve.min_score": 8.0,
    "auto_approve.min_driver_successes": 3,
    "auto_approve.allow_new_cover_letter": False,
    # registration switches per ATS (default off; user turns on per ATS)
    "register.auto": True,  # sites the user has never applied on: the agent creates the account
    "register.per_ats": {},  # {"workday": False} turns automatic registration off for one ATS
    "register.allow_keys": [],  # tenant keys where the user said "I have no account here, register for me"
    # scheduler (minutes; 0 disables)
    "schedule.discover_minutes": 720,
    "schedule.mail_minutes": 60,
    "schedule.execute_minutes": 5,
    "schedule.canary_minutes": 1440,
    "schedule.paused": False,
    # queueing
    "queue.min_score_for_draft": 8.0,
    "executor.concurrency": 1,
    # notifications: per-category switches
    "notify.task_started": True,
    "notify.todo": True,
    "notify.status_update": True,
    "notify.task_result": True,
    "notify.telegram_chat_id": "",
    "app.base_url": "http://127.0.0.1:8000",
    # discovery
    "sources.greenhouse": [],  # board tokens
    "sources.lever": [],
    "sources.ashby": [],
    "sources.workday": [],  # [{"host": "altera.wd1.myworkdayjobs.com", "site": "Altera", "tenant": "altera"}]
    "sources.pdportal": False,  # the portal refuses automated browsers; postings come in through the importer in the user's browser
    # the large tech employers' own career sites (sources/bigtech.py); always watched unless switched off
    "sources.bigtech": {"amazon": False, "apple": False, "google": False, "microsoft": False, "meta": False, "nvidia": False, "amd": False, "intel": False},
    "sources.search_terms": [],  # what to type into a career site's search box
    # intake rules (intake.py): what gets stored at all. Empty lists = no restriction; the first-run guide fills these in from the persona.
    "intake.enabled": True,
    "intake.title_any": [],
    "intake.title_role_any": [],
    "intake.title_none": [],
    "intake.countries": [],
    "intake.max_age_days": 90,
    "intake.exempt_sources": ["pdportal", "manual"],
    "scoring.max_per_run": 60,
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
    # A notice about how the employer handles applicant data, shown in a dialog that blocks the form ("I understand" / "Accept"):
    # acknowledge it and go on. Such notices are a condition of applying at all; the answers on the form itself are not touched.
    "consent.acknowledge_notices": True,
    "browser.visible_sites": [],   # tenant keys whose pages are refused in a hidden window: these run in a visible one (found out automatically)
    # network (net.py)
    "proxy.mode": "system",   # system: whatever this computer is set to use | none: connect directly | custom: proxy.url
    "proxy.url": "",          # http://127.0.0.1:7890, socks5://127.0.0.1:1080
    "proxy.username": "",     # the password is kept with the other secrets
    "proxy.bypass": "",       # extra hosts that never go through the proxy, comma separated
    "identity.share": True,
    "identity.emails": {},    # provider -> the e-mail of the user's account there, when it is not the application e-mail
    "identity.custom": [],    # sign-in providers the user added: [{"name": "…", "url": "sign-in page", "domains": ["example.com"]}]
    "sso.order": ["microsoft", "linkedin", "google", "apple", "github", "facebook", "indeed", "seek", "xing"],
    # a site offers "Sign in with Microsoft / Google / LinkedIn" and you are signed in to that provider here:
    #   ask  - the first time on each site, ask which way to sign in (the provider shares your name and e-mail with the site)
    #   auto - use the provider without asking, in the order below
    #   never - never use a provider; register with e-mail or ask you to sign in
    "sso.mode": "ask",
    "sso.sites": {},     # tenant key -> provider you approved for that site ("" = you said not to use one there)
    "sso.offered": {},   # tenant key -> providers the site was seen to offer (filled in by the agent)   # use the saved Microsoft / Google / LinkedIn sign-in on sites that offer "Sign in with ..."
    # per-job résumé tailoring (tailor.py)
    "tailor.mode": "select",            # off | select (reorder / choose only, no wording changes) | rephrase (may reword bullets; checked against the original)
    "tailor.auto": True,                # write one while the draft is prepared; False = only when asked
    "tailor.min_score": 8.0,            # jobs below this use the résumé as uploaded
    "tailor.reorder_entries": "projects",  # none | projects | all
    "tailor.reorder_skills": True,
    "tailor.allow_drop": False,         # leave out bullets that do not matter for the posting
    "tailor.min_bullets": 2,            # never fewer than this per entry
    "tailor.target_pages": 0,           # 0 = as many pages as the original
    "tailor.review": True,              # a draft with a newly tailored résumé always waits for the user
}

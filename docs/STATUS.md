# Status: what has been run for real

A feature is only as good as the last time it was actually used. This page separates three things:

- **Used for real**: run against real websites or services, with a real result (an application submitted, a mailbox read).
- **Run end to end**: exercised completely, but in a scratch location or without the final irreversible step.
- **Unit-tested only**: covered by the test suite, which never reaches a real AI service or a real website.

Keep this distinction when you change something: say what you ran it against.

Last updated for 2.1.1 (2026-11-23), with figures read from the author's own installation. The author uses the program on Windows with the Claude and ChatGPT subscriptions.

2.0 replaced how an application is worked - one agent from the posting to the confirmation, instead of a pipeline of drivers and checks. What 1.x had run for real with the old chain is listed as history; what the new agent has and has not done is stated row by row.

## The application chain

| Part | Status |
|---|---|
| Reading postings: Greenhouse, Lever, Ashby, SmartRecruiters, Workday boards, the eight built-in career sites | Used for real |
| Reading postings: job-board feeds (16 in the catalogue) | Run end to end: every feed read with the real reader; a full scheduled scan with feeds has not been watched |
| A posting whose source gives only a summary: marked, its own page read for the whole text before it is scored, "only a summary" in the reason when that fails | Unit-tested: which feed items are teasers, the text of a page as a reader sees it, what is taken for the posting and what is not (a sign-in wall, a page that says less), the score and its reason. No real job board's feed and no real posting page has been read by it; pages that need a sign-in will stay summaries |
| Reading postings: any careers page, read by the AI | Used for real on a few sites |
| Scoring | Used for real |
| An interview from an employer's email: on the calendar only, a notice when it arrives or moves and at its reminders (since 2026-11-24) | Unit-tested (the arrival, a move, a reminder of the same date, an assessment staying a task); not yet seen with a real invitation |
| A posting's field from the fixed list; the postings labelled before, sorted into it by the model in the background | Run on the author's copy (2026-11-23): the 1,120 postings that had a label (502 different ones) were sorted into 75 entries of the list in three rounds of the background task, none left; the 80 never scored have none. Unit-tested with a stand-in for the model; the list's names checked in the three languages |
| An email about an application made elsewhere, put on the calendar | Used for real once (2026-11-23): an interview invitation went onto the calendar with its time and meeting link. The email's card stayed open beside the item's own card, and the item was closed by mistake: in 2.1.1 the card closes; after 2.1.1 an item of one's own calendar is no card on the to-do page at all - on the calendar only, deleted there (with Undo), its reminder a notice with "Got it" (unit-tested, tried on the demo copy) |
| The application agent: one agent that reads the pages, signs in or registers (with a password it never sees), fills the form from the profile and the résumé, uploads files, asks what it was not given | **Used for real: 34 applications sent from 2026-11-19 to 21**: 25 on employers' own sites (Workday, SAP SuccessFactors, Greenhouse and large employers' own careers sites), 8 through the university's co-op portal and 1 by e-mail - 23 of them in the automatic mode, 11 after the applicant's approval; 21 were already confirmed by the employer's mail on 2026-11-23. Before that, run end to end on the project's evaluation forms (`eval/`), judged by what the employer's side received, with Claude Fable 5.2: a profile-first wizard, a form in a frame from another site and a site that needs an account - every check passed (62 of 62), including a run killed part-way and taken up again; and six more shapes, run once each after the agent's brief was moved to stand with its instructions - a form made of the page's own lists, cards and file window that objects only when it is sent (12 of 12), a site the applicant has an account and an old draft on (11 of 11: signed in with the stored login, put right what had changed, replaced the old résumé, took the line in the list of applications as the confirmation), a posting that has been taken down (3 of 3: nothing sent, not to the employer's other openings either), the setting "I approve it first" (15 of 15: prepared and did not send; sent the approved text after the approval), the setting "the last press is mine" (11 of 11: gave the window over, announced no press of its own, found out that it went), and an application inside the co-op portal through the program's queue (9 of 9: documents uploaded under their types, a package made, one application for the right posting). In the approval run the agent asked whether the applicant has a LinkedIn page - a box the form does not require - and would not send while that was open; a record with a question open cannot be approved in the program either. On three real postings, told to prepare and not to send - a SAP SuccessFactors site, a Workday site, Google Careers - it made the account where one was needed, filled every step and stopped before the press that sends: two were ready to send, one had a question open |
| Sending: by itself when nothing is open, after the record is approved, or the window handed to the applicant at the last step | The three ways and what each run is told: unit-tested with a stand-in for the agent's run. Through the queue to a confirmation on the evaluation form: run again after the older pipeline was removed (18 of 18 checks; 70 tool calls and under five minutes for both runs), and once more with Claude Opus 5.5 at medium thinking depth after the agent got its tool for a résumé and its ear for the applicant (18 of 18; 68 tool calls, a little over three minutes). On real sites: 23 applications sent in the automatic mode and 11 after the applicant's approval (2026-11-19 to 21). The handed-over window has not been used by a person on a real site |
| Speaking to a run that is working, several applications at once (never two on one site), the agent's window shown on request, a résumé for the posting as the agent's tool, the figures by application on the Analysis page | Unit-tested, and tried in the browser on the demo data (a word said to a run, Stop, the settings, the figures). No real application has been spoken to while it was worked; several applications have been worked at once on real sites (of 331 runs from 2026-11-19 to 21, many side by side); the résumé tool has not been called by a real run (the evaluation's applicant has no Word résumé to rewrite) |
| A run cut off after it said it was about to send: the outcome is recorded as not known, and the next run looks on the site before anything is pressed | Unit-tested, and run on the evaluation form (killed and taken up again). Has not happened on a real site |
| The record of an application: answering what is open, correcting an entry, a note about the whole, approval; an answer kept for this application or "also from now on" | Unit-tested through the API with a stand-in for the agent's run; the page looked at on a scratch copy |
| The three ways a run stops without a report (the AI service's allowance, the application's budget, the same place three times), and the applicant's "stop" | Unit-tested |
| A stored password typed only where the site's sign-in lives, by the program, never shown to the agent | Unit-tested on a local page. On a real site an account was registered with a password made up to the site's own rules |
| What the agent writes down about a site, and the notes about recruiting systems that ship with the program | The notes written during real runs are read by the runs after them. The shipped notes were written from applications made by hand; whether they shorten a run has not been measured |
| What an application takes | The 34 runs that sent a real application (2026-11-19 to 21) took 32 to 296 tool calls (median 120), a median of 14 minutes on the budget's clock, and 0.5 to 11.8 million cached tokens (median 3.7 million) - inside the subscriptions' allowance; at list prices about 0.2 to 5.2 US dollars each (median 1.7) |
| A cover letter written during the agent's run; a résumé rewritten for the posting offered to the run | Cover letters: used for real (24 written from 2026-11-19 to 21). The rewritten résumé in the agent's run: written, not run |
| A source that needs a sign-in (the co-op portal), read by the agent: it signs in, finds the list and saves the postings with a script, seeing what was stored | Run end to end on the evaluation site's portal (`eval/run.py --scan`: a sign-in, a list on two pages, postings opened by a POST with a token, built unlike the one the agent's notes describe): with Claude Fable 5.2 it signed in with the stored login, listed everything, wrote its own script, stored every new posting with the right employer, deadline and way of applying, and left a note - 16 tool calls, about a minute. 9 of 10 checks; the tenth was the harness asking too much (the agent had opened one posting the program already had, once, to see what a posting's page is like) and has been reworded, not run again. On the real co-op portal the scheduled scans have stored 186 new postings since 2026-11-19, and the agent has sent 8 applications through it |
| UBC PD Portal | Importing postings with the bookmarklet: used for real. The agent reading the portal on the scheduled scans: used for real (186 new postings stored from 2026-11-19), reading every faculty's postings. Narrowing the list to the applicant's programme first (since 2026-11-23): in the agent's brief and notes, not yet run on the portal. Applying through it: used for real (8 applications sent by the agent) |
| An e-mail that names no posting: the agent reads the applicant's list on the employer's site and says which application it is about; or it is linked by hand from its card | Run for real 4 times; unit-tested with a stand-in for the agent |
| A confirmation link or a code a site sends by e-mail while an account is made | The agent's `mail` tool reads the mailbox; used on real runs |
| Workday boards: the program's own requests at Workday's pace; after "too many requests" or a security check, the boards read through their own pages in the program's browser, in the same scan | On the real scans of 2026-11-16 to 24 Workday refused every board's first request, whatever the pace, and a rest kept only in memory was forgotten at each restart. Reading the boards' pages in the browser is unit-tested with a stand-in page (the pace, a check that passes by itself, one that does not, a 429 from the page, the window); it has not been run against Workday itself yet |
| The second browser backend (nodriver) and the contract both browsers keep to | Unit-tested on local pages in both browsers; sign-ins through it are listed in their own rows |
| What 1.x did - a driver per recruiting system, the fallback chain, the AI take-over of a page, the gate on what it could press, recipes and plugins learned from runs, the self-check that replayed saved pages | Removed in 2.0, without a fallback. With it, 1.x sent real applications that were confirmed by mail (Greenhouse, Microsoft Careers, a BambooHR site, a JazzHR site); they stay in the history |
| Sign-in with Google / Microsoft / LinkedIn and others | Microsoft: used for real. Google refuses sign-in in the default browser; through the second browser backend a sign-in was made, and that it is kept for the next run has not been confirmed |
| The analysis page: applications, automation, AI cost | Applications and automation: run on the author's own data. AI cost: run on the author's real requests (884 recorded from 2026-11-19 to 23) and on made-up data (the demo copy) |
| Recording model requests (usage, cost) | Claude and ChatGPT subscriptions: used for real - 884 requests recorded from 2026-11-19 to 23 over whole application runs, with tokens by kind, and the refused ones with their reason (rate-limited, unavailable). Anthropic API and OpenAI-compatible services: unit-tested with stand-ins that report usage, not checked against what a real service bills. The ChatGPT subscription reports usage only with an answer, so a failed turn has none |
| Mail tracking with Gmail | Used for real |
| Mail tracking with Outlook and generic IMAP | Unit-tested only |
| Telegram notifications | Chinese: used for real. English: checked for untranslated text, not sent |
| Telegram / Discord buttons, replies, commands, the assistant | Covered by tests with the services' replies recorded by hand; not yet used against the real services. Discord: no bot bound on the author's copy |
| The calendar: deadlines, interviews, assessments and requests from mails, by month, week and day; reminders | Used for real on the author's data; a reminder sent for real (2026-11-23) |
| Times converted from the employer's time zone, dates from stated periods, interview end times (2.1.0) | Unit-tested, including British Columbia's clock. Running on the author's copy since 2026-11-23; a conversion between two different zones in a real email has not been checked by hand yet |
| Updates from inside the program | Looking for a release: used for real (the author's copy checks GitHub). Downloading, checking, preparing and switching to a GitHub release: unit-tested and covered by CI; the author's copy switches to builds staged on it through the same tray restart, used for real. 2.1.0 is the first release such a copy can fetch |
| Change fragments, release manifests, the generated changelog and release notes | Used for real: 2.1.0 was prepared, validated by CI, tagged and published by the release workflow with notes generated from its fragments (2026-11-23) |

## The server

| Part | Status |
|---|---|
| Refusing requests from other websites and foreign `Host` headers | Unit-tested only (requests with the headers a browser would send); not attacked from a real page |
| The remote window, as pictures (a page that needs a person, on a computer without a screen) | Run end to end on Windows with the program told it has no screen: a sign-in started in the page, the notice, the window opened, e-mail and password typed and submitted through it, "done" pressed, the sign-in saved. Not run: on a phone; with a Chinese input method; a real site's sign-in; from another device over HTTPS |
| The remote window, as a virtual screen (Xvfb, x11vnc, the bridge to the page, noVNC) | The decisions are unit-tested everywhere; the real screen, a real browser window on it and the bridge are run by CI on Linux and in the container. The picture in a browser through noVNC has not been looked at by a person |
| Secrets in an encrypted file (no keyring) | Unit-tested; run in the container by CI |
| The doctor | Run on Windows and in WSL; by CI on Linux and in the container |
| Running as a systemd user service; upgrading a copy that runs as one | Unit-tested only (the unit, the orderly stop). Not run on a system with systemd |
| Carrying a sign-in to another computer | Unit-tested, through the API; not used for a real site |
| The container image | Built and run by CI: starts as an ordinary user, healthy, the doctor finds the browser, the virtual screen, the PDF converter and the fonts, the administrator is set in the terminal and stays signed in over a restart. Not run by the author day to day; the ARM64 image is only built at release |
| The login (first set-up, sign-in, sign-out, the lock after wrong passwords) | Run end to end on a scratch copy with a test account; the lock and the proxy rules are unit-tested only |
| Listening beyond this computer, a path prefix, HTTPS by a reverse proxy | Unit-tested only: not reached from another device, not run behind a real proxy |
| Resetting the administrator password from the tray | Unit-tested only |

## AI services

| Part | Status |
|---|---|
| Claude subscription | Used for real, daily |
| ChatGPT subscription | Used for real, the application agent included: of the 34 runs that sent a real application, 8 used the Claude subscription, 6 the ChatGPT subscription and 20 both |
| Claude API, OpenAI-compatible services (OpenAI, Gemini, DeepSeek, Qwen, OpenRouter, custom) | Unit-tested only (no real keys were used) |
| Failover to a backup service | Used for real, often: from 2026-11-19 to 21 the ChatGPT subscription refused 250 requests as rate-limited and the Claude subscription went on - also in the middle of application runs (20 of the 34 runs that sent an application used both) |
| An agent's budget: so many tool calls and a deadline, the same for every service, and the model's run ended with it | Unit-tested with a stand-in for each of the four services (a model that never stops by itself): the count, the clock, a backup going on with what is left. Interrupting a real ChatGPT turn and cancelling a real Claude query when a budget runs out have not been done against the real command lines, and the built-in figures have not been tried on a long real form |
| Reading the allowance | Claude and ChatGPT subscriptions: read for real. DeepSeek and OpenRouter: written from their documentation, unit-tested only |

## Packages

| Part | Status |
|---|---|
| Windows installer (its own window, Inno Setup behind it) | Run end to end from the .exe into a scratch folder, as a test build with its own identity: install through the window driving itself and without a window (dependencies and browser downloaded for real), refusing to run while the installed copy is running, repair, cancel from the window in the middle of a download (the previous version's files were back), removal through the window keeping the data and deleting it. CI repeats these on every release. Not run: an upgrade over a copy installed by 1.0.3 or earlier, the entry under Settings > Apps clicked by hand, the folder dialog, the real desktop shortcut |
| macOS disk image | Built, set up and started by CI on every release, which also checks that a newer app refuses to set up over a running copy and keeps the data once it is quit. The staged upgrade and the way back are the same code as on Linux and Windows (`scripts/prepare.py`), but have not been run on a Mac by hand. Not used day to day; not signed or notarised |
| Linux installer | Run for real in Ubuntu under WSL, without a desktop: install, refusing to run (and to uninstall) while a program runs out of the folder, an upgrade whose dependencies cannot be installed (the installed version was put back and still worked), an interrupt in the middle (the old files were back), uninstall keeping and deleting the data. That Ubuntu lacked the libraries Chromium needs, and the installer said so and named the command that installs them; the browser step succeeding is covered by CI, which runs all of this on every release. The zenity windows have not been run |
| Portable zip | Used for real on Windows |
| Tray launcher | Used for real on Windows. macOS and Linux: started by CI only as far as importing the menu-bar support |

## Interface

| Part | Status |
|---|---|
| Chinese interface | Used for real |
| English interface | Written with an AI's help; the pages render and were looked at, the wording has not been proof-read by a native speaker |
| French interface | Complete, written with an AI's help; not read by a native speaker |
| Region packs (CA, US, GB, EU, AU, SG) | Written from knowledge of how forms ask in each country; not checked item by item against real forms |
| School portal catalogue | Only UBC has been used; the other entries are marked as untested or unsupported |

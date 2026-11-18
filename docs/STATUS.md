# Status: what has been run for real

A feature is only as good as the last time it was actually used. This page separates three things:

- **Used for real**: run against real websites or services, with a real result (an application submitted, a mailbox read).
- **Run end to end**: exercised completely, but in a scratch location or without the final irreversible step.
- **Unit-tested only**: covered by the test suite, which never reaches a real AI service or a real website.

Keep this distinction when you change something: say what you ran it against.

Last updated for 1.0.3 (November 2026). The author uses the program on Windows with a Claude subscription.

## The application chain

| Part | Status |
|---|---|
| Reading postings: Greenhouse, Lever, Ashby, SmartRecruiters, Workday boards, the eight built-in career sites | Used for real |
| Reading postings: job-board feeds (16 in the catalogue) | Run end to end: every feed read with the real reader; a full scheduled scan with feeds has not been watched |
| A posting whose source gives only a summary: marked, its own page read for the whole text before it is scored, "only a summary" in the reason when that fails | Unit-tested: which feed items are teasers, the text of a page as a reader sees it, what is taken for the posting and what is not (a sign-in wall, a page that says less), the score and its reason. No real job board's feed and no real posting page has been read by it; pages that need a sign-in will stay summaries |
| Reading postings: any careers page, read by the AI | Used for real on a few sites |
| Scoring, drafting, review, revising a draft in plain words | Used for real |
| Greenhouse driver | Used for real: applications submitted and confirmed by mail |
| Forms explored by the AI (no dedicated driver) | Used for real: applications submitted on Microsoft Careers (Eightfold), a BambooHR site and a JazzHR site |
| The fallback chain (driver → the form's own verdict → AI take-over → verdict → you) | Used for real on Microsoft Careers: the AI filled fields that appeared after an answer and corrected a phone entry the form rejected. Second run of the same draft without AI help: unit-tested only |
| Recording where a run's time goes | Unit-tested, and run through the test pipeline's form; shown on made-up data (the demo copy). No real application has been recorded with it yet |
| Learning from runs: finding what stands out, the agent writing a recipe or a plugin, the gate, the trial, taking it out | Unit-tested, with a real browser for the generic driver following a recipe and a plugin and falling back when one fails. The agent's part was tested with a stand-in for the model: no revision has been written by a real model or tried on a real site yet. The gate replays how saved pages are *read*; whether a revision *fills* correctly is only found out in its trial |
| The two browsers doing the same thing: the contract (selectors, frames, boxes the page controls, files, windows, the mouse) and the sign-in window | Unit-tested on local pages, each test run in the automated and in the ordinary browser against one expected answer. It covers the ways of asking the program's own code uses, not all a site can do; a real site that behaves differently in the ordinary browser is still found on that site |
| The contract a learned plugin keeps to before its trial | Unit-tested with plugins written for the purpose (honest ones, and six that are not). No plugin written by a real model has been put through it; it cannot tell whether a plugin works the control it was written for - the trial does that |
| The self-check: saved form pages replayed against the current code | Unit-tested with a real browser on the test form: a page that stops matching is kept and marked, and moved aside only when a later sample of the same form page passes. Every site's form is read by the agent now, so what these pages guard is the driver's side of filling and reading back - finding each control and reading it - not the reading of a form, and not whether typing into a control works |
| Writing a site's driver after the first application that goes through there | Unit-tested with a stand-in for the model. What is written is recipes and plugins for the generic driver, not a driver class of its own; no real site has had one written yet |
| Offering a driver that held up to the project as an issue | Unit-tested: the card, the four answers, the preference, the address of the issue page. The page itself was not opened on GitHub, and no issue has been submitted |
| Tools a plugin adds for the take-over agent | Unit-tested: the check, the tool being offered and called, a failing tool taking its revision out. No take-over by a real model has used one |
| Forms with several steps, walked by what is on the screen (resumed forms, optional steps in between, a review page at the end) | Used for real on Amazon's application form up to its "Job-specific questions" step: the optional text-message step was skipped, the step was filled by the driver and the AI with the approved answers, and the form was handed over where it refused an answer longer than it allows; on a second posting it went on through "Work Eligibility" to the review page. Rewriting an answer to fit a length limit: used for real on that form (1,400 characters to 186, the form went on). A question only the applicant can answer joining the draft, and being filled on the next run: unit-tested only. Recognising the review page before filling, noticing a submission the user makes in the window during the run, and the comparison of earlier answers with the review page: unit-tested only |
| Reading a form's later steps before approval, by walking it with the draft's answers (never submits) | Used for real on one Amazon draft, three walks in a hidden window: the first two used the AI (the second read 12 answers the site already held on "Work Eligibility" and 7 more from the review page for three steps the site never opened again, three AI calls); the later ones needed no AI call - the driver filled the two radio questions from where the take-over had found them, reached the review page in about half a minute, unfolded its seven folded sections and found all 18 answers of the first step there. Nothing was submitted. A question only the applicant can answer stopping the walk, and the walk going on after the answer: unit-tested only. Starting the walk automatically right after a new draft is made: unit-tested only (the real draft predates it and was started by hand). |
| Walk-type forms read and filled by the agent (Workday) | Used for real on one Workday form (six steps): the agent read four steps in its first pass, the walk read the rest and reached the review page with every question answered from the profile and the documents on file (the transcript was attached by the agent); nothing was submitted. It took three walks to get there while faults were fixed; one clean pass on a posting that has not been touched before has not been seen yet. Filling the approved draft of such a form and the applicant submitting it: not run yet. A stand-in answer for a question only the applicant can answer: unit-tested prompt and plumbing, not seen for real |
| A confirmation link from an e-mail | The rules that decide whether a link is opened are unit-tested; opening one during a real sign-up has not been seen |
| An approved draft on an agent-read form, submitted by the program | Used for real: applications submitted and confirmed by the employer |
| An e-mail that names no posting: looked up on the employer's site, or linked by hand from its card | Unit-tested only |
| The account a site offers after a submission | Unit-tested only |
| Polite Workday listing (pauses, waiting out "too many requests") | Unit-tested only; a full scan of the Workday boards has not been watched since |
| The second browser backend (nodriver) | Its tests pass with the package installed; sign-ins through it are listed in their own rows |
| Ashby driver | Run end to end on real forms (filled, read back, not submitted) |
| Workday driver | Listing and the sign-in page elements used for real; filling after sign-in, registration and the review page are written from earlier manual applications and have not been run |
| UBC PD Portal | Importing postings with the bookmarklet: used for real. Signing in and scanning through the program (second browser backend): written, not confirmed on the real portal. Applying through the portal: not run |
| Sign-in with Google / Microsoft / LinkedIn and others | Microsoft: used for real. Google refuses sign-in in the default browser; through the second browser backend a sign-in was made, and that it is kept for the next run has not been confirmed |
| The analysis page: applications, automation, AI cost | Applications and automation: run on the author's own data. AI cost: run on made-up data (the demo copy) and on the author's records from before requests were kept, which carry no cost; real requests recorded by this version have not accumulated yet |
| Recording model requests (usage, cost) | Claude subscription: used for real (a connection test was recorded with its tokens by kind and the cost the command line reported); a full task with many requests has not been looked at yet. Anthropic API, ChatGPT subscription and OpenAI-compatible services: unit-tested with stand-ins that report usage, not checked against what a real service bills. The ChatGPT subscription reports usage only with an answer, so a failed turn has none |
| Mail tracking with Gmail | Used for real |
| Mail tracking with Outlook and generic IMAP | Unit-tested only |
| Telegram notifications | Chinese: used for real. English: checked for untranslated text, not sent |

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
| ChatGPT subscription | Text, structured output and tool calls used for real; a whole site exploration has not been run with it |
| Claude API, OpenAI-compatible services (OpenAI, Gemini, DeepSeek, Qwen, OpenRouter, custom) | Unit-tested only (no real keys were used) |
| Failover to a backup service | Used for real once: a ChatGPT subscription had actually run out and the calls moved to Claude. A switch in the middle of an AI-driven browser session: unit-tested only |
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
| English interface | Machine-translated; the pages render and were looked at, the wording has not been proof-read |
| Region packs (CA, US, GB, EU, AU, SG) | Written from knowledge of how forms ask in each country; not checked item by item against real forms |
| School portal catalogue | Only UBC has been used; the other entries are marked as untested or unsupported |

# Status: what has been run for real

A feature is only as good as the last time it was actually used. This page separates three things:

- **Used for real**: run against real websites or services, with a real result (an application submitted, a mailbox read).
- **Run end to end**: exercised completely, but in a scratch location or without the final irreversible step.
- **Unit-tested only**: covered by the test suite, which never reaches a real AI service or a real website.

Keep this distinction when you change something: say what you ran it against.

Last updated for 1.0.0 (November 2026). The author uses the program on Windows with a Claude subscription.

## The application chain

| Part | Status |
|---|---|
| Reading postings: Greenhouse, Lever, Ashby, SmartRecruiters, Workday boards, the eight built-in career sites | Used for real |
| Reading postings: job-board feeds (16 in the catalogue) | Run end to end: every feed read with the real reader; a full scheduled scan with feeds has not been watched |
| Reading postings: any careers page, read by the AI | Used for real on a few sites |
| Scoring, drafting, review, revising a draft in plain words | Used for real |
| Greenhouse driver | Used for real: applications submitted and confirmed by mail |
| Forms explored by the AI (no dedicated driver) | Used for real: applications submitted on Microsoft Careers (Eightfold), a BambooHR site and a JazzHR site |
| The fallback chain (driver → the form's own verdict → AI take-over → verdict → you) | Used for real on Microsoft Careers: the AI filled fields that appeared after an answer and corrected a phone entry the form rejected. Second run of the same draft without AI help: unit-tested only |
| Forms with several steps, walked by what is on the screen (resumed forms, optional steps in between, a review page at the end) | Used for real on Amazon's application form up to its "Job-specific questions" step: the optional text-message step was skipped, the step was filled by the driver and the AI with the approved answers, and the form was handed over where it refused an answer longer than it allows; on a second posting it went on through "Work Eligibility" to the review page. Recognising the review page before filling, noticing a submission the user makes in the window during the run, and the comparison of earlier answers with the review page: unit-tested only |
| Ashby driver | Run end to end on real forms (filled, read back, not submitted) |
| Workday driver | Listing and the sign-in page elements used for real; filling after sign-in, registration and the review page are written from earlier manual applications and have not been run |
| UBC PD Portal | Importing postings with the bookmarklet: used for real. Applying through the portal: not run; the portal refuses automated browsers, which the program does not work around |
| Sign-in with Google / Microsoft / LinkedIn and others | Microsoft: used for real. Google refuses sign-in inside an automated browser; the program hands that step to you |
| Mail tracking with Gmail | Used for real |
| Mail tracking with Outlook and generic IMAP | Unit-tested only |
| Telegram notifications | Chinese: used for real. English: checked for untranslated text, not sent |

## The local server

| Part | Status |
|---|---|
| Refusing requests from other websites and foreign `Host` headers | Unit-tested only (requests with the headers a browser would send); not attacked from a real page |

## AI services

| Part | Status |
|---|---|
| Claude subscription | Used for real, daily |
| ChatGPT subscription | Text, structured output and tool calls used for real; a whole site exploration has not been run with it |
| Claude API, OpenAI-compatible services (OpenAI, Gemini, DeepSeek, Qwen, OpenRouter, custom) | Unit-tested only (no real keys were used) |
| Failover to a backup service | Used for real once: a ChatGPT subscription had actually run out and the calls moved to Claude. A switch in the middle of an AI-driven browser session: unit-tested only |
| Reading the allowance | Claude and ChatGPT subscriptions: read for real. DeepSeek and OpenRouter: written from their documentation, unit-tested only |

## Packages

| Part | Status |
|---|---|
| Windows installer | Run end to end from the .exe into a scratch folder: install, upgrade over a running copy (data untouched), uninstall keeping data, reinstall, uninstall deleting everything; the installed copy started and answered. Not run: writing the real desktop shortcut and the Settings > Apps entry through the installer, uninstalling from Settings > Apps, the folder dialog |
| macOS disk image | Built, set up and started by CI on every release. Not used day to day; not signed or notarised |
| Linux installer | Built, installed, upgraded, uninstalled and started by CI on every release, without a desktop. The zenity dialogs have not been run |
| Portable zip | Used for real on Windows |
| Tray launcher | Used for real on Windows. macOS and Linux: started by CI only as far as importing the menu-bar support |

## Interface

| Part | Status |
|---|---|
| Chinese interface | Used for real |
| English interface | Machine-translated; the pages render and were looked at, the wording has not been proof-read |
| Region packs (CA, US, GB, EU, AU, SG) | Written from knowledge of how forms ask in each country; not checked item by item against real forms |
| School portal catalogue | Only UBC has been used; the other entries are marked as untested or unsupported |

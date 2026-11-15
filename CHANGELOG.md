# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.1] - 2026-11-15

### The analysis page

The page is now three views over one time range (everything, the last 30 or 90 days, or your own dates), each with the
change against the period before where there is one to compare with.

- **Applications.** The funnel counts what an application *has been* (an interview before a rejection still counts as
  an interview), each step a part of the one before; next to it, where every application stands now, adding up to the
  total. Months follow local time. Groups with fewer than five applications show counts, not percentages. Replies by
  the month they arrived are shown apart from outcomes by the month of sending. Missed postings show why and when.
- **Automation.** What the program's tasks did: done, not finished (handed to you, waiting for you, still running) and
  failed are told apart - a filling task that handed the form over is not a failure and not a success. Success rate,
  typical duration, why tasks failed and how far they had got, repeats and retries, and the AI cost per success. Each
  run opens to the model requests it made. There is no "hours saved": the program has no record of how long the same
  work takes by hand.
- **AI cost.** What the model calls used and what that comes to, over time and by model, service and feature; tokens
  by kind (input, cache read, cache write, output) by count and by cost; cost per result (everything a kind of task
  spent, failed runs included, over what it produced); what failures, retries on a backup service and repeated runs
  cost; and the runs and requests far above the others of their kind (by Tukey's fence, not a made-up threshold).

The cards of a row share its height, so tops and bottoms line up; rows are as tall as their content. Detail never
grows an overview card: the numbers behind a chart open in a panel below its row, across the page; the full list of
runs, a single run with its model requests, and the price editor open in a drawer; long tables are paged.

### Recording what the AI costs

- Every request to an AI service is recorded: service, model, the feature and the task that asked, how long it took,
  how it ended, and tokens by kind. Failed requests are kept too, and a retry on a backup service is tied to the call
  it repeats.
- Tokens are counted one way for every service. Cached tokens that a service includes in its prompt count are taken
  out; reasoning tokens are part of the output and not added to it. What the service reported is kept word for word.
- Cost is an estimate at list price unless the service reports a cost itself (the Claude subscription's command line
  does). Claude models have built-in prices; for other models you enter your own on the page, and earlier requests
  are estimated again. A call within a subscription costs nothing extra: its figure is what it would cost on the
  pay-as-you-go API, and is shown apart from pay-as-you-go cost. A request whose usage or price is not known has no
  cost - it is listed as such and never counted as zero.
- Every change of an application's status is kept from now on, and tasks remember the steps they went through.
- Totals from before (calls and tokens per task) are carried over as history, without a model and without a cost:
  neither was recorded then, and neither is made up.

### Security

- The local server now refuses requests that do not come from its own pages. It has no login and relies on being reachable
  only from this computer; before this change a web page open in the user's browser could send it requests (approve a
  pending draft, change a setting), and a domain name pointed at `127.0.0.1` could read from it. Requests with a foreign
  `Host` header, and API requests from another site, are answered with 403. The whole origin is compared - scheme, host
  and port - so a page served by another program on the same computer is not taken for the program's own page either.

- Sites are told apart by the host of an address, never by a name appearing somewhere in it: a look-alike address such
  as `evilgreenhouse.io` or `evil.example/?next=myaccount.google.com` is no longer taken for the real site when a posting
  is recognised or when the program decides that a sign-in has finished.
- A prompt can only be saved or reset under a key from the registry; a crafted key could name another `.md` file.
- Location text from a posting can no longer stall the regular expressions that read it.
- Importing a table of postings takes a file path, so it is available on the command line only
  (`autoapply import-tsv <path>`); the API endpoint for it is gone.
- Identifiers of postings read from careers pages are derived with SHA-256; stored ones are re-keyed once at start-up.

### Fixed

- Forms with several steps that the AI explored (Amazon's application form, for example) are now walked by what is on
  the screen, not by the page numbers recorded in the draft. Such forms resume where an earlier attempt stopped, skip
  steps they already have and put optional offers in between, so "fill page 1, press Next, fill page 2" failed with
  *could not advance to the next page* - often on a page that had nothing to do with the draft, like an offer of text
  message updates. Now each step is handled on its own: fill the questions that are there, read what the form reports,
  let the AI finish what is left, go on with the form's own forward button ("Skip & continue" included), and where there
  is none let the AI find the way. Optional offers are declined. The run stops at the review page, where you submit.
  Answers the form did not ask for again are compared with the review page and listed for you when they cannot be
  confirmed. A step that will not go on is handed to you in the window with the reason, instead of failing the run.
- Whether a form has moved to another step is told by what can be seen of the step (the step the form marks as current,
  its headings, controls and buttons). The first `<form>` of a page was used before; on Amazon's page that is a hidden
  log-out form, so the program never noticed that "Skip & continue" had worked.
- A take-over on one step is given every approved answer of the application, not only the ones the driver located on
  that step, so a question the driver cannot find gets its approved value and never a newly made-up one.
- A form that names a missing answer only after "Continue" gets one more round of finishing before the step is handed
  over. An error text that was on the page before the fields were changed no longer counts as a new problem.
- A multi-select that shows its choices as chips is no longer reported as "required, still empty".
- You sit at the same window as the program. When you submit the application (or close the window) while the program is
  still working on the form, it now notices: the confirmation page ends the run and the application is recorded as
  submitted with what the page showed. Before, the confirmation page was treated as one more step to fill in, and the
  run ended with "no confirmation page seen".
- A step the form itself calls a review is recognised before anything is filled in. Controls that a page keeps in
  collapsed or cut-off sections (the summaries on a review page) no longer count as questions that are on the step.
- An application whose filling was cut off because the program was closed twice no longer shows "filling in" for ever;
  it can be started again.
- Forms the AI explored have no driver code, so a take-over there no longer leaves a "driver patch suggestion" card that
  nobody could act on (open ones are closed once). What the take-over found is kept in the notes for the site, and
  those notes are now also given to the model that answers the questions of the next draft for the site - a length
  limit a form only shows after typing is respected the next time.
- An approved answer that a form refuses for its length or format is rewritten by the AI take-over to fit, instead of
  being handed back to you on every run. Before, the fixed rule of that prompt was "never alter an answer", so an answer
  of 1,400 characters in a field that takes 200 stopped Amazon's form each time. The rewrite keeps to what the approved
  answer says; you are shown the old and the new text before anything is submitted. What was learned is kept: the draft
  holds the adapted answer and the limit (the next run needs no AI), the notes for the site name the limit, and a
  question with a known limit is answered within it from the start.
- A question that only you can answer (the profile does not say) is handed over once. The step is no longer given to
  the AI again and again for the same thing, and the question joins the draft as an open question: answer it once in the
  program (with "remember this answer") and it is filled from then on.
- What a form asks that the draft did not have is no longer lost. If you answer it in the window, the answer is read
  from the page, written into the draft and remembered in your profile, so no form asks it twice. If you do not, the
  draft comes back to you with the question in it (pending again, "needs your answer"); answering and approving it
  starts the filling again.
- A draft made from a form whose later steps could not be read yet (they open only after the earlier ones are filled)
  names those steps instead of looking complete.
- A control is found by its label only when the label is the question. A label that merely contains the question's
  words is another question: "First Name" was filled into "Legal First Name" when its own field was not on the page.

### Repository

- Security policy, code of conduct, issue and pull-request templates, weekly dependency updates.
- The shell scripts are executable after a clone (`./start.sh` works without `chmod`).
- CI uses current versions of the GitHub actions and rehearses the publish step on every run.

## [1.0.0] - 2026-11-14

The first release of the rewrite. The previous code base is kept on the `legacy-v0` branch; nothing of it is carried over.
Why it was rewritten, and what is done differently, is in the README under *What the previous version got wrong, and what changed*.

### The application chain

- Postings from the careers pages you choose: Greenhouse, Lever, Ashby, SmartRecruiters and Workday boards, eight large tech companies, job boards that publish a feed, or any careers page read by the AI. 46 employers and 16 job boards are checked and ready to pick from.
- Scoring against rules written in plain language; hard exclusions are applied before any AI is used.
- Drafts: the real form is read, every question is answered from your profile only, each answer shows its source and confidence, and unanswered questions are left for you.
- Review in the page, with changes asked for in plain words.
- Execution: a driver fills the form; the program reads what the form itself reports (invalid fields, error messages, required fields still empty); an AI finishes what is left, from your profile only; what remains is listed for you in a visible window. Nothing is called filled in while the form says otherwise.
- Tracking through your mailbox, read-only (Gmail, Outlook, any IMAP mailbox).
- Notifications on Telegram, in the interface language.

### You and your data

- A first-run guide sets the program up for your career stage, field and target roles; not only for software roles.
- The profile is a Markdown document you and the AI both edit; salary, notice period and referees have a form of their own.
- Region packs describe how forms ask in Canada, the United States, the United Kingdom, the European Union, Australia and Singapore.
- Everything stays on your computer. Export and restore in one file.

### AI services

- Claude subscription, ChatGPT subscription, the Claude and OpenAI APIs, Gemini, DeepSeek, Qwen, OpenRouter and any OpenAI-compatible endpoint.
- Backups: when the service in use runs out or cannot be reached, the same step is repeated on the next one, for the main and the small model alike.
- Allowance: shown where a service reports it (Claude and ChatGPT subscriptions, DeepSeek, OpenRouter), with a warning before it runs out.

### Packages

- Windows: an installer with a window of its own (choose the location and the shortcuts; upgrade, repair and uninstall with the same program; Chinese and English).
- macOS: a disk image with the app.
- Linux: a self-extracting installer.
- A portable zip for all three.
- A tray / menu-bar launcher: status, what needs you, pause, start at sign-in.
- Every package is built by the release workflow and installed and started on its own system before it is published.

### Known limits

- The packages are not code-signed.
- Workday and the UBC portal driver have not been run for real past the sign-in step.
- The macOS and Linux packages are exercised by CI only.
- The English interface is machine-translated.

[Unreleased]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Liam-Frost/AutoApply/releases/tag/v1.0.0

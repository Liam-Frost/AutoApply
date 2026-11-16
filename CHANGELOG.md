# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **AutoApply can live on a server**: a Linux machine, a NAS, a container - no screen, no desktop - and be used from
  another computer or a phone.
  - **The remote window.** What opens a browser window on a desktop - signing in to a site, pressing Submit
    yourself, taking over a form - is shown in the program's own page where there is no screen: a notice at the top
    of the page (and a Telegram message with a link), and you click and type on the picture of the page. A site that
    refuses a hidden browser gets a real window on a virtual screen (Xvfb), shown the same way through noVNC. The
    window is served to another device over HTTPS only; nothing typed is logged, no picture is stored, and neither
    is shown to the AI.
  - **Secrets without a keyring**: where the system has none, passwords and keys go into one encrypted file. Its
    master key can be given from outside (`AUTOAPPLY_MASTER_KEY_FILE`).
  - **`autoapply doctor`** and *Settings -> Advanced -> This computer*: what the computer lacks for the program's
    whole job - the browser's libraries, a virtual screen, a PDF converter, fonts, where secrets are kept,
    unencrypted access - each with the command that fixes it.
  - **`autoapply service install`**: a systemd user service, started with the computer and restarted when it fails;
    the Linux installer registers it with `--service` and upgrades a copy that runs as one, letting the running task
    finish first.
  - **A container image** (`ghcr.io/liam-frost/autoapply`, x86-64 and ARM64) with everything a server lacks, and a
    `docker-compose.yml`. `autoapply set-admin` sets the administrator in the terminal, for computers that have no
    browser of their own.
  - **A sign-in can be carried to another computer**: exported under Site accounts as a file encrypted with a
    passphrase, imported on the server - for passkeys and for sites that only accept a computer they know.
- **The program learns from its runs, and keeps what it learned.** After a run that filled a form, plain arithmetic
  looks for what stood out against earlier runs on the same site - a step several times slower than usual, the AI
  taking over again and again, a field the driver could not fill. Only then is the AI asked to write down what the
  program should do differently there: a *recipe* (data the generic driver follows: how to work a kind of control,
  when to wait) or, where no recipe can say it, a small *plugin* (code).
  - It is kept under `data/learned`, not in the program's folder, so an upgrade does not lose it; after an upgrade it
    is checked again before it is used, and parked - not deleted - if it no longer passes.
  - Before it is in force it has to pass a gate: a plugin may import only what a driver works with, it must load,
    and the site's saved pages must still be read as before.
  - In force, it is on trial: where it fails in a run, the ordinary way takes over in that same run and it is taken
    out; it is also taken out when runs with it keep failing or get slower. Two good runs make it permanent.
  - By default this happens by itself; *Analysis -> Time & learning* has the switch to be asked first, and lists
    each thing learned with why, its text, how its trials went, and buttons to take it out or try it again.
  - The read-back against the approved draft and the rules about submitting are not something a revision can touch.
- **A site without a driver of its own gets one written as soon as an application there has gone through.** The
  first time, the generic driver fills it and the AI steps in where that fails. Afterwards the AI is given that run -
  every take-over, every field the driver could not fill, the notes kept about the site, the steps of its form - and
  writes what the generic driver needs to fill that site without help. It goes through the same check and trial as
  everything else learned (a trial that fails takes it out again), and is asked for once per site.
- **What was learned can include a tool for the AI.** Where the AI had to work something out step by step on a site
  and will need it again, the code it writes may add a tool of its own for the take-over on that site. Such a tool is
  checked like the rest, cannot be about submitting or signing in, and one failure takes it out.
- **A driver the program wrote can be given back to the project.** When a site's driver has held up in its trial, a
  card asks whether to report it: this once, always, not this time, or never (the preference is also under *Analysis
  -> Time & learning*). The program sends nothing itself: saying yes opens GitHub's new-issue page in your browser
  with the text filled in - the site's address, the driver, the program's version; no answer of yours, nothing from
  your profile - and it is yours to read and submit.
- **Where a run's time goes** is recorded for every run: the program working the form (per field), waiting for the
  AI, tools the AI called, waiting for the site, and - shown but never counted - waiting for you. *Analysis -> Time &
  learning* shows it per application system over time, per run, and step by step for one run.

### Changed

- **The Windows installer is rebuilt.** It was a self-extracting archive around a PowerShell script that drew its
  own window, which is why the taskbar showed PowerShell, the file had no icon or version details, and the progress
  line showed unreadable characters. The window looks the same - the program's own design, English or Chinese, light
  or dark - but is now a program of its own with the program's icon, name and version, and the installing behind it is
  done by Inno Setup, so the program is registered and removed the way Windows expects.
  - **An upgrade can be taken back.** The new version is copied beside the installed one and swapped in; if its
    dependencies cannot be installed, or you cancel, the previous version's files return. Before, the old folders
    were deleted first and a failure left a broken installation.
  - **It does not stop the program for you.** While AutoApply is running the installer says so and waits; it used to
    end every Python process whose command line mentioned the folder, whatever it was doing.
  - **uv comes in the package**, one fixed version checked by its SHA-256 when the installer is built. The installer
    no longer downloads a script and runs it.
  - **The browser is asked for on every install and upgrade** (and by the start scripts and the macOS and Linux
    packages): "its folder exists" was taken to mean it was there, so an upgrade that needed a newer build did not
    get one.
  - **Progress you can read, and a Cancel button**: a percentage where the download reports one, a moving bar where
    it does not. The log is kept with your data (`data/logs`, the last twelve), not in the temporary folder.
- **The macOS app and the Linux installer work the same way** as the Windows installer, through the same code
  (`scripts/prepare.py`): an upgrade is laid out beside the installed version and swapped in, and put back when its
  dependencies cannot be installed or you stop it; uv comes in the package (for Intel and ARM alike) instead of being
  downloaded as a script; a running AutoApply is not killed - you are asked to quit it; logs stay with the data.
  The Linux installer no longer needs `unzip` or `curl`, and ends with a result a script can rely on (0 ready, 2
  stopped, 7 running, 1 failed).
- **A browser that was downloaded but cannot start is found at install time**, on every system: it is started once.
  On Linux, where that usually means missing system libraries, the installer says so and names the command that
  installs them, instead of the program failing later on its first application.
- The tray icon and its notifications are AutoApply to Windows, not `pythonw.exe`, and shortcuts are written directly
  instead of through PowerShell.

### Fixed

- **A sign-in stays in the browser it was made in.** Which browser does a site's work used to be decided by the kind
  of work, so a site you had signed in to in the ordinary browser was read or filled in the automated one, with the
  cookies carried over - where the site showed you as signed out and asked for a sign-in you already had (Google's
  careers site; the university portal before). Now the browser is decided per site, by where its sign-in is: reading,
  filling, scanning and signing in all happen there. Where each sign-in was made is recorded when it is saved; a site
  that signs in through a provider follows the provider; and a provider's sign-in is no longer shown to the other
  browser at all, which is what could make the provider sign the real one out.
- **Filling a form in the ordinary browser works like filling it in the automated one.** Once a site's work followed
  its sign-in there, the first application stopped with `"Tab" has no attribute "closed"`: that browser had only ever
  been used to sign in and to read. Every test that drives a form now also runs in the ordinary browser (in CI too),
  which is how the rest was found and fixed: asking whether the window is still open, the page's short forms
  (`page.check(...)`), keys such as the space bar, and
  - the browser is now closed in order, so its profile keeps the session as the site last left it; it used to be ended
    outright, which lost what had changed during the run;
  - a profile's own cookies are no longer written over with the saved copy at every start.
- **The ordinary browser is always a window.** Hidden, it calls itself `HeadlessChrome` - not the browser you signed
  in with - and the university portal's firewall, which lets the window in, turned every hidden scan away (the card
  then advised switching on what was already on). A sign-in made in a window is now used in a window: where nobody
  has to look it opens and closes by itself (on a server, on the virtual screen). A site that turns the hidden
  browser away is remembered the same way for every caller, the firewall's own check is given time to pass, and if a
  window is refused too the card asks for the sign-in that renews the pass.
- **An e-mail that cancels an interview is no longer announced as an invitation to one.** The reading of an e-mail
  said what it was about (an interview) and that was taken for what it said. It now also says what the e-mail does:
  announces, changes, recalls or cancels. A cancellation does not move the application to that stage - and takes it
  back to where it was if it stood there; the notice says "Interview cancelled", "Interview arrangements changed",
  "Offer withdrawn" and so on.
- **The card says whose sign-in is missing.** When the run stopped on a provider's own sign-in page - or the site's
  sign-in is the provider's, as with Google's careers site - there is one card for the provider ("sign in to Google
  again"), not a card per posting offering "use my Google account" for Google itself.
- **An answer in a draft can be changed after the draft was approved.** The "Edit" button was only there until you
  approved, so a wrong answer noticed afterwards - or one a run failed on - could not be corrected, and neither
  could the résumé. Now every answer can be changed for as long as the application has not gone out. The draft stays
  approved (the change is your own), what was changed is listed with the draft, and "Fill in again and submit" uses
  the answers as they are now. A draft is closed only when it is an old version, when the application was sent, or
  while a run is filling the form from it - and it says which.
- **A list whose button shows less than the entry it holds no longer stops a run.** A phone-code list has "+1 United
  States", "+1 Canada", "+1 Bahamas"...; once one is chosen its button reads "+1". The program took "the button did
  not change to the entry's text" for a failed choice, then took "+1" against "+1 Canada" for a difference from the
  draft, and the AI, asked to look, could only say that the country is not visible - so the run was handed to you
  although the right entry had been chosen. Now the list itself is asked which entry it holds: it is opened, the
  entry it marks as chosen is read, and it is closed again. The approved entry: no difference, nobody is asked.
  Another entry: a difference, and the message says which. The same goes for a location list that shows "Vancouver,
  Canada" for "Vancouver, BC, Canada".
- **"You have already applied" is one answer, wherever the program meets it.** Met while a form was being filled, it
  was understood; met while the form was being read - the AI reporting it, or the site's own list of your applications
  showing the posting - it became a card saying the program could not work the site. Now the application is recorded
  as sent, with what the site showed (and its date, when the site gives one; no date is made up), and the cards and
  drafts that waited on it are closed.
- **A posting that turned out closed (or a site that was down) on a second attempt no longer ends in "FOREIGN KEY
  constraint failed".** The empty application is taken away together with the record of its status changes.
- **The university's co-op portal is worked in the ordinary browser for everything**, not only for signing in: a
  browser rule saved by an earlier version sent reading and applying to the automated browser, which the portal turns
  away. When its list of postings is not on the page, the error now says what the page showed.

## [1.0.3] - 2026-11-16

### Added

- **A login.** The page asks for one, on this computer as well as from anywhere else: the program holds your profile,
  your documents and your sign-ins to employers' sites. There is one account, the administrator's, and you choose its
  name and password the first time you open the page on the computer the program runs on - nothing is generated, shown
  or written to a log. Only a salted hash is kept. Five wrong passwords in a row close the door for a quarter of an
  hour. Forgotten: the tray icon's "Reset the administrator password", or `autoapply reset-admin`. The tray icon and
  the command line use a token kept beside the data instead of a login.
- **Settings -> Access & security**: where the server listens (this computer only, every network, one address), the
  port, a path prefix for serving it under a reverse proxy, how long a login lasts, the administrator's password, and
  "sign out on every device". HTTPS is left to a reverse proxy: tell the program one is in front and the login is only
  sent over HTTPS. The address, port and prefix are kept in `data/access.json`, so a wrong value can be repaired with
  a text editor; they take effect when the server is restarted.
- An e-mail that does not say which application it is about is matched on the employer's own site (read with the saved
  sign-in, read-only), and the card for it lets you choose the application yourself.
- An optional second browser backend (nodriver), chosen per site and operation; off by default.

### Changed

- Workday listings are read politely: descriptions only for postings that are new and that your rules keep, a pause
  between requests, and "too many requests" is waited out and retried.
- Nothing the program starts opens a console window on Windows.

### Fixed

- A pick-list that has to be searched (a location or school picker that shows a few entries and a search box) is
  searched the way a person does it: the search is typed key by key into whatever the list takes typing in, and the
  entry that is the wanted one is chosen - "Vancouver, Canada" for "Vancouver, BC, Canada", never a guess between two
  that fit. Before, the search box's value was set by program, which such lists ignore (some close), so the driver
  failed and the agent - which did try to search - had no tool that could type; the field came back to you on every
  run. The agent also has a plain "type these keys" tool now, for controls none of the helpers know.

### Security

- The route that serves the interface answers from a list of the built files instead of putting a path together from
  the address. 1.0.2 already kept such a path inside the interface's folder; this form leaves nothing to check, and
  code scanning recognises it. A link in that folder that leads out of it is not served.

## [1.0.2] - 2026-11-15

### Changed

- **Forms that are a walk through several steps are read and filled by the AI agent, not by coded steps.** On such sites
  (Workday for now; the list is the setting `agent.reads`) the coded driver signs in and hands over; the agent looks at
  each page and decides what to do there, and the program's own rules stay what they were: nothing is made up, nothing
  is submitted without the approved draft, every value is read back and compared, the run keeps its evidence. Coded
  reading of these forms broke on every new site - a list that opens late, a notice taken for an error, a field without
  a name - and each break came back to you as one more draft.
- **Every site's form is read by the agent** (`agent.reads` is `["*"]`); the coded drivers sign in and are otherwise
  tools.
- **An approved draft is submitted by the program whoever filled the form.** A form the agent read used to be handed
  to you for the last click in every case, and so was any run in which the AI had worked on the form. Neither is a
  reason: the answers are the ones you approved, and they are read back before anything is sent. The program submits
  unless you keep the last click for that site or company, an answer is below your confidence bar, or the run leaves
  something that is yours to settle - a question the profile does not answer, a field that could not be filled, an
  answer that could not be confirmed. Then it stops and gives you the window, with the reason.
- **What the agent works out about a site is kept as the site's plan and used on its next posting.** Which questions
  a step has, what kind of control each is and where it is: a later posting takes a known step from the plan, answers
  it from your profile and fills it with no agent. A plan holds structure only (never an answer, never code), a place
  enters it only after it was checked on the live page, a step is taken from it only when every place it names is
  there, and an entry that is not found twice is dropped, so a changed form is read by the agent again. Plans are JSON
  files under `data/sites/`.
- **What should happen by itself does.** A draft whose form still has unread steps is read on without a button; the
  button stays as "read now". Every ten minutes, postings whose score has reached the draft threshold and that have no
  draft yet get one (six at a time, best first) - also right after the threshold is lowered in the settings; before,
  the threshold counted only at the moment a posting was scored. Regular jobs (scanning for postings, reading mail,
  the self-check) count their interval from their last run, not from the start of the program: a scan every twelve
  hours never came round on a program that is closed or restarted more often than that. The activity page shows the
  regular jobs with their last and next run and a "run now", and their intervals can be changed there.
- **A form is read to its end before you are asked anything, and you are asked once.** Where a required question that
  only you can answer would stop the reading, the agent enters a stand-in to get past it and says so in the draft. A
  stand-in is never submitted: the draft cannot be approved until you have answered, and your answer replaces it
  (setting `recon.provisional`).
- The agent knows which documents you have on file and can attach them. A form that asks for a transcript on a later
  step gets it; "Did you attach your transcript?" is answered by attaching it, not by asking you.
### Fixed

- Pressing Submit in the program's window no longer closes it. Between the review page and the page that follows there
  is a moment with nothing to read; the program took that for the window having been closed, ended the run, closed the
  window on you and missed the submission. It now waits for the next page, and reads a confirmation from the page's
  title and address as well as from its text.
- An application that has been sent leaves nothing waiting, however the program learns of it - it submitted, you
  submitted, the employer's site says an application already exists, or a confirmation arrives by e-mail. Its cards
  under "needs me" (failed runs, sign-in requests raised for it, open questions) are closed, a draft still waiting for
  approval is closed, and queued work on its form is cancelled. Applications that were already sent are put in order
  when the program starts.
- A confirmation e-mail for an application whose form the program had filled now confirms it, even when the program
  believed the run had failed or was filling the form again at that moment. Before, such a mail was recorded and changed
  nothing.
- When the employer's site answers "you have already applied for this position" instead of showing the form, the
  application is recorded as sent with what the page said. Before, this was read as an expired sign-in and you were
  asked to log in.
- Asking to fill or mark an application that is already sent is answered in plain words, and the out-of-date card
  disappears, instead of an English "application is already confirmed".
- Workday: a session that is signed in is recognised. The candidate home shows "Sign In" for a moment before it shows
  the account menu, and the program looked at whichever came first - so right after a sign-in (yours, or its own with
  the saved password) it concluded that nobody was signed in, tried the sign-in page again, was sent on to the candidate
  home and waited there for an e-mail field: "automatic login failed", however often you signed in. It now waits until
  the page has settled. A sign-in page the program cannot work no longer counts as a wrong password.
- Workday: opening the application form waits for the form to appear, and presses "Use My Last Application" once
  more when the first press came before the page was ready. Before, the program looked for the form a moment after
  the press and gave up with "application flow did not open".
- Workday: a step is read once its fields are there (the progress bar comes first; a draft made in between was empty
  and looked ready - an empty first step is now an error). The résumé upload is recorded when its box has no id. A date
  box that a click cannot reach is given the focus instead. "Résumé successfully uploaded" is no longer taken for an
  error of the form, which stopped the reading on that step.
- Workday forms are read as far as they go in one pass, and the reading goes on by itself. A field the program cannot
  work no longer ends the reading (it is noted in the draft). When the form stops at a question only you can answer,
  your answer starts the reading again from there - before any approval - and is used there; answers you typed into
  an earlier draft of the application are not asked for again. The draft says how far the form was read and which
  steps are still unread. Before, such a draft looked ready, and approving it ended in "the form changed" and yet
  another draft.
- Workday: several rows of one question that the site carries over from your last application (the websites) are left
  as they are when they already hold the entries; retyping them made two rows equal for a moment and the form answered
  "You can't add duplicate website URLs". The draft shows what the rows hold. Questions on questionnaire steps are read
  with their real wording (some came out without any, or with the chosen value as their name), a group of tick boxes
  is one question with several choices, and "First Name" under "Legal Name" and under "Preferred Name" are told apart -
  one answer for both had put the preferred name into the legal name. A list is read from its own box: the choices of
  the field before could be recorded for it, which later looked like a changed form.
- An answer the employer's site holds from an earlier application is compared with your profile when the form is
  walked: where the profile plainly says something else, the draft marks it "differs from your profile" and shows both,
  and you decide which one goes in.
- A card that asks you to sign in to a site is closed as soon as the program is signed in there, however that came
  about. A draft that is built clears the "failed" note of the attempt before it.

- A confirmation link in an e-mail ("confirm your e-mail address to finish signing up") is opened by the program -
  when, and only when, it is the site's own: the program is signing up or in on that site at that moment, the link is
  https and leads to that same site (another domain, a mail service's redirect, a look-alike host, an address with a
  user name, a port or a bare IP in it are not opened), and the address is in the mail word for word. The address,
  which carries a one-time token, is not shown to the model or written to a log. If the link leads away from the site,
  the window goes back and nothing is typed there. A link that is not opened is reported, and the account is marked as
  needing you. The site's password is typed on the site's own pages only.
- Tailoring a résumé with "reorder and allow rewording" never reworded anything: the instruction the model works
  under said "keep the applicant's facts exactly as written", and it took that for the wording too. It now says what
  is meant - facts, numbers and tools stay, the words around them may follow the posting - and the request asks for
  rewording where a bullet describes what the posting asks for in other words. Every rewording is still checked in
  code (no new number, no new tool or product name) and shown in the list of changes.
- Entries a form already holds in another order than the draft lists them are left where they are, and the draft takes
  the form's order. An upload that was read as "the file box" is made on the step it was read on, not on another step's
  file box. A step is named by the form's own "you are here" mark and read once it has stopped loading; before, the
  frame between two steps was read as a step with nothing on it, and three of them ended a walk as "going in circles".

- A filled, correct form is no longer handed back to you over how a control reads. A search box whose choices show as
  pills beside it counts as answered; a ticked box is a ticked box whatever the control calls it; and what still reads
  differently from the draft is looked at by the agent on the page before you are told - only what it finds different
  is reported, with what the form shows.
- A document the form already shows is not uploaded again; every visit used to add another copy.
- Optional questions and sections that take entries (work experience, education, languages, links) are filled from
  your profile by default; "fill optional items too" on the settings page turns that off.
- The self-check deals with what it finds instead of reminding you: it tries another posting before it blames a system,
  removes saved pages that are out of date, raises no cards and closes the old ones.

- A list that is searched (a location or school picker) is no longer taken for a list of its first few entries. The
  agent marks it as searched and looks the applicant's own value up in it; the answer is not limited to the entries
  it happened to see; and when editing a draft you can type a value that is not among the ones listed.
- A form that creates your account on the site together with the application ("Create a Career Profile account",
  marked optional) gets that section filled: the agent chooses the password option and the program types a generated
  password it keeps for you (never shown to the model). After the submission the site's confirmation e-mail is
  completed under the rules for links, and the account is ready for the next application there; if that does not
  work, the account page says what is missing. Before, the section was left empty and the account stayed "being
  registered".

- Calls through the ChatGPT sign-in have a cost: the list prices of `gpt-6.1-sol` and `gpt-5.6-luna` (OpenAI's price
  page, 2026-11-15, with the long-context tier) are built in, and requests recorded without a price are estimated
  again when the program starts. The two notes on the AI settings tab about what had not been checked are gone.
- A document a form kept from an earlier application - another résumé, cover letter or transcript than the one for
  this application - is removed and replaced by the current one instead of being sent along with it.

- The drafts page: select all or any drafts and approve them, have them rebuilt, or drop the postings in one go; the
  version has its own column; and a draft shows one state in plain words (the second, internal one beside it is gone).
- The analysis page has "last 7 days" and "today" (the local calendar day).

- A saved sign-in is found when the same employer's sign-in page is reached from another address. An employer whose
  postings appear under two addresses (a careers site and its own domain) was asked for a new sign-in under the
  second one, although the sign-in page - and the saved account - was the same. The account is now found by the host
  of the sign-in page (exactly that host), and both addresses share its saved session and password.
- A search on the jobs page says how many matching postings are in the other groups (applied, not applying), with
  one click to see them all.

- A form's account section is handled by what is known: when an account for the site is saved the agent signs in
  ("Already have an account") instead of registering a second time, and falls back to creating one only when the
  site says the account does not exist; with no saved account it creates one. Before, it was told to create one in
  every case.
- A password the site itself refuses counts towards "failed twice" again, so that a wrong stored password is not sent
  over and over; a sign-in page the program could not work still does not count.
- The legend of "where each application stands" keeps an entry on one line.

### Security

- The route that serves the interface could be made to return files outside its folder with an address such as
  `/..%2F..%2Fdata/...`. The server is reachable from this computer only and refuses requests from other sites, so this
  was open to programs on the same computer; it now serves files of the built interface only.

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
- A form whose later steps open only after the earlier ones are filled is now read to the end before you are asked to
  approve anything. Reading without filling saw only the first step, so the draft looked complete and the rest came up
  in the middle of filling. Now, once the first draft has an answer for every question, the form is walked in a hidden
  window with the draft's own answers, step by step, up to the review page; nothing is submitted and no window is handed
  to you. What the later steps ask joins the draft: answered from your profile where it says, and as an open question
  where only you can answer. Answering it starts the walk again from there. The draft is shown as ready only when the
  walk reached the review page or cannot go further without you, and such a draft is never approved by itself. The
  walk fills in the employer's form, which may keep what was entered as an unfinished application; it can be turned
  off (in the settings), and started by hand on the draft's page for a draft made before this version. The draft names
  the steps that are still unread.
- A step the walk stands on is read completely, not only where the form complains. Questions the employer's site
  already holds an answer to (from an earlier application, or your account there) join the draft marked "already on the
  site", so the draft shows everything the form will send; the program leaves them as they are unless you change them
  in the draft. Steps the site has complete and never opens again are read from the review page.
- Every question a take-over reports comes with where it is on the page, and is refused when its label is not the
  form's own wording, so the driver finds and fills it by itself the next time - no AI for a form that was walked once.
  A radio question known only by the label of one of its choices is set and read as the whole group.
- Answers a review page keeps folded ("Show all answers") are unfolded before the draft is compared with it, so
  answers that are there are no longer listed as "could not be confirmed".
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

[Unreleased]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Liam-Frost/AutoApply/releases/tag/v1.0.0

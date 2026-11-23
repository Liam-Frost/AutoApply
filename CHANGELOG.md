# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **One design system for the whole interface.** Every page is rebuilt from the same shared pieces, so content no
  longer decides layout. Lists are one kind of table: a column's width comes from its definition, never from the
  longest value in it, every row has the same height, long names are cut with the whole text in a tooltip, and the
  less important columns give way first when the window is narrow - the page itself never scrolls sideways. Buttons,
  fields, selects and tabs of one level are the same height everywhere; an icon alone always has a name; rarely used
  and destructive actions live in a row's menu instead of a red button on every row. The browser's own tooltips are
  gone: one tooltip, one menu and one popover, with the keyboard, in both themes.
- **Applications**: the next step is a short task ("Prepare for the interview", "Await reply") with whose move it is;
  *Next event* shows the time and what it is (the calendar's words) instead of repeating the company and position;
  the latest news is one line. **Postings** rows are one height, the score and the deadline line up.
- **Site accounts**: one credential cell (dots and an eye, or "not saved" and a plus; a shown password hides itself
  again after 30 seconds), and the states that were mixed up are said apart - the credential, the saved session (never
  called "signed in": it is a saved session, with the latest date it can be valid to), and whether the program can
  sign in by itself. A failure shows as a short state with its reason behind it; the technical detail is in the row's
  details. Clearing a session, removing a saved password and deleting an account are three separate things in the
  row's menu. The third-party sign-in cards share one structure and line up; a provider's settings are behind its menu.
- **Wording**: concise product language in English, Chinese and French, one name per thing
  (`docs/ux-writing-glossary.md`); long subtitles and helper paragraphs went behind an (i) or were removed, keeping
  what is needed to decide and every safety statement. Dates are written one way everywhere.
- **Analysis**: the cards are put together by what they hold, not stretched to one height. The time to a first record
  and the to-dos waiting are one strip of figures; the kinds of to-dos dealt with (the first five, the rest behind
  *Other kinds*) and the to-dos waiting longest (with their state, and *View all*) are two cards of their own; missed
  postings have a row of their own. Two cards share a row only when they hold about as much - on every tab.
- **Settings → Notifications** in five parts: channels, what to notify about, quiet hours, handling it from your phone,
  and calendar and reminders. The time zone is chosen from a list you can search - by city (in English or your
  language), country, zone name or offset ("+08", "UTC-7") - with each zone's offset now, from the program's own time
  zone rules; an old spelling (`US/Pacific`) goes on working, and a saved value that is not a time zone is shown as
  such, never replaced without you. Each kind of calendar item's reminders are chips ("1 day before", "30 minutes
  before") added from the usual choices or any amount in minutes, hours or days, instead of a list of minutes to type.
  Quiet hours are a switch and two times ("22:00 to 08:00 the next day"), what still goes through behind the (i).
- **About** in three tabs. *Overview*: the name, the version, how this copy runs and its links in one compact block;
  then one *Software update* section - where the version stands (up to date, a newer one, downloading, ready to switch,
  switching, failed) with only the actions that state allows, the update settings (a short list of choices, the
  channel, the hours for switching by itself), and *Advanced*, folded: how to update a copy run from source by hand,
  how updates work, the runtime details and *Copy diagnostics*. A version prepared or kept to go back to is named by its
  version ("2.0.2, local build, Nov 22"), not by its folder. *Changelog*: every release on one timeline, all of them
  folded at first - a line each with its date and a short title; opened (one at a time), a release shows its main
  changes in a few lines, in your language, and *View the full release notes* opens the notes as written. Search and
  one filter by kind; a link to a release opens it (the address keeps it). Changes not released yet are a block of
  their own above the releases. *Licences*: every component the program runs on - what it declares and what those
  pull in - searchable, each with its licence's text.
- **The files written for a posting you are not applying for are archived with it** - kept, not deleted, and back
  where they were if you take the posting up again (a file you archived yourself stays archived).
- Documentation for contributors: `docs/component-guidelines.md`, `docs/ux-writing-glossary.md`,
  `docs/ui-quality-assurance.md`, `docs/ui-ux-audit.md`; a UI lab at `/ui-lab` shows every shared component in its
  states.

### Added

- **Times in the employer's time zone are converted to yours.** A mail that says "Tuesday, November 24, 10:00 AM (Surrey
  local time)" used to be kept as 10:00 on your own clock. The mail reader now says which zone a time is in - from the
  place the mail or the posting gives for the employer, not from an abbreviation alone ("PT" is not one clock:
  British Columbia stopped changing its clocks in 2026, the US West Coast did not) - and the program converts it with
  its own, current time zone rules. The item shows the time on your clock, the mail's own words, and what it was
  converted from; when a mail gives a time and nothing tells whose, the item says so. A scheduling tool's "shown in
  your time zone" is left as it is. *Settings → Notifications → Calendar and reminders → Calendar time zone* names your zone
  when it is not this computer's.
- **A period that fixes a date gives one**: "you have 14 days to complete the assessment" becomes a date counted from
  the day the invitation was sent, on the calendar and with its reminders. A reminder that comes in the middle and says
  "within two weeks" again does not start the period again; an extension the employer announces, or a date a mail
  states outright, does move it.
- **An interview keeps the end its mail gives** ("10:00 to 10:45", or "a 45-minute interview"), converted like its
  start: the calendar draws it that long and the calendar feed carries it. Without one, nothing is claimed.
- Cards that were waiting when this version starts are read once more for both.

### Fixed

- **"Ready: switch to 2.0.2" on a program that already was 2.0.2.** A version that was prepared and is the one
  running (or older) is not offered; the page says it is up to date.
- A later mail that names no time (the meeting's invitation) no longer wipes the time's own words off the card.
- **Files**: postings whose application was withdrawn, or that you are not applying for, were listed under *In
  preparation*. They have their own group, *Not submitted*; their files are kept and can be archived in one go.
- **Analysis**: a short card beside a long one is no longer stretched to the same height; the kinds of cards from
  before 2.0 have names, and two kinds with one name are one row.
- A chosen reminder is as tall as the buttons that add one, its words centred.
- **A calendar item's time on the applications page was read as UTC**: an interview at 10:00 showed as 18:00 (or
  03:00), eight hours off the calendar. It is the same wall-clock time everywhere now, whatever the time zone of the
  browser; the day of an outcome and the name of an exported file use the local day too.
- **An information request that had been answered was still shown as the application's next event.** What is done is
  not next.
- A row's menu could close the moment it opened when it was pressed right after scrolling.
- Deleting several files for good is asked about as the dangerous thing it is; so is withdrawing several applications.
- Text the program kept before 2.0.2 is still recognised after this release's rewording (the wording of 2.0.2 is kept
  for that).
- **Quiet hours were on the computer's clock**, not yours: with the program running in another time zone (a server),
  they were someone else's night. They follow the calendar time zone now.
- A reminder at the start of a timed calendar item was called "the morning of the day".
- The time an update was last looked for was shown eight hours off.
- A select with nothing chosen yet had an arrow three times too big.
- An API address that nothing answers is a "not found", no longer the interface's page.

## [2.0.2] - 2026-11-22

2.0.2 brings what was planned for 2.0.1 and 2.0.2 in one release: a calendar with reminders and a feed for your calendar app; the cards on Telegram and Discord with the buttons that deal with them, and an assistant in the chat; one page per application; the program in English, Chinese and French; and updates from inside the program.

### Added

- **Calendar** (sidebar, under *Needs you*): everything with a time - deadlines of postings not yet sent, interviews, assessments, offers to answer, information an employer asked for, people to get back to, and your own events - in three views with three jobs. The month to plan: what is coming and where it bunches; on a crowded day an interview or an assessment keeps its line and the day's other deadlines are one count, and how many lines fit is measured, so a busy day never grows the grid. The week to schedule: a time grid where what has a time sits at its hour, side by side with what it meets, while deadlines are counted in the whole-day strip instead of stacking up at 23:59; a click on an empty half hour starts a new event there. The day to do: one list - what is late, what has a time, the deadlines to act on first, the other things to do, what is done. One panel for an item from any view, with what the item has (the time as the mail wrote it, the posting, the application, its reminders) and what can be done with it: mark it done, change its time, give it a link and open it; on a deadline, open the posting, start an application or mark it as not applying. Quick filters and a full filter (every kind, application status, company, priority employers, score) share one state; a search; a line of what is coming (due today, due in 7 days, upcoming interviews, overdue), each number opening the list it counts. Colours by kind in both themes, always with a glyph and words; red only for what is late. The view, the date and the filters stay when you switch views and are in the address. Keys: T, ← →, M / W / D, N, /.
- **Reminders of your own** on any calendar item - as many as you want, "this long before" (5 / 15 / 30 minutes, 1 / 2 hours, 1 / 2 days, 1 week, or any number of minutes); a whole-day item is reminded of in the morning. Each kind of item gets its own by itself (*Settings → Notifications → Calendar reminders*; an interview a day before and 30 minutes before). They follow the item when its date moves, stop when it is done, carry the item's link as a button on Telegram and Discord, and appear at the top of the to-do page. The fixed "the day before and on the day" is gone: the cards already open got the reminders of their kind. Reminders go out in the quiet hours too, unless you tick that they should wait.
- **The calendar in your calendar app**: download what the page shows as an `.ics` file, or subscribe to an address that your calendar app reads again by itself (titles, times, links and a line - never answers or mail text; each item's reminders included). The address has its own read-only token and can be replaced.
- **The link an employer's mail gives** - the meeting of an interview, the start of an assessment, the page to answer an offer - is taken from the mail with what it asks: one link becomes the item's link (an *Open* button on the card, the calendar and the reminder); several are listed for you to choose from. A link is taken only as it is in the mail, never made up, and your own choice is kept when a later mail comes.
- **Discord**, next to Telegram (*Settings → Notifications*): a bot of your own sends the cards to your direct messages; bind it with a short code you send it. A channel webhook works too, for notifications without buttons. Each channel can take its own kinds of notification.
- **Deal with a card from your phone.** Cards on Telegram and Discord carry the buttons that deal with them - continue, enter the code, retry, don't apply, answer the question, approve and send (the card lists the answers the agent was not sure of and the files that go with it). Reply to a card to answer its question, give it the code, or say something to the agent of that application. Commands: /status, /todo, /pause, /resume, /scan, /app.
- **An assistant in the chat**: anything else you write to the bot goes to a small agent that can look up how things stand, start, retry or stop an application, mark a posting as one you are not applying for, pause and resume, scan, and enter the answers you give it to the questions an application waits on. It narrows what it looks up ("the ones closing this week", "not applied yet, score 8 or more"), knows what is on the calendar in the next days, and remembers what the conversation was about ("and the other one?") for twelve quiet hours. Several things at once wait for your press on a confirmation button. It cannot approve, send e-mail, change your profile or ask for a password. A **summary each morning** on your phone, if you switch it on: what waits for you, today's calendar, what went out and what came back yesterday - put together by the program, without the AI.
- **The program in your language, and French.** Dates, times, numbers and amounts follow the interface language. Every page, and everything the program says - statuses, reasons, refusals, card titles, task summaries, notifications - is written with message keys, English as the source with a note for translators: said in the page's language (each browser can use its own) and in the program's language on your phone. What was kept before (a card's title, an application's latest event) is recognised at the first start and read in the reader's language too. What the AI writes for you follows the language you chose. **Français** is the third language, complete, with its dates, numbers and plural forms. A language is two files and a line in `languages.json` (see CONTRIBUTING); one below 95% complete is offered as a test.
- **About page and updates** (sidebar, under *System*): the version and how this copy runs, the data folder, this version's changes, links, and the components with their licenses. Updates: look for a new release (stable, or pre-releases too), download it with its checksum checked, prepare it next to the running version (its own dependencies from its lock file; nothing in the package is run), and switch through the tray's restart - the database backed up, the new version tried, what is in progress finished, and the old version kept running if the new one does not start; the version before is kept to go back to. By itself: off, tell me (once a day; the default), prepare it, or update by itself when idle within a window of hours (03:00-05:00 by default). The notification on the phone has *Update when idle*; switching now is on the page. A source checkout or a container is told how to update instead. The update look asks GitHub only and sends nothing about you.
- **Analysis: where the time goes.** Questions you were asked in several applications, each with *Write into my profile*; how long a posting waits for its first record (from finding it and from beginning it); what waits for you and for how long, with the oldest open cards; why good postings were missed (no link, never started, waited for you, did not get through, still under way, withdrawn); how long a submission with an unknown outcome stayed unknown.
- **How an application gets done** (*Analysis → Automation*): how many runs an application takes, how each run ended, the share of the work spent going over an application again in later runs, and the steps and time to get one ready to send, by recruiting system. Read from each application's own record of its runs.

### Changed

- **Postings and applications, each one thing.** *Postings* is what is out there and whether to apply: To decide, Started, Not applying (yours, or a rule - named), Closed, Archived; a posting with an application only leads to it. Correct a posting's company, title, deadline, link or description - the next scan does not write over what you changed, and says what the source has now ("use the source's" takes it back); delete a posting you added yourself; "I applied myself" on one or several. *Applications* lists every application from the moment it is begun: Waiting for you, In progress, Sent, Moving, Ended, Archived - with whose move it is (you, the agent, the employer), the one thing to press, and the deadline or the next date. Approve several at once after seeing, for each, the answers the agent was not sure of and what changed. One page per application: where it stands with the buttons for now and everything under *More* (not applying after all, record what came back - an interview or assessment with a date goes on the calendar - a note of your own, correct the record, archive), then the record (what was the draft page), the agent, materials, mail, the story and the posting. The drafts page and its menu entry are gone (the number is on *Applications*); "Sources" moved into the postings page; old addresses lead to the new places.
- **Material library: what each file is for, whose it is, where it went.** Your own files, files written for one posting, and files the agent put together from yours (now in the library, with what they hold); the application each belongs to and how it stands; the records, uploads and mails it went with. Filters for what went out and what an application in progress still uses. Files of applications that are over can be archived in one go - archived, never deleted - and a file that went out with an application is archived instead of deleted: it is what was sent.
- **A mail in the conversation of an application is about that application.** A reply to a mail the program sent for an application, or a mail in a conversation already placed, goes to that application whatever its wording - it is no longer guessed from the company's name. When you say which application a mail is about, the other mails of its conversation that nobody could place go with it.
- **A changed fact stops the applications that would send the old one.** When you change your profile, applications that are not sent yet and have answers resting on a changed line - named as their source, or holding the old value - stop where they are (an approval goes back to waiting) and one card lists them with the answers concerned. Prepare them again (the agent changes only those answers) or send them as they are. One being worked is told at once.
- **A record that waits for approval keeps its window** for ten minutes (*Settings → Automation → How the agent works*): approved in that time, the agent sends it from that page instead of opening the site again, finding the form and checking every field over. At most three such windows at once; they do not count among the applications worked at once.
- **The next run starts from where the last one stopped**: its brief has the address, the page and what the page showed, so it checks instead of going over every field again.
- **Fewer looks**: after waiting or opening an address, the agent is told what changed and the start of what the page says - in the runs so far, 79% of the calls after a wait and 51% after opening an address were a look at the page, each a whole turn of the model.

### Fixed

- **A version staged for the next restart is also used at the next start.** Started with nothing running (the shortcut, `start.bat`, after the computer slept), the tray used to start the version that ran last and switch to the staged one only at a restart. It now checks the staged one (database backed up, the release imported), starts it, and starts the previous one if it does not pass or does not come up.
- **A company's name with the posting's fields glued to it** ("Ballard Power SystemsDepartment: ...Work Term: ...Contact: ...") is read as the name, on the calendar and the postings page; what was kept is not changed, and the portal's postings are taken in with the name only from now on.

### Known limits

- The packages are not code-signed.
- The English and French text was written with an AI's help and has not been read by a native speaker yet; corrections are welcome (see CONTRIBUTING).

## [2.0.0] - 2026-11-21

2.0 changes how an application is worked. One AI agent takes it from the posting to the confirmation, with everything the program knows in front of it and ordinary browser tools in its hands. The pipeline around the model that 1.x had grown - a driver per recruiting system, a form read into a structure before anything was filled, an AI "take-over" for pages that would not fill, a gate on what it could press, recipes and plugins learned from runs, a self-check replaying saved pages - is removed, not kept as a fallback. The README says why.

### Changed

- **One agent works an application.** It reads the pages, decides what each step is, signs in or registers, fills every section from your profile and résumé, uploads the right files and looks again after each step. It is given the whole context at once: the posting, your profile, your files, what earlier runs on this application did and what is written down about the site. It keeps that context for the whole run: it stands with the agent's instructions and is sent whole with every step, so when a long run's conversation is shortened by the AI service (the Claude command line summarizes the older part once it fills up), your profile and your answers are still there in your own words. The run's journal says when that happened.
- **How applications are sent is one setting** (*Settings → Automation → How it is sent*): by itself when nothing is open; after you have approved the record; or the agent stops at the last step and gives you the window. Companies you name are always yours to send. A new installation sends by itself when nothing is open; an installation that asked for an approval of every draft still does after the update, and one that kept the last click still keeps it.
- **A draft is the record of the application**: what was entered for every question and where it comes from, written by the agent after it worked the real form. Answer what is open, correct an entry or write what to change, and the agent goes back to the site and changes it.
- **An answer belongs to the application it was given for.** It becomes something the program knows about you from then on only when you tick "also from now on" - offered ticked for a question about you in general, unticked for one about this job.
- **Four things are fixed whatever the agent decides**: nothing about you is invented (what is missing is asked); sending follows your setting, and an application is recorded as sent only with its confirmation (the page's own words, its address, what ties it to the posting, and a picture of the page as it stood); a password is typed by the program into the site's own sign-in page and never shown to the agent - it is taken out of everything the agent's tools answer and of the journal, and a box that holds it is covered in the pictures the agent takes - and human checks are yours; an application has a budget (400 steps and 45 minutes by default) and asks when it is used up.
- **A backup carries what the agent wrote down about each application** (its journal, what the application has used of its budget, what you said when you asked for it), so that an application restored on another computer is taken up where it stood. The pictures taken on the way are left out.
- **A run that is cut off is taken up again.** Where an application stands, its record, its journal and what it has used are kept by the program, not by the model: the next run reads them and goes on from what the site actually holds. If a run said it was about to send and did not say what came of it, the application is recorded as "outcome not known" and the next run looks for it on the site before anything is pressed.
- **You can speak to the agent while it works.** The application's page and its draft show what the agent writes down as it goes, with a box under it: what you say reaches the run with its next action and stays on the application's record. Said too late for that run, the agent takes the application up again with it.
- **Several applications at once** (*Settings → Automation → How the agent works*): three at a time unless you set otherwise, up to six - never two on the same site, where there is one account and one sign-in.
- **The agent's browser window can be shown** (same place): off, it works in the background; on, the window is on screen while it works, to watch or - after *Stop* - to go on in yourself. An application whose last press is yours always shows its window.
- **A résumé rewritten for the posting is the agent's to ask for.** The program used to decide before the agent ran (by score and switches); now the agent has a tool for it and is told what there is and what your settings say. Switched off, none is written; and with "look at a new one first" on, an application with a résumé written just now waits for your approval, as before.
- **What only you can give is asked for while the agent waits.** A code a site sent to your phone - or to a mailbox the program cannot read just then - is typed into a box on the to-do card and goes straight into the page the agent is waiting on. An approval on your phone has a *Done* button: the agent goes on at once, in the same session, before the approval runs out. You are asked only when the page is still there after a few seconds - a second factor that remembers your device passes by itself - and when the page goes on, the agent goes on without anyone pressing *Done*. A CAPTCHA is done in the window; if the window was hidden, the application is taken up again in one you can see. Nobody there for ten minutes: one card remains, and pressing it takes that application up ahead of the queue. A code or a link a site sends by e-mail the agent reads itself, at any point of an application.
- **Nothing is left standing.** Every application that is not finished has work in the queue or a card with you - checked as a whole after every run, at start-up and every few minutes, and put right where it does not hold: an application whose task ended in an error is tried again later and once more after that, and then says on a card what happened; a card that work waits for is put off until tomorrow by "not now", not closed; a closed card whose work still waits is made again; "not applying, close" on an application that did not get done takes it off the list of what is under way; a card about an application that is finished is closed.
- **Sources and followed employers are in the sidebar**, under Postings - not only behind a quiet link on the postings page.
- **How often new mail is looked for is a setting** (*Settings → Automation → Schedule*), next to the pass over the last days that stands behind it. Where the mailbox is asked every few minutes what is new, no separate looks for one application's confirmation are queued; those that are queued are dropped once the application is confirmed.
- **The settings page has one row of navigation**: the second row, which repeated the titles of the sections below it, is gone.
- **Analysis: applications by hour, day, week or month.** The chart of how many were sent follows the stretch of time the page is set to - hours for today (and only for today), days for a month, weeks for a season, months beyond - or the scale you choose, with the steps in which nothing was sent shown as such. The axis names every step it has room for, by the width it really has.
- **How hard the model thinks is yours to set for every service**, not only for Claude: the ChatGPT sign-in and the services with an OpenAI-style interface have the same choice (left unset, the service's own default).
- **List prices for the current OpenAI models** (GPT-6.2 Astra and Sol, the GPT-6 and 5.x families), with their long-context rates.
- **A question to you is one line with the form's own choices.** The agent asks one question for each box or list of a form - not a section's ten lists described in one question to be answered in a text box - with that list's choices to pick from and, where it has a basis, its own suggestion, which you can take with one press. What it asked is no longer listed a second time among the answers.
- **An application that goes by e-mail is sent as one.** The agent reads the posting for the address, the subject and what to attach, writes the mail, and hands it to the program, which sends it from your own mailbox - after you have looked at it (the default: you can change the recipient, the subject and the text first), or by itself if you set so (*Settings → Automation → How the agent works*). The mailbox's own record of the sent mail is the evidence that the application went out. Needs Gmail connected through the API and authorized once more: sending is a permission the program did not have.
- **A reply to an employer's question is written for you.** When a mail about one of your applications asks you something, the card has a reply ready: answered from your profile and the application, with every point only you can answer marked `[[like this]]` in the text. It cannot be sent while a mark is left, and goes into the same conversation when you send it.
- **The agent can put your files into the shape a posting asks for.** Résumé, cover letter and transcript as one PDF, a form with fewer upload boxes than documents, a prescribed file name, only some pages: the agent makes that file from the ones you have (PDFs, Word documents, pictures) instead of asking you to. Your own files are not changed, and the made file stays with the application.
- **A card with a date of its own can be closed without doing it** (a survey after applying, say).
- **A posting the employer took down is taken off your list.** When the posting's page says it no longer exists and the employer's own search does not have it, the agent reports it as gone: the posting goes offline, the application is put away, and you get a notice instead of "did not work - try again?". If it is in fact still there, one button takes it up again.
- **The agent can change browsers.** A site that turns the automated browser away ("access forbidden", a check that never ends) is taken up again in the ordinary one by the agent itself, and the site is remembered. No wording of a page decides any more whether the other browser may be tried.
- **The service can be replaced while it runs.** A new version is staged next to the running one (`scripts/stage_local_release.py`), and *Restart the server* in the tray - or `--restart` on that script - backs up the database, checks the new version, lets the old one hand over what it is working at a safe point, and switches; if the new one does not come up, the old one is started again. What is queued or waiting for you stays in the queue. Not yet: taking back work from a version that died without handing over.
- **A cover letter is written as a task of its own**, and the application goes on when it is ready; an uploaded file is read back from the site's own list of attachments before it counts as given.
- **A mailbox whose authorization ran out says so**: a card to authorize Gmail again, instead of sign-in cards for every employer that was waiting for a mail.
- **Settings show one limit for the agent**: what one application may take, over all its runs. The limits for reading a portal and an employer's site keep their values and are no longer on the page.
- **Three kinds of stop have three answers.** The AI service's allowance ran out: the task waits and is tried again. The application's budget is used up: you are asked whether to give it another. It ended at the same place three times: it is brought to you. You can also stop a run that is working (*Stop*, on the application's page, its draft and under *Activity*).
- **What is learned about a site is sentences.** The agent writes down what the next application there should know, and reads it the next time. Notes about Workday, Greenhouse, Ashby, SmartRecruiters, Lever, SAP SuccessFactors, Amazon, Google Careers and Orbis co-op portals ship with the program. *Analysis → Site notes* lists what was written and clears it per site.
- **The agent's manual can be read and changed** (*Settings → Expert tools → Prompts*). Whether optional sections are filled, what happens to consent notices and job alerts, whether an account is registered: these are sentences in the manual or in your profile now, not switches.
- **A portal that needs a sign-in is read by the agent.** It signs in to the co-op portal with the saved login (you approve on your phone), finds the list and gives the postings to the program - by a script it writes or takes from its notes, so that hundreds of postings are not typed out again through the model, and it is shown every posting that was stored. How the list was read the last time is in its notes, not in code that runs before it.
- **Which application an e-mail is about** is settled by the agent reading your list of applications on the employer's site - signing in again if the saved sign-in has run out. It is sent there whether or not a sign-in is saved; what the program has to get in with is said to it.
- **Analysis → Automation counts by application as well as by run**: how many applications were brought to where one press sends them, how many of those without you (sign-ins aside), how many of those that were to be sent are out with their evidence, and the time and AI use one application takes. The table by recruiting system is gone.
- **Your profile is written as soon as your résumé is uploaded.** The first-run guide asked for a résumé and then for a second press of a button to make the profile from it - under a "skip, next" that was the page's main button, so the guide could be finished with an empty profile. A résumé uploaded while the profile is empty starts the writing by itself now, wherever the upload is made (the guide, the files page, the profile page); the guide goes on meanwhile and says where it stands on the résumé step, on the summary and on "try one".
- **"Generate from résumé" is a task in the queue, not a request the page waits for.** What was written used to live in the page that asked: another page and back, and it was gone - with the minute it took. The page can be left now; opened again, it shows the task queued, being written, what it wrote, or why it did not work. With no profile, what was written is saved as the profile; with one, it is a draft kept until you adopt it (as you edited it) or discard it. The task has a worker of its own, so it does not stand behind a scan or a form that is being read.

### Removed

- The drivers for Greenhouse, Ashby, Workday and the UBC portal, the explorer for other sites, the fallback chain, the AI take-over of a page, the gate on what it could press, the watch for an early submission, the answer cache, recipes and plugins learned from runs and their sharing as issues, the self-check that replayed saved pages, and the timing of driver runs - with their settings, cards and pages. Tasks that waited in the queue under the old kinds are carried over to the one task there is now; cards about drivers and learned code are closed.
- Settings that steered the old pipeline: who reads a form, when a draft passes without you, who presses Submit per recruiting system or by confidence, whether the AI may take over, learning from runs, automatic registration per system, sign-in with a provider, the self-check interval, budgets per kind of AI work. Applications sent with 1.x and their drafts stay in the history.

### Fixed

- **A run in which the model never worked no longer uses up the application's time.** A run that ended at once because the AI service could not be reached, or its allowance was used up, was charged the minutes it took to start a browser and wait: nine of them took twenty of an application's forty-five. Such runs are on the record and cost nothing; time taken this way before is given back.
- **A mail is sent through a connection that drops, and not twice.** One cut connection left a reply unsent. Reading is asked again; a mail that may or may not have gone out is looked for in the mailbox by its own id before it is sent again. What you are told when it still fails is a sentence, not the error's text.
- **An application stood in the list of records once for every time it had been approved.** A new version of a record superseded the pending one before it, not the approved ones; approved, worked again and approved again, an application showed as three records, each "approved, queued".
- **"Claude Code CLI not found" for an application with a long brief (Windows).** The agent's manual and the brief of the run are given to the Claude command line as its system text, on the command line itself; Windows takes 32,767 characters there and answers "file not found" to more. An application with a long posting, a full profile and a journal of a few runs went over it, could not be started at all, and was reported as Claude not being installed. A long system text is now given in a file; and when the command line is there but cannot be started, the message says that.
- **A sign-in whose button did nothing was sent with an empty password.** The program typed the stored password, pressed the button and emptied the box again; when the press had done nothing (an ordinary browser opens its own list of saved passwords over the form, and the first click only closes it), the agent sent the form itself - empty - and the site answered "invalid login name/password", twice. The program now follows the press: it presses again through the page, then sends the form directly, and tells the agent whether the form went out.
- **"Remember the password I type" is kept in the ordinary browser's sign-in window too.** Every sign-in card offers it; in the window of the ordinary browser (the one used for sites that refuse an automated browser, the co-op portal among them) nothing was ever remembered, whatever was ticked - the applicant signed in, and was asked to again each time the session ran out. The login is now taken from what the sign-in form sends, as the browser reports it: nothing is put into the page, and a form the browser's own password manager filled in is heard as well as one that was typed. A password given at a site's own sign-in on another address (a university's login) is that site's and is kept; one given at Google, Microsoft or LinkedIn during "sign in with" still never is. A card offers to remember only where its window can: a card for a sign-in provider says that only the sign-in is kept, and a card whose window the program does not look into (a site that refuses the automated browser, with the ordinary browser switched off) points to the Accounts page instead.
- **Nothing is scored or drafted for an applicant nothing is known about.** With the profile empty, postings were scored against an applicant block with nothing in it - scores that stayed, since a posting is scored once - and the best of them had their forms read: minutes at the employer's site for a draft in which every question was "no answer", and a card for each. Scoring and the reading of forms wait for a profile now: one card says so ("your profile is still empty"; none while the profile is being written), and both go on by themselves when the first thing about you is saved. Scanning for postings is not held back. A draft that was written before this, while the profile was empty, has its unanswered questions asked again when the profile is there.

## [1.0.4] - 2026-11-18

### Added

- Analysis → Automation has a table by recruiting system: how reading its forms and filling them went (success rate with the counts under it, forms handed over and submissions awaiting confirmation listed apart), how long the program itself worked, how often a filling run handed the form to you, how often the AI took a page over, and what the model was asked for that system's postings. Every site's form is read by the AI first now; this is where to see on which systems that pays.
- A contract both browsers keep to (`tests/test_browser_contract.py`): the selector shapes the program writes, the frames it looks for, boxes the page itself is in charge of, files, windows and the mouse - each written once and run in the automated and in the ordinary browser against the same expected answer. The sign-in window has the same (`tests/test_takeover.py`). The tests that are run once more in the ordinary browser are one list now (`tests/ordinary_browser.txt`), with the sign-in flows in it.
- A learned plugin has to keep to a contract before it is tried on an application: on a form it was not written for it either declines a field and leaves it alone or fills it and the field holds the value; it reads what is there; it changes nothing else, leaves the page where it is and sends nothing - and so do the tools it offers. A rule of a learned recipe has to name the field it is for.
- **What each source gave, and why the rest was not taken in.** "Sources and watched employers" lists every source
  with when it was last read (and, for one that cannot be read now, when it last could and what it gave then), how
  many postings it gave, how many passed the hard conditions, and the reasons the others were dropped, counted; and
  where the postings it did give stand now: at the threshold, below it, ruled out by a scoring rule, not scored yet.
  A summary over all sources says which kind of reason accounts for "it read hundreds and there is nothing to apply
  for", with a link to try the conditions on a few titles. Numbers only: postings that were dropped are not kept.
  (It showed the latest scan and nothing before it; a source that failed today showed an error and no history.)
- **An overview of what the settings come to** (Settings opens on it). Two halves, read-only, every line leading to
  the place where it is changed. *What I apply to*: what you told the program, the hard conditions a posting has to
  pass before it is taken in, your scoring preferences, and the thresholds from which a draft is prepared - each
  marked as which of these it is. *What the program may do now*: finding postings, preparing drafts, approving,
  pressing Submit, creating accounts, accepting privacy notices, letting the AI take over, learning - each with who
  does it now and the exceptions by system and by company. It is read from where the program reads its rules, not
  written beside them.
- On a draft, every reason why it is you who presses Submit leads to the setting that decides it.
- **What you typed and did not save is not lost without a word.** Leaving a page with unsaved changes - the settings,
  a prompt, any editor of the profile - asks first: save, discard, or keep editing. So does switching what is being
  edited (another prompt, another AI service, another section or tab of the profile), and closing or reloading the tab
  gets the browser's own question. Nothing is asked when nothing was changed.
- **The settings say how each tab is saved.** A line under the tabs names it: the button at the top right, a part's
  own button, or at once. The button shows how many changes wait ("3 changes not saved yet"), is inactive when there
  are none, and the tabs that hold unsaved changes are marked. The three access settings that need a restart are
  labelled so.
- **What a mail asks of you becomes a to-do with its date.** An invitation to an interview or an assessment ended
  in a notice and a status; what to do and by when stayed in the mail. It is now a card with the date the mail
  states (and the mail's own wording of it, time zone and all): said the day before and on the day, moved when the
  employer moves it, closed when the employer calls it off. You can complete it, change its date, or add one. A
  date is only ever what the mail states - a mail that names none gets a card without one. A contact's follow-up
  day makes a card the same way.
- **"Remind me later."** Any card can be put off - until tomorrow, in three days, next Monday, or a day you choose.
  It is out of the way and out of the count until then, and is shown and said again when the time comes.
- **Quiet hours.** Set hours in which nothing is sent to your phone (off by default). What comes in then is kept
  and sent as one message when they end; it is on the page all along. A sign-in the program begins by itself that
  would ask for an approval on your phone is not begun in those hours - a card waits for you instead. The approval
  of a sign-in you started yourself still reaches you.
- **The plan: what is being done, what comes next, and what you can do about it.** The activity page opens on the
  plan now - what is running, what is queued in the order it will be taken, what waits for you and for what, what
  you set aside, and what is set for a later time. A queued task can be done first, set aside and taken up again,
  or cancelled (an application whose work is cancelled does not go on saying "queued"). A running task is not cut
  off halfway.
- **"Finish what is being done and stop."** For closing or restarting the program: it starts nothing new, tells
  you when the last task has ended, and goes on with the queue when it is started again. No more watching the
  list until nothing is running.
- **A pause stops what the program does by itself, not what you ask for.** Paused, nothing ran at all - also not
  "look for mail now", pressed by you. Timed scans, automatic scoring, drafts and retries stay stopped; what you
  start by hand runs.
- **A limit on how many drafts wait for you.** A scan can bring thousands of postings, and every one that scored
  well got a draft. The program now stops starting drafts by itself once twenty are being prepared or wait for
  your approval (the number is a setting; 0 for no limit) and goes on, best first, when you have dealt with some.
  Drafts you ask for by hand are not limited.
- **"My applications": every application that has gone out, each on a page of its own.** What the program knew
  about an application was spread over the jobs list, the draft, a card, the activity record and the list of runs.
  The new page lists what has gone out and what waits for its outcome, by stage, and exports the list as a table
  (CSV). One application opens to everything about it: where it stands and what comes next, with the things you can
  do about it right there; what shows it was sent; the files that were submitted; the e-mails about it; the people
  you know at the employer; and everything that happened to it, with who said each change. News about an
  application - in the program and on Telegram - now leads to this page, and so do its cards and the jobs list.
- **You can put an application's record right.** A step that happened where the program could not see it - an
  interview in person, a phone call, withdrawing on the employer's site - can be recorded, with a date and a note;
  so can the date an application was sent. It is kept as yours in the history. An e-mail that was put on the wrong
  application can be taken off it, and one the program could not place can be put on the right one, from the
  application's own page.
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

- Settings → System → Backup says when the data was last exported (read from the export itself), what an export holds and what it does not, and keeps restoring on this computer apart from moving to another one: passwords and API keys are in no export and have to be entered again elsewhere, and saved sign-ins are encrypted for this computer - they are signed in to again, or carried one by one with a passphrase.
- A draft's answer that was given before says where: confirmed by you on this employer's form and when, filled there last time without your confirmation, or last used on another employer's form - which one - and not yet confirmed here.
- An agent has one budget, the same whichever AI service does the thinking: so many tool calls, and a moment on the clock by which it ends. Until now each service counted in its own way (model turns, its own turns, requests) and the ChatGPT sign-in did not count at all, with a time limit that started again with every message - an agent that kept calling tools could occupy the place where forms are filled for as long as it liked. When the budget ends the model's run is ended too (the ChatGPT turn is interrupted, the Claude query cancelled), and the result says which it was: finished by itself, out of steps, or out of time. A backup service that takes over goes on with what is left.
- How much each kind of work gets - reading a new form, taking over a fill, signing in, turning a page, checking values, looking up an application's status - is a setting: Settings → Automation → "How much the AI may do at a time".
- `docs/DESIGN_SYSTEM.md` describes how pages are built now: the four states of a page that reads data, the one way
  an action is carried out, what a layer over the page does with the keyboard, labels and names of controls,
  foreground colours and the contrast test, where a page keeps what it shows. Two rules are no longer unconditional:
  "the outcome of an action goes into a toast" and "what a figure counts goes into a tooltip".
- **A draft says what to look at before the table of everything.** Above the answers: the questions that have no
  answer, the answers the program is not sure of, a sensitive question met for the first time, what changed with
  the form, the files written for this posting, and who presses Submit and why - each line leading to its row. The
  full table stays as it was.
- In the library, the folder of a posting shows the employer on one line and the title with the place and term on
  the next: several postings of one employer were cut off to the same few letters.
- The activity record says in words which browser a task worked in when it was not the usual one, and why ("the
  ordinary browser: this site's account rule says so"); it showed the internal note as it stood. The note itself is
  under "technical details". "Retry with nodriver" is "try again in the ordinary browser".
- **The settings are grouped by what they are about, and every section has an address.** Ten tabs named after parts
  of the program became six groups - search goals and matching, automation and work plan, materials and answers,
  accounts and connections, notices and reminders, system and data - each a page of named sections
  (`/settings/automation/submit`, `/settings/accounts/ai`, ...). What moved where:
  the two score thresholds for preparing a draft now stand side by side; automatic approval is an expanding part of
  "approval and submission" instead of a card under "advanced", and that section says in plain sentences what the
  choices on the page come to; how often the mailbox is checked is in the work plan (it sat under "sources"), with a
  link from the mailbox; archiving and the re-posting window are "data retention" (they sat under "intake
  conditions") and say that archiving changes no application; the outbound proxy, the browser used for a site and
  the inbound access are three sections that say how they differ; how long a login lasts and the password are
  "account security", saved apart from where the server listens; the prompts are an expert tool at the end.
  Learning from runs and sharing what was learned are settings now (they could only be found on the analytics
  page, which still shows what was learned and links here). The conventions of your cover-letter template (names
  in bold, links to keep, text to replace) can be set on the page; they could only be set in the data.
- **Sources and watched employers are a page of the postings**, not three cards of the settings: the employers you
  watch, the school portal with its switch, sign-in state and sign-in, and what the last scan read. The portal's
  switch is there once (it was in two places).
- **Cards and notices lead to the section that needs changing.** A card about the mailbox authorisation, the AI
  service or its allowance, or a site that refuses the program's browser has a button that opens that section; the
  notices about the AI allowance link to it too.
- **Network accounts page: the everyday part first.** Which browser an account uses, importing passwords from
  Chrome, carrying a sign-in to another computer and adding an account by hand are under "advanced".
- Turning résumé adjustment on without a Word résumé says so on the spot, with a link to the upload. The AI service
  section says when a change of service or model takes effect: for tasks that start afterwards, not the one in
  progress.
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

- A posting whose source gives only a summary is no longer scored as if the summary were the posting. A job board's feed often carries a teaser of a few lines; such a posting is now marked, and before it is scored or its overview written its own page is read for the whole text (by a plain request, and in a browser when the page is drawn by script). When the page cannot be read the score is given on the summary, the model is told that it reads one - what a summary does not mention has not been shown to be absent - and the score's reason says "only a summary". The posting's page in the program says so as well. A teaser that is too short to score gets its chance to be completed instead of staying unscored for good, and once the whole text was read a later scan does not put the teaser back.
- A filling run now records how often it handed the form to the applicant. The column for it was there and was never written; the figure is counted from the run's steps, so earlier runs have it too.
- In the ordinary browser, several things were not done the way the automated browser does them: filling a box pressed Ctrl+A and Backspace first (in the search box of a list of chosen entries, Backspace on an empty box removes the entry chosen before) - it now selects and replaces the text without keys; typing "key by key" put the whole text in at once, so a list that searches as one types heard nothing - each character is now a key going down and coming up; text was matched with regard to case; and two selector shapes the program's own code writes (`visible=true`, `text=…`) were not understood there - Greenhouse's check for a challenge frame failed on the first.
- The sign-in window in the ordinary browser now keeps a sign-in on a site nothing can check (no driver, no known address) when the applicant closes the window, as the automated browser's window does; it used to say "window closed before sign-in was verified" every time. The two windows also agree now on what a finished sign-in leaves behind: its card is closed, and a sign-in provider's session is not listed as a site account.
- The self-check no longer deletes the saved form pages that stop matching, and no longer counts deleting them as a repair. A page that does not match may be out of date or may show that the code lost something, and the page alone cannot say which: it is now kept and marked with since when and what was missing, and is moved aside (not deleted) only when a later sample of the same form page passes. Samples are pruned by count among the passing ones only. The result of a self-check names what fails, what is new and what recovered; the diagnostics list has a line for it. Nobody is asked to do anything about it.
- The cards of the earlier self-check are closed one by one on what the run shows about each - the page matches again, a later sample replaced it, the page is gone, or the system's forms are read by the agent - instead of all at once.
- A cover letter or tailored résumé that is written again no longer replaces the one before it. Every writing went to the same file, so the records of the earlier versions - and the drafts approved with them - opened whatever had been written last, and a writing that failed half-way left them with half a file. Each writing now has a folder of its own (the file keeps the name the employer sees), and it becomes the one in use only once it is there as a PDF; the library shows which version each file is, and "use this version" on an earlier one now really switches to it. Records from before the change that share a file with a later one say so, in the library and on the draft.
- A tailored résumé that fails its checks (over the page limit) is kept as a record and no longer becomes the résumé in use; the one before it stays.
- A task told to use the ordinary browser ("retry in the ordinary browser" on a scan) now reads every listing in it. Listings are fetched side by side on helper threads, and those were handed the task's metering record only - not the browser it was told to use, not whether the applicant had asked for it, and not its own count of model calls, which missed everything its helpers asked the model. What a task is now goes with every part of its work as one copy of the context (`context.py`), and each helper's model call is its own: several helpers wrote the call they were making into one shared record.
- Reading one employer's board no longer takes other employers' postings offline. The rule for capped or filtered listings ("not shown for N days") looked at every posting of the same service, so a board that was down or switched off lost its postings to the next board that answered. Both rules now look only at the listing that was read, and the days are counted from the first reading that did not show the posting rather than from when it was last seen - a listing that could not be read for a week has said nothing in that week.
- **The PDF preview keeps to its box, and draws each page once.** "Fit to width" was the width at the moment the
  file was opened: after the window or the layout changed, the pages stayed as wide as before. They are drawn again
  for the new width. Zooming twice in a row, or while the pages were still appearing, left two drawings filling the
  same box - every page twice, in two sizes; a newer drawing now stops the older one, and the pages that are shown
  stay until the new ones are there. Each page says which page it is.
- **A page comes back as it was left.** On the postings page the group, the filters, the sort order and the posting
  that is open are in the address: a reload shows the same list, the browser's Back closes the open posting (and
  keeps the filters), and the address can be kept or sent. The analytics page keeps its view and its stretch of time
  the same way. Going back to a page returns to where it was scrolled to, once its list has been read.
- **On a narrow screen the page comes first.** The sidebar was laid out across the top - on a phone, a third of the
  screen of navigation, theme and language before the page began. It is a bar now: the page that is open, how many
  things wait for you, whether the program is running, and "menu", which opens the full navigation as a panel (and
  holds the keyboard while it is open). The postings and drafts tables show what a row is, where it stands and what
  needs attention; the other columns are on the row's own page.
- **Text that can be read in both themes.** The weakest text of the light theme (dates, counts, hints, group names)
  stood at 2.9:1 against its background and is at 4.5:1 or more on every surface now, with the secondary text
  darkened to keep the two apart; the dark theme's weak text likewise. In the dark theme, a count in the sidebar,
  an error message and a button that deletes put white on a pale red (2.1:1): they use a colour made for standing
  on it. A test holds every pair of text and background to the number, in both themes.
- **Keyboard and screen reader: what a control is, and what it is called.** A column header that sorts is a button
  and says how the table is sorted. A posting's name is a link (Enter opens its details, and closing them puts the
  focus back on it). A label is tied to the control it names across the forms - a click on it reaches the control, a
  screen reader reads the label with the field - and a row of tick boxes or a choice made with buttons is named as
  a group; stand-alone boxes (search, "paste an address") are named by their hint; the tick boxes of the drafts list
  say which draft they tick. "Choose a file" is a button the keyboard can reach (it was a label around a hidden
  input) on every page that uploads. In the library, opening a file and ticking it are two controls. The program's
  own drop-down passes on `id`, `aria-labelledby` and `aria-describedby`, and marks options that cannot be chosen.
- **A drawer or a question that opens over the page takes the keyboard with it.** The focus goes into it, Tab
  stays in it, what is behind cannot be reached or pressed, Escape closes the one on top (a question over a drawer:
  the question), and when it closes the focus goes back to where it was. A question that cannot be undone starts
  on "cancel", not on the button that does it. The posting's detail uses the same drawer as the rest of the program
  (it had a copy of its own). After going to another page, the keyboard is at that page's title.
- **"Not now" on a draft is not "send it back".** The button closed the draft, so that it could not be approved
  any more. It is a way back to the list now, and the draft stays where it was. Sending a draft back is its own
  button, asks first, and says what comes next. A posting whose only draft was sent back reads "not applied" again;
  it stayed at "a draft is waiting for you" with no draft to open.
- **A batch acts on what is shown.** Ticking a posting and then filtering it off the page left "0 postings" above
  and "1 selected" below, and the batch buttons acted on it. What a filter, a search or a reload takes off the page
  is unticked. And what a batch could not do stays ticked, to be tried again.
- **"Due today" and "due tomorrow" go by the calendar.** At noon, a deadline of 23:59 the same day was "due
  tomorrow" (half a day, rounded up to one), and a deadline that had passed that morning was "due today". Today is
  today, with the time; what is over says so. The overview and the postings page use one function for it.
- **"Sent" is one number, and the three words about what came of it mean the same everywhere.** The overview
  counted the applications whose posting is not archived, the analytics those with a day of sending: two numbers
  for "applications sent" with nothing to say why they differed (and "my applications" showed a third). Sent is now
  every application that stands at "submitted" or later, on all three; a page that shows a part of it says which
  part and how many it leaves out - the overview's chart of stages the archived ones, the analytics those without a
  date. "Acknowledged" (anything came back, an automatic confirmation included), "came to something" (an
  assessment, an interview, or a rejection) and "reached an assessment / interview" replace "heard back", "clear
  outcome" and their variants, and are computed in one place for both pages.
- What a figure counts can be opened with a click, a tap or the keyboard; it was a tooltip, there for a mouse only.
- **A task that ended is not an application that was sent.** In the automation figures, a filling task that found
  the application already sent - and did nothing - counted as a success, and one that pressed Submit and saw no
  confirmation as "filled in, waiting for you". The first counts neither way now; the second is "Submit pressed,
  outcome not known".
- **A list follows what happens while it is open.** Postings, drafts, applications, the overview, to-dos, accounts,
  the library and the activity record read themselves again when the counts in the sidebar change (a draft got
  ready, a card was settled from the phone) and when the window is looked at again; the activity record every few
  seconds while a task is running. The filter, the search, what is ticked and the scroll position stay. (Most pages
  showed what they read when they were opened, until they were opened again; the to-dos had a timer of their own
  that ran whether anyone was looking or not.)
- **A button that is doing something says so, and does it once.** Approving a draft, filling a form in again,
  saving the settings, preparing a draft and every other action that goes through the shared runner: the button that
  was pressed is shown as busy until the action is over, and pressing it again meanwhile does nothing (three clicks
  on "approve" used to be three requests). When an action succeeded and the page could not be read afresh, it says
  that - not "failed". Work that was queued says so with a link to where it stands in the work plan. What the server
  refuses when the settings are saved stays under the button until they are saved again, instead of in a message
  that is gone after nine seconds.
- **A page says whether what it shows is there, still being read, or out of date.** Postings, drafts, to-dos,
  activity, the overview, accounts, the library and the applications started from an empty list: until the answer
  came they said "0" and showed the picture for "nothing here", and when the service could not be reached they went
  on showing what they had as if it were current. They now say "reading…" until something has been read; when it
  cannot be read, that - with a button to try again; and when a later read fails, that what is shown was read at
  such a time and may be out of date. The footer of the sidebar says when the service cannot be reached and since
  when the counts have not been updated. A request that got no answer is worded as that, not as "Failed to fetch".
- A source that could not be reached (a timeout, a name that does not resolve) is said to be unreachable; it was
  shown as "this step was not completed".
- **Saving one part of a page took back what was being edited in another.** Saving an AI service, sending a test
  message or any other action on the settings page read every setting afresh and so undid unsaved changes on every
  tab; saving one editor of the profile reset the others. Reading afresh now takes what is new and leaves what is
  being edited. "Save" on the settings page sends what was changed and nothing else, and says how much it saved -
  it used to answer "settings saved" also where it saved nothing (the form of an AI service has its own button).
- **No tool of the AI sends an application - whatever the button is called by, and whichever tool would press it.**
  The AI that reads forms and the one that steps in while filling could not click a button whose text says "Submit".
  That was the whole of it: a button named only by an `aria-label` (an icon) passed; the tools that open a list or
  type clicked whatever they were pointed at first; the key tool would press Space on a focused Submit button, or
  Enter in a field - which sends the form - as long as some list was open anywhere on the page. Every tool that
  clicks or presses a key now asks one question of what it would land on: is this the control that sends the
  application, by any of the ways a control gets its name? Enter is available where it takes an entry of an open
  list, and in a text area. "Next" and "Save and continue" work as before. The tools a learned plugin adds get a
  page that asks the same question, and a plugin that clicks or sends from script inside the page is not learned.
- **If a form is sent before the program means to send it, that is seen and said.** The page itself is watched for
  the application going out (told apart from leaving a step, and from a search box with a "Submit" button). Should
  it happen while a form is being read or filled, the program does not press Submit after it, does not hand you the
  window to send it again, and does not report "failed - fill it in again": the application stands at "outcome of
  the submission not known", with what was pressed named on the card.
- **An answer you confirmed for one employer is a suggestion for the next, on every system.** On the sites without
  dedicated support this was already so. On Workday, Greenhouse and the others, answers were kept for the whole
  system, as if every employer on it asked the same question: "Have you previously worked for us?", confirmed as
  "Yes" on one employer's form, went to the next employer as your confirmed answer. Answers are now kept per
  employer everywhere; what you answered elsewhere is still offered first - marked as less than certain, saying
  which employer it came from, and not counted as confirmed. Answers kept before this are offered the same way.
  A new employer's first form therefore has a few more answers to look at than before.
- **A mail is not put on an application that did not exist when it was written.** Which application a mail is about
  was decided by employer and title, the newest first - and when the mail was written was not looked at: a mail of
  forty days ago could move an application made yesterday for a posting of the same name. Now an application that
  came after the mail is not considered (an application you sent by hand and the program met later counts from when
  it was sent); the posting's own number in the mail settles it when it is there; and what you said a mail is about
  on its card is not changed by anything the program finds afterwards.
- **Work that is for later is still there after you save a setting, and after a restart.** "Try again in half an
  hour" - the retry of a site that did not answer, the look for a confirmation e-mail after a submission - was a
  timer in the program's memory. Saving any setting rebuilt the schedule and dropped every one of them; so did
  closing the program. Such work is now a task in the queue that is not taken before its time: the list of tasks
  shows when it is due, and asking for the same work now ("draft it now" while a retry waits) takes that task
  forward instead of leaving it to wait.
- **Who presses Submit is said the same way everywhere.** A draft could say "submitted automatically" in one line
  and, in the steps below it, "this system has no driver yet: you check and press Submit"; the settings page promised
  that a site without dedicated support always stops for you. Neither has been true since which driver fills a form
  stopped deciding who submits. The decision is made in one place, from your settings; the last step of a draft's
  plan is that decision in words, made when you look at the draft (so an old draft says what is true now, and
  changes when you change the setting), and the settings page names the two things that do stop an automatic
  submission: an entry the program could not check and the AI chose, and a form that still reports something for you.
- **"Submit was pressed, and no page said it was received" is a state of its own.** It used to be a failed run - or
  "filled, not confirmed" - and either way the card's main button was "fill in and submit again": the one thing that
  applies twice if the first time went through. Whether Submit was pressed is now a fact the run keeps (also in the
  window you submit in: the page is watched for the form being sent), and the application stands at "outcome of the
  submission not known" until something settles it:
  - the employer's confirmation e-mail, which the program goes on looking for - or looks for now, from the card;
  - "I did submit it";
  - "it did not go through: fill it in again" - asked once more before it is done, and done by nothing else.

  A form that answers the click with its own complaints was not sent, and is a failed run as before. A window that
  closed without Submit being pressed is "filled in, not submitted yet", and its card offers to open the window again.
  Cards that older versions filed as failures of this kind are re-filed when the program starts.
- **An application that has gone out only moves forward.** Where an application stands was written in some thirty
  places, each with its own idea of what it might overwrite. Three things followed:
  - An application that had reached an interview, an assessment, an offer or a rejection could be filled in again:
    the run refused to start for "submitted" and "confirmed" only, and retrying an old task did not look at all.
  - A run that ended late wrote its outcome over what a mail had said in the meantime - a confirmation or an
    invitation that arrived while the window waited for Submit went back to "submitted" or "failed", and the mail's
    evidence was replaced by the page's.
  - A mail was stored first and applied to its application second: a failure in between left the mail "read" for
    good and the application where it was.

  The status now has one way in, and the rule sits on the status itself, where nothing can go round it. A run puts
  its outcome on the record as the record stands when it ends; what it saw on the page is added to the evidence, and
  a failure is not reported about an application that has gone out. A mail and what it does are written together.
  Retrying work on the form of a sent application is refused, and says why. The history of an application keeps who
  said each change: the run, a mail, the employer's site, or you.
- **A card that asks you to sign in to Google (or another provider) finishes when you have.** The card's button opened
  the window without the provider's own check for "signed in", so the window could be signed in and nothing noticed:
  the session was not kept and the tasks that waited went on waiting.
- **Forgetting a sign-in forgets which browser it was made in.** After a sign-in was removed, the next one was still
  opened in the browser of the one that no longer existed, whatever the rules said.
- **A sign-in carried over from another computer replaces the one that is there.** The ordinary browser kept using the
  cookies of the session that was being replaced, while the import said it had worked.
- **Mail is read in the order it was written.** A cancelled interview followed by a new invitation, read newest first,
  took the interview away again.
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
- **An account whose e-mail address is not confirmed is confirmed by the program, whenever it is met.** Workday shows
  "An email has been sent to you. Please verify your account." in the banner it also uses for errors, so a registration
  that had worked was filed as failed. From then on every run tried the password, was told to verify the account first,
  and asked you to sign in - to an account nobody could sign in to - while the site's mail, with a link on the site's
  own address, lay unopened. "Not confirmed yet" is now a state of the account: after registering, at a later sign-in
  and after a submission the same thing happens - the site's mail is looked for back to when the account was made, its
  link is opened, and the program signs in. If that link no longer works, the site is asked for another mail. Only when
  all of that fails are you asked, and then to open the mail, not to sign in. Accounts that were stuck this way are
  put back in line when the program starts.
  - Mail that carries a code or a link for an account is recognised by more subjects ("Verify your candidate
    account", "Confirm your ... email address") and, as before, never summarised or shown to a model.
  - A link read from an HTML mail is kept as a browser would follow it ("&amp;" in its address was left in).
- **An address that gives no answer is a site that is down, wherever it happens.** A connection that timed out at the
  first page of a sign-in was reported as a failed task and left there, while a site that answered with an error page
  was tried again. Both are the same thing now: tried again by itself (the first time after five minutes), nobody is
  asked to do anything, and it is never counted as a password that failed or a page that could not be worked.
- **The co-op portal is signed in to by the program; only the approval on your phone is yours.** The portal's sign-in
  used to be handed to you whole, every time its session ran out. Save your CWL login name and password for it on the
  Accounts page, and the program goes through the portal's sign-in itself: the password is typed on the university's
  login address only, you get a message when Duo waits for your approval, and the program waits three minutes for it.
  An approval that did not come is not asked for again behind your back - the card waits for you. A password the
  university refuses is not sent a third time. The scan signs in the same way an application does; before, it made a
  card without going near the sign-in.
- **A site that keeps its sign-in on another address gets its password there.** Amazon's careers site asks for the
  e-mail on its own page and sends the window to another Amazon address for the password. The program took that for
  "another site, with its own account", found no password for it and stopped at the password box, with the right
  password saved. A sign-in that begins on the site's own pages and is led on by the site is the site's sign-in; the
  address is remembered once the password has worked there (also when you sign in by hand). A sign-in that begins on
  another address still gets nothing typed.
- **A sign-in through an institution is gone through again before you are asked.** The co-op portal's own session
  lasts about an hour, the university login behind it longer: when the portal's has run out, the program follows the
  portal's sign-in link once - nothing is typed - and asks you only if a password or a second factor is wanted.
  The card for such a site no longer offers to register an account.
- **A site's security check is told as what it is.** Eight sources on Workday failed every scan with "429 Too Many
  Requests": not a rate limit, but a security check that does not accept requests from this computer's network
  address. Each was asked four times, with growing pauses. Now one such answer is enough: the service is left alone
  for six hours, the scan says so in one line, and requests to one service are paced together even when sources are
  fetched side by side.
- **Postings for other programmes of study are set aside before anything reads them.** A university co-op portal
  lists every faculty's postings, and each says which programmes it is for. That statement is now used: a posting
  whose programmes do not include yours is marked "not applying" with the programmes it names, without being scored.
  "Open to all majors" and postings that name no programme are not touched. Your programme is taken from the first
  entry of your profile's Education section, or set under Settings.
- **Getting through many postings takes a fraction of the time.**
  - Several postings are read by the model at once (four by default) instead of one after the other.
  - The long overview of a posting - most of what the model wrote for each - is written only for postings that score
    6 or more; for the others a button on the posting writes it when you want it.
  - The employers' listings are fetched side by side instead of one after the other.
  - Scanning, scoring and mail no longer hold applications up: they have a worker of their own, forms have the other.
  - When more postings wait than one run takes, the next run follows in a minute, not five.
- **What the program knows about a site is kept in one place.** It was in five - notes in a file per site, the steps
  of its form in another, recipes and plugins in a folder, and what was found out about signing in spread over
  settings - under three spellings of the site's name. Each site is now one record under one name: where it signs in,
  which browser its sign-in lives in, the notes, the steps of its form, and what was learned for it. *Analysis ->
  Time & learning* lists the sites, shows all of it for one, and can clear one (its sign-in stays). What earlier
  versions kept is brought over at the first start; the files it is read from are moved into a folder named
  "migrated" beside them, not deleted. Answers stay where they were: an answer is yours, not the site's.
- **An entry a site makes by itself is no longer handed to you as bare empty fields.** A form that reads the uploaded
  résumé can turn a personal project into a second "work experience" and then want its job title and city; you got
  two questions, "Job title" and "City", with no way to say that the entry should go. Now the AI holds such an entry
  against your profile: it fills what the profile states, removes an entry the profile plainly contradicts (and says
  so with the draft), and where it cannot tell asks you one question about the whole entry - remove it, or keep it.
  Fields of one of several like-named entries say which entry they belong to and are not filled into whichever comes
  first. And a question the filling ran into can be taken out of the draft ("This is not one to fill in").
- **A field the program cannot check is shown to you instead of passing silently.** A list that shows "+1" for
  "+1 Canada" and does not mark its chosen entry was accepted on the AI's word. It still is - the form is not stopped
  for it - but the field is listed on the card as one to look at, and an application with such a field is not
  submitted automatically.
- **From a review of the whole program** - places where a fault had been patched for the one case that showed it:
  - *Why reading a form stopped* was a word of the AI's own, and every word the program did not know meant "sign
    in". It is now one of six (sign-in, CAPTCHA, closed, already applied, site not answering, other), each with one
    consequence; a page that simply could not be worked is no longer a sign-in card.
  - *Signing in somewhere resumed every waiting task* - also the ones waiting for another site, which failed again
    and asked again. A task is now resumed by what it waited for.
  - *An answer confirmed for one employer* was reused on every other site without a driver of its own as if confirmed
    there too ("Have you worked for us before?"). It is still offered, as a suggestion to check.
  - *Two employers sharing one word* in their names ("... Robotics") were taken for one when an e-mail was matched to
    an application.
  - *Mail from an employer you applied to* is read even when it uses none of the usual words (another language).
  - *The settings page no longer overwrites the program's own record* (which browser a sign-in lives in, which site
    signs in on which, how far the mailbox was read) when a page that was left open is saved.
  - *"Has it been submitted?" and "was it applied for before?"* were read from the page by a list of English
    phrases; a confirmation in other words or another language was "not submitted". Where the phrases find nothing and
    the answer matters - after Submit, on a page without the form, when the window is closed - the AI now reads the
    page. It has to quote the page's own sentence, and a quote that is not on the page is not believed.
  - A handler that lets a busy page pass no longer lets a mistake in the program pass with it.
  - One list of the states in which an application counts as sent, instead of five; the portal's special rules live
    in the portal's driver; two settings nothing read, an unused copy of the browser rules, unused code and a card
    text for a card that is no longer made are gone; site rules saved with "login only" are stored as what they mean.
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

[Unreleased]: https://github.com/Liam-Frost/AutoApply/compare/v2.0.2...HEAD
[2.0.2]: https://github.com/Liam-Frost/AutoApply/compare/v2.0.0...v2.0.2
[2.0.0]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.4...v2.0.0
[1.0.4]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Liam-Frost/AutoApply/releases/tag/v1.0.0

# Contributing

Most useful contributions need no knowledge of the whole program: they add one entry to a list. This page says where
each list is and how to check an addition. Run `uv run pytest` before sending anything; the tests never reach a real
AI service or a real website.

## Getting set up

```bash
git clone https://github.com/Liam-Frost/AutoApply
cd AutoApply
./start.sh                     # or start.bat: installs uv, Python, the dependencies and the browser, builds the interface, starts
uv run pytest                  # the tests: no real AI service, no real website
uv run python scripts/demo.py --serve 8020     # a copy with made-up data to click around in, without touching your own
```

You need [Node.js](https://nodejs.org/) 20 or newer to build the interface. `cd frontend && npm run dev` gives hot reload.

## Sending a change

- Open a pull request against `master`. Changes are merged by squash, so one pull request becomes one commit; its title
  is the commit message.
- CI runs the tests and then builds every package and installs it on Windows, macOS and Linux. It has to pass.
- Say what you ran the change against. "Unit tests" and "a real form, not submitted" are both fine; they are not the same.
- Keep personal data out: no real names, e-mail addresses or application records in code, tests, screenshots or logs.
  `scripts/demo.py` has fictional data for screenshots.
- By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through
  [SECURITY.md](SECURITY.md), not through an issue.

## Ground rules

These are not open for change, because the program acts on a person's behalf:

- Nothing is written about the applicant that is not in their own material. Checks live in code, not only in prompts.
- An application is submitted only after the user approved its draft. Tools given to the AI cannot submit.
- No getting around a site's protections: no solving or bypassing CAPTCHAs, no disguising the browser. A site that
  refuses the program's browser is handed to the user.
- Passwords and sessions stay on the user's computer (system keyring, encrypted files). They never go into prompts or logs.

## Add an employer to the recommended list

File: `backend/autoapply/catalog.json`. One entry:

```json
{"name": "RBC", "url": "https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1", "kind": "workday", "fields": ["business", "software"], "regions": ["CA"]}
```

- `url` is the employer's careers page. `employers.detect(url)` must recognise it as a board with a public API
  (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) or one of the built-in sites.
- **Only add an address you have checked.** Guessed addresses are wrong more often than right: of 64 written from
  memory, 28 answered. For Workday, the test is a POST to `https://<host>/wday/cxs/<tenant>/<site>/jobs` with
  `{"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}` that returns a `total` above zero.
- `fields` are the keys in `persona.FIELDS`; `regions` are ISO country codes.

## Add a sign-in provider

File: `backend/autoapply/browser.py`, `IDENTITIES`. An entry needs the provider's sign-in page, the domains its
session cookies live on, and `done`: a function of the address bar that is true once sign-in has finished (the page
the provider lands on afterwards). Add the lower-case name to `sso.order` in `config.py`.

## Add a job board

File: `backend/autoapply/catalog.json`, `boards`. A board is a job site for a field (academic, medical, design, a public job
bank) that publishes its newest postings as an RSS or Atom feed:

```json
{"name": "BMJ Careers", "url": "https://www.bmj.com/careers/jobsrss/", "kind": "feed", "style": "employer: title", "fields": ["health"], "regions": ["GB"]}
```

`style` says how the board writes item titles, so employer and job title can be told apart: `"employer: title"`,
`"title, employer"`, `"employer is hiring title"`, or `""` when the title is only the job. Fetch the feed and read a few
items before adding it; a feed that answers 403 to a plain request, or needs an account or a key, does not belong here.
Users can also paste any feed address themselves under Settings → Sources.

## Add a school portal

File: `backend/autoapply/portals.json`. School portals sit behind a school login and usually forbid automated access, so
an importer never runs in the program's browser: it is a bookmarklet the student clicks while signed in, in their own
browser, which sends the postings on the page to the program running on their computer.

- The working example is UBC's portal: `backend/autoapply/sources/pdportal_import.js` (the bookmarklet), `sources/pdportal.py`
  (what it sends, turned into postings) and `agent/playbooks/orbis.md` (what the agent is told about applying through
  a portal of that kind).
- `status` in `portals.json` must be honest: `supported` only when the importer has been used for real by someone with an
  account there; `same_system` for a school on the same portal software that nobody has tried; `none` otherwise.
- Never ask for, store or transmit a school password, and never work around the portal's sign-in.

## Add a region pack

File: `backend/autoapply/regions.json`, one entry per country (or a shared one with a `countries` list, like `EU`):
`profile` (what the applicant's profile should state for that country), `questions` (how forms there ask about the right
to work, with the local wording), `diversity`, `formats`, `consents`, and `never` (identifiers that are never filled in
automatically). A pack describes how forms ask. It is not legal advice and it never contains an answer: answers come
from the applicant's profile. Add the country to `COUNTRY_PATTERNS` in `intake.py` if it is not recognised yet.

## Add a mailbox

File: `backend/autoapply/mailbox.py`, `PRESETS`: IMAP host, port, and a `how` text telling the user where to get an
app password. Mail must stay read-only: folders are opened read-only and bodies fetched with `BODY.PEEK[]`.

## Change the interface

The interface is built from shared pieces with fixed behaviour, so that content never decides layout: a long name is
cut, not allowed to stretch a column; every row of a list has one height; a tooltip looks the same everywhere. Before
adding or changing a page, read `docs/component-guidelines.md` (start with its ten "Rules for a new page") and
`docs/ux-writing-glossary.md` for the words. In short:

- A list of records is a `DataTable` with cells; long text is `Trunc`; hover help is `v-tip` / `InfoTip` - never a
  hand-made `<table>` for records, never `title="…"`.
- One visible action per row or card, the rest in a `Menu`; delete is last, `danger`, and confirmed.
- Only tokens from `frontend/src/style.css`: no colours, font sizes or z-index numbers of your own. Light and dark.
- Every word is a key, concise and in the glossary's terms, in English, Chinese and French
  (`python frontend/scripts/i18n-apply.py patch.json`).
- A new shared component gets a section in the UI lab (`/ui-lab`) and a paragraph in the guidelines.

What checks it: `npm test` in `frontend/` (static rules: no native tooltip, no stray colour, no unnamed icon button,
no hand-made record table; the pure layout functions) and `uv run pytest tests/test_ui_layout.py tests/test_ui_pages.py`
(a real browser measures the lab and every page: row heights, column widths, overflow, names, three window sizes,
three languages, both themes). `docs/ui-quality-assurance.md` says how to run them, how to take before / after
screenshots (`scripts/ui_shots.py`) and what still has to be looked at by hand (zoom, text scaling, touch).

To work on a page against made-up data: `python scripts/demo.py --serve 8022`, then in `frontend/`
`npx vite --config vite.demo.config.js` (never develop against a real installation's data).

## Add or fix a translation

Everything the program shows is written with keys, in English, with a note for translators on each; a language is a
pair of files. Chinese, English and French are there.

**The interface** (`frontend/src/locales/`):

- `en.json` is the source: every key, in English. `notes.json` says for each key where it is shown and what its
  placeholders are - read it before translating a key.
- Every other language is one file next to it (`zh.json`, `fr.json`). A key a language does not have is shown in
  English.
- `{name}` placeholders are filled in at run time; a translation keeps exactly the same ones. Plural forms are
  separated by `|`, in the order of the language's plural categories (English and French: `one | other`; Chinese: one
  form). A `|` that is meant as a character is written `{'|'}`.
- Dates, times, numbers and amounts are never written into a message by hand: they come formatted from
  `frontend/src/i18n/format.js` (Intl).

**What the program says** (a status, a reason, a notification, a refusal - `frontend/src/locales/server/`):

- The server writes `T("server.<module>.<key>", name=value)` (`backend/autoapply/say.py`, imported as `T`). The
  messages are in `server/<lang>.json`, with their notes in `server/notes.json` - the same languages and the same rules
  as the interface's. A message is said in the page's language where an API answer leaves (the page sends `X-Lang`) and
  in the program's language in notifications. What the program keeps (a card's title, an application's latest event,
  JSON results) keeps its key and is read in the reader's language.
- Chinese written in the server's code is data only (patterns that read what sites and mails say, words looked for):
  `tests/test_say.py` lists the files where it may be and fails on a sentence for people anywhere else.
- What the AI or an employer wrote is kept as it was written.

**A new language:** copy `en.json` and `server/en.json` to `<id>.json` and `server/<id>.json`, translate them with the
notes beside you, and add the language to `languages.json` (its id, its BCP 47 tag, its own name and its English name -
the English name is what the AI is told the applicant reads). Run `npm run i18n:status` in `frontend/`, which writes how
complete each language is; below `beta_below` percent a language is offered as a test. `npm test` and `uv run pytest`
check that every key used exists, has a note, and that translations keep the placeholders and the plural forms.

## Add a field of work or a career stage

File: `backend/autoapply/persona.py`: `FIELDS` (title words that mark the field, words that rule a posting out),
`STAGES` (words for the kind of posting, page limit, how cautious submitting is), `PROFILE_ASKS` / `FIELD_ASKS`
(what forms ask this kind of applicant), `WRITING` / `FIELD_WRITING` (how a cover letter is pitched).

## Help the agent on a job-application system

There are no drivers. Every site is worked by one agent with the same browser tools, and what helps it on a system
is words: `backend/autoapply/agent/playbooks/<system>.md`. The first line names the hosts the notes are about
(`hosts: myworkdayjobs.com, myworkdaysite.com`); the rest is what is true of that system on every employer's site -
how its sign-in works, what its steps are called, which control does not behave like it looks, what its résumé parser
gets wrong, how a sent application is confirmed. Write what you saw when you applied there, in plain sentences, and
nothing about a person. `ashby.md` is a short example.

A change to how every form is worked belongs in the manual, `backend/autoapply/agent/apply.md`. Before proposing one,
run the evaluation (`python eval/run.py --all`, or one shape at a time: `--form profile_first`, `embedded`, `account`,
`widgets`, `returning`, `closed`, `approve`, `hand_over`, and `--scan` / `--portal-apply` for the co-op portal; it
spends your AI allowance) and say what it gave: a run is judged by what the employer's side received, not by what
the agent says. A shape of form the agent got wrong on a real site and that none of these has belongs here as a new
form: `eval/forms/<name>.html`, its posting in `eval/server.py`, what a careful person would have got right in
`eval/run.py`.

## Reporting what was verified

`docs/STATUS.md` separates what has been run for real from what has only been written and unit-tested. Keep that
distinction when describing a change: say what you ran it against.

# UI/UX audit

The state of the interface on the base commit `939c6f3` (2.0.2 plus the empty design-system scaffold), written as a work list for
the migration of each page to the shared components in [component-guidelines.md](component-guidelines.md). Line numbers are those of
the base commit (`git show 939c6f3:<path>`), paths are under `frontend/src/` unless they start with `style.css`.

**How it was measured.** Code: every file in `views/`, `components/`, `style.css`, `App.vue`. Running program: the demo build with
made-up data, driven by Playwright (Chromium) at 1440, 1280 and 1024 px wide in Chinese and English (light), and at 1440 px in dark;
43 pages and states per configuration, plus the drawers, menus and the question dialog. For each: row heights of every table, whether its box scrolls
sideways, column widths, elements with a native `title`, groups of controls that break onto more lines, text squeezed into short
lines, elements wider than their parent, sizes and weights of type, heights of controls. The demo has no site accounts and no
contacts, so those two lists were measured with made-up rows put in by request interception (five accounts in different states, five
identity providers, three contacts); every other figure is from the demo's own data. Nothing was written to the demo. The dark
theme gave the same measurements as the light one and no finding of its own beyond G22; screenshots and the scripts are in the
audit's scratch folder (`scratchpad/ui/audit/`).

Severity: **P0** wrong information, or the layout breaks (content cut off, the page scrolls sideways, text one character wide);
**P1** visible on ordinary data on every visit, or blocks keyboard / touch use; **P2** inconsistency and polish.

## 1. Summary: the root causes

| # | Root cause | What it produces | Where |
| --- | --- | --- | --- |
| **R1** | **Content decides the layout.** Tables are `table-layout: auto` with no column contract (`style.css:223-229`); widths are nudged cell by cell with inline `min-width` / `max-width`; a select is as wide as its chosen option; a card is as tall as what happens to be in it; the first column of `.list > .item` is `auto`. | The same column is 49, 132 or 339 px wide depending on the tab; rows of one table are 61-204 px high; a table 1,189 px wide in a 1,150 px box; identical cards whose controls sit at different heights. | Applications, Postings, Site accounts, Contacts, Sources, the record of an application, Overview lists, analytics tables |
| **R2** | **No truncation primitive.** Text wraps wherever it is, or is cut ad hoc (`.ell`, `.clamp2`, inline `max-width`, `overflow-wrap: anywhere`); the whole text is in a native `title` in some places and nowhere in others. | Uneven rows; a 43-48 px column holding a sentence three characters per line; job titles of 10 and 41 characters giving different row heights. | every list page, Files, Overview, analytics name cells |
| **R3** | **The browser's tooltip is the tooltip.** 91 native `title`s in the source; figures are explained three different ways (`title`, `<Explain>`, a CSS `ⓘ` on `.kpi[title]`). | Slow, unstyled, clipped, not reachable by keyboard or touch; icon and glyph buttons whose only name is a `title`. | Calendar (66 rendered), Postings (61), analytics (37-57), Overview, Needs you, Files, settings panels |
| **R4** | **No hierarchy of actions.** Every action is a visible button; groups are `flex-wrap: wrap` (`.row`, `.acts`, `.page-head .actions`); a destructive action is a red button on the row or card; menus are hand-made three times. | Rows of 4-8 buttons breaking onto 2-3 lines; a red button per row; 16 primary buttons on one page; a menu that Escape does not close. | Needs you, Postings drawer, Site accounts, Files, Contacts, Application, Activity, settings panels |
| **R5** | **One weight for every state.** `.tag` and `.badge` are the same filled, 600-weight pill (`style.css:216`; 77 + 59 uses) for stage, whose move, deadline, source, recruiting system, counts, save hints. A status cell holds several facts at once. | 2-3 pills per table row; the state that matters does not stand out; "status" on the accounts page means three things. | Applications, Postings, Site accounts, Needs you, Activity, Files, Settings |
| **R6** | **No progressive disclosure.** Explanation and technical detail are laid out on the page: a subtitle on 14 of 17 page heads, 191 helper paragraphs of 110+ characters (40,700 characters in English), raw failure text, engine names (`Playwright` / `nodriver`), internal identifiers, raw ISO dates. | Pages three to five screens long (`/settings/system` 4,421 px); the one sentence that matters is lost among ten that do not. | Settings (all groups and panels), Site accounts, Profile, Sources, analytics, Activity, Application |
| **R7** | **Styling lives in the page.** 634 inline `style=` attributes, 104 inline pixel widths (34 different values); 10 font sizes, 7 weights, 32 size/weight pairs on screen against 6 + 3 tokens; controls of one level 27, 28, 32, 34, 36 and 38 px high; one undefined token, one hard-coded colour. | Controls on one line that do not line up; bold as the default emphasis (27-34% of the characters on a list page are weight 600+, 43% on Needs you). | everywhere; worst in Settings (77 inline styles), Profile (53), Application (37) |
| **R8** | **The same thing built several times.** Company + title is rendered seven ways; dates through eight helpers and five raw strings; three menus; two bulk bars; tabs with and without roles; three "unsaved" markers; two copies of the posting's facts and description; `DataState` on 9 of 20 views. | Inconsistent look and behaviour - and one real bug: the same calendar item is shown at different times on two pages (A1). | everywhere |
| **R9** | **Responsive rules test the window, not the box.** `.col-more` hides at `@media (max-width: 1000px)` while the content box is already 734 px at a 1,024 px window; `.kv` has a fixed 240 px label column whatever card it is in. | Between about 1,001 and 1,300 px of window: every Applications tab scrolls sideways (+160 to +455 px), a card overflows the page (accounts: the page itself scrolls sideways by 10-320 px), columns collapse to 40-75 px. | Applications, Site accounts, Contacts, analytics tables, Overview, Profile, Settings |
| **R10** | **Words written as speech.** Buttons, states and column headers are sentences; one thing has several names; sentences are assembled from key fragments with Chinese punctuation typed into the templates. | Wide buttons and pills; "Done, go on" / "I'm done, continue" / "Done, continue" for one action; a full-width "。" at the end of an English sentence. | Needs you, Application, Site accounts, Sources, Settings, Overview |

Nine of the ten are fixed in the shared layer first (DataTable and its cells, `Trunc`, `v-tip`, `Menu` / `Popover`, `Status`, the `--h-*`
and `--fw-*` tokens, `PageHead help`, `SectionHead help`); a page migration is then mostly deleting local styling and choosing what goes
behind a menu or a tooltip. R10 is the writing glossary's.

## 2. Inventory

One row per issue. "Shared?" says whether the fix is in the shared layer (so the page only has to adopt it) or in the page.

### 2.1 Shared layer and shell

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | `style.css:223-229` (`table`, `th, td`, `.table-wrap`) | `table-layout: auto`; cells `vertical-align: top`, no row height. Column widths follow the longest cell: Applications' date column is 49 / 132 / 339 px on three tabs of one page. | R1 | P1 | `DataTable` with column definitions (`width` / `min`-`max` / `flex`), fixed layout, one `density` per table | yes | all 8 data lists (appendix B) |
| G2 | `style.css:229` `.table-wrap { max-height: calc(100vh - 240px) }` | A scrolling box inside the scrolling page: 658 px box, 2,025 px of rows (Postings), 2,071 px (Applications, sent). Undone by inline `max-height: none` in 4 places (`AccountsView.vue:155`, `ContactsView.vue:56`, `RecordPanel.vue:124`, `RunsView.vue:174`). | R1 | P1 | `DataTable` decides once: its own box with the sticky header, or page scroll; no per-page override | yes | Postings, Applications |
| G3 | `style.css:322-337` | `.col-more` is hidden by window width (≤ 1000 px). At a 1,024 px window the content box is 734 px and all 8 columns stay: Applications scrolls sideways by 239 (waiting), 196 (sent), 455 (in progress), 160 px (ended). | R9 | P1 | `DataTable` column `priority`, by the box's width (`layoutColumns`) | yes | Postings (optional columns), Contacts (+94 px), accounts (+377 px) |
| G4 | 91 native `title` (appendix A) | Rendered: 66 on Calendar, 61 on Postings, 57 / 37 / 37 on the analytics views, 11 on Overview and Needs you. | R3 | P1 | `v-tip`, `v-tip.overflow`, `InfoTip`, `IconButton`, `Status tip` | yes | - |
| G5 | `components/Select.vue:119`, `style.css:447` (`.sel`) | The select is an inline-flex button as wide as the chosen option: 89 px ("nodriver") and 119 px (zh) / 133 px (en) ("Follow site rules") in two cards side by side; a filter bar re-flows when a filter is chosen. | R1 | P1 | `.sel` takes its width from where it stands: full width in a form field, a fixed width in a toolbar or card; the value cuts with an ellipsis (it already can) | yes | Site accounts, filter bars of Postings / Applications / Needs you, Settings |
| G6 | `style.css:177,187,191,394,447,451` | Heights of controls meant to be one level: button 34, `.sm` 27-28, select 32 (`.sm` 27), filter input 36, input 38 (35 in `.emp-add`). On one line: 32 / 36 in every filter bar, 34 / 38 in Sources' add row and in settings rows. | R7 | P1 | `--h-sm` 28 / `--h-md` 32 / `--h-lg` 36 for button, input, select, segmented control alike | yes | every page with a filter bar or a form |
| G7 | `style.css` + inline | On screen: sizes 10, 11, 12, 12.5, 13, 13.5, 14, 16, 20, 26 px; weights 400, 450, 500, 550, 600, 650, 700; 32 pairs. 13.5 px is the inline `<pre>` of the job description (`JobsView.vue:432`, `ApplicationDetail.vue:370`); 12.5 px is `code, pre` (`style.css:125`); 550 is every button and `.mat-item .name`; 650 is `.card-title`. | R7 | P1 | `.t-primary` / `.t-secondary` / `.t-meta`, `--fw-regular/medium/semibold`; no size outside the six tokens | yes | - |
| G8 | `<b>` for the primary line of a row (`ApplicationsView.vue:137`, `JobsView.vue:278`, `AccountsView.vue:160`, `ContactsView.vue:61`, `EmployersPanel.vue:57`, `SourcesView.vue:71`) | Weight 700 in dense rows; share of characters at weight ≥ 600: Postings 34%, Applications 27-33%, Needs you 43%. | R7 | P1 | `EntityCell` (primary line `--fw-medium`) | yes | all lists |
| G9 | `style.css:216` (`.tag, .badge`) | One pill for everything. Pills per table row: Applications 2-3, Postings 1.3, accounts 1.8; 80 on Activity, 66 on Applications (sent), 38 on Postings. | R5 | P1 | `Status` (dot + words) as the default in tables; `.tag` only for interview / overdue / failed / waiting for you; `.meta` for attributes (system, source, "added by you") | yes | all lists, Needs you, Files |
| G10 | `style.css:296` `.list > .item { grid-template-columns: auto minmax(0, 1fr) auto }` | The first column is an unbounded no-wrap pill. Overview, English, 1,024 px: "Application confirmation received" leaves 14-20 px for the text - "Kingsley Health · Business Analyst" stands one word per line, 108 px high, and runs under the time. | R1, R9 | **P0** | first column bounded (`Status`, or a fixed 96 px slot that cuts); middle column `Trunc` | yes | Overview (3 lists), Activity (5 lists), Profile history, Settings "try it" |
| G11 | `style.css:167` `.kv { grid-template-columns: 240px 1fr }` | Fixed label column in any container. In the half-width "carry a sign-in" card the controls no longer fit: the card is 67 px (zh) / 121 px (en) wider than its parent at 1,280 px, 323 / 377 px at 1,024 px, and the **page** scrolls sideways by 10 / 64 / 266 / 320 px. | R9 | **P0** | label column `minmax(120px, 240px)`, controls `min-width: 0`; one column when the box is narrow (container query) | yes | Site accounts; every `.kv` in a `.cols` card (Settings, Application forms) |
| G12 | `style.css:156-161` (`.page-head .actions`, `.row`: `flex-wrap: wrap`) | A group of actions breaks onto more lines instead of some of them moving behind a menu: 8 buttons on 2 lines (Postings drawer), 6 on 2 (Files preview), 4-5 on 2 (Needs you at 1,024 px), 3 on 2-3 (provider cards). | R4 | P1 | `<div class="actions">` (one line, 8 px apart) + `Menu` for the rest, by decision | yes | see J8, F2, T2, C3 |
| G13 | Menus built by hand: `ApplicationDetail.vue:205-211` + scoped CSS `:383-388`; `JobsView.vue:250-253` (`details.colpick`); `TodosView.vue:341-352` (a row of buttons that unfolds) | The application's "More" menu: Escape does not close it while focus is on its button (the handler is on the menu, which never gets focus), no arrow keys, `z-index: 20`. The column picker does not close on a press outside. | R4, R8 | P1 | `Menu`, `Popover` | yes | Calendar's `FilterMenu` (leave) |
| G14 | `ui.js:83` `ask(text, { danger })` | Red and "focus on Cancel" only when the caller says so: 9 callers do. Destructive without it: bulk **permanent** delete of files (`FilesView.vue:117`: the confirm button is the blue default and has the focus), withdraw (`ApplicationsView.vue:71`, `ApplicationDetail.vue:61`), discard a record (`ApplicationDetail.vue:69`), cancel a task (`RunsView.vue:33`), discard a mail (`MailOut.vue:41`), drop a question (`RecordPanel.vue:67`), sign out everywhere (`AccessPanel.vue:69`), restore a prompt (`PromptsPanel.vue:47`). No question at all: delete a browser rule (`BrowserPanel.vue:42`), unlink Discord (`SettingsView.vue:493`), revoke a noted line (`ProfileView.vue:153`). | R4, R8 | P1 | one rule: a menu item marked `danger` always asks with `{ danger: true }` | yes (rule) + each page | - |
| G15 | Three ways to explain a figure: `title` on the tile + CSS `ⓘ` (`style.css:551`, `CostPanel.vue:106-118`), `<Explain>` (a `<details>` that grows the tile it is in; 19 uses), a `.card-sub` paragraph | - | R3, R8 | P1 | `InfoTip` beside the label everywhere; `Explain` only where the text is several sentences → `Popover` | yes | analytics, Overview |
| G16 | Dates: `fmtTime` (42 uses), `fmt` (9), `stampDay` (6), `dayText` (8), `shortDayText` (7), `dateTimeOf` (5), `dateOf` (4), `clockOf` (11), and raw strings: `ContactsView.vue:65` (`2026-11-20`), `JobsView.vue:289` (`first_seen`), the facts of a posting (`JobsView.vue` facts, `ApplicationDetail.vue:163-164`: "2026-11-22 23:59"), `AboutView.vue:90` (`checked_at.replace('T', ' ')`), `JobsView.vue:398` (`slice(0, 7)`) | The reader sees "11/26", "2026/11/25 03:15", "2026-11-22 23:59", "Yesterday 22:52" and "2026-11-20" in one program; A1 is the bug this makes possible. | R8 | P1 (A1: P0) | one contract: which fields are wall-clock (calendar items, deadlines) and which are UTC instants (what happened); `DateTimeCell` takes the formatted text | yes (`i18n/format.js`) | - |
| G17 | `DataState` in 9 views; own versions in `ApplicationDetail.vue:172-175`, `AnalyticsView.vue:85-90`, `RunsView.vue:87`; none in Contacts, Profile, Settings, Sources, About | A page that could not be read says so on some pages and shows an empty page on others. | R8 | P2 | `DataState` on every page that reads | page | - |
| G18 | `components/SideDrawer.vue:29`, `App.vue:127` | Icon-only close buttons: named by `aria-label`, nothing for a mouse (no tooltip); the toast's is the glyph "✕". The drawer's head scrolls away with the content (`.drawer` is the scroller, `style.css:309`). | R3 | P2 | `IconButton`; drawer head sticky | yes | every drawer |
| G19 | Hard-coded full-width punctuation in templates: 30 places in 20 files (e.g. `AccountsView.vue:121,124`, `EmployersPanel.vue:67`, `HomeView.vue:77`, `SettingsView.vue:234,469,473,487,539`, `SplitBar.vue:22`, `RunsView.vue:181`, `RemoteView.vue:151`, `ProfileView.vue:234`, `TodosView.vue:257`, `SourcesView.vue:51`, `AiPanel.vue:166-305`, `WelcomeView.vue:186-263`) | English shows "…aren't saved。", "(every 3 h)" in full-width brackets, "Google　Canada" with an ideographic space. The no-Chinese test does not catch punctuation. | R10 | P1 (en, fr) | punctuation belongs to the key; extend the test to U+3000-303F and U+FF00-FFEF | writing + test | - |
| G20 | Sentences assembled from fragments around a link (`AccountsView.vue:185` 3 keys, `SourcesView.vue:91` 5, `SettingsView.vue:250,301` 5, `RunsView.vue:96` 6, `HomeView.vue:74-78` 6) | Word order cannot change per language; a fragment key like `settings.page.text` holds a full stop. | R10 | P2 | one key with a named link slot (`<i18n-t>` or `{link}`) | writing | - |
| G21 | `components/SetSection.vue:17` | A sentence in a pill beside each of 25 section headings ("Saved with "Save" at the top right"). | R5, R10 | P2 | `.meta`, 2-3 words ("Saves at once"), or nothing where it is the default | yes | Settings |
| G22 | `ProfileView.vue:209` `background: var(--bg2)` (no such token); `style.css:525` `.star.on { color: #e0a300 }`; `style.css:688` `font-size: var(--fs-md, 16px)` (the fallback contradicts the token, 14 px: a settings section heading is the size of body text) | The referee card has no background of its own; the star does not change with the theme. | R7 | P2 | tokens | yes / page | - |
| G23 | `App.vue:110-117` (sidebar foot) | Theme (3), language (3), pause, sign out: 8 controls always on screen for things set once. | R4 | P2 | theme and language behind one "Appearance and language" `Menu` / `Popover`; pause stays | shell | - |

### 2.2 Applications (`views/ApplicationsView.vue`) and the review drawer

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `:45` `dateTimeOf(asDate(r.next_date.start))`; `i18n/format.js:6` (`asDate` appends `Z`); `calendar.js:51-52` reads the same string as local wall-clock time | **The two pages show different times for one item.** API `next_date.start = "2026-11-25T10:15"` (Granite Software, coding test). Calendar, day view: **10:15** in every time zone. Applications: **03:15** with the browser in America/Vancouver, **18:15** in Asia/Shanghai, 10:15 only in UTC. The calendar is right (the server sends wall-clock time for calendar items). | R8 | **P0** | read `next_date.start` with the calendar's parser (`calendar.js startOf`) / a shared `wallClock()` in `format.js`; a test with a non-UTC zone | page + `format.js` | check every `asDate(` on a calendar or deadline field (`TodosView.vue:179` uses `new Date(x.start)`: local, right) |
| A2 | `:143` (date cell: time, then a pill with `next_date.title`, `nowrap`) | The pill repeats the company that is two columns to the left ("Granite Software - coding test"; with real data "Company · Title: …"). Column 339 px (zh) / 341 px (en); table 1,189 / 1,248 px in a 1,150 px box at 1,440 px: sideways by 39 / 98 px; by 199 px at 1,280; by 455 px at 1,024. The "Updated" column is pushed out of view. | R1, R2 | **P0** | `DateTimeCell`: `primary` = the time, `secondary` = the kind ("Interview", "Assessment"), `tip` = the item's title; fixed width (about 136 px) | yes (cell) | - |
| A3 | `:44-51` | One column, three meanings: the next calendar item (time + title), the deadline (day + "4 days left" pill), or "—". Width 132 px on "waiting", 49 px on "sent", 339 px on "in progress". | R1 | P1 | header "Next date"; the same `DateTimeCell` shape for both (date, what it is); tone `warn` for a near deadline instead of a pill | page | - |
| A4 | `:139-142` | "Next" cell: inline `min-width: 240px`; a "You" pill, a sentence from the server (up to 22 zh characters; wraps: 4 of 9 rows on "in progress" end with one orphan character on a second line), and a primary button under them. Row 76 px on "waiting" (en: 76-98), 61-65 elsewhere. On "waiting" the same fact is said four times in a row: tab "Waiting for you", stage pill "Waiting for approval", pill "You", sentence "The record waits for your approval", button "Look over and approve". 4 primary buttons for 4 rows. | R1, R4, R5, R10 | P1 | stage as `Status` (the sentence is its `tip`); whose move as `.meta`, only on tabs that mix them; one `button.ghost.sm` as the row's action; row `comfortable` 64 px | yes + page | Postings J2 |
| A5 | `:145` (`max-width: 260px`, `.clamp2`, `col-more`) | "Latest" collapses when another column takes the room: 72 px wide on "in progress" (48 px of text: 11 lines of 3-4 characters, cut to 2), 43 px in English (13 lines), 32-39 px at 1,024 px (16 lines). | R1, R2 | P1 | flexible column with `min` 160 px and `priority` (hidden first); `Trunc lines="2"` | yes | - |
| A6 | `:137` | Company in `<b>` (700), title on a second line that wraps (titles of 10-41 characters). | R2, R7 | P1 | `EntityCell primary secondary to` | yes | - |
| A7 | `:107-110` | Subtitle of 123 characters describing how a table works; "Check the mailbox" and "Export (CSV)" always in the head (and export again in the bulk bar, `:161`). | R4, R6 | P2 | no `sub`; head: no primary, export and "check the mailbox" in a `Menu` | page | - |
| A8 | `:154-163` | Bulk bar: `position: sticky; bottom: 16px` inside the flow (it adds its height to the page when it appears); 6 controls; inline `border-color: transparent`. | R8 | P2 | `BulkBar` | yes | Postings J9, Files F6 |
| A9 | `:165-183` | Review drawer: 11 inline styles; each card titled "Company · Title" in bold, unbounded; a sticky footer built inline (`:178`); subtitle `applications.reviewSub`. | R7, R8 | P2 | `SideDrawer` with a footer slot; `EntityCell` for the card head; `Status` for "N open questions" | yes + page | - |
| A10 | `:118` (`style="width: 220px"`), `:119-120` | Search 36 px high beside selects 32 px high; the "whose move" filter repeats the tabs. | R7 | P2 | `.filters` with one height; drop the filter on tabs where it has one value | yes + page | - |

### 2.3 One application (`views/ApplicationDetail.vue`, `components/RecordPanel.vue`, `components/AgentJournal.vue`)

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | `:177-185` | Title "Company · Title" as an unbounded 26 px heading; a subtitle of five facts joined by "·" (back link, system, place, deadline, posting link). | R2 | P2 | title = company, title of the job as `.t-secondary`; facts as `.meta`; the back link first | page | - |
| D2 | `:188-213` | Status card: stage pill enlarged inline (`font-size: 14px`, `:190`), whose move, sent date, a sentence, the explanation, `TechDetails`, pills for the open cards, then up to 3 buttons and "More ▾" - whose 9 items begin with the two buttons already shown beside it. | R4, R5 | P1 | one primary + one secondary + `Menu` (the rest, destructive last); stage as `.tag` at its own size | yes + page | - |
| D3 | `:205-211`, `:383-388` | The hand-made menu (G13): Escape does not close it from its button; 9 buttons in a column; a click-catcher `div` over the page. | R4, R8 | P1 | `Menu` | yes | - |
| D4 | `:204` | The reason an action is disabled is a native `title` on a disabled button (never shown by keyboard; not at all on touch). | R3 | P1 | a line under the actions, or `v-tip` on a focusable wrapper | page | `JobsView.vue:344` |
| D5 | `:215-252` | Three forms (outcome, note, correction) open as cards between the status and the tabs and push the tabs down; each begins with a paragraph (126 and 178 characters). | R6 | P2 | `Popover` (note) / `SideDrawer` (outcome, correction); the paragraph → `InfoTip` | page | - |
| D6 | `RecordPanel.vue:125-167` | The answers: widths by inline percentages (`34%`, `22%`); rows 48-107 px (en 48-129; 48-194 at 1,024); a pill per row for confidence; a "Change" button per row (10); a row becomes a form when edited; the answer in a `<pre>` with an inline font size; the required mark coloured inline. | R1, R4, R5 | P1 | `DataTable standard`: question (`Trunc lines="2"`), answer (2 lines), basis (optional column), confidence as `Status`; editing in the `expanded` row; "Change" as an `IconButton` | yes + page | - |
| D7 | `RecordPanel.vue:99-121` | Before the answers: a red callout with a paragraph (220 characters), the "look first" panel, the agent's summary - three stacked blocks; on an ordinary record the table starts below the fold. | R6 | P2 | one block "To check (N)" with the items; the how-to → `InfoTip` | page | - |
| D8 | `:314-322` | Mail: per mail a pill, a bold subject, sender, summary, and an "Unlink" button always visible. | R4 | P2 | `EntityCell`-like row; unlink in the row's `Menu` | page | - |
| D9 | `:356-372` and `JobsView.vue:368-439` | The posting's facts, score, overview and description exist twice with the same inline styles (`font-size: 13.5px; line-height: 1.6`, the mask for "show more"). Facts show raw `deadline` / `posted` strings. | R8 | P2 | one `JobFacts` / `JobText` pattern used by both | yes (pattern) | Postings drawer |
| D10 | `AgentJournal.vue:38-65`, `style.css:754` | The journal is a 320 px scroller inside the page; "Stop" is a red ghost button always visible; a 169-character sentence under the input. | R4, R6 | P2 | no inner scroller (or the newest N + "show all"); stop asks, sits at the end; the sentence → `InfoTip` | page | - |
| D11 | `:254-256` | Tabs: `role="tablist"` / `role="tab"` without tab panels or arrow keys; elsewhere (`ProfileView`, `RunsView`, `TodosView`) the same `.seg` has no roles at all. | R8 | P2 | one tabs pattern (`.seg` + roles + arrow keys) | yes | Profile, Activity, Analytics |

### 2.4 Postings (`views/JobsView.vue`) and its drawer

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| J1 | `:277-283`, `style.css:439` (`.jobcell { min-width: 260px; max-width: 460px }`) | Three lines in a cell (company + pills, title + link glyph, place · term · months); rows 62, 63, 79 and 103 px in one table (up to 184 px at 1,024). | R1, R2 | P1 | `EntityCell` (company; title + place as the second line, cut); "added by hand" and "also listed" as `.meta` after the primary line; row 64 px | yes | Applications A6 |
| J2 | `:291-296` | The last column is a link-pill, a reason pill, a state pill or a button, by row; on "to decide" every row carries a "Start applying" button: 30 buttons. | R4, R5 | P1 | `Status` (with `tip` for the excluding rule); the row's action as `button.ghost.sm`; the application as a plain link | yes + page | - |
| J3 | `:216-218` | The head's `.primary` is a navigation link ("Sources") - not this page's main action; three actions. | R4 | P1 | no primary, or "Scan"; "Sources" a secondary link; "Add by hand" in a `Menu` | page | - |
| J4 | `:238-254` | Filter bar: search, 4 selects, a number, 2 checkboxes, clear, count, column picker = 2 lines at 1,440 px (71 px; the count and "Columns" alone on the second), 3 lines at 1,024 (114 px). Search 36 px, selects 32 px. | R4, R7 | P1 | search + direction + deadline in the bar; the rest in a filter `Popover` (as on the calendar); count at the end | yes + page | - |
| J5 | `:250-253` | Column picker: `<details>` with an absolutely placed box (clipped by the table box's edge, stays open on a press outside). | R8 | P1 | `Popover` / `Menu` with checkable items | yes | - |
| J6 | `:278`, `:281` | "★" in a `<span>` with a `title` and inline `cursor: default` (no accessible name); "↗" as a link whose only name is its `title`, 30 times. | R3 | P1 | `EntityCell` slot `after` with an `aria-label`; `IconButton`-style link `icon="external"` | yes | - |
| J7 | `:290` | Deadline: a `title` on the `<td>`; "today" / "tomorrow" as a warn pill after the date. | R3, R5 | P1 | `DateTimeCell primary` = day, `secondary` = "today", `tone="warn"` | yes | - |
| J8 | `:338-349` | Drawer: 8 buttons in a wrapping row - 2 lines, the red "Delete" alone on the second; above it a row of up to 6 pills. | R4 | P1 | primary "Start applying", "See the posting", then a `Menu` (mark as sent, skip, score again, edit, archive, delete last) | yes + page | - |
| J9 | `:374-402` | Contacts, duplicates and history are `.callout`s (the blue "notice" style) though they are ordinary sections; with the "has an application" callout, up to 4 blue boxes. | R5 | P2 | `SectionHead` + plain lists; callout only for what needs attention | page | - |
| J10 | `:352-366` | The edit form opens inside the drawer above the facts; `:361` cuts the source's text by counting characters (`slice(0, 80) + '…'`). | R2 | P2 | `Trunc`; the form as the drawer's second view (`back`) | page | - |
| J11 | `:308-320` | Bulk bar: 6 buttons, inline style on "unpick". | R8 | P2 | `BulkBar`; rare actions in its `Menu` | yes | - |

### 2.5 Needs you (`views/TodosView.vue`)

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | `:223-332` | 14 cards, 16 `.primary` buttons on the page (two in a card where "Open" and "Done" both are); 3-5 buttons per card plus a muted sentence after them. At 1,024 px (en) the actions of every dated card break onto 2 lines (76 px). | R4 | P1 | per card: one primary, one secondary, `Menu` for the rest ("not now", "close", "open the application") | yes + page | - |
| T2 | `:341-352` | "Remind me later" on every card (14 times), unfolding into 6 more controls in the card. | R4 | P1 | an item of the card's `Menu` opening a `Popover` (tomorrow / 3 days / Monday / a date) | yes + page | - |
| T3 | `:206-216` | Head of a card: title at 16 px / 650, a due pill, a system pill, the created time; under it a chip that repeats the company from the title ("Meridian Foods - references requested" / "Meridian Foods · Supply Chain Analyst") with a third pill ("2 days left"). 43% of the page's characters are weight ≥ 600. | R5, R7 | P1 | title at `--fw-medium`; one date (`DateTimeCell`), the system as `.meta`; the job as `EntityCell` only when the title does not already name it | yes + page | - |
| T4 | keys `todos.*` | Buttons as speech: "I can't right now", "Leave it, close", "It is taken care of", "Give it to the agent"; one action worded three ways ("Done, go on", "I'm done, continue", "Done, continue"), dismissing five ways ("Not now", "I can't right now", "Close", "Leave it, close", "Don't apply, close"). | R10 | P1 | glossary: "Done", "Continue", "Dismiss", "Snooze" | writing | - |
| T5 | `:305`, `:221` | "Try again with nodriver" as a button; the last failure's raw text in a warn callout. | R6 | P1 | "Try another browser" in the `Menu`; the raw text in `TechDetails` | page | Activity R4 |
| T6 | whole page | 2,942 px for 14 items (cards 140-244 px); the right half of every card is empty at 1,440 px. | R1 | P2 | denser card: head and actions on one line when there is no explanation | page | - |
| T7 | `:333-339`, `:173-184` | The date editor unfolds as a row in the card; the "rang recently" callout has its own row layout with inline styles. | R8 | P2 | `Popover` with the date field; the callout's rows as `DateTimeCell` + actions | page | - |
| T8 | `:189-191` | 7 categories in a `.seg`: 2 lines at 1,024 px (en, 64 px). No roles. | R9 | P2 | tabs pattern that scrolls or folds into a select when narrow | yes | Profile P1 |

### 2.6 Overview (`views/HomeView.vue`)

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | `:135-141`, `:147-152` | G10 on this page: text 14-20 px wide and overlapping the time at 1,024 px (en). | R1, R9 | **P0** | see G10 | yes | - |
| H2 | `:68-78` | Four tiles; the fourth's label is a sentence with two percentages ("applications sent · acknowledged 74% · came to something 42%": 3 lines at 1,024 px), then an `<Explain>` assembled from 6 fragments. | R6, R10 | P1 | tile = number + 2-3 words; the two rates as their own small figures or in the `InfoTip` | page + writing | - |
| H3 | `:91`, `:103`, `:150` | Company and title three ways on one page: "Company · Title" in one bold line; company / title on two lines; "Company" bold + "· Title" muted. | R8 | P1 | `EntityCell` in all lists | yes | Needs you, Files, analytics `.missed`, review drawer |
| H4 | `:85`, `:90`, `:104` | Icon sizes and colours inline; the deadline's tone by inline `color` and `font-weight: 600`. | R7 | P2 | `DateTimeCell tone` | yes | `ContactsView.vue:65` |
| H5 | `:62-63` | "Check your email", "Scan for new jobs" - the same two actions are "Check the mailbox" on Applications and "Scan for new postings" / "Scan now" on Postings / Sources. | R10 | P2 | one wording | writing | - |

### 2.7 Site accounts (`views/AccountsView.vue`)

Measured with made-up rows (the demo has none): five providers (signed in with a note, signing in, expired, failed with a note, custom) and
five accounts (ready; needs you, with a message and detail; locked; waiting for a confirmation; never signed in).

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | `:123-139`, `style.css:504-505` | Provider cards: nothing inside has a fixed place. From the card's top, the browser select starts at 86 / 87 / 106 / 124 px (zh) and 86 / 87 / 108 / 143 px (en); the e-mail field at 155 / 157 / 176 px (zh), 157 / 190 / 212 px (en), or is absent; the note at 159-252 px; the action row is 27, 62 or 97 px high. Cards in one grid are 248, 284 and 303 px. Only an inline `min-height: 36px` (`:125`) tries to hold the state line. | R1 | P1 | `ProviderCard`: head (name, `Status`), one state line (cut, reason in `tip`), one action line (main action + `Menu`), optional e-mail line always at the same place | yes (pattern) | - |
| C2 | `:130-135` | Actions: select + "Sign in again" + red "Delete sign-in session" (+ red "Remove"): 2 lines (62 px) in zh, 3 lines (97 px) in en at 267 px card width. | R4 | P1 | main action on the card; delete session, remove, browser choice in the `Menu` (danger last) | yes | - |
| C3 | `:131` | The browser engine ("Follow site rules" / `Playwright` / `nodriver`, typed into the template) on the face of every card; width 89 or 119-133 px by value (G5). | R6, R1 | P1 | `Popover` "Browser for this sign-in" from the card's `Menu`; human names | page | accounts table `:174`, `BrowserPanel.vue:40` |
| C4 | `:126-128` | State line: the session sentence ("Saved Nov 20 11:12, valid until 01/20/2027 at most" / "…, may stop working once closed"), or, after a failure, the raw reason in warn colour - "Last attempt failed: The window closed … (net::ERR_ABORTED at https://appleid…)": 74-93 px of text where the others have 36. | R6, R2 | P1 | `Status` "Signed in · until Jan 20" / "Sign-in failed" with the short reason as `tip`, the raw text in `TechDetails` | yes + page | - |
| C5 | `:136`, `style.css:527` | The e-mail field appears only when signed in, has a 68-character placeholder as its only label (cut: "Email for this account (if different from your applic"), and saves on change without saying so. | R1, R10 | P1 | a labelled field in the provider's `Popover` or detail, saved by a button | page | - |
| C6 | `:137-138` | A note (74 px in one card, 37 in another, none in two) is part of the card's flow. | R1, R6 | P1 | `InfoTip` in the card head | page | - |
| C7 | `:162-168` | Password cell, three layouts: saved → the word and a "Show" button (2 lines in a 72-78 px column); not saved → the word wrapped into 2 lines in a 35-42 px span and an "Enter" button that opens the "Advanced" section far below the table and fills its form; shown → the password in `<code>` in the row, widening the column. | R1, R8 | P1 | `CredentialCell`: "••••••" + eye `IconButton` (asks first), or "Not saved" + "Add" opening a `Popover` right there; fixed width | yes (pattern) | - |
| C8 | `:157`, `:169-174` | "Status" pills the account's readiness (six values, e.g. "Can sign in automatically", "You need to sign in once"), then a paragraph (`max-width: 320px`) and `TechDetails`; "Sign-in status" is a sentence about the saved session; "Password" is a third state. Rows 91, 103, 104, 130 and 204 px. | R5, R1, R6 | P1 | two facts, two columns: Password (`CredentialCell`) and Sign-in (`Status`: ready / needs you / expired / locked / never, reason in `tip`); message and detail in the row's detail (`SideDrawer` or `expanded`) | yes + page | - |
| C9 | `:176` | "Sign in" and a red "Delete" on every row (20 buttons for 5 rows, 5 red). | R4 | P1 | "Sign in" as `button.ghost.sm`; delete, clear session, browser in the row's `Menu` | yes | Contacts K2, employers S1 |
| C10 | `:156-179` | Table wider than its box: +198 px in English at 1,440 px (1,348 in 1,150), +121 px (zh) / +358 px (en) at 1,280, +377 / +614 px at 1,024; the login column is 321 px because of one long address; the row's actions are out of view. | R1, R9 | **P0** | `DataTable standard`; login as `Trunc`; "How it got here" optional (`priority`) | yes | - |
| C11 | `:183-222` | "Advanced" is a card holding three cards; opening it also adds a select to every row of the table above (explained by a 339-character paragraph, `:185`). The "carry a sign-in" card overflows (G11). | R6, R9 | **P0** (overflow) / P1 | three plain sections (import, carry, add by hand) reached from the head's `Menu`, each in a `SideDrawer` or section; the per-row browser choice in the row's `Menu` | page | - |
| C12 | whole page | Subtitle of 219 characters; 8 paragraphs of 110+ characters (2,310 characters of helper text). | R6 | P1 | appendix C, D | page | - |
| C13 | `:144-152` | "Add your own" provider is a `details.tech` (the class for raw output) with three inputs of inline widths. | R8 | P2 | `Popover` form from "Add a provider" | page | - |

### 2.8 Files (`views/FilesView.vue`)

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | `:241-249` | Preview actions: 6-7 controls on 2 lines (62 px); the red "Delete permanently" alone on the second; a select among the buttons whose only name is a `title`. | R4, R3 | P1 | "Download" + "Rename" + `Menu` (use as…, stop using, archive, delete last) | yes + page | - |
| F2 | `:141` | The head's select ("what the uploaded file is for") is named only by a `title`. | R3 | P1 | `aria-label`; or ask for the kind after choosing the file | page | - |
| F3 | `:117` | Bulk permanent delete asks without `danger` (G14). | R4 | P1 | `{ danger: true }` | page | - |
| F4 | `:180-185` | Three checkboxes above the list: 2 lines in the 360 px pane (55 px, en). | R4 | P2 | one filter `Popover` | page | - |
| F5 | `:194-199` | A pill per file for one of six states. | R5 | P2 | `Status`; `.tag` only for "file missing" | yes | - |
| F6 | `:203-209`, `style.css:426` | Its own bulk row (`.fm-bulk`), unlike the other two pages. | R8 | P2 | `BulkBar` | yes | - |
| F7 | `style.css:412,435` | Fixed-height three-pane layout with three inner scrollers; at ≤ 1,200 px of window (not of box) the preview drops below, 80vh high. | R9 | P2 | container query; otherwise keep the structure | page | - |
| F8 | `:158`, `:218` | Folder names cut with the whole text in a `title`; the preview's file name breaks anywhere (`overflow-wrap: anywhere`). | R2 | P2 | `Trunc` | yes | - |

### 2.9 Contacts, Sources, Profile, Activity

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| K1 | `ContactsView.vue:57-70` | Rows 58-82 px (58-98 in English, 58-104 at 1,280, 64-157 at 1,024, where the table also scrolls sideways by 94-158 px): the role wraps to 5 lines in 63 px, the note is a 2-line clamp in a 51-75 px column, `max-width` inline. | R1, R2 | P1 | `DataTable standard`: `EntityCell` (name, role), company, `Status`, `DateTimeCell`, note `Trunc lines="2"` (optional column) | yes | - |
| K2 | `:67` | "Edit" and a red "Delete" on every row. | R4 | P1 | row opens the form; delete in the `Menu` | yes | - |
| K3 | `:65` | Follow-up date as the raw ISO string, overdue by inline colour and weight. | R8 | P1 | `DateTimeCell tone="warn"` | yes | - |
| K4 | `:36-49`, `:26` | The form opens as a card at the top and the window is scrolled to it. | R4 | P2 | `SideDrawer` | page | - |
| K5 | keys | "1 open postings", "{n} people": no plural forms. | R10 | P2 | plural keys | writing | - |
| S1 | `components/EmployersPanel.vue:36-62` | Add row with inline widths (34 / 38 px controls on one line); "★" glyph toggle with both an `aria-label` and a different `title`; a disabled row is `opacity: 0.55` inline; red "Remove" per row; chips whose detail is a `title`. | R3, R4, R7 | P1 | `DataTable`, `IconButton pressed`, `Menu`, `v-tip` | yes | - |
| S2 | `SourcesView.vue:39-56` | Portal card: pill, paragraph, a checkbox with a hint, a primary button, a hint of three fragments, a disclosure with steps and a `<pre>`; 4 long paragraphs (about 1,000 characters). | R6 | P1 | state as `Status`, one action, the rest behind "How to import" (`Popover` / `SideDrawer`) | page | - |
| S3 | `SourcesView.vue:66-90` | Report table: 7 columns with phrase headers ("Passed the hard conditions", "Why the rest was dropped", "In the library now"), sentence cells, error and detail rows by `colspan`; error text coloured inline. | R1, R10 | P1 | `DataTable` with `expanded`; numeric columns right-aligned with short headers and `headerTip` | yes + writing | - |
| S4 | `SourcesView.vue:19-22` | No `DataState`: a failed read is a toast. | R8 | P2 | `DataState` | page | - |
| P1 | `ProfileView.vue:144-147` | 7 tabs and a link-button to Files inside the same `.seg` (inline `order: 9`): 2 lines in English at 1,440 px (63 px). | R4, R9 | P1 | tabs pattern; "Files" as a head action | yes + page | - |
| P2 | `:181-224` | Salary and references: each field a `<label class="small">` wrapping an input with an inline width (13 widths); rows break (53 px: "Negotiable" alone on a line); a referee is 7 fields and a delete button in one wrapping row; `var(--bg2)` (G22). | R1, R7 | P1 | `.field` grid (label above, same heights); referees as a small `DataTable` or cards with a `Menu` | page | - |
| P3 | `:170`, `:224`, `:260`, `:275`, `:287`, `:146` | "Unsaved" three ways: a warn pill beside each Save (5 places), a dot on the tab, the Save button's disabled state. | R8 | P2 | the dot + the button; no pill | page | Settings |
| P4 | `:140-142` | State pills ("generating…", "N fields still empty") in the head's actions slot. | R5 | P2 | `Status` under the title or in the tab | page | - |
| P5 | `:180`, `:207`, `:244`, `:274`, `:279`, `:286` | 11 paragraphs of 110+ characters (2,878); the stories tab opens with 462 characters. | R6 | P1 | appendix D | page | - |
| P6 | `:265-266`, `:278`, `:290` | Editor heights (`68vh`, `60vh`), the preview box's border and padding, a font size: all inline. | R7 | P2 | an `.editor` pattern | yes | Settings prompts |
| U1 | `RunsView.vue:192-210` | "What was done": 80 rows on one page, 7,705 px, a pill and a `TechDetails` in each; no paging (DESIGN_SYSTEM §6 asks for it). | R1, R5 | P1 | `DataTable compact` + `Pager`; status as `Status`; detail in the `expanded` row | yes | - |
| U2 | `:104-167` | Work plan: the same row five times with inline `min-width: 64px; justify-content: center` on the pill (8 times) and inline `font-weight: 400` (5 times); up to 3 ghost buttons per row. | R7, R4 | P2 | one row component; "do first" visible, the rest in a `Menu` | page | - |
| U3 | `:180` | The interval's number input has no label or name; "Yesterday 17:53" breaks into two lines at 1,024 px. | R2 | P1 | `aria-label`; `.atomic` | page | - |
| U4 | `:205`, `:98`, `:217` | "Try again in the ordinary browser" with a `title` naming `nodriver`; a release id pair in a hint; a notice's raw error. | R6 | P2 | `Menu` item with a `hint`; `TechDetails` | page | - |
| U5 | `:92-96` | The state card: a bold word, a sentence, and a line of six fragments with a count, a limit and a link. | R6, R10 | P2 | `Status` + the count as a figure; the rule in an `InfoTip` | page + writing | - |

### 2.10 Settings (`views/SettingsView.vue` and its panels), analytics, the rest

| ID | Where | What happens (measured) | Cause | Sev | Fix | Shared? | Also on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X1 | `SettingsView.vue` (53 long paragraphs, 12,711 characters), `AiPanel.vue` (12; 3,080), `AccessPanel.vue` (5; 1,394), `MailboxPanel.vue` (4; 1,358, one of 536), `NetworkPanel.vue` (4), `BrowserPanel.vue` (2), `PromptsPanel.vue` (one of 469) | Group pages 1,254-1,863 px; "System and data" 4,421 px (5,456 at 1,024). Most fields carry a sentence or three beside them. | R6 | P1 | per field: `InfoTip` beside the label (a sentence) or a `Popover` (more); a consequence that cannot be undone stays as one line; appendix D row by row | yes + page | - |
| X2 | `.kv` rows with a `.hint` after the control on the same line (e.g. `:312-314`, `:376-378`, `:592-596`) | The hint starts beside a 90-100 px input and wraps under it as the box narrows; labels that are questions wrap in the 240 px column. | R1, R6 | P1 | `.field`: label (+ `InfoTip`), control, unit; no inline hint | yes | - |
| X3 | 77 inline styles; input widths 70, 90, 100, 110, 120, 220, 320 px | - | R7 | P2 | size classes for number / time / text fields | yes | Profile |
| X4 | `BrowserPanel.vue:36-43` | A rule is 8 controls in a wrapping row (2 lines, 80 px at 1,024); engine names as option text; delete without asking; internal examples as placeholders (`pdportal:ubc`). | R4, R6 | P1 | rules as a `DataTable compact` with a `Menu`; human names for the browsers | page | - |
| X5 | `AiPanel.vue:313-314`, `:217`, `:316`; `ModelPick.vue:21` | "↑" / "↓" glyph buttons named only by `title`; red buttons on the face of each service; "type it" explained by a `title`. | R3, R4 | P1 | `IconButton`; `Menu`; `v-tip` | yes + page | - |
| X6 | `:615-651` | Backup: four lists of prose always open (what an export holds, what it does not, restoring, moving). | R6 | P2 | two actions and one line; the lists behind "What is in an export" (`Popover`) and a "Restore / move" disclosure | page | - |
| X7 | `PromptsPanel.vue` actions, `AccessPanel.vue:83` | 4 buttons on 2 lines and a 3-option `.seg` on 2 lines at 1,024 px. | R4, R9 | P2 | `.actions` + `Menu`; tabs pattern | yes | - |
| X8 | `:204-206`, `:210` | Unsaved: pill with a count, dot per tab, "Discard", a primary that reads "Saved" when there is nothing to save. | R8 | P2 | keep the count as `Status`; the button reads "Save" always (disabled) | page | Profile P3 |
| N1 | `analytics/*.vue` | 37-57 native titles per view; three ways to explain a figure (G15); a `.card-sub` sentence under every card title (62 helper texts in three panels, 27 of them long). | R3, R6 | P1 | `InfoTip` on the card title (`SectionHead help`); `v-tip` on bars; `Trunc` in name cells | yes | - |
| N2 | `AppsPanel.vue:80-87`, `style.css:553-554` | English, 1,280 px: the card head holds a title and two segmented controls; the title is squeezed to 17 px - "Applications per week" one character per line, 74 px high. | R1, R9 | **P0** | the title never shrinks below its words (`.atomic` + the controls wrap under it, or move to a `Menu`) | yes (`SectionHead`) | every `.card-head` with a `.seg` |
| N3 | compact tables (appendix B) | Sideways scroll inside cards: +6 to +51 px at 1,280 (3 tables), +18 to +91 px at 1,024, +141 px in English at 1,440 (services, in a 404 px card). | R1, R9 | P1 | bounded name column + optional columns by the card's width | yes (`.an-table`) | - |
| N4 | `SitesPanel.vue:44` | A red "Clear" on every row. | R4 | P2 | `Menu` | yes | - |
| L1 | `CalendarView.vue`, `calendar/*.vue` | No layout findings (no sideways scroll, no broken groups at any width). 18 native titles (66 rendered: every day cell's "+" has one); the subtitle restates the title. | R3 | P1 | attribute-level only: `title` → `v-tip` / `IconButton`; delete `sub` | page | - |
| B1 | `AboutView.vue:90`, `:131-132` | "Checked at" is the server's string with the `T` replaced by a space (no time zone handling); two hints of 242 and 260 characters. | R8, R6 | P2 | `fmtTime`; `InfoTip` / `Popover` | page | - |
| M1 | `RemoteView.vue:151`, `:168-169`, `:163`, `:182` | Title built with a typed-in full-width colon; back / reload icon buttons named only by `title`; two paragraphs under the picture (300 and 237 characters). | R3, R6, R10 | P1 | `IconButton`; one sentence + a `Popover` "How this works" | yes + page | - |
| M2 | `WelcomeView.vue` | 18 long paragraphs (4,433 characters), 17 inline styles, typed-in punctuation at `:186-263`. A wizard may explain - one sentence per step. | R6, R10 | P2 | shorten; `InfoTip` beside choices | page + writing | - |

### 2.11 Words (for the glossary)

| ID | What | Evidence | Fix |
| --- | --- | --- | --- |
| W1 | The system has five names. | English catalog: "the agent" 94, "the program" 76, "the app" 38, "the AI" 18, "AutoApply" 15. Chinese: three words in 137 / 96 / 57 strings. DESIGN_SYSTEM §5 allows two. | one name for what acts ("the agent") and one for the product; never "the app" |
| W2 | One thing, several words. | posting / job ("Scan for new jobs", "Scan for new postings", "Scan now"); draft 53 / record 43 ("View draft" opens the tab called "Record"); mail 43 / email 26 / e-mail 14; delete 34 / remove 25 / discard 15 / clear 8; "Needs you" (navigation) / "items need you" (tile) / "Needs your action" (card) / "Waiting for you" (tab); Files / library; sign in 105 / log in 11. | glossary; one word each |
| W3 | Sentences built from fragments. | G20. | one key per sentence |
| W4 | Buttons that talk. | T4; "Have the agent do it again", "It did not go through: do it again", "Approve; I press Submit", "Look over and approve", "Give it another budget". | verb + object, ≤ 3 words; the nuance in a `hint` or the confirmation |
| W5 | States that are sentences. | "Can sign in automatically", "You need to sign in once", "Waiting for its e-mail address to be confirmed", "Saved {time}, may stop working once closed"; the server's `next` ("There is a test: do it as the mail says"). | 1-3 words ("Ready", "Needs you", "Unconfirmed", "Expired"); the rest is the `tip` |
| W6 | Column headers that are phrases. | "How it got here", "Login name or e-mail", "Sign-in status" beside "Status", "Passed the hard conditions", "Why the rest was dropped", "Times the median of its kind". | a noun; `headerTip` for the rest |
| W7 | Typed-in punctuation and missing plurals. | G19, K5. | keys |
| W8 | Text from the server stays in the server's language. | English interface, Chinese `last_event` and `next` in Applications. | out of this work's scope; noted |

## 3. Work list per page

What must change when the page is migrated. Shared-layer items (G…) are assumed done first.

**Shell (`App.vue`)** - 3 titles → `v-tip`; toast close → `IconButton`; theme and language behind one menu (G23); nothing else.

**Overview (`HomeView.vue`)** - no `sub`. Tiles: number + short label, the rates out of the label (H2). All four lists: `EntityCell` +
`Status` + `DateTimeCell`, bounded first column (G10, H1, H3). `Explain` → `InfoTip`. Bars: `v-tip`. Remove 15 inline styles.

**Needs you (`TodosView.vue`)** - no `sub`. Card = icon, title (medium), one date, `.meta`; one primary + one secondary + `Menu` (snooze,
dismiss, open the application, try another browser) (T1, T2, T5). Snooze and "change the date" as `Popover`s. Raw failure text into
`TechDetails`. Categories as the tabs pattern. Wording per T4. "Later" list: `DateTimeCell` + one action.

**Calendar (`CalendarView.vue`, `calendar/`)** - do not restructure. Replace the 18 titles (appendix A), delete `sub`. Mostly fine.

**Postings (`JobsView.vue`)** - no `sub`; head per J3. Filters: 3 in the bar, the rest in a `Popover`; column picker as `Popover` (J4,
J5). `DataTable comfortable`, selectable, sortable: score (fixed), `EntityCell`, optional columns with `priority`, `DateTimeCell`,
`Status` + one ghost action (J1, J2, J6, J7). `BulkBar`. Drawer: 2 buttons + `Menu`, sections instead of callouts, `Trunc`, formatted
dates, the edit form as a second view (J8-J10); share the facts / description block with the application page (D9).

**Sources (`SourcesView.vue`, `EmployersPanel.vue`)** - no `sub`. Employers as `DataTable standard` with star `IconButton` and a `Menu`;
chips with `v-tip`. Portal card reduced to state + action + "how" (S2). Report as `DataTable` with `expanded` rows, short headers
(S3). `DataState`.

**Applications (`ApplicationsView.vue`)** - fix A1 first (it is a bug, independent of the redesign). No `sub`; head actions into a `Menu`.
`DataTable comfortable`, selectable, clickable: `EntityCell` · stage `Status` · next (one ghost action, `.meta` for whose move) ·
next date `DateTimeCell` (fixed) · sent (optional) · latest `Trunc lines="2"` (optional, hidden first) · updated (optional) (A2-A6).
`BulkBar`. Review drawer on `SideDrawer` with a footer (A9).

**One application (`ApplicationDetail.vue`, `RecordPanel.vue`, `AgentJournal.vue`)** - head per D1. Status card: `Menu` instead of
the hand-made one, no duplicates, disabled reasons readable (D2-D4). Forms out of the page flow (D5). Record: `DataTable standard`
with `expanded` editing; one "to check" block (D6, D7). Mail and timeline rows with `Menu` / `DateTimeCell` (D8). Posting tab from the
shared block (D9). Journal without the inner scroller (D10). Tabs pattern (D11). 37 + 29 inline styles to remove; the scoped
`<style>` block goes with the menu.

**Profile (`ProfileView.vue`)** - `sub` → `PageHead help`. Tabs pattern, Files link out of the tabs (P1). Salary and references on a
field grid (P2). One "unsaved" marker (P3). State out of the actions slot (P4). Paragraphs per appendix D. Editor pattern (P6).
`DataState`. Versions list: `Status` + `DateTimeCell` + one action.

**Files (`FilesView.vue`)** - no `sub`. Structure stays. Preview actions: 2 + `Menu` (F1); name the selects (F2); `danger` on bulk
delete (F3); filters in a `Popover` (F4); `Status` for file states (F5); `BulkBar` (F6); `Trunc` (F8); container query (F7).

**Contacts (`ContactsView.vue`)** - `sub` → help. `DataTable standard`, clickable; `Menu` per row; form in a `SideDrawer`; formatted
dates; `DataState`; plurals (K1-K5).

**Site accounts (`AccountsView.vue`)** - `sub` → help. `ProviderCard` with fixed slots, a `Menu`, the browser choice and the e-mail in a
`Popover`, the note as an `InfoTip` (C1-C6). `DataTable standard`: `EntityCell` (site, host; system as `.meta`) · login (`Trunc`) ·
`CredentialCell` · sign-in `Status` (reason in `tip`) · origin (optional) · "Sign in" + `Menu` (C7-C10). "Advanced" dissolved into
three places reached from the head's `Menu` (C11, C13). Raw failure text into `TechDetails`. The `.kv` overflow is fixed by G11.

**Analytics (`AnalyticsView.vue`, `analytics/*.vue`)** - no `sub`. The layout system (`.an-row`, `.card-foot`) is sound and stays; tables
stay compact. Replace 39 titles (41 with `SplitBar` and `StackChart`); `Explain` and `.kpi[title]` → `InfoTip`; `.card-sub` → `SectionHead help`; `Trunc` in name cells;
card heads that hold controls (N2); column priorities in compact tables (N3); `Menu` in the sites table (N4).

**Activity (`RunsView.vue`)** - no `sub`. Tabs pattern. "What was done" as `DataTable compact` with `Pager` and `expanded` detail (U1);
work plan rows as one component with a `Menu` (U2); name the interval input (U3); technical names out of labels (U4); state card
(U5). 28 inline styles.

**Settings (`SettingsView.vue`, `SetSection.vue`, `AiPanel`, `MailboxPanel`, `AccessPanel`, `NetworkPanel`, `BrowserPanel`,
`DoctorPanel`, `PromptsPanel`)** - the structure (six groups, linkable sections) stays. Every field: label + `InfoTip`, control of one
height, no inline hint (X1, X2); appendix D row by row. `SetSection`'s save hint as `.meta` (G21). Browser rules as a table (X4);
`IconButton`s and `Menu`s in the AI panel (X5); backup lists behind disclosure (X6); one "unsaved" marker (X8). The notification
matrix stays a compact table.

**About (`AboutView.vue`)** - mostly fine. No `sub`; `fmtTime` for "checked at"; two hints → `InfoTip` / `Popover`; its scoped styles
already use tokens.

**Outgoing mail (`MailOut.vue`)** - mostly fine (`DataState`, one form). `sub` becomes a link to the application; discard asks with
`danger`; fields at one height; callouts to one sentence.

**Remote window (`RemoteView.vue`)** - `IconButton`s for back / reload; one `Popover` for the two explanations; the title's punctuation
into the key; keep a one-sentence `sub`.

**Setup guide (`WelcomeView.vue`)** and **Login (`LoginView.vue`)** - structure fine. Shorten to one sentence per step; punctuation into
keys; inline styles (17) to classes. Login's instructions stay (first run).

**Drawers and dialogs** - `SideDrawer`: sticky head, close as `IconButton`, a footer slot (used by the review drawer, the forms moved
out of pages). `ConfirmDialog`: fine in behaviour (focus, Escape, danger focus on Cancel); callers must pass `danger` (G14). Posting
drawer: J8-J10. Review drawer: A9. Analytics drawers (`RunDetail`, lists): compact tables with `Trunc`, raw errors in
`TechDetails`. Calendar's detail panel and share dialog: leave.

## Appendix A. Native `title` attributes

`title=` / `:title=` is written 176 times in `frontend/src` (base commit, lab excluded). 87 of them are component props (`PageHead` 17, `EmptyState` 29, `SetSection` 25, `SideDrawer` 11, `DetailPanel` 2, `ListPanel` 1, and 2 on `AaSelect`, which hands them on as a native title): not tooltips. The other 89, plus the 2 that `AaSelect` passes through, are browser tooltips. Rendered, that is 61 elements with a title on `/jobs`, 66 on `/calendar`, 57 on `/analytics?view=ai`, 37 on the other two analytics views, 11 on `/home` and `/todos`.

### A1. Becomes an `IconButton` label (icon- or glyph-only control: the name and the tooltip are one prop) (10)

- `frontend/src/components/AiPanel.vue:313` `<button>` - `↑` glyph, no `aria-label` today: `IconButton icon="chevron_up"`
- `frontend/src/components/AiPanel.vue:314` `<button>` - `↓` glyph, no `aria-label` today: `IconButton icon="chevron"`
- `frontend/src/components/EmployersPanel.vue:56` `<button>` - `★` toggle, has `aria-label` and a different `title`: `IconButton pressed`, one label
- `frontend/src/views/CalendarView.vue:244` `<button>` - has `aria-label` too: `IconButton`
- `frontend/src/views/CalendarView.vue:245` `<button>` - has `aria-label` too: `IconButton`
- `frontend/src/views/CalendarView.vue:283` `<button>` - `IconButton icon="x" size="sm"`
- `frontend/src/views/JobsView.vue:281` `<a>` - `↗` link whose only name is the title: `IconButton`-styled link, `icon="external"`
- `frontend/src/views/RemoteView.vue:168` `<button>` - no `aria-label` today
- `frontend/src/views/RemoteView.vue:169` `<button>` - no `aria-label` today
- `frontend/src/views/calendar/MonthView.vue:60` `<button>` - `IconButton icon="plus" size="sm"`

### A2. Becomes an overflow tooltip (`<Trunc>` / `v-tip.overflow`): the title repeats text that is cut (19)

- `frontend/src/views/FilesView.vue:158` `<button>` - folder of a posting: two cut lines (`EntityCell`-like)
- `frontend/src/views/HomeView.vue:138` `<div>` - mail summary clamped to two lines: `<Trunc lines="2">`
- `frontend/src/views/analytics/AppsPanel.vue:64` `<span>` - `.hbars .lab`
- `frontend/src/views/analytics/AppsPanel.vue:119` `<span>` - `.hbars .lab`
- `frontend/src/views/analytics/AppsPanel.vue:130` `<span>` - `.hbars .lab`
- `frontend/src/views/analytics/AutoPanel.vue:124` `<span>` - `.name`
- `frontend/src/views/analytics/AutoPanel.vue:234` `<span>` - `.one`
- `frontend/src/views/analytics/AutoPanel.vue:280` `<span>` - `.one`
- `frontend/src/views/analytics/CostPanel.vue:162` `<span>` - model name
- `frontend/src/views/analytics/CostPanel.vue:205` `<span>`
- `frontend/src/views/analytics/CostPanel.vue:228` `<span>` - two on this line (label, unit)
- `frontend/src/views/analytics/CostPanel.vue:252` `<span>` - `.hbars .lab`
- `frontend/src/views/analytics/CostPanel.vue:273` `<span>`
- `frontend/src/views/analytics/CostPanel.vue:292` `<span>`
- `frontend/src/views/analytics/CostPanel.vue:323` `<span>`
- `frontend/src/views/analytics/CostPanel.vue:340` `<span>`
- `frontend/src/views/calendar/AgendaRow.vue:21` `<button>` - `v-tip.overflow="fullName(x)"` (calendar: change the attribute only)
- `frontend/src/views/calendar/EventChip.vue:20` `<button>` - `v-tip.overflow="fullName(item)"` (calendar: change the attribute only)

### A3. Becomes an info tooltip (`v-tip` on the control, or `InfoTip` beside its label) (38)

- `frontend/src/App.vue:90` `<span>` - count badge in the navigation: `v-tip`
- `frontend/src/App.vue:102` `<span>` - "new version" tag: `v-tip`
- `frontend/src/App.vue:117` `<button>` - who is signed in: show the name as `.t-meta` text above the button, or `v-tip`
- `frontend/src/components/EmployersPanel.vue:39` `<label>` - what "priority" does: `InfoTip` after the checkbox label
- `frontend/src/components/EmployersPanel.vue:47` `<button>` - chip: kind and URL - `v-tip`
- `frontend/src/components/ModelPick.vue:21` `<button>` - `v-tip` on the button
- `frontend/src/components/RecordPanel.vue:150` `<button>` - what "not mine" does: `v-tip`
- `frontend/src/components/StackChart.vue:56` `<button>` - legend toggle: `v-tip`; state by `aria-pressed`
- `frontend/src/views/CalendarView.vue:238` `<button>` - keyboard shortcut "(N)": `v-tip`
- `frontend/src/views/CalendarView.vue:242` `<button>` - keyboard shortcut "(T)": `v-tip`
- `frontend/src/views/CalendarView.vue:247` `<button>` - `v-tip`
- `frontend/src/views/CalendarView.vue:261` `<button>` - quick filter chips: `v-tip`
- `frontend/src/views/CalendarView.vue:279` `<button>` - summary figure: `v-tip`
- `frontend/src/views/CalendarView.vue:280` `<button>` - summary figure: `v-tip`
- `frontend/src/views/CalendarView.vue:281` `<button>` - summary figure: `v-tip`
- `frontend/src/views/CalendarView.vue:282` `<button>` - summary figure: `v-tip`
- `frontend/src/views/JobsView.vue:278` `<span>` - `★` mark with no accessible name: `EntityCell` slot `after`, `aria-label` + `v-tip`
- `frontend/src/views/JobsView.vue:280` `<span>` - "also listed" tag: `.meta` + `v-tip`
- `frontend/src/views/JobsView.vue:346` `<button>` - what archiving does: the menu item's `hint`
- `frontend/src/views/RunsView.vue:205` `<button>` - when to use it: the menu item's `hint`
- `frontend/src/views/analytics/AutoPanel.vue:128` `<td>` - on the `<td>`: `headerTip` of the column, or `InfoTip` in the cell
- `frontend/src/views/analytics/AutoPanel.vue:131` `<td>` - on the `<td>`: `InfoTip` in the cell when the figure is partial
- `frontend/src/views/analytics/AutoPanel.vue:132` `<td>` - on the `<td>`: `InfoTip` in the cell when the figure is partial
- `frontend/src/views/analytics/AutoPanel.vue:203` `<td>` - the companies behind a count: `Popover` (a list)
- `frontend/src/views/analytics/CostPanel.vue:106` `<div>` - KPI tile: `InfoTip` (the other panels use `Explain`; one way for all)
- `frontend/src/views/analytics/CostPanel.vue:110` `<div>` - KPI tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:114` `<div>` - KPI tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:118` `<div>` - KPI tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:165` `<td>` - on the `<td>`: `InfoTip` in the cell
- `frontend/src/views/analytics/CostPanel.vue:231` `<td>` - on the `<td>`: `InfoTip` in the cell
- `frontend/src/views/analytics/CostPanel.vue:243` `<div>` - waste tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:244` `<div>` - waste tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:245` `<div>` - waste tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:246` `<div>` - waste tile: `InfoTip`
- `frontend/src/views/analytics/CostPanel.vue:275` `<td>` - on the `<td>`: `v-tip`
- `frontend/src/views/calendar/FilterMenu.vue:60` `<label>` - `InfoTip` after the label
- `frontend/src/views/calendar/WeekView.vue:76` `<button>` - `v-tip`
- `frontend/src/views/calendar/WeekView.vue:99` `<div>` - the "now" line's time: `v-tip`

### A4. Becomes a chart datum tooltip (`v-tip` on the bar or segment; the figure is also in the row) (6)

- `frontend/src/components/SplitBar.vue:22` `<i>` - segment: label, value, share (also: hard-coded full-width punctuation in the template)
- `frontend/src/views/HomeView.vue:124` `<div>` - pipeline bar
- `frontend/src/views/analytics/AppsPanel.vue:65` `<div>`
- `frontend/src/views/analytics/AppsPanel.vue:105` `<div>`
- `frontend/src/views/analytics/AppsPanel.vue:120` `<div>`
- `frontend/src/views/analytics/AppsPanel.vue:131` `<div>`

### A5. Becomes a status reason (`Status tip`, a disabled control's reason via `v-tip`, or `TechDetails` when it is raw output) (11)

- `frontend/src/components/RecordPanel.vue:182` `<span>` - `Status tone="warn" tip`
- `frontend/src/views/ApplicationDetail.vue:204` `<button>` - why the action is disabled: `v-tip` (a disabled button needs a focusable wrapper) or a line under the actions
- `frontend/src/views/FilesView.vue:197` `<span>` - `Status tone="warn" tip`
- `frontend/src/views/FilesView.vue:198` `<span>` - `Status tone="warn" tip`
- `frontend/src/views/JobsView.vue:290` `<td>` - on the `<td>`: `DateTimeCell primary secondary tone`
- `frontend/src/views/JobsView.vue:293` `<span>` - the rule that excluded it: `Status tip`
- `frontend/src/views/JobsView.vue:344` `<button>` - why "score again" is disabled
- `frontend/src/views/TodosView.vue:208` `<span>` - the date as the mail wrote it: `DateTimeCell tip` / `v-tip`
- `frontend/src/views/analytics/AutoPanel.vue:101` `<div>` - raw messages joined into one title: `Popover` or the row's detail
- `frontend/src/views/analytics/AutoPanel.vue:241` `<span>` - `Status tip`
- `frontend/src/views/analytics/RunDetail.vue:49` `<span>` - raw error string: `TechDetails` under the table or `Status tip` with the short reason

### A6. Is really an accessible name: use `aria-label` (plus `v-tip` where a mouse user needs it), drop `title` (3)

- `frontend/src/components/Select.vue:119` `<button>` - pass-through of a caller's `title` (FilesView.vue:141, :244): callers pass `aria-label`; remove the pass-through
- `frontend/src/views/ProfileView.vue:146` `<span>` - unsaved dot: has `aria-label`; add `v-tip`, drop `title`
- `frontend/src/views/SettingsView.vue:210` `<span>` - unsaved dot: has `aria-label`; add `v-tip`, drop `title`

### A7. Delete (says what the element already says) (2)

- `frontend/src/views/ApplicationsView.vue:143` `<span>` - same words as the tag it sits on; the cell becomes `DateTimeCell` (its `tip` = the whole thing)
- `frontend/src/views/CalendarView.vue:268` `<button>` - title equals the button text ("Search")

## Appendix B. Every `<table>`

31 tables. "DataTable" = a list of records a person scans, sorts, opens or acts on; "compact table" = figures that belong to a
card (kept as `.an-table`, with `Trunc` in its name cells and no native titles). Row heights are the measured minimum to maximum at
1440px, zh (en where noted).

| File:line | What it lists | Measured | Becomes |
| --- | --- | --- | --- |
| `views/ApplicationsView.vue:126` | applications | rows 61-76 (en 65-98); date column 49 / 132 / 339px by group; sideways +39 to +455px | **DataTable** `comfortable`, selectable, clickable |
| `views/JobsView.vue:257` | postings | rows 62 / 63 / 79 / 103 (184 at 1024); 30 row buttons, 38 pills | **DataTable** `comfortable`, selectable, clickable, sortable |
| `views/AccountsView.vue:156` | site accounts | rows 91-204 (mock data); sideways +198px en at 1440 | **DataTable** `standard` (CredentialCell, Status, Menu) |
| `views/ContactsView.vue:57` | contacts | rows 58-82 (en 58-98; 64-157 at 1024) | **DataTable** `standard`, clickable (opens the edit form) |
| `components/EmployersPanel.vue:52` | watched employers | inline `opacity: 0.55` for a disabled row; `★` glyph button; red "Remove" per row | **DataTable** `standard` (EntityCell name + host, IconButton star, Menu) |
| `views/SourcesView.vue:66` | what each source gave | error and "more" rows added with `colspan="7"` | **DataTable** `standard` with the `expanded` slot (error detail, dropped reasons) |
| `components/RecordPanel.vue:125` | the answers of a record | rows 48-107 (en 48-129, 194 at 1024); a row grows to a form when edited | **DataTable** `standard`: answer cut to two lines, `expanded` row for editing and for the whole answer |
| `views/analytics/SitesPanel.vue:35` | sites with agent notes | rows 45-46; red "Clear" per row; detail row by `colspan` | **DataTable** `compact`, clickable, `expanded` slot, Menu |
| `views/RunsView.vue:175` | scheduled jobs (2-5 rows, a number input in each) | rows 58-59; "Yesterday 17:53" breaks in two at 1024 | compact table (a small form); `.atomic` on times, a label for the input |
| `views/SettingsView.vue:534` | notification kinds by channel (checkbox matrix) | `style="width: auto"` | compact table |
| `components/NetworkPanel.vue:50` | connection test results | - | compact table; result → `Status`, the raw detail → `TechDetails` |
| `views/AboutView.vue:145` | components and licences | rows 41 | compact table (already even) |
| `components/ColumnChart.vue:54` | a chart's numbers | rows 39-40 | compact table |
| `components/SeriesTable.vue:25` | a chart's numbers, paged | - | compact table |
| `views/analytics/AppsPanel.vue:91` | sent per period | - | compact table |
| `views/analytics/AppsPanel.vue:154` | backlog by kind | - | compact table |
| `views/analytics/AutoPanel.vue:120` | task kinds | rows 47-48; sideways +91px at 1024 (9 columns, one of them `style="width: 210px"`) | compact table; optional columns by container width |
| `views/analytics/AutoPanel.vue:186` | recruiting systems | rows 37 | compact table |
| `views/analytics/AutoPanel.vue:199` | questions asked again | title on the `<td>` lists companies | compact table; the list → `Popover` |
| `views/analytics/AutoPanel.vue:230` | runs (overview, top N) | rows 53-54; sideways +18px at 1024 | compact table; `Trunc` for the subject |
| `views/analytics/AutoPanel.vue:276` | runs (all, in the drawer) | paged | compact table; `Trunc` |
| `views/analytics/CostPanel.vue:158` | models | rows 53-54 | compact table; `Trunc` |
| `views/analytics/CostPanel.vue:178` | services | rows 39-40; sideways +141px en at 1440 (in a 404px card) | compact table; "Paid by" column bounded |
| `views/analytics/CostPanel.vue:201` | features | rows 37 | compact table |
| `views/analytics/CostPanel.vue:224` | cost per result | rows 53-54; sideways +6px at 1280 | compact table |
| `views/analytics/CostPanel.vue:269` | costly tasks (top N) | rows 53-57; sideways +51px at 1280 | compact table; `Trunc` |
| `views/analytics/CostPanel.vue:288` | heavy requests (top N) | rows 53-54; sideways +27px at 1280 | compact table; `Trunc` |
| `views/analytics/CostPanel.vue:319` | costly tasks (all, drawer) | paged | compact table |
| `views/analytics/CostPanel.vue:336` | heavy requests (all, drawer) | paged | compact table |
| `views/analytics/CostPanel.vue:352` | price list | - | compact table |
| `views/analytics/RunDetail.vue:43` | the requests of one run | raw error in a `title` | compact table; `Status tip` / `TechDetails` |

Lists that are not `<table>` today but are the same kind of thing (records in rows) and should be looked at with the tables:
`.list > .item` in `RunsView.vue:106-166` (work plan), `:193` (activity: 80 rows on one page, 7,705px, no paging), `:213` (notices);
`ProfileView.vue:298` (versions); `FilesView.vue:187` (`.mat-item`); `HomeView.vue:83-152`; `ApplicationDetail.vue:314` (mail), `:342` (timeline).
The work plan and the activity list are candidates for `DataTable compact` (status, what, when, a menu); the rest stay lists but take
`EntityCell` / `Trunc` / `Status` for their parts.

## Appendix C. Every `PageHead` `sub`

14 of the 17 page heads carry a subtitle; none of them tells the reader something needed to decide anything on the page. Lengths are en / zh characters.

| Page | File:line | Key | en / zh | Recommendation |
| --- | --- | --- | --- | --- |
| Overview | `views/HomeView.vue:61` | `home.whatYouNeedTo` | 61 / 20 | delete: restates the title |
| Needs you | `views/TodosView.vue:172` | `todos.thingsTheAppCant` | 117 / 30 | delete; the second sentence ("handled, the task continues") is said by each card's result toast |
| Calendar | `views/CalendarView.vue:236` | `calendar.sub` | 62 / 17 | delete: restates the title (one-line change, no restructuring) |
| Postings | `views/JobsView.vue:215` | `postings.sub` | 92 / 27 | delete; "applications are on the Applications page" is what the Application column's link says |
| Sources | `views/SourcesView.vue:32` | `sources.thePostingsAreRead` | 40 / 12 | delete: restates the title |
| Applications | `views/ApplicationsView.vue:107` | `applications.sub` | 123 / 41 | delete: describes how a table works (open a row, tick rows) |
| Application | `views/ApplicationDetail.vue:177` (slot) | back link · system · place · deadline · posting link | - | keep the slot, as a breadcrumb line: back link first, then `.meta` facts; the deadline as `DateTimeCell`-style text, the posting link as an action |
| Profile | `views/ProfileView.vue:139` | `profile.everythingUsedToFill` | 117 / 32 | help tooltip (`PageHead help`): "what is not written here is not made up" is worth one hover, not a line |
| Files | `views/FilesView.vue:140` | `files.page.allTheFilesUsed` | 128 / 42 | delete: the folder list says the same |
| Contacts | `views/ContactsView.vue:32` | `contacts.peopleYouKnowAt` | 222 / 70 | help tooltip: keep only "Your notes; the program never contacts anyone"; the rest → the empty state |
| Site accounts | `views/AccountsView.vue:115` | `accounts.oneEntryPerJob` | 219 / 64 | help tooltip (`PageHead help`): where passwords and sign-ins are kept; delete the line |
| Analytics | `views/AnalyticsView.vue:70` | `SUBS[view]` (4 keys, 86-127 / 34-45) | - | delete; each view's tab names it, and each figure has its own explanation |
| Activity | `views/RunsView.vue:66` | `runs.whatTheProgramIs` | 88 / 28 | delete: the tabs say it |
| About | `views/AboutView.vue:61` | `about.sub` | 55 / 18 | delete |
| Outgoing mail | `views/MailOut.vue:48` | `m.about` (data: which application) | - | keep: it is the subject of the page, not an explanation; make it a link to the application |
| Remote window | `views/RemoteView.vue:151` | `remote.thisIsABrowser` | 118 / 51 | keep one sentence: a person arriving from a phone notification needs to know what the picture is |
| Settings | `views/SettingsView.vue:203` (none) + `:212` group line `here[2]` | 6 group descriptions | - | no `sub`; the group description under the tabs: delete (the tab names the group) |

## Appendix D. Helper text that is always on the page

Every element of class `hint`, `muted`, `card-sub`, `callout` (and plain `<p>`, `<Explain>`) whose English text is 110 characters or more: **191 paragraphs, 40,700 characters** in the English catalog. Lengths are en / zh characters; several keys on one line are one sentence put together from fragments (see W3 in the inventory). The recommendation is the default for the element's role (a field's hint, a card's introduction, a conditional callout) unless the text needs its own; "keep" always means "keep, shortened". Shorter helper texts follow the same defaults.

Per file (helper texts in all / of them long / English characters):
`SettingsView.vue` 74/53/12711, `WelcomeView.vue` 25/18/4433, `AutoPanel.vue` 23/12/3328, `AiPanel.vue` 25/12/3080, `ProfileView.vue` 22/11/2878, `AccountsView.vue` 12/8/2310, `AppsPanel.vue` 22/9/2304, `CostPanel.vue` 17/6/1745, `RecordPanel.vue` 17/5/1644, `AccessPanel.vue` 13/5/1394, `MailboxPanel.vue` 5/4/1358, `ApplicationDetail.vue` 22/4/1324, `TodosView.vue` 13/3/1137, `SourcesView.vue` 13/4/1049, `EmployersPanel.vue` 5/3/936, `JobsView.vue` 11/5/868, `RunsView.vue` 8/3/865, `AboutView.vue` 8/2/792, `NetworkPanel.vue` 5/4/723, `CalendarView.vue` 4/3/694, `LoginView.vue` 5/4/605, `PromptsPanel.vue` 2/1/550, `RemoteView.vue` 2/2/537, `FilesView.vue` 9/2/533, `BrowserPanel.vue` 3/2/508, `MailOut.vue` 6/2/429, `SitesPanel.vue` 2/1/355, `AgentJournal.vue` 4/1/304, `EventDetail.vue` 2/1/228, `DoctorPanel.vue` 1/1/133.

| Where | Key(s) | en / zh | Recommendation |
| --- | --- | --- | --- |
| `AccessPanel.vue:78` | `settings.access.byDefaultOnlyThis` | 169 / 50 | help tooltip on the section head (`SectionHead help`) |
| `AccessPanel.vue:79` | `settings.access.theRunningServerListens` | 145 / 51 | keep (conditional state), one sentence + its action |
| `AccessPanel.vue:94` | `settings.access.whenAnotherDeviceOpens` | 241 / 84 | keep (security warning tied to the chosen option), one sentence |
| `AccessPanel.vue:99` | `settings.access.autoapplyDoesNotDo` | 181 / 91 | popover on the section head (`SectionHead help`); delete from the card body |
| `AccessPanel.vue:121` | `settings.access.theOnlyAccountOnly` | 149 / 46 | help tooltip on the section head (`SectionHead help`) |
| `AgentJournal.vue:64` | `journal.howItHears` | 169 / 58 | help tooltip beside the input |
| `AiPanel.vue:181` | `settings.ai.usesYourOwnClaude` | 254 / 74 | popover on the section head (`SectionHead help`); delete from the card body |
| `AiPanel.vue:184` | `settings.ai.thePlanNameIs` +1 | 197 / 51 | popover on the section head (`SectionHead help`); delete from the card body |
| `AiPanel.vue:187` | `settings.ai.theAgentThatWorks` | 198 / 58 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `AiPanel.vue:200` | `settings.ai.theAgentThatWorks` | 198 / 58 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `AiPanel.vue:204` | `settings.ai.afterChangingTheModel2` | 110 / 31 | help tooltip (`InfoTip` beside the field's label) |
| `AiPanel.vue:209` | `settings.ai.usesYourChatgptSubscription` | 285 / 125 | popover on the section head (`SectionHead help`); delete from the card body |
| `AiPanel.vue:236` | `settings.ai.thisServiceDidntReturn` +1 | 157 / 48 | help tooltip (`InfoTip` beside the field's label) |
| `AiPanel.vue:237` | `settings.ai.theAgentThatWorks2` | 169 / 50 | help tooltip (`InfoTip` beside the field's label) |
| `AiPanel.vue:242` | `settings.ai.forTheMainModel2` | 189 / 69 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `AiPanel.vue:257` | `settings.ai.whenAServiceRuns` | 381 / 105 | popover on the section head (`SectionHead help`); delete from the card body |
| `AiPanel.vue:325` | `settings.ai.checkedEveryMinutesUsage` | 152 / 69 | help tooltip on the section head (`SectionHead help`) |
| `AiPanel.vue:327` | `settings.ai.noBackupServicesYet` | 115 / 37 | keep as the empty state's text, shortened |
| `BrowserPanel.vue:23` | `settings.browser.playwrightIsUsedBy` | 136 / 57 | help tooltip on the section head (`SectionHead help`) |
| `BrowserPanel.vue:33` | `settings.browser.anAccountRuleSays` | 288 / 86 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `DoctorPanel.vue:22` | `common.doctor.sub` | 133 / 41 | delete (the list says it) |
| `EmployersPanel.vue:34` | `settings.employers.companiesYouWantTo` | 282 / 87 | popover on the section head (`SectionHead help`); delete from the card body |
| `EmployersPanel.vue:42` | `settings.employers.detectedAs` +3 | 257 / 92 | keep "Detected as: X" as a `.meta`; the consequence → InfoTip |
| `EmployersPanel.vue:67` | `settings.employers.addingRemovingAndThe` +3 | 285 / 74 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `MailboxPanel.vue:90` | `settings.mailbox.readingCodesAndActivation` | 456 / 160 | popover on the section head (`SectionHead help`); delete from the card body |
| `MailboxPanel.vue:100` | `settings.mailbox.authorizingAsksForReading` | 536 / 193 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `MailboxPanel.vue:123` | `settings.mailbox.open` +2 | 130 / 45 | keep (the steps of a sign-in in progress) |
| `MailboxPanel.vue:131` | `settings.mailbox.authorizationCodesAndTokens` | 219 / 68 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `NetworkPanel.vue:26` | `settings.network.theAppGoesOnline` | 235 / 75 | popover on the section head (`SectionHead help`); delete from the card body |
| `NetworkPanel.vue:36` | `settings.network.withoutAProtocolHttp` | 149 / 54 | help tooltip (`InfoTip` beside the field's label) |
| `NetworkPanel.vue:49` | `settings.network.afterChangingTheSettings` +2 | 118 / 33 | help tooltip on the section head (`SectionHead help`) |
| `NetworkPanel.vue:60` | `settings.network.sitesSlowerThanSeconds` | 119 / 39 | help tooltip (`InfoTip` beside the field's label) |
| `PromptsPanel.vue:60` | `settings.prompts.theInstructionsTheProgram` | 469 / 134 | popover on the section head (`SectionHead help`); delete from the card body |
| `RecordPanel.vue:101` | `record.questionsForYouHow` | 220 / 70 | keep one sentence under the callout's title; the rest goes |
| `RecordPanel.vue:108` | `record.toDecide` +1 | 147 / 35 | keep (a count, not an explanation); shorten to "N to check" |
| `RecordPanel.vue:206` | `record.tailorAgainHint` +1 | 154 / 45 | help tooltip on the section head (`SectionHead help`) |
| `RecordPanel.vue:209` | `record.tailorNeedsWord` +1 | 129 / 53 | help tooltip on the section head (`SectionHead help`) |
| `RecordPanel.vue:216` | `record.afterHandOver` +1 | 557 / 173 | popover behind "What happens after approval"; keep one line with the outcome |
| `AboutView.vue:131` | `about.howSwitch` | 242 / 68 | popover beside the switch button ("what a switch does") |
| `AboutView.vue:132` | `about.privacy` | 260 / 107 | help tooltip beside "Check for updates" ("what is sent") |
| `AccountsView.vue:121` | `accounts.manyJobSitesLet` +1 | 327 / 128 | popover on the section head; keep one line: "Only the sign-in is kept, never these accounts' passwords" |
| `AccountsView.vue:151` | `accounts.afterAddingItClick` | 333 / 105 | popover inside the "add your own" form (already behind a disclosure) |
| `AccountsView.vue:184` | `accounts.whichBrowserAnAccount` | 118 / 42 | delete: the summary lists what is inside; the section head says "Advanced" |
| `AccountsView.vue:185` | `accounts.onceThisIsOpen` +2 | 339 / 94 | delete: explains the layout trick (a select appearing in every row) that the migration removes; the browser choice moves into the row's menu |
| `AccountsView.vue:189` | `accounts.inChromeGoTo` | 188 / 79 | keep, as steps (it is the instruction for the action below); cut to the path and one sentence |
| `AccountsView.vue:195` | `accounts.someSignInsCannot` | 397 / 131 | popover on the section head; keep one line: "Delete the file when you are done: whoever has it and the passphrase is signed in" |
| `AccountsView.vue:217` | `accounts.aWorkdayIdIs` | 252 / 130 | help tooltip beside "Site ID" (InfoTip → Popover: it has an example) |
| `AccountsView.vue:218` | `accounts.theUniversitysCoOp` | 241 / 94 | popover beside "Site ID" (shown only to the persona that has the portal) |
| `ApplicationDetail.vue:217` | `application.outcomeHow` | 126 / 39 | help tooltip (`InfoTip`) beside the control or heading it explains |
| `ApplicationDetail.vue:242` | `application.fixHow` | 178 / 56 | popover (`InfoTip` opening a `Popover`) beside the control or heading it explains |
| `ApplicationDetail.vue:299` | `application.evidenceAlready` +2 | 127 / 37 | help tooltip (`InfoTip`) beside the control or heading it explains |
| `ApplicationDetail.vue:324` | `application.noMail` | 127 / 36 | keep as the empty state's text (`EmptyState`), shortened |
| `CalendarView.vue:310` | `calendar.share.exportText` | 143 / 50 | calendar: leave as is (inside its own dialog) |
| `CalendarView.vue:313` | `calendar.share.subscribeText` | 218 / 69 | calendar: leave as is (inside its own dialog) |
| `CalendarView.vue:315` | `calendar.share.localOnly` +1 | 300 / 96 | calendar: leave as is (inside its own dialog) |
| `FilesView.vue:238` | `files.page.theDraftThatExists` | 129 / 36 | keep (state of this file), one sentence |
| `FilesView.vue:239` | `files.page.thisVersionsFileHas` +1 | 257 / 71 | keep the title line; the history lesson → popover |
| `JobsView.vue:230` | `postings.addHint` | 116 / 33 | help tooltip (`InfoTip` beside the field's label) |
| `JobsView.vue:350` | `postings.noLink` | 139 / 44 | keep (blocks the main action), one sentence |
| `JobsView.vue:354` | `postings.editHow` | 124 / 30 | help tooltip (`InfoTip` beside the field's label) |
| `JobsView.vue:429` | `postings.jdSummary` | 181 / 66 | keep (warns that the text is partial), one sentence |
| `JobsView.vue:437` | `postings.jdNone` | 149 / 52 | keep as the empty state's text, shortened |
| `LoginView.vue:39` | `login.theFirstSetUp` | 113 / 50 | keep (first-run instruction, nowhere else to learn it); one sentence each |
| `LoginView.vue:40` | `login.ifThatComputerIs` | 110 / 37 | keep (first-run instruction, nowhere else to learn it); one sentence each |
| `LoginView.vue:45` | `login.autoapplyHoldsYourProfile` | 231 / 79 | keep (first-run instruction, nowhere else to learn it); one sentence each |
| `LoginView.vue:49` | `login.atLeastCharactersIf` | 117 / 37 | keep (first-run instruction, nowhere else to learn it); one sentence each |
| `MailOut.vue:59` | `mail.theProgramIsNot` +1 | 202 / 57 | keep (blocks sending), one sentence + the link |
| `MailOut.vue:60` | `mail.theTextHasPlace` | 146 / 54 | keep (blocks sending), one sentence |
| `ProfileView.vue:180` | `profile.usedWhenAnApplication` | 162 / 48 | help tooltip on the section head (`SectionHead help`) |
| `ProfileView.vue:207` | `profile.onlyFilledInWhen` | 251 / 72 | popover on the section head (`SectionHead help`); delete from the card body |
| `ProfileView.vue:224` | `profile.savingWritesThisTo` | 189 / 81 | popover on the section head (`SectionHead help`); delete from the card body |
| `ProfileView.vue:236` | `profile.onlyWhatYouUploaded` +1 | 131 / 40 | help tooltip on the section head (`SectionHead help`) |
| `ProfileView.vue:240` | `profile.queuedItStartsIn` | 119 / 36 | keep (state of a running job), one sentence |
| `ProfileView.vue:241` | `profile.theAiIsReading` | 154 / 45 | keep (state of a running job), one sentence |
| `ProfileView.vue:243` | `profile.whatWasGeneratedAt` | 137 / 48 | keep (result of the job), one sentence |
| `ProfileView.vue:244` | `profile.theProgramOnlyCopies` | 261 / 74 | popover on the section head (`SectionHead help`); delete from the card body |
| `ProfileView.vue:274` | `profile.applicationFormsOftenHave` | 462 / 138 | popover on the section head (`SectionHead help`); delete from the card body |
| `ProfileView.vue:279` | `profile.writeInChineseOr` | 231 / 70 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `ProfileView.vue:286` | `profile.writeInPlainLanguage` | 219 / 56 | popover on the section head (`SectionHead help`); delete from the card body |
| `RemoteView.vue:163` | `remote.thisIsAReal` | 300 / 100 | keep one sentence under the picture; the rest → one `Popover` "How this works" |
| `RemoteView.vue:182` | `remote.clickThePictureThen` | 237 / 69 | keep one sentence under the picture; the rest → one `Popover` "How this works" |
| `RunsView.vue:96` | `runs.draftsWaitingForYou` +5 | 234 / 70 | keep the figure ("Waiting for you: 3 / 10") as a `Status`; the rule and the link → InfoTip |
| `RunsView.vue:173` | `runs.anIntervalCountsFrom` | 262 / 66 | popover on the card title (`SectionHead help`) |
| `RunsView.vue:189` | `runs.besidesEveryMinutesPostings` | 266 / 97 | popover (`InfoTip` opening a `Popover`) beside the control or heading it explains |
| `SettingsView.vue:216` | `settings.page.whatIsWrittenBelow` | 111 / 38 | keep (conditional state), one sentence |
| `SettingsView.vue:220` | `settings.page.fromTopToBottom` | 201 / 57 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:230` | `settings.page.everyStepOfAn` +2 | 166 / 42 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:248` | `settings.page.notSetUpYet` | 141 / 49 | keep (state of the profile), one sentence |
| `SettingsView.vue:249` | `settings.page.yourProfileDecidesWhat` | 152 / 47 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:250` | `settings.page.howPostingsAreScored` +4 | 143 / 42 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:257` | `settings.page.thisIsAFilter` | 414 / 131 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:260` | `settings.page.separateWithCommasMatches` | 153 / 74 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:267` | `settings.page.someSourcesAUniversitys` | 353 / 121 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:278` | `settings.page.oneTitlePerLine` | 163 / 48 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:295` | `settings.page.careerSitesLikeAmazons` | 167 / 53 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:301` | `settings.page.whichEmployersAreWatched` +4 | 249 / 71 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:310` | `settings.page.whenNewPostingsAre` | 114 / 37 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:314` | `settings.page.whenThisManyApplications` | 248 / 79 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:322` | `settings.page.theAgentWorksEach` | 127 / 45 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:334` | `settings.page.whenYourProfileAnswers` | 228 / 68 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:335` | `settings.page.theAgentStopsBefore` | 152 / 46 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:336` | `settings.page.theAgentIsTold` | 162 / 51 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:337` | `settings.page.howFormsAreFilled` +1 | 289 / 90 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:344` | `settings.page.fromThePostingTo` | 261 / 83 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:357` | `settings.page.eachApplicationHasIts` | 158 / 50 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:359` | `settings.page.whenARecordIs` | 373 / 118 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:365` | `settings.page.applicationsThatAreSent` | 211 / 65 | keep one line ("goes from your own mailbox and cannot be taken back"); rest → InfoTip |
| `SettingsView.vue:368` | `settings.page.whenOnTheBrowser` | 263 / 82 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:377` | `settings.page.switchesItOffIt` | 229 / 77 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:378` | `settings.page.switchesItOffThe` | 256 / 75 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:380` | `settings.page.pause` +3 | 305 / 101 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:384` | `settings.page.theRestWaitsFor` +2 | 220 / 63 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:396` | `settings.page.forEachPostingThe` | 168 / 59 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:397` | `settings.page.thereIsNoWord` +2 | 175 / 59 | keep (conditional state), one sentence + its action |
| `SettingsView.vue:419` | `settings.page.keepsYourRSum` | 170 / 61 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:421` | `settings.page.whenTickedAnApplication` | 115 / 28 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:445` | `settings.page.whenASiteNeeds` +1 | 385 / 116 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:449` | `settings.page.toHaveASite` +1 | 247 / 95 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:459` | `settings.page.afterTheServiceOr` | 375 / 115 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:469` | `settings.page.progressThingsThatNeed` +1 | 169 / 62 | help tooltip on the section head (`SectionHead help`) |
| `SettingsView.vue:473` | `settings.page.theAddressALink` +1 | 151 / 46 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:479` | `settings.page.likeTelegramNotificationsArrive` | 226 / 81 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:488` | `settings.page.aBotCanOnly` | 126 / 48 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:496` | `settings.page.validForMinutesOnce` | 119 / 38 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:510` | `settings.page.theButtonsDoWhat` | 405 / 138 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:511` | `settings.page.commandsStatusWhatIs` | 162 / 79 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:513` | `settings.page.askItHowThings` | 276 / 79 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:518` | `settings.summary.hint` | 152 / 42 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:551` | `settings.page.nothingFromTheseHours` | 402 / 117 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:554` | `settings.page.invitationsToInterviewsAnd` +2 | 163 / 46 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:560` | `settings.reminders.intro` | 206 / 64 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:579` | `settings.page.howTheProgramReaches` | 142 / 52 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:583` | `settings.page.byDefaultThePrograms` | 256 / 74 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SettingsView.vue:589` | `settings.page.theseThreeOnlyDecide` | 220 / 59 | popover on the section head (`SectionHead help`); delete from the card body |
| `SettingsView.vue:596` | `settings.page.postingsWithTheSame` | 121 / 42 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:652` | `settings.page.toUpdateTheProgram` | 159 / 42 | help tooltip (`InfoTip` beside the field's label) |
| `SettingsView.vue:659` | `settings.page.notNeededDayTo` +2 | 188 / 47 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `SourcesView.vue:43` | `sources.theProgramReadsThe` | 227 / 84 | popover on the section head (`SectionHead help`); delete from the card body |
| `SourcesView.vue:48` | `sources.whenThePortalRefuses` +2 | 166 / 51 | help tooltip (`InfoTip` beside the field's label) |
| `SourcesView.vue:65` | `sources.theInTheLibrary` +4 | 121 / 35 | help tooltip on the section head (`SectionHead help`) |
| `SourcesView.vue:91` | `sources.passedTheHardConditions2` +4 | 208 / 48 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |
| `TodosView.vue:220` | `todos.theSignInWindow` | 159 / 53 | keep (conditional state), one sentence + its action |
| `TodosView.vue:229` | `todos.inThisSignIn` | 171 / 50 | popover (`InfoTip` opening a `Popover`) beside the control or heading it explains |
| `TodosView.vue:259` | `todos.sentUsedOld` | 173 / 33 | popover (`InfoTip` opening a `Popover`) beside the control or heading it explains |
| `WelcomeView.vue:140` | `welcome.itFindsPostingsScores` | 198 / 54 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:151` | `welcome.aiIsNeededTo` | 293 / 93 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:162` | `welcome.theseDecideWhatPostings` | 147 / 37 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:183` | `welcome.theProgramReadsYour` | 283 / 99 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:189` | `welcome.theAiIsReading` | 187 / 54 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:192` | `welcome.aNewVersionWas` | 203 / 59 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:193` | `welcome.yourProfileHasBeen` | 235 / 66 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:198` | `welcome.thisStepNeedsAn` | 113 / 40 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:206` | `welcome.suggestionsByAi` +1 | 448 / 133 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:220` | `welcome.pickAFewTo` | 170 / 53 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:223` | `welcome.theseCompaniesHavePostings` +1 | 165 / 47 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:230` | `welcome.aSchoolPortalUses` | 443 / 156 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:232` | `welcome.pasteTheUrlOf` | 132 / 47 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:239` | `welcome.yourSettingsAreNow` +2 | 299 / 85 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:246` | `welcome.yourProfileIsStill2` | 203 / 48 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:266` | `welcome.yourProfileIsStill3` | 151 / 46 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:267` | `welcome.yourProfileIsStill4` | 160 / 45 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `WelcomeView.vue:268` | `welcome.youCanAlsoSet` | 226 / 80 | keep in the wizard, at most one sentence per step; the rest → InfoTip beside the choice |
| `analytics/AppsPanel.vue:45` | `analytics.apps.acknowledgedAnythingCameBack` | 115 / 39 | already behind a disclosure (`Explain`): becomes an `InfoTip` beside the figure's label |
| `analytics/AppsPanel.vue:48` | `analytics.apps.cameToSomethingIt` | 165 / 43 | already behind a disclosure (`Explain`): becomes an `InfoTip` beside the figure's label |
| `analytics/AppsPanel.vue:56` | `analytics.apps.applicationsHaveBeenSent` +3 | 370 / 120 | popover on the card title (`SectionHead help`): what the figure counts |
| `analytics/AppsPanel.vue:61` | `analytics.apps.eachStepIsA` | 141 / 47 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AppsPanel.vue:96` | `analytics.apps.theFirstTwoColumns` | 163 / 48 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AppsPanel.vue:101` | `analytics.apps.theShareOfApplications2` | 132 / 37 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AppsPanel.vue:142` | `analytics.first.explain` | 279 / 75 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AppsPanel.vue:151` | `analytics.backlog.explain` | 155 / 43 | already behind a disclosure (`Explain`): becomes an `InfoTip` beside the figure's label |
| `analytics/AppsPanel.vue:169` | `analytics.apps.scoredOrHigherAnd` | 129 / 45 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AutoPanel.vue:75` | `analytics.auto.completedRanToAn` | 455 / 142 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:118` | `analytics.auto.durationIsTheMedian` | 158 / 47 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AutoPanel.vue:144` | `analytics.auto.theFiguresAboveCount` | 334 / 99 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:145` | `analytics.auto.theAgentWorkedApplications` | 144 / 61 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AutoPanel.vue:149` | `analytics.auto.applicationsBroughtToWhere` | 206 / 72 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:152` | `analytics.auto.ofThePreparedApplications` | 177 / 49 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:155` | `analytics.auto.ofTheApplicationsYou` | 225 / 67 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:164` | `analytics.auto.fromEachApplicationsOwn` | 324 / 95 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:165` | `analytics.auto.applicationsHadRunsIn` +1 | 144 / 53 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/AutoPanel.vue:171` | `analytics.auto.toolCallsOfEvery` | 152 / 54 | already behind a disclosure (`Explain`): becomes an `InfoTip` beside the figure's label |
| `analytics/AutoPanel.vue:196` | `analytics.asked.explain` | 205 / 73 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/AutoPanel.vue:216` | `analytics.unknown.explain` | 232 / 67 | already behind a disclosure (`Explain`): becomes an `InfoTip` opening a `Popover` beside the figure's label |
| `analytics/CostPanel.vue:144` | `analytics.cost.costIsDividedIn` +1 | 165 / 50 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/CostPanel.vue:199` | `analytics.cost.oneCallCanContain` | 138 / 41 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/CostPanel.vue:222` | `analytics.cost.everythingAKindOf` | 170 / 55 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/CostPanel.vue:267` | `analytics.cost.highWellAboveMost` | 170 / 63 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/CostPanel.vue:286` | `analytics.cost.comparedWithOtherRequests` | 120 / 40 | help tooltip on the card title (`SectionHead help`): what the figure counts |
| `analytics/CostPanel.vue:350` | `analytics.cost.usDollarsPerMillion` | 430 / 143 | popover on the card title (`SectionHead help`): what the figure counts |
| `analytics/SitesPanel.vue:32` | `analytics.sites.withEveryApplicationThe` | 331 / 107 | popover on the card title (`SectionHead help`): what the figure counts |
| `calendar/EventDetail.vue:142` | `calendar.alarm.hintAllDay` +1 | 216 / 72 | popover (`InfoTip` opening a `Popover`) beside the field's label; keep a consequence, if any, in ≤ 1 line |

## Resolution

State after the migration of every page to the shared layer and the integration pass that followed it (branch
`ui/design-system`). "Resolved" means the cause is gone in the code **and** it was looked at in the running program
(Playwright, demo data, 1440 px in zh and en; 1024 / 1280 px in en and dark spot checks): no page scrolls sideways at
those widths, every DataTable has one row height per table, no native `title` is rendered in `main`, and the console is
clean on every page, tab and overlay walked. "Code only" means the code says so but it was not looked at in this pass;
"not verified" means neither.

### Root causes

| # | State | How (or why not) |
| --- | --- | --- |
| R1 | Resolved | Every list of records is a `DataTable` (fixed layout, widths from the column definitions, one density per table); cards line up by structure (`ProviderCard`, `CardHead`). Hand-made tables left: the compact figure tables of analytics (`.an-table`, fixed layout with a `<colgroup>`), the settings matrix, and the answers of a record (`RecordPanel`, see D6). |
| R2 | Resolved | `Trunc` / `.cut` / `.cut2` and `v-tip.overflow` - the page title too (`PageHead`: one line, cut, overflow tooltip, actions kept at the right). |
| R3 | Resolved | No native `title` in `views/` or `components/` (grep) and none rendered; one tooltip (`v-tip`, `InfoTip`, `HelpPop`). |
| R4 | Resolved | `.actions` (one line) + `Menu`; destructive items last, `danger`, asked with `{ danger: true }` (bulk withdraw added in this pass). |
| R5 | Resolved | `Status` by default, `.tag` for what must stand out, `.meta` for attributes; green only for real success (the "reached an assessment / interview" figure is no longer green). |
| R6 | Mostly | Page subtitles gone except the calendar's (`calendar.sub` describes the page; the calendar was not to be restructured - drop the `sub` there). Help is behind (i). Long hints remain in Settings, Welcome and the PD Portal card of Sources. |
| R7 | Resolved | Inline `style=` only in `views/calendar/*` and `CalendarView.vue` (left by rule); sizes and weights from tokens. |
| R8 | Mostly | One date contract (G16), one tabs component (every tab row, Profile's with the unsaved dot), one loading / error component (`DataState`; About, Analytics and Settings keep their own forms of it, Login / Remote / Welcome read nothing that needs it). |
| R9 | Resolved | Optional columns by the box's width (`priority`); container queries for `.kv`, `.fields` and the record's answers. |
| R10 | Mostly | Glossary applied to the catalogs, the calendar's values included; a few sentences are still glued from fragments around links (glossary §5). |

### P0 and P1 rows

| ID | State |
| --- | --- |
| G1, G2, G3 | Resolved (`DataTable`; no inner scroller with a page override; `priority`). |
| G4 | Resolved. |
| G5, G6 | Code only for `.sel` widths and `--h-*` heights; the filter bars of every list page were looked at: one height. |
| G7, G8, G9 | Resolved. |
| G10 / H1 | Resolved: the first column of `.list > .item` is bounded (136 px, cut); the first-run guide's keep / discard list was given a column of its own width in this pass. |
| G11 | Resolved (`.kv` label column `minmax(96px, min(240px, 34%))`, one column in a narrow box); the accounts page does not scroll sideways at 1024. |
| G12, G13 | Resolved. |
| G14 | Resolved for every `danger` menu item and for bulk withdraw; "unlink a mail" and "drop a question" ask without red on purpose (both can be undone). |
| G15 | Resolved (`HelpPop` / `InfoTip`; no `<Explain>` left). |
| G16 | Resolved in this pass: one form of a day everywhere (`dateOf`: "11月20日" / "Nov 20", the year only when it is not this year); a scheduled time is day + time (`dateTimeOf`); a moment of what happened is relative (`when`: today / yesterday / a day). `shortDayText` is now `dayText`; "11/20" is left for a chart's axis. The raw date of About and the quota's reset time go through the same functions. |
| G19 | Resolved (catalog scan: no full-width punctuation in en / fr values). |
| A1 | Resolved (calendar parser for `next_date`). |
| A2-A6 | Resolved. |
| D2, D3 | Resolved; the status card's "More" now looks like every labelled "More" (secondary, `more` icon). |
| D4 | Not resolved: the reason an action is disabled is not shown. Needs a line under the actions, or a focusable wrapper with `v-tip`. |
| D6 | Partly: confidence is a `Status`, "Change" an `IconButton`, widths are classes, every cell starts on the first line's baseline, the basis column gives way in a box under 820 px. The answers stay a wrapping `<table>`: an answer is the text sent and is read whole (a `DataTable` would cut it to two lines); editing stays in the row. |
| J1-J8 | Resolved; a row's one visible action is `button.ghost.sm` (Postings, Site accounts, Activity alike). |
| T1-T5, T8 | Resolved. |
| H2, H3 | Resolved. |
| C1-C4, C6-C12 | Resolved (cards and table at 1440 / 1024; drawers and menus opened). C5 code only. |
| F1, F2, F3 | Code only (`Menu` in the preview, `aria-label`, `danger`); the preview of a file was not opened in this pass. |
| K1-K3 | Resolved; since this pass the contact's form in its drawer is a `.fields` form (labels above, as the other forms) and the list is `comfortable` (two-line rows). |
| S1 | Resolved (`DataTable`, `IconButton pressed`, row `Menu`); its own "Scan now" was removed in this pass (it repeated the page's). |
| S2 | Partly: state as `Status`, one action; the hint under it is still a paragraph glued around a link. |
| S3 | Resolved; S4 (P2) resolved in this pass (`DataState`). |
| P1, P2, P5 | Resolved (tabs with the unsaved dot, `.fields`, help behind (i)). |
| U1, U3 | Code only (`Pager`, `aria-label`). |
| X1 | Partly: most fields have their help behind (i); long hints remain under some controls. "Saved with Save at the top right" is no longer repeated on every section (only a section that saves otherwise says how). |
| X2 | Partly: hints are under their control; not every one became an (i). |
| X4 | Partly: rules are fixed rows with an `IconButton` delete (nothing is stored before Save, so no question); human names for the browsers; not a `DataTable`. |
| X5 | Resolved. |
| N1, N2, N3 | Resolved; the backlog table's header no longer wraps. |
| L1 | Partly: tooltips done; the `sub` remains (R6). |
| M1 | Code only (`IconButton`s); the remote window was not opened in this pass. |

### Found in the integration pass and fixed

- Tabs: one component everywhere (Analytics views and its chart / table switch, an application's parts, the groups of
  Applications and Postings, Profile - with a `dot` per tab for unsaved changes); arrow keys on all of them.
- Toasts rise above the BulkBar while it is shown (`body:has(.bulk-frame) .toasts`), measured with a failing bulk action.
- Heads: a section head inside a card became `CardHead` (Sources, the record's "Review these first"); back links sit
  under the title and name the page they lead to (Sources, an application); a card's explanation is its (i), not a
  paragraph under the title (Profile salary and source editor).
- Same action, same look: "scan" has one icon (`refresh`), "start an application" one icon (`draft`) and the plural
  wording "Start applications" in the bulk bar; a row's action is ghost; a labelled "More" is secondary with the `more`
  icon.
- Dates: see G16. Lists of names: `listed()` (`Intl.ListFormat`) in `i18n/format.js`, used by Files, Action required,
  Welcome and the profile's regions.
- Found by the QA page tests and fixed: the Postings row action is never cut (its column is sized from the words in the
  shown language, measured on a hidden copy); the headers of the analytics figure tables are one line in every language
  (wider bounded columns `w-m` / `w-l`, and where a narrow card still squeezes one it is cut with an overflow tooltip);
  the sidebar's pause button fits in French ("Mettre en pause" / "Reprendre").
- First-run guide (walked on a fresh instance, zh and en, 1440 and 1024): the AI step opens like the other steps, no
  longer tells the reader to press a Save that is not there, and no longer offers the panel's test of saved settings
  beside its own; the last step puts the secondary action first; the keep / discard list lines up.

### Not resolved, and what would do it

- Server-side texts stay in the language they were written in (W8): to-dos and agent summaries made in Chinese show in
  Chinese in the English interface. Needs the server to keep keys and parameters, not sentences.
- Analytics → backlog by kind shows the raw value `note` for one kind: the server sends no label for it
  (`by_kind[].label`) - a backend fix.
- D4, the calendar's `sub`, and the glued sentences listed in glossary §5.

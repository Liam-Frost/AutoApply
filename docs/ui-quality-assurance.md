# UI quality assurance

How the interface is kept from sliding back: what is checked automatically, where each check lives, how to run it,
and what still needs a person's eyes. The rules themselves are in `docs/component-guidelines.md` (the shared
components and what each guarantees) and `docs/DESIGN_SYSTEM.md` (tokens, wording, page structure).

The idea in one line: **a rule that matters is a number a test measures, on the shared component, once** - not
something each page has to remember.

## What is checked where

| Layer | What it catches | Where | Needs |
| --- | --- | --- | --- |
| Static rules | a browser tooltip (`title="…"`), a hex colour or a pixel font size in a component, a hand-made `<table>` for a list of records, an icon button without a name | `frontend/tests/ui-rules.test.js` | Node |
| Pure functions | column widths and which optional column goes first (`tablelayout.test.js`); where a tooltip, menu or popover is put at every edge of the window, and what a `v-tip` binding means (`float.test.js`); what the calendar shows in a cell (`calendar.test.js`); focus order (`focus.test.js`) | `frontend/tests/*.test.js` | Node |
| Contrast | every text token on every background it stands on is at least 4.5:1, in both themes, and the two copies of the dark tokens agree | `frontend/tests/contrast.test.js` | Node |
| Words | every key exists in every language with the same placeholders; no text of its own in a component | `frontend/tests/i18n.test.js`, `text.test.js` | Node |
| Layout of the shared components | what is actually drawn, measured in a browser on the UI lab (below) | `tests/test_ui_layout.py` | the built interface, Chromium |
| Layout of the pages | the same kind of measurement on the real pages with the demo's data | page-level tests - **not written yet**; they come when the pages are migrated to the shared components | the built interface, Chromium |
| Screenshots | everything a number does not say: spacing, weight, balance, colour | `scripts/ui_shots.py` - for a person, before a release; not a gate | a running demo copy, Chromium |

### The layout tests (`tests/test_ui_layout.py`)

They open `/ui-lab` - every shared component in its states, with made-up data - and measure boxes. They never assert
how wide a text is (fonts differ between computers): they compare boxes with each other and with the tokens, to
within one pixel.

- **DataTable**: every row of a table has the height of its density (40 / 56 / 64); the same columns with short and
  with absurd values are exactly as wide; header cells and body cells share their left edges and widths; a table never
  reaches out of the place it was put in - it fills it, or scrolls inside its own box; in narrower boxes the optional
  columns go, the highest `priority` first, and the table scrolls sideways only when nothing is left to give up;
  nothing in a cell reaches out of the cell's padding without cutting itself; the page never scrolls sideways (1440,
  1024, 640 wide, and with the lab narrowed to 480).
- **Text**: a `Trunc` that is cut (`scrollWidth > clientWidth`) shows the whole text in the program's tooltip
  (`#aa-tip`) and is tied to it with `aria-describedby`; one that fits shows none; made wider, it stops having one.
  Nothing in the lab carries a `title` attribute. Buttons, badges, `.atomic` labels, states, plain attributes, dates
  and cut text are one line, in English and Chinese, also at 480px.
- **Controls**: a button, a field, a drop-down and a segmented control of one level are one height (32; small 28) and
  on one line; the three button sizes are 28 / 32 / 36; a badge is 20; an `IconButton` has a name, no `title`, and is
  a square of 28 (small 24); under way it keeps its size and its neighbour stays where it was.
- **Overlays**: the tooltip shows at once on keyboard focus (not on focus the program moved) and Escape hides it; it
  stays inside the window at all four corners; a `Menu` opens with the keyboard, the arrow keys, Home and End move,
  Enter picks, Escape closes, the focus is back on the button, and pressing it does not press the row it stands in; a
  `Popover` takes the focus (to what it is for, not to an (i)), Escape and a press outside close it and the focus goes
  back; both stay inside the window at the right edge.
- **Themes and languages**: the table and control checks run in light and dark, in English and Chinese.
- **Accessibility basics**: every button and link has a name; every stop of the Tab key shows a focus ring (2px or
  more); under `prefers-reduced-motion` nothing has a transition or animation longer than a millisecond.
- **Accounts** (provider cards of one row equal in height with their feet in line; the credential button at the same
  place in every row): skipped until the lab has an `Accounts` section.

A test marked `xfail(strict=True)` is a known fault with its reason in the mark: it fails the run on the day the fault
is fixed, and the mark is then removed - so the fix cannot be undone unnoticed.

### The static rules (`frontend/tests/ui-rules.test.js`)

Each rule has a list (`PENDING`) of the files that do not follow it yet, with the number of places left in each:

- a file that is not listed may have none, and a listed file never more than its number - a new one fails;
- a listed file that has become clean fails too, until its line is deleted - so it stays clean.

The lists only get shorter. `UI_RULES_REPORT=1 npx vitest run tests/ui-rules.test.js` prints them as they would be
written today. A `<table>` that really is a small grid of figures (not a list of records) is added to `TABLES` in
the test, with the reason beside it.

## Running them

```sh
# static rules, pure functions, contrast, words (seconds)
cd frontend
npm test                                    # everything
npx vitest run tests/ui-rules.test.js       # one file

# layout tests (about a minute; one server and one browser for the whole run)
cd frontend && npm run build && cd ..       # they look at the BUILT interface: build first, every time
uv run playwright install chromium          # once
uv run pytest -q tests/test_ui_layout.py
```

The layout tests start the program themselves (`tests/ui_server.py`): a copy on a free port with a throw-away data
folder filled by the demo's seed, its own keyring namespace, no sign-in, no background work and no AI. They never
touch your own data. Without `frontend/dist` or without Chromium they are **skipped** with the reason; in CI
`AUTOAPPLY_REQUIRE_UI_TESTS=1` turns that into a failure, so a missing build cannot pass for a green run. Set it
locally when you want to be sure they ran:

```sh
AUTOAPPLY_REQUIRE_UI_TESTS=1 uv run pytest -q tests/test_ui_layout.py -rs
```

When one fails, the message names the table, the row or the element and the pixels. To look at it:
`uv run python scripts/demo.py --serve 8022`, then open `http://127.0.0.1:8022/ui-lab` (`?only=DataTable,Cells` shows
some sections, `?narrow=480` narrows the page).

## Screenshots before and after a change

`scripts/ui_shots.py` photographs every page and every lab section of a **running demo copy** at 1920 / 1600 / 1440 /
1280 / 1024, light and dark, Chinese and English, and can put two sets beside each other.

```sh
# before the change (on the commit you start from, interface built)
uv run python scripts/demo.py --serve 8022          # in another terminal; made-up data
uv run python scripts/ui_shots.py --out shots/before

# after the change: build, start the demo again, then
uv run python scripts/ui_shots.py --out shots/after --compare shots/before
# -> shots/after/compare.txt (share of differing pixels per picture) and shots/after/diff/index.html (side by side)

# a smaller round while working
uv run python scripts/ui_shots.py --out shots/after --pages jobs,applications,lab-DataTable --widths 1440,1024 --langs en
```

- It is **not a CI gate**. Fonts and text rendering differ between computers and browser versions: compare only sets
  taken on one computer, from the same data. Two demo copies seeded on the same day show the same things; over
  midnight the relative dates move.
- Stable on purpose: animations off, a fixed window and scale, no caret, the page's clock held at noon.
- It refuses port 8000 (a real installation) unless `--i-know` is given: your own applications, accounts and mail do
  not belong in a folder of screenshots. Keep `shots/` out of commits.

## What a person still checks (before a release)

Tests measure boxes; they do not see whether a page reads well. With the demo copy open, go through the pages that
changed:

- **Zoom 125% and 150%** (Ctrl +) at a 1366 or 1440 wide window: nothing overlaps, no button leaves its card, the
  table still gives up columns instead of scrolling the page, the side bar turns into the top bar when it should.
- **Text scaling**: the system's larger-text setting (Windows: Accessibility > Text size 130%; macOS: larger text);
  and the browser's minimum font size at 16. One-line controls stay one line; rows keep their height and cut.
- **Touch** (a tablet, or the browser's device mode with touch): an (i) opens on a press and closes on the next;
  nothing important is only in a hover; every target is at least 28px; the bulk bar does not cover the last row.
- **Keyboard only**: Tab through the page - the order follows what is seen, the focus is always visible and never
  lands behind an open drawer; Escape closes the innermost layer first.
- **Both themes** side by side for anything with colour: a state colour on its soft background, a chart, a focus
  ring on a selected row.
- **Long and empty data**: the longest company name, a job without a title, no data at all (the empty state), the
  data read failing (stop the demo: the stale notice).
- **Languages**: Chinese, English and French for anything with a new label (French is the longest).
- **A real screen reader pass** (NVDA or VoiceOver) over a page whose structure changed: titles, table headers, the
  names of icon buttons, what a menu and a popover announce.

## Adding a check

**A new shared component**

1. Give it a section in the lab (`frontend/src/views/lab/sections/NN-Name.vue`) that shows every state with made-up
   data, *including the hard ones*: the longest text, CJK text, text without spaces, nothing at all, a narrow box.
   Mark what a test will look for with `data-*` attributes (the lab uses `data-dt`, `data-t`, `data-level`), not with
   classes that may change.
2. Add its guarantees to `tests/test_ui_layout.py` as measurements: equal to a token, equal to its neighbour, inside
   its box - never an absolute text width. If the guarantee is pure arithmetic, put the arithmetic in a function and
   test that in `frontend/tests/` instead: it is faster and says more.
3. Break it on purpose once (a style in the browser's inspector, or a temporary edit) and see the test fail: a check
   that cannot fail checks nothing.
4. If the component replaces something pages did by hand, add a static rule (or extend one) in
   `frontend/tests/ui-rules.test.js` so that the old way cannot come back, with the pages that still do it listed in
   `PENDING`.

**A new page, or a page that was migrated**

1. Delete its lines from the `PENDING` lists of `ui-rules.test.js` (the test tells you which).
2. Add it to `PAGES` in `scripts/ui_shots.py`.
3. Add it to the page-level tests once they exist: no sideways scroll at 1440 / 1024 / 640, no `title` attributes,
   every button and link named, rows of its table one height - with the demo's data (extend `scripts/demo.py`'s seed
   when the page needs data the demo does not have; made up, never real).

## Known limits

- The layout tests run in Chromium only, at 100% zoom, with the fonts of the computer they run on.
- They run with `prefers-reduced-motion` on (a measurement never lands inside a transition); one test turns it off to
  prove that there is motion to remove.
- The lab's texts are English whatever the language: the Chinese runs check the fonts and the program's own frame,
  not translated labels in the components. Translated pages are the page-level tests' job.

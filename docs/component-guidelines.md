# Component guidelines

The shared pieces every page is built from, and what each of them guarantees. A page says *what* to show; these
components decide *how* it is shown - sizes, truncation, tooltips, alignment - the same way everywhere. A page does not
define its own table widths, button behaviour, text cutting or tooltip.

Layers (lower ones never import higher ones):

```
L5 pages             views/*.vue
L4 business patterns components/cells/*, ProviderCard, CredentialCell, calendar/*
L3 composites        DataTable, PageHead, SectionHead, BulkBar, SideDrawer, DetailPanel, Menu, Popover
L2 primitives        button classes, IconButton, Trunc, Status, .tag, InfoTip, v-tip, AaSelect
L1 foundations       tokens in src/style.css; rules in docs/DESIGN_SYSTEM.md
```

Styles live in `src/style.css` (tokens, base, older components) and `src/styles/{foundations,table,overlay,patterns}.css`.
Components do not carry colours or sizes of their own: they use tokens. No `<style scoped>` with hex colours or pixel
font sizes in a view.

## Tokens added for these components (`src/style.css`)

| Token | Value | Use |
| --- | --- | --- |
| `--h-xs … --h-xl` | 24 / 28 / 32 / 36 / 40 px | height of a control of that level: a button, an input, a select and a segmented control of one level are the same height |
| `--row-compact / -standard / -comfortable` | 40 / 56 / 64 px | DataTable row height |
| `--fw-regular / -medium / -semibold` | 400 / 500 / 600 | weights; data-dense areas use medium for the primary line, not bold |
| `--z-sticky … --z-toast` | 20 / 40 / 41 / 60 / 70 / 80 | sticky bar, drawer veil, drawer, menu or popover, tooltip, toast |
| `--dur-fast`, `--dur`, `--ease` | 120ms, 160ms | transitions; none under `prefers-reduced-motion` |
| `--tip-bg`, `--tip-fg` | reverse of the page | tooltip |

## Text (`Trunc.vue`, classes in `styles/foundations.css`)

| Kind of text | Rule |
| --- | --- |
| button, badge, short label, date, time, number | never wraps (`.atomic` / built into the component) |
| company, job title, site, file name | one line, cut with an ellipsis; the whole of it in an overflow tooltip |
| domain, e-mail, URL | one line, cut; never `word-break: break-all` on running text |
| description in a table | at most two lines |
| paragraph | wraps naturally |
| technical detail | not in a row: in a popover, a drawer or `TechDetails` |

- `<Trunc :text="s" />` - one line, ellipsis, tooltip **only when it is actually cut** (it re-checks when its box
  changes size). Props: `text` (String), `lines` (Number, default 1; 2 clamps to two lines), `as` (tag, default `span`).
  Also usable with a slot for the content when `text` gives the tooltip's words.
- Classes for roles: `.t-primary` (14px medium, `--text`), `.t-secondary` (13px regular, `--text-2`), `.t-meta` (12px,
  `--text-3`), `.num` (tabular numerals), `.atomic` (no wrap).
- Cutting is presentation only: the data is never shortened, and never by counting characters.

## Tooltip (`v-tip`, `src/tip.js`, `TipLayer.vue`, `InfoTip.vue`)

One tooltip for the whole program; the browser's own (`title="…"`) is not used for anything a person should read.

```html
<button v-tip="$t('accounts.showPassword')">…</button>          <!-- says what an icon does -->
<span class="cut" v-tip.overflow>{{ company }}</span>             <!-- only when cut; the element's own text -->
<span v-tip.overflow="fullText">…</span>                          <!-- only when cut; this text -->
<span v-tip="{ text, placement: 'bottom' }">…</span>              <!-- placement: top (default) | bottom | left | right -->
<InfoTip :text="$t('jobs.scoreHelp')" />                          <!-- a small (i): hover, focus, or a press on touch -->
```

- Shows after 350ms of hover or at once on keyboard focus; hides 100ms after leaving; the pointer can move into it;
  Escape hides it; it flips and shifts to stay inside the window; it is put on `<body>` (never clipped by a table or
  card); it follows the theme; no animation under reduced motion.
- An empty or missing text shows nothing. The element is tied to it with `aria-describedby` while it shows.
- A tooltip holds a few words or a sentence. Several sentences, a list, anything to press: `Popover`. A whole record:
  `SideDrawer` / a detail panel.
- `title` stays only where it is an accessible name the element has no other way to carry (an `<iframe>`).
- Never both `title` and `v-tip` on one element. An icon-only button gets its name from `aria-label` (`IconButton`
  does both).

## IconButton (`IconButton.vue`)

```html
<IconButton icon="eye" :label="$t('accounts.showPassword')" @click="reveal(a)" />
```

Props: `icon` (name in `Icon.vue`), `label` (required: the accessible name **and** the tooltip), `size` (`sm` 24px |
`md` 28px, default `md`), `tone` (`''` | `danger`), `pressed` (Boolean, for toggles: sets `aria-pressed`), `loading`,
`disabled`. Always square, never wraps; the hit area is at least 28px even when the glyph is smaller. Loading swaps the
glyph for the spinner without changing its size.

## Buttons and what an action looks like

| Action | Looks like |
| --- | --- |
| the page's main action | `button.primary` (one per page head) |
| other page actions | `button` (secondary) |
| common light action in a row or card | `button.ghost.sm` or an `IconButton` |
| rarely used | an item of a `Menu` |
| destructive | a `danger` item at the bottom of a `Menu`, confirmed with `ask(…, { danger: true })` |

Buttons never wrap (`white-space: nowrap` is in the base style). A group of actions is `<div class="actions">` (one
line, same height, 8px apart); when there is not room for all, the secondary ones belong in a `Menu`, by decision -
not by letting them wrap. Red is not shown on every row: a row's delete lives in its menu.

## Menu (`Menu.vue`) and Popover (`Popover.vue`)

```html
<Menu :label="$t('common.more')" :items="[
  { id: 'clear', label: $t('accounts.clearSession'), icon: 'x' },
  { id: 'delete', label: $t('accounts.deleteAccount'), icon: 'trash', danger: true },
]" @pick="onPick" />
```

`Menu` props: `items` (`{ id, label, icon?, danger?, disabled?, hint? }`; a `{ divider: true }` separates), `label`
(name of the trigger), `icon` (default `more`), `align` (`end` | `start`). Slot `trigger` replaces the default
`IconButton`. Emits `pick(id)`. Arrow keys, Home / End, Enter, Escape; focus returns to the trigger; closes on a press
outside; on `<body>`, placed like the tooltip.

`Popover` props: `label`, `placement`, `width` (px). Slots: `trigger="{ open, toggle }"`, default (the content).
Focus goes into it, Escape and a press outside close it, focus returns. For help that is more than a sentence, and for
small forms (a provider's browser setting).

Which layer for what: tooltip - a few words, nothing to press; popover - explanation or a light form; menu - choosing
an action; drawer / detail panel - a whole record; dialog (`ask`) - a decision that must be made; toast - what came of
an action.

## DataTable (`DataTable.vue`, `src/tablelayout.js`, cells in `components/cells/`)

```html
<DataTable :columns="cols" :rows="shown" row-key="id" density="comfortable" selectable v-model:selected="picked"
           v-model:sort="sort" clickable @row="open" :label="$t('applications.title')">
  <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" :to="'/applications/' + row.id" /></template>
  <template #cell-date="{ row }"><DateTimeCell :primary="…" :secondary="…" /></template>
  <template #empty><EmptyState … /></template>
</DataTable>
```

Column: `{ id, header, width?, min?, max?, flex?, align?: 'start'|'center'|'end', priority?: Number, sortable?,
headerTip?, class? }`.

- **Fixed**: `width` (px). **Bounded**: `min` and `max`. **Flexible**: `flex` (shares what is left, never under `min`,
  never over `max`). **Optional**: `priority` > 0 - when the table is narrower than the sum of the minimum widths, the
  column with the highest `priority` number is hidden first; columns without `priority` are never hidden. If what
  must stay still does not fit, the table scrolls sideways inside its own box (the page never does).
- Widths are computed from the column definitions and the box's width (`layoutColumns` in `tablelayout.js`, a pure
  function, tested) and written into a `<colgroup>` of a `table-layout: fixed` table: **no cell content can change a
  column's width**. Header and cells share the same columns.
- `density`: `compact` 40px, `standard` 56px, `comfortable` 64px. Every data row of a table has that height; a cell
  cuts what does not fit (cells are `overflow: hidden`, content vertically centred). A row may be taller only when it
  is opened on purpose (slot `expanded`).
- `selectable` adds a 40px checkbox column; `v-model:selected` is a `Set` of row keys. `clickable` makes the row a
  link target (`@row`), with the keyboard too. `v-model:sort` is `{ by, dir }`; sorting itself is the page's.
- Sticky header inside the scrolling box; row hover and selected states; slots `cell-<id>="{ row }"`,
  `head-<id>`, `empty`, `expanded="{ row }"`; prop `expandedKey`.
- What does not fit a row at all (a reason, a diagnosis, a mail's text) is not in the table: it is behind a status
  tooltip, a popover or the row's page.

Cells:

- `EntityCell` - `primary`, `secondary?`, `to?` (router link on the primary line), slot `after` (a small mark after
  the primary line). Two lines, each cut on its own with an overflow tooltip; without `secondary` the primary line is
  centred. Company + title, site + host, name + e-mail, file + kind.
- `DateTimeCell` - `primary` (the date or time, already formatted), `secondary?` (what it is), `tone?`
  (`''|'warn'|'bad'|'muted'`), `tip?` (the whole thing). Never wraps.
- `Status` (primitive) - `tone` (`ok|warn|bad|info|''`), `label`, `tip?` (a short reason: shows an (i) and a tooltip).
  A dot and words, low weight: the default in a dense table. `.tag` (a filled badge) is for the few states that must
  stand out (interview, overdue, failed).
- Plain values: `<Trunc>`; nothing: `—` in `.t-meta` (`<span class="none">—</span>`).

## Status, badge, metadata

Three weights, in falling order - most things are the third:

1. `.tag` / `.tag.ok|warn|bad|info` and the calendar's `.ev-kind` - a state that matters to the business and must be
   seen: interview, assessment, overdue, failed, waiting for verification.
2. `Status` - an ordinary state in a dense place: `● Auto sign-in ready`, `● Session saved`.
3. `.meta` - a plain attribute, no fill: Workday, Greenhouse, "registered by the program", "employer site".

Colour is never the only sign (a dot has its words). Red is for danger, failure and what is overdue; green only for
what really succeeded - progress in hiring is not all green. The kinds of calendar items keep their `--ev-*` colours
everywhere they appear (`calendar.js FAMILY`, `views/calendar/look.js`).

## Page head, section head, bars

- `PageHead` - `title`, `help?` (an `InfoTip` beside the title: what the page is for, only if it helps), `sub?` (a line
  under the title: only what the reader must know to decide something here - most pages have none). Slot: the page's
  actions, secondary first, the primary one last.
- `SectionHead` - `title`, `help?`, `count?`; slot for the section's actions.
- Filters: `.filters` - search first, then the selects, the count at the end; rarely used conditions go behind a
  filter popover (as on the calendar), not in the bar.
- `BulkBar` - appears when rows are ticked, fixed to the bottom of the view (it never moves the page); says how many,
  then the actions, then "clear".

## Words

Every text a person reads is a key in `frontend/src/locales/` (see CONTRIBUTING). The words themselves follow
`docs/ux-writing-glossary.md`: a title names the thing, a button is a verb, a state is a short phrase, a column header
names an attribute. Catalogs are changed with `python frontend/scripts/i18n-apply.py patch.json` (all languages and the
note at once).

## The UI lab

`/ui-lab` (not in the navigation) shows every shared component in its states with made-up data; a section is a file
in `frontend/src/views/lab/sections/`. A new shared component gets a section; the layout tests
(`tests/test_ui_layout.py`) look at the lab.

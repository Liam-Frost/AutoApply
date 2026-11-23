# Component guidelines

The shared pieces every page is built from, and what each of them guarantees. A page says *what* to show; these
components decide *how* it is shown - sizes, truncation, tooltips, alignment - the same way everywhere. A page does not
define its own table widths, button behaviour, text cutting, tooltip or tab row. This file is a contract: where it and
a component disagree, one of them is wrong. Token values and the rules behind them (in Chinese) are in
[`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md); words in [`ux-writing-glossary.md`](ux-writing-glossary.md); the checks that
hold all this in [`ui-quality-assurance.md`](ui-quality-assurance.md).

## Rules for a new page

1. Start with `PageHead` (title, `help?`, actions: secondary first, at most one `button.primary`, last).
2. A list of records is a `DataTable` with cells (`EntityCell`, `DateTimeCell`, `Status`, `Trunc`) - never a hand-made `<table>`.
3. Parts of the page are `Tabs`; filters are `.filters`; sections are `SectionHead`, cards `CardHead`.
4. A row or card has one visible light action (`button.ghost.sm` or `IconButton`); the rest go into a `Menu`; delete is its last, `danger` item, confirmed with `ask(…, { danger: true })`.
5. Text that can be long is `<Trunc>` (or `.cut` / `.cut2`); text is never shortened by counting characters.
6. Hover help is `v-tip` / `InfoTip` / `HelpPop` - never `title="…"`. An icon alone is an `IconButton` with a `label`.
7. A few words: tooltip; more, or something to press: `Popover`; a whole record: `SideDrawer`; a decision: `ask`.
8. Forms: `.fields` with `label.f`, buttons in `.actions.form-acts`; every control has a name (label, `aria-label`).
9. Only tokens: no hex colour, pixel font size or bare `z-index` in a component; both themes and zh / en must work.
10. Every word is an i18n key (`frontend/scripts/i18n-apply.py`); a new shared piece gets a section in `/ui-lab`.

## Layers

Lower layers never import higher ones:

```
L5 pages             views/*.vue
L4 business patterns components/cells/*, ProviderCard, calendar/*
L3 composites        DataTable, PageHead, SectionHead, CardHead, BulkBar, Tabs, SideDrawer, DetailPanel, Menu, Popover, HelpPop
L2 primitives        button classes, IconButton, Trunc, Status, .tag, InfoTip, v-tip, AaSelect
L1 foundations       tokens in src/style.css; rules in docs/DESIGN_SYSTEM.md
```

Styles live in `src/style.css` (tokens, base, older components) and
`src/styles/{foundations,table,overlay,patterns,accounts,analysis-settings}.css`. Components carry no colours or sizes
of their own: they use tokens. No `<style scoped>` with hex colours or pixel font sizes in a view.

## Tokens these components rely on (`src/style.css`)

| Token | Value | Use |
| --- | --- | --- |
| `--h-xs … --h-xl` | 24 / 28 / 32 / 36 / 40 px | height of a control of that level: a button, an input, a select and a segmented control of one level are the same height |
| `--row-compact / -standard / -comfortable` | 40 / 56 / 64 px | DataTable row height (and `.rows > .r`) |
| `--fw-regular / -medium / -semibold / -bold` | 400 / 500 / 600 / 650 | weights; dense areas use medium for the primary line; bold only for a page title and large figures |
| `--z-sticky`, `--z-overlay`, `--z-drawer` | 20, 40, 41 | sticky bar, drawer veil, drawer |
| `--z-pop`, `--z-tip`, `--z-toast` | 60, 70, 80 | menu or popover, tooltip, toast |
| `--z-dialog`, `--z-select` | 90, 100 | a question (`ask`; its veil covers a toast too), the list of an `AaSelect` (it can open in any of the above) |
| `--dur-fast`, `--dur`, `--ease` | 120ms, 160ms | transitions; none under `prefers-reduced-motion` |
| `--tip-bg`, `--tip-fg` | reverse of the page | tooltip |

A box on `<body>` (tooltip, menu, popover) opened from inside a higher layer is lifted above that layer by
`zOver` (`src/float.js`); no page writes a `z-index` number.

Reduced motion: the global rule in `style.css` makes every style change a 0.01ms transition, i.e. one frame late. So a
floating box has `transition: none` (`.tip-box`, `.pop`, `.menu-pop` do), and one that is placed after it is drawn
stays unseen until placed with `opacity` (not `visibility`: it is inherited, and the children would then also become
visible a frame late and could not take the focus).

## Text (`Trunc.vue`, classes in `styles/foundations.css`)

| Kind of text | Rule |
| --- | --- |
| button, badge, short label, date, time, number | never wraps (`.atomic` / built into the component) |
| company, job title, site, file name | one line, cut with an ellipsis; the whole of it in an overflow tooltip |
| domain, e-mail, URL | one line, cut; never `word-break: break-all` on running text |
| description in a table | at most two lines |
| paragraph | wraps naturally |
| technical detail | not in a row: in a popover, a drawer or `TechDetails` |

- `<Trunc :text="s" />` - one line, ellipsis, tooltip **only when it is actually cut** (looked at when the tooltip is
  about to show, so a column made wider says nothing). Props: `text` (String), `lines` (Number, default 1; `2` and more
  use `.cut2`, a two-line clamp), `as` (tag, default `span`). With a slot, `text` is only what the tooltip says.
- Classes: `.cut` (one line; in a flex row or grid it also needs to be allowed to shrink - it has `min-width: 0`),
  `.cut2` (two lines), `.t-primary` (14px medium, `--text`), `.t-secondary` (13px, `--text-2`), `.t-meta` (12px,
  `--text-3`), `.num` (tabular figures), `.atomic` (no wrap), `.none` (the `—` where there is no value).
- Cutting is presentation only: the data is never shortened, and never by counting characters.
- Joined lists use `Intl.ListFormat` with the current language (`listed()` in Files, Todos, Welcome) - never a typed
  `、` or `, `. A sentence with a link or a strong part in it is `<i18n-t keypath="…" scope="global">` with named
  slots (`#link`, `#strong`) - never a sentence glued from pieces.

## Tooltip (`v-tip`, `src/tip.js`, `TipLayer.vue`, `InfoTip.vue`)

One tooltip for the whole program: one element, `#aa-tip.tip-box` (`role="tooltip"`), always in `<body>` and hidden
(`TipLayer.vue`); one set of listeners on the document. The browser's own (`title="…"`) is not used for anything a
person should read.

```html
<button v-tip="$t('accounts.showPassword')">…</button>          <!-- says what an icon does -->
<span class="cut" v-tip.overflow>{{ company }}</span>             <!-- only when cut; the element's own text -->
<span v-tip.overflow="fullText">…</span>                          <!-- only when cut; this text -->
<span v-tip="{ text, placement: 'bottom', max: 400 }">…</span>    <!-- placement: top (default) | bottom | left | right; max width px (320) -->
<span v-tip.press="text" tabindex="0">…</span>                    <!-- also shown and hidden by a press (a finger cannot hover) -->
<InfoTip :text="$t('jobs.scoreHelp')" />                          <!-- a small (i): hover, focus, or a press -->
```

- Hover: shows after 350ms of rest; once one was shown, the next shows at once (300ms); hides 100ms after leaving; the
  pointer can move into it and it stays (its words can be selected).
- Focus: shows at once, but **only when the focus was moved with the keyboard** (Tab, arrows, Home / End, Page keys) and
  the element is `:focus-visible` - not after a click, and not when a menu or drawer gives the focus back. Escape hides
  it; Enter / Space on the element it describes hides it (except `.press`).
- It flips and shifts to stay inside the window (`place` in `float.js`), follows its element while that moves, hides
  when the element leaves the window or the page scrolls (unless it shows for the keyboard). No animation under reduced
  motion.
- An empty or missing text shows nothing. While it shows, the element has `aria-describedby="aa-tip"` (added to any
  ids it already has).
- A tooltip holds a few words or a sentence. Several sentences, a list, a link, anything to press: `Popover` (or
  `HelpPop`, which chooses). A whole record: `SideDrawer` / a detail panel.
- `title` stays only where it is an accessible name the element has no other way to carry (an `<iframe>`). Never both
  `title` and `v-tip` on one element. `AaSelect` turns a `title` given to it into `v-tip` (and uses it as the name when
  there is no `aria-label`); prefer `aria-label` on it.
- `InfoTip` props: `text` (required), `label` (the button's name, default "More information"), `placement`. It is a
  `button.info-tip` (20px box, 16px glyph) with `v-tip.press`; its click does not reach the row around it.

## IconButton (`IconButton.vue`)

```html
<IconButton icon="eye" :label="$t('accounts.showPassword')" @click="reveal(a)" />
```

Props: `icon` (name in `Icon.vue`), `label` (required: the accessible name **and** the tooltip), `size` (`md` 28px,
default | `sm` 24px, still pressed within 28px), `tone` (`''` | `danger`), `pressed` (Boolean, for toggles: sets
`aria-pressed`), `loading`, `disabled`. Always square, never wraps. Loading puts the spinner where the glyph was
(same size, same place), sets `aria-busy`, and a press while loading does nothing.

## Buttons and what an action looks like

| Action | Looks like |
| --- | --- |
| the page's main action | `button.primary` (one per page head) |
| other page actions | `button` (secondary) |
| common light action in a row or card | `button.ghost.sm` or an `IconButton` |
| the one action in a table row that waits for the person (approve, sign in) | may be `button.sm.primary` - one per row, only where it is that row's point |
| rarely used | an item of a `Menu` |
| destructive | a `danger` item at the bottom of a `Menu`, confirmed with `ask(…, { danger: true })` |

Buttons never wrap (`white-space: nowrap` is in the base style). A group of actions is `<div class="actions">` (one
line, same height, 8px apart, `flex: none` children; a `<span class="grow">` in it pushes what follows to the end).
When there is not room for all, the secondary ones belong in a `Menu`, by decision - not by letting them wrap. Red is
not shown on every row: a row's delete lives in its menu.

## Menu (`Menu.vue`) and Popover (`Popover.vue`)

```html
<Menu :label="$t('common.more')" :items="[
  { id: 'clear', label: $t('accounts.clearSession'), icon: 'x', hint: $t('…') },
  { divider: true },
  { id: 'delete', label: $t('accounts.deleteAccount'), icon: 'trash', danger: true },
]" @pick="onPick" />
```

`Menu` props: `items` (`{ id, label, icon?, danger?, disabled?, hint? }`; `{ divider: true }` separates), `label`
(required: the trigger's name and tooltip, and the menu's name), `icon` (default `more`), `align` (`end` default |
`start`: which edges of trigger and menu line up), `placement` (`bottom` default | `top` | `left` | `right`), `size`
(`md` | `sm`, of the default trigger), `disabled`. Slot `trigger="{ open, toggle, attrs }"` replaces the default
`IconButton` - bind `attrs` (`aria-haspopup`, `aria-expanded`, `aria-controls`) to it. Emits `pick(id)`, `open`,
`close`; exposes `open()`, `close()`, `toggle()`. Keyboard: ArrowDown on the trigger opens; in the menu arrows,
Home / End (and Page keys), type-to-jump, Enter, Escape (closes this menu only, not the drawer under it), Tab closes;
the pointer and the keyboard move the same mark. Focus returns to the trigger; a press outside closes; the page
scrolling under it closes it. On `<body>`, placed by `float.js`. A press inside does not reach the row around it.

`Popover` props: `label` (the box's name), `placement` (`bottom` default | `top` | `left` | `right`), `align`
(`start` default | `center` | `end`), `width` (px, default 320; never wider than the window less 16px). Slots:
`trigger="{ open, toggle, attrs }"` (bind `attrs`), default `="{ close }"` (the content). Emits `open`, `close`;
exposes `open()`, `close()`, `toggle()` (a menu item can open a popover: `ProviderCard`). The focus goes to the content's
`[data-first]`, else its first control that is not an (i), else the box; Tab stays inside; Escape (unless a select in
it used it) and a press outside close it - a press in its own select list, a tooltip, or a menu / question opened from
it does not; the focus returns. It **follows its trigger** while the page scrolls, the window changes size or its
content grows. For help that is more than a sentence, and for small forms (a provider's sign-in settings).

Which layer for what: tooltip - a few words, nothing to press; popover - explanation or a light form; menu - choosing
an action; drawer / detail panel - a whole record; dialog (`ask`) - a decision that must be made; toast - what came of
an action.

## HelpPop (`HelpPop.vue`)

```html
<HelpPop :text="$t('analytics.cost.help')" :label="$t('analytics.cost.title')" />
<HelpPop :label="title"><p>…</p><ul>…</ul></HelpPop>
```

Help behind a small (i), whatever its length; the page does not choose. Props: `text`, `label` (what the help is
about: the popover's name), `width` (340), `placement` (`bottom`). It is an `InfoTip` (tooltip) when it has only a
`text` of at most about three tooltip lines (160 units, a full-width character counting two); it is a `Popover` from
the same-looking (i) when the text is longer or content is given in the slot (several paragraphs, a list, a link).
Nothing (no `text`, no slot) shows nothing.

## Tabs (`Tabs.vue`)

```html
<Tabs v-model="tab" :label="$t('todos.needsYou')" :items="[
  { id: 'all', label: $t('todos.all'), count: 12 },
  { id: 'login', label: $t('todos.signInOrVerify'), count: 0, disabled: true },
]" />
```

Which part of a page is shown. Props: `items` (`{ id, label, count?, disabled?, icon?, dot? }` - `icon` before the
label; `dot` marks a tab that holds changes not saved yet, said to a screen reader too), `modelValue` (the selected id),
`label` (required: the row's accessible name), `id` (tabs get ids `<id>-<item id>`, so a panel can say
`role="tabpanel" :aria-labelledby="'<id>-' + tab"`), `controls` (the panel's id: `aria-controls` on the selected tab).
Emits `update:modelValue`.

- It is a `.seg.tabs` (`role="tablist"`, buttons `role="tab"` with `aria-selected`): the look and height (`--h-md`) of
  a segmented control; `count` is a low-weight tabular figure after the label (`.n`), shown when it is not empty
  (`0` shows).
- Roving tabindex: one Tab stop (the selected tab, or the first usable one). ArrowLeft / ArrowRight (round the ends),
  Home, End move the focus **and select**; a disabled tab is passed over.
- One line, always: when longer than its place it scrolls sideways inside itself (no scroll bar; a wheel scrolls it;
  an edge with more tabs past it fades). The selected tab is brought into view when it changes - the row scrolls,
  never the page. In a flex row give it `min-width: 0` so it can be narrower than its tabs.
- Not for a filter that narrows one list by a value (that is a `.seg` of buttons with `aria-pressed`, or a select), and
  not for navigation between pages (`a.seg-link` with `aria-current="page"`, as Settings does).

## DataTable (`DataTable.vue`, `src/tablelayout.js`, cells in `components/cells/`)

```html
<DataTable :columns="cols" :rows="shown" row-key="id" density="comfortable" selectable v-model:selected="picked"
           v-model:sort="sort" clickable @row="open" :label="$t('applications.title')" :row-class="(r) => ({ late: r.late })">
  <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" :to="'/applications/' + row.id" /></template>
  <template #cell-date="{ row }"><DateTimeCell :primary="…" :secondary="…" /></template>
  <template #empty><EmptyState … /></template>
</DataTable>
```

Column: `{ id, header, width?, min?, max?, flex?, align?: 'start'|'center'|'end', priority?: Number, sortable?,
headerTip?, class? }`.

- **Fixed**: `width` (px). **Sharing**: every column without `width` takes part in sharing the room left after all
  minimums, by `flex` (**default 1**; `flex: 0` stays at its minimum), between `min` (default 64px) and `max` (default
  none). **Optional**: `priority` > 0 - while the minimums do not fit, the column with the highest number is hidden
  first (of equals, the later one); a column without `priority` is never hidden. If what must stay still does not fit,
  the table scrolls sideways inside its own box (the page never does).
- When every sharing column has reached its `max` and room is left, the table still fills its box: the columns that
  are not fixed **grow past their `max`** in proportion (all columns, when all are fixed). `max` is where sharing
  stops, not a hard limit.
- Widths are computed from the definitions and the box's width (`layoutColumns`, a pure, tested function) and written
  into a `<colgroup>` of a `table-layout: fixed` table: **no cell content can change a column's width**.
- The box takes its width from its place, never from its content (`.dt-scroll` is `contain: inline-size`): in a flex
  row the DataTable needs `flex: 1` (else it collapses); in a block or a grid cell it simply fills it.
- Props besides the above: `rows`, `rowKey` (a field name, default `id`, **or a function** `(row) => key`), `density`
  (`compact` 40px | `standard` 56px, default | `comfortable` 64px), `selectable` (a 40px checkbox column; Shift + press
  ticks a range; the header box ticks the rows shown), `selected` (`v-model:selected`, a `Set` of keys),
  `selectLabel` (`(row) => name` of its checkbox), `selectAllLabel`, `sort` (`v-model:sort`, `{ by, dir }`; the first
  press sorts ascending; sorting itself is the page's), `clickable` (`@row(row, event)` on a press or Enter, not from a
  link, button, input, `[data-row-stop]` in it, nor at the end of a text selection), `label` (the table's name),
  `expandedKey` + slot `expanded="{ row }"` (the one row opened on purpose, the only row that may be taller),
  `maxHeight` (px or CSS length: the body scrolls under the sticky header), `rowClass` (`(row) => class`).
- Every data row has the density's height; a cell cuts what does not fit (`overflow: hidden`, content centred
  vertically). Slots: `cell-<id>="{ row, index, column }"`, `head-<id>="{ column }"`, `empty`, `expanded`. A cell
  without a slot shows the value in a `Trunc`, or `—`.
- `class="bare"` takes the frame away (no border, radius, shadow or background): a table inside a card.
- What does not fit a row at all (a reason, a diagnosis, a mail's text) is not in the table: it is behind a status
  tooltip, a popover or the row's page.

Cells:

- `EntityCell` - `primary`, `secondary?`, `to?` (router link on the primary line; the link itself is what is cut, so
  its focus ring is around the words), slot `after` (a small mark after the primary line). Two lines, each cut on its
  own with an overflow tooltip; without `secondary` the primary line is centred. Company + title, site + host, name +
  e-mail, file + kind. (`.entity` also works outside a table: `.rows > .r > .entity`.)
- `DateTimeCell` - `primary` (the date or time, already formatted), `secondary?` (what it is, how far), `tone?`
  (`''|'warn'|'bad'|'muted'`), `tip?` (the whole thing, as a tooltip). Never wraps; no `primary` shows `—`.
- `CredentialCell` - the password of a site account; one layout in every state, so the column reads straight down.
  Props `saved`, `value` (the password **only while it is shown**, else `null`), `loading`; emits `reveal`, `hide`,
  `copy`, `add`. Saved: eight dots (`role="img"`, named "password saved") and an eye; shown: the value in `<code>`, cut,
  with copy and a crossed eye; not saved: the words and a plus. The value is never put into a tooltip, a name or a log.
- `Status` (primitive) - see below. Plain values: `<Trunc>`; nothing: `<span class="none">—</span>`.

## Status, badge, metadata

Three weights, in falling order - most things are the third:

1. `.tag` / `.tag.ok|warn|bad|info` and the calendar's `.ev-kind` - a state that matters to the business and must be
   seen: interview, assessment, overdue, failed, waiting for verification. `.tag` is `display: inline-block`, 20px,
   one line, cut with an ellipsis where its place is narrower. One filled thing per row.
2. `Status` - `tone` (`ok|warn|bad|info|''`), `label` (required), `tip?`: a 6px dot of the tone and the words (13px,
   `--text-2`, cut with an overflow tooltip); `tip` is a short reason behind a small focusable (i) (`v-tip.press`).
   The default in a dense table: `● Auto sign-in ready`, `● Session saved`.
3. `.meta` (`.meta.small`) - a plain attribute, no fill: Workday, Greenhouse, "registered by the program".

Colour is never the only sign (a dot has its words). Red is for danger, failure and what is overdue; green only for
what really succeeded - progress in hiring is not all green. The kinds of calendar items keep their `--ev-*` colours
everywhere they appear (`calendar.js FAMILY`, `views/calendar/look.js`).

## Heads and bars

- `PageHead` - `title` (required), `help?` (an `InfoTip` beside the title: what the page is for, only if it helps),
  `sub?` / slot `sub` (a line under the title: only what the reader must know to decide something here - most pages
  have none). Default slot: the page's actions, secondary first, the primary one last. The keyboard lands on its `h2`
  after a change of page.
  A title too long for its line is cut to one line with the whole of it in a tooltip (an application's company and
  position); a link back to the list the page belongs to sits under the title and names that list.
- `SectionHead` - `title`, `help?`, `count?`; default slot: the section's actions (at the right). Not used inside a card.
- `CardHead` - `title` (required; a `Trunc`, cut, never squeezed), `help?` (through `HelpPop`, so a sentence is a
  tooltip and more is a popover; or slot `help` for several paragraphs / a link), `note?` (a plain figure or fact after
  the title, `.meta.small`; slot `after` replaces it), default slot: the card's controls (`.card-tools`). When the
  controls leave the title too little room (under about 11em) they go under it as a group - by rule, not by where words
  break.
- Filters: `.filters` - search first, then the selects, the count at the end; rarely used conditions go behind a
  filter popover (as on the calendar), not in the bar.
- `BulkBar` - `count` (it shows when > 0), emits `clear`; default slot: the actions. It lies fixed over the bottom of
  the page's own area, centred, and moves nothing when it comes or goes (the page gets room to scroll its last rows
  clear of it). Says how many, then the actions, then "clear". Put it at the top level of a page - **never inside a box
  that is a size container (`container-type`) or has a `transform` / `filter`**: there `fixed` would mean that box.

## Forms

- `.fields` - a grid of fields (columns of at least 168px, as many as fit). Each field is `label.f` with the words
  above its control (`<label class="f">{{ $t('…') }}<input …></label>`); `.f.span2` takes two columns (one in a box
  under 420px), `.f.all` the whole row; a checkbox is `label.check` in the grid.
- `.kv` - the older two-column form of Settings (label left, control right); `src/labels.js` pairs its labels with
  controls. `.field` + `.hint` - a single field with a line of help under it (popover forms).
- Widths: `.w-full`; `input.w-num` / `.w-short` / `.w-mid` / `.w-long`; `textarea.prose` (writing),
  `textarea.editor` (`.tall`) with `.editor-preview`. A control has no width of its own otherwise.
- The buttons of a form: `<div class="actions form-acts">`, secondary first; `<span class="grow">` pushes the primary
  to the end. Errors of the last submit stay with the form: `run(…, { form })` + `<FormError name>`.
- `AaSelect` - used like `<select>` (`v-model`, `<option>`s in the slot), `small`, `disabled`, `placeholder`;
  `id`, `class`, `style`, `aria-label`, `aria-labelledby`, `aria-describedby` go to its button; keyboard like a native
  one; its list is on `<body>` at `--z-select`.
- Controls that say what a value means instead of asking for it as text (below; styles in `styles/controls.css`): a
  choice among many by name - `Combobox` (a time zone: `TimeZonePicker`); "this long before" offsets -
  `ReminderRules`; one on / off - `ToggleSwitch`; one of a few - `RadioList`; a setting with a name and one control - `SettingRow`. A time of day is `input type="time"`.
  Never a list of numbers or an id to type where one of these fits.

## Lists that are not tables

`.rows > .r` - fixed rows (`--row-standard`, `.rows.tight` = `--row-compact`) for short lists in cards: `.lead` (a
fixed 112px first part: a date, a figure), `.entity` (the main part, as in `EntityCell`), `.end` (the actions, at the
right). Anything with columns to compare, sort or tick is a `DataTable` (`class="bare"` in a card).

## ProviderCard (`ProviderCard.vue`, `styles/accounts.css`)

A sign-in provider on the accounts page. Props `provider` (`{ key, name, region, note, custom, email, session:
{ saved_at, valid_until, expired } | null }`), `state` (`''` | `'trying'` | why the last try failed), `backend`
(`''` | `playwright` | `nodriver`). Emits `login`, `forget`, `remove`, `save({ backend, email })`; it does nothing by
itself. One structure whatever is known, so cards side by side line up row by row: head (name, region, note behind an
(i), the session as a `Status`), three facts that are always there (`—` when empty), foot (one main action - primary
when there is no session - and a `Menu`: settings, forget the session, and for an added provider remove, `danger`). The
rarely set settings open in a `Popover` from the menu item.

## Dates, lists and messages

- One way to write a date (`src/i18n/format.js`): a day is "Nov 20" / "11月20日", with the year only when it is not this
  year; something scheduled (a deadline, an interview, a reminder) is the day and the time; something that happened (a
  mail, a run, a change) is relative while it is recent ("Today 13:52", "Yesterday 09:30"), then the day and the time.
  Short numeric dates ("11/20") are for chart axes only. A time the server gives as local wall-clock text (the
  calendar's items, a deadline) is read with `at()` from `src/calendar.js`, never through `asDate()` (which reads UTC).
- Several things in one sentence are joined with `listed()` (Intl.ListFormat), not with typed commas.
- A toast says what came of an action; while the `BulkBar` is shown, toasts rise above it - they never cover its buttons.
- Density: two-line entities are `comfortable`; one-line lists and tables inside cards are `standard`; logs and figure
  tables are `compact`. The compact figure tables of the analysis page (`.an-table`) keep their own markup: fixed
  columns, one-line headers (the long form in a tooltip), numbers right-aligned.

## Words

Every text a person reads is a key in `frontend/src/locales/` (see CONTRIBUTING). The words follow
`docs/ux-writing-glossary.md`: a title names the thing, a button is a verb, a state is a short phrase, a column header
names an attribute. Catalogs are changed with `python frontend/scripts/i18n-apply.py patch.json` (all languages and the
note at once).

## Combobox (`Combobox.vue`, search in `src/combobox.js`)

```html
<Combobox id="f-food" v-model="food" :label="$t('…')" :options="[{ value, label, hint?, group?, keywords?, disabled? }]"
          :groups="[{ id: 'fruit', label: $t('…') }]" :placeholder="$t('…')" :invalid="bad" />
```

A select you can search, for a list too long to scan (a time zone among 600). The trigger is an `AaSelect`'s (`.sel`,
`--h-md`): the chosen option's `label` and, muted, its `hint` on one line, cut at the end (the hint goes first), the
whole of it in an overflow tooltip. Pressing it - or ArrowDown, Enter, Space, a letter (which starts the search with
it) - opens a list on `<body>` (`.sel-pop`, `--z-select`, so a popover around it stays open and it lies over a drawer
or a question) with a search field at the top that has the focus. The list stays beside its trigger while the page
scrolls (it closes when the trigger leaves the window); it opens upwards when there is not room below.

Props: `modelValue`, `options`, `groups` (the order of the headings; options without a group, or with one not named
here, come first), `label` (required: the accessible name of the trigger - with the value - of the search field and of
the list), `placeholder` (the trigger when nothing is chosen), `invalid` (`aria-invalid`, the danger border),
`disabled`, `emptyText` (no option matches), `searchPlaceholder` (what can be typed, in the search field), `width`
(the list's; default the trigger's, at least 320, never wider than the window). Emits `update:modelValue`, `change`
(with the value), `open`, `close`; exposes `open()`, `close()`.

- A value that is not among the options is shown as itself in the trigger - never dropped or replaced.
- Search (`src/combobox.js`, tested): case- and accent-insensitive over `label`, `hint`, `value` and `keywords`; first
  the options whose label starts with it, then a whole word, the start of a word, anywhere, every word anywhere. The
  headings stay in their order and only where something matches; an option in two groups (a zone under Common and its
  region) is listed once while searching. An input method (Chinese) composing a word is not interrupted.
- Keyboard: ArrowUp / ArrowDown (round the ends), Home / End, PageUp / PageDown move the mark past disabled options and
  keep it in sight under the sticky heading; Enter picks; Escape closes without a change (and only the list: not the
  popover or drawer it is in); Tab closes and the focus moves on from the trigger. The pointer moves the same mark (on
  a move, not when the list scrolls under a still pointer). A press anywhere in the list leaves the focus in the search.
- ARIA: the trigger `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls`, named by `label` and the value; the
  search field `role="combobox"`, `aria-activedescendant`; the list `role="listbox"`; a group `role="group"` with
  `aria-label` (its visible heading is `aria-hidden`); options `role="option"` with `aria-selected`; how many match is
  said in a polite live region while searching.
- 600 options open in about 60 ms; nothing is virtualised.

When: a choice among many (more than about 15) that people find by name - a time zone, a country. A few options:
`AaSelect`. An action: `Menu`.

## TimeZonePicker (`TimeZonePicker.vue`, `src/timezones.js`)

```html
<label for="time-zone">{{ $t('settings.time.zone') }}</label>
<TimeZonePicker id="time-zone" v-model="s['time.zone']" :label="$t('settings.time.zone')" />
```

The time zone setting, on `Combobox`. It loads `GET /api/time/zones` itself, once per open page (again after an hour). The
value saved is the IANA id, `''` = follow the computer - never an offset. Props: `modelValue`, `label` (default
"Time zone"), `disabled`; `id` and other attributes go to the trigger. Emits `update:modelValue`, `change`.

- Options: first "Follow this computer" (`''`) with the computer's offset and zone as its hint; then *Common* (the
  computer's zone, the five chosen lately in this browser - `localStorage`, a per-viewer convenience - and a fixed list of
  widely used zones), the regions by the id's first part (Americas, Europe, Asia, Africa, Australia & Pacific, Atlantic,
  Indian Ocean, Antarctica & Arctic; each sorted by offset, then name), *Other names* (fixed offsets `Etc/…`, old
  spellings, names of no place such as `CET`).
- An option: label = the place in the interface language - the city (a catalog name for about 60 common cities,
  `tz.city.*`, else the id's last part with spaces, plus the state where the id has one: "Knox (Indiana)") and the
  country (`Intl.DisplayNames`, its short name unless that is an abbreviation; left out where it is the city: Hong
  Kong); `Etc/UTC` "Coordinated Universal Time", `Etc/GMT+5` "Fixed offset UTC−05:00"; an old spelling as written.
  Hint = `UTC−07:00 · America/Vancouver`; an old spelling's `UTC−08:00 · same as America/Los_Angeles`.
- Offsets are the server's (its own tzdata, now): British Columbia is UTC−07:00 all year since 2026, which an old
  browser's Intl data gets wrong, so no offset is ever worked out in the browser.
- Search: city in English and the interface language (and other cities on that clock: Beijing, Seattle, Montreal, …),
  country in both, IANA id, offset however typed ("+08", "UTC-7", "utc -7", "+5:30", "+0530", "GMT-8"), and the
  generic zone name from Intl ("Pacific Time", 北美太平洋时间 - worked out when the browser is idle).
- A saved old spelling (`US/Pacific`) works and is shown as written with what it stands for. A saved value that is not a
  zone (`chosen_valid: false`) is shown as itself, `invalid`, with a line under the field: it is not a time zone and the
  computer's zone is used until another is chosen. It is never replaced without the person choosing.

When: wherever a time zone is set. Not for showing a zone (that is text).

## ReminderRules (`ReminderRules.vue`, `src/reminders.js`)

```html
<ReminderRules v-model="s['calendar.reminders'].interview" :label="$t('calendar.kind.interview')" />
```

The reminders a kind of calendar item gets by itself. The value stays what the backend keeps: minutes before the item
(`[1440, 30]`; `0` = at the start; `[]` = none). Props: `modelValue`, `label` (what they are of: the group's name, and
the "+"'s "Add reminder: Interview"), `allDay` (an item of a whole day: reminded in the morning, whole days apart - "2
hours before" is the morning before, as `alarms.give_defaults` makes it), `disabled`. Emits `update:modelValue` and
`change` with the list normalised: whole minutes, each once, largest first.

- Chips (`.fchip.lg`, the words centred): "1 day before ×", "30 minutes before ×"; the × is an `IconButton` named
  "Remove reminder: 1 day before"; after a removal the focus goes to the next × (or the +). `[]` shows a muted
  "No reminder" and the +.
- + opens a `Popover`: the usual choices (At the start, 15 / 30 minutes, 1 / 2 hours, 1 / 2 days, 1 week; for a whole
  day only the start and whole days) as toggle buttons - one already chosen is shown pressed with a check, and pressing
  it again removes it; and a custom amount: a whole number, a unit (`AaSelect`: minutes / hours / days before) and Add
  (Enter in the field adds too). What cannot be added says why under it: not a whole number, below 0, more than 60 days
  (what `alarms.add` keeps and `PUT /api/settings` accepts), already there.
- The words of one reminder are `formatReminder(minutes, { allDay })` in `src/reminders.js` (tested), with the
  calendar's `calendar.alarm.*` wording: weeks, days, hours, else minutes; 0 "At the start" (a whole day: "Morning of
  the day").

When: a list of "this long before" offsets anywhere. A single time of day: `input type="time"`.

## ToggleSwitch (`ToggleSwitch.vue`)

```html
<ToggleSwitch id="quiet-on" v-model="s['notify.quiet'].on" :label="$t('settings.quiet.on')" />
<ToggleSwitch v-model="on" :aria-label="$t('…')" />        <!-- without words beside it -->
```

A setting that is on or off as a whole and takes effect as such (quiet hours on). A `button role="switch"` with
`aria-checked`; a track and knob from tokens, `--h-xs` tall (on: `--primary` with an `--on-primary` knob; off: a
`--text-3` outline and knob); Space and Enter flip it as they press any button. Props: `modelValue`, `label` (the words
beside it: its name, and a press on them flips it too), `disabled`. Attributes (`id`, `aria-label`, `aria-describedby`)
go to the button. Emits `update:modelValue`, `change`.

When: one on / off setting. Several independent options of one kind (which notifications): checkboxes in `.set-opts`.
A choice among several: `RadioList` / `.seg`.

## RadioList (`RadioList.vue`)

```html
<RadioList v-model="mode" name="update-mode" :label="$t('about.policy')" :options="[
  { value: 'off', label: $t('about.mode.off'), hint: $t('about.mode.offHow') },
  { value: 'auto', label: $t('about.mode.auto'), hint: $t('about.mode.autoHow'), disabled: true, reason: $t('about.mode.needsInstall') },
]" @change="save" />
```

A choice of one among a few, as a compact list of native radios - not cards. A `fieldset` named by its `legend` (the
`label`); one row per option, `--row-compact` (40px) high, no box or border of its own (a hover ground only): the
option's words in body text and, muted, its `hint` on the same line while it fits, under the words otherwise (a flex
row that wraps - nothing is measured). In a hint that wraps, the radio stands by the first line.

Props: `modelValue`, `options` (`{ value, label, hint?, disabled?, reason? }`; values may be strings, numbers or
booleans), `label` (required: the legend and the group's accessible name), `name` (the radios' name, made up when not
given), `disabled` (the whole list), `hideLabel` (the legend for a screen reader only, when a title right above already
says it). Emits `update:modelValue` and `change` (the new value) - only on a real change. Each radio is named by its
label (`aria-labelledby`) and described by its hint (`aria-describedby`), so a screen reader does not read the hint as
part of the name.

An option that cannot be chosen (`disabled`) is drawn muted and passed over by the keyboard; when it has a `reason`
(a few words: "Needs an installed copy") that is said **in place of its hint** (`.rl-hint.rl-reason`) and is what the
radio is described by - the person sees why, not an explanation of something they cannot pick. Without a `reason` the
hint stays. A list where every option the person could want is disabled is the wrong control: say why once instead.

Keyboard: native - Tab comes to the chosen radio (or the first when none is), the arrow keys move and choose, Space
chooses; a disabled option is passed over by the browser.

When: three to six options a person compares by their one-line explanations (an update mode, a policy). Two options
without explanations are a `ToggleSwitch` or a `.seg`; a long list or one that needs searching is an `AaSelect` /
`Combobox`. Never big cards for this.

Styles: `styles/controls.css`, with the other controls (the reason uses the hint's class: nothing of its own).
Lab: `/ui-lab?only=RadioList` (`views/lab/sections/54-RadioList.vue`: wide, in 320px, a checkout's update modes with
two disabled and their reason, a disabled option without one, numbers, a whole list disabled, a hidden legend).

## SettingRow (`SettingRow.vue`)

```html
<SettingRow :label="$t('about.channel')" for="u-channel">
  <AaSelect id="u-channel" v-model="channel">…</AaSelect>
</SettingRow>

<SettingRow v-slot="{ labelId, descId }" :label="$t('about.byItself')" :description="$t('about.privacyShort')">
  <RadioList v-model="mode" :label="$t('about.byItself')" hide-label :aria-labelledby="labelId" :aria-describedby="descId" :options="…" />
</SettingRow>
```

One setting as a row: what it is on the left - its name, an (i) when it needs one, a muted line under the name - and
the control on the right. The row draws nothing of its own (no box, no border, no hover); a list of them is a grid with
`row-gap: var(--s4)`, parted from other groups by a rule, not by cards.

Layout: a grid of two columns, the name's `minmax(9em, 15em)` and the control's the rest, `column-gap: var(--s6)`; the
two stand on one **baseline** - the name beside the first line of the control, whatever it is (a select's words, the
first option of a `RadioList`, a time field, a text field). The row is its own size container: in a box under 640px
the name stands above the control (one column, `row-gap: var(--s2)`). Nothing is measured; nothing has a fixed height.

Props: `label` (required: the setting's name, `--fs-md` medium), `for` (the id of the control it names: the name is
then a `<label for>`, and a press on it reaches the control), `help` (an (i) beside the name, through `HelpPop`: a
sentence is a tooltip, more a popover), `description` (one muted line under the name, `--fs-xs`; or the slot
`description`). Default slot: the control, with the slot props `labelId` (the name's id) and `descId` (the
description's id, `undefined` when there is none) - for a control that is not one element `for` can point at: a
`RadioList` (`fieldset`) takes `aria-labelledby="labelId"` (and `hide-label`, so the legend is not shown twice), a pair
of time fields sits in a `role="group"` named by `labelId`, and anything the description explains takes
`aria-describedby="descId"`. No events: the control's own `v-model` / `change` do the work.

Keyboard: nothing of its own - Tab goes to the (i) when there is one, then into the control.

When: a setting with a name and one control - settings pages, a card of options. Not for a form that is filled in and
sent with a button (that is `.fields` with `label.f`), not for facts that are only read (a `dl`; the about page's facts
use the same two columns, so they line up with the settings below them).

Styles: `styles/controls.css` ("SettingRow"), with the other controls (`.sr-control .rl-text { align-self: baseline }`
makes a RadioList's first baseline its first option's words).
Lab: `/ui-lab?only=SettingRow` (`views/lab/sections/57-SettingRow.vue`: a list of radios, a select with help, two
times, a switch, a text field - wide, and in a box of 480px).

## The about overview (`views/AboutView.vue`, `views/about/Overview*.vue`, `Update*.vue`, `styles/about.css`)

```
[logo] AutoApply
       v2.0.0 · Running from source (i)
[Source code] [Releases] [Report an issue] [License]

┌ Software update ─────────────────────────────── [New version available] ┐
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │     Current version          →          Latest version               │ │
│ │          2.0.0                               2.0.2                   │ │
│ │                                         Released Nov 22              │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ Last checked  Today 13:27                                                │
│ [Check for updates] [What's new in 2.0.2]                                │
│ This copy runs from source and is updated by hand.  See the steps        │
├──────────────────────────────────────────────────────────────────────────┤
│ Update policy            Notify only                          [Change]   │
│ Channel                  Stable releases                                  │
├──────────────────────────────────────────────────────────────────────────┤
│ › Advanced                                                               │
└──────────────────────────────────────────────────────────────────────────┘
```

**One column of reading width**: `.about-overview` is at most **880px**, at the page's left; the rest of a wide window
is the page's margin (no card wider than the column, nothing stretched to fill it). The only two things side by side
are the two versions, which hold the same (a name, a number, a line) and are as tall as each other.

1. **The head** (`OverviewHead.vue`), a compact block without a card: the mark (`logo-mark.svg`, 48px, on
   `--logo-tile`; the one logo of the block) and "AutoApply" (`--fs-xl`, semibold); under the name one line, `--fs-sm`:
   the version that runs ("v2.0.0", `about.vVersion`; a build of one's own "v2.0.2 (local build, Nov 23)" - its folder's
   name is under Advanced, never here) · how this copy runs, with an (i) saying what that means for updates
   (`about.kindTip.*`). Under both, the project's links from `update.repo` - Source code, Releases, Report an issue,
   License - as a row of `a.btn.sm` (a `nav` named "Project links"), wrapping on a phone. No paragraphs.
2. **"Software update"**, one card (`UpdateSection.vue`, `section.card.up-sec` named by its title), its parts one
   under the other, each after a rule across the whole card:
   1. *The state* (`UpdateStatus.vue`) - the card's centre:
      - the head: `CardHead` "Software update" with the state as a **badge** at its end (`.tag` of the state's tone:
        "Up to date" ok, "New version available" info, "Ready to switch" ok, "Switching" warn, "… failed" bad, "Not
        checked yet" neutral; a spinner before it while something goes on; `role="status"`, so a change is said). For a
        copy that does not update itself the badge says what the look found.
      - **the two versions** (`.up-cmp`, on `--surface-2`, `--r-md`): "Current version" and the version that runs, and
        the release the state is about - "Latest version", "Prepared" (ready, a failed switch) or "Switching to" -
        each centred in its half, the number at `--fs-2xl`, a line under it ("Released Nov 22" - GitHub's day, known
        for the newest out; "Local build, Nov 23"; a "Pre-release" tag). An arrow (`forward`, primary) between them
        and the right number in the primary colour only when it is ahead (or a switch is under way); "None found"
        when the channel has no release, "—" before the first check. Downloading / preparing: a progress bar (and the
        percentage) across the panel under them.
      - under the panel: the state's one line (an error in `--bad`, what preparing or a switch does) and a notice (a
        failed check beside a known state, `--warn`); then the other facts on one quiet wrapping line (`dl.up-more`:
        a newer release than the one prepared, next start (i), switch when idle (i), previous release, last checked) -
        a fact the two versions already show is not repeated.
      - **the actions** the state allows (`model.actions`), the main one last and `primary`, with **What's new in X**
        (`a.btn` / `RouterLink.btn`) right after the check - a link to X's entry in this copy's changelog, else to its
        release page; the (i) on how a switch works stays with the last action when the row wraps. A copy run from source
        or in a container gets **Check for updates** and **What's new** only, and one line "This copy runs from source and
        is updated by hand." with **See the steps** - a `Popover` (`UpdateSteps.vue`: where to run them, the commands in a
        `pre` with a copy button) - never a button that pretends to install or switch. A copy started by hand with a
        prepared release says that the switch needs the tray app.
   2. *The update settings* (`UpdateSettings.vue`), **a summary first**: `dl.up-sum` in SettingRow's two columns
      (one column under 640px of it) - **Update policy** "Notify only" with **Change** (`button.sm`, named "Change update
      policy") at the row's end, **Channel** "Stable releases", and for "Update automatically" only **Automatic switch
      window** "03:00 – 05:00". **Change** puts a compact editor in the summary's place (a `form`, `SettingRow`s): the
      modes as a `RadioList` (the privacy line "Checking only asks GitHub for its list of releases; nothing about you is
      sent" under the name, visible where the choice is made; the modes this copy cannot use disabled with the reason -
      a checkout or a container: "Needs an installed copy" on Download automatically and Update automatically), as soon
      as "Download automatically" or "Update automatically" is chosen a `.callout.warn` under the list saying what it
      does by itself (downloads and installs into the data folder, network and disk; restarts into a new version
      without asking, in the window, when idle; a copy started by hand: the switch needs the tray app), the channel
      (`AaSelect`), and the switch window (two `input type="time"` in a group, "This computer's clock.") only while
      "Update automatically" is chosen; **Cancel** and **Save** (primary) at its end. Nothing is saved before Save; Save
      sends only what changed, in one `PUT /api/settings` (`update.mode`, `update.channel`, `update.window` - the window
      only with the automatic mode and only whole), the page shows the new values at once and says "Saved", then reads
      the state again; a refused save keeps the editor open with the error said. Cancel and Escape close it unchanged.
      The focus goes to the chosen mode when it opens and back to **Change** when it closes.
   3. *Advanced* (`UpdateAdvanced.vue`), a controlled disclosure (`button` with `aria-expanded` / `aria-controls`),
      closed on every load - the page holds its state (a refresh, or the Changelog tab and back, closes it; it is not in
      the address). In it, one under the other: **Runtime details** (Python, system, how it runs, the data folder with a
      copy button, the commit or the release folder with its build day, in SettingRow's two columns) with **Copy
      diagnostics** (and its (i)); **Manual update** (a checkout or a container: `UpdateSteps`, as See the steps shows
      it); **How updates work** (what is sent where, how a switch works, what idle means).
   Text keeps a reading width (`72ch`); no fixed heights, nothing stretched to fill a gap.
3. Narrow (the card under 480px): the versions' panel takes less padding; their lines wrap evenly (`text-wrap:
   balance`). Under 640px of their box the summary, the editor's rows and the runtime details put their names above
   their values.

What the page does (`AboutView.vue`): reads `/about` and `/system/update`, asks again every 2 s (3 s while switching)
while something goes on by itself, does the actions (check, prepare, switch / roll back after `ask`), saves the update
settings (`savePolicy(changes)`: one `PUT /settings`, the state patched at once, then read again; truthy once saved),
and - only when a newer version is known - reads `/about/changelog` once to know which versions this copy's changelog
has (for "What's new"). The tabs are in the path (`/about`, `/about/changelog`, `/about/licenses`).

Components: `UpdateSection` (`model`, `about`, `status`, `changelog`, `save`; emits `act`), `UpdateStatus` (`model`,
`changelog`; emits `act`), `UpdateSettings` (`policy`, `kind`, `save` - a function `(changes) => truthy once saved`,
so the editor stays open when the save is refused), `UpdateAdvanced` (`v-model:open`, `about`, `status`),
`UpdateSteps` (`kind`: `source` | `container`).

Lab: `/ui-lab?only=UpdateStates` - the whole card in the page's 880px column for a state chosen from a select (its
settings are said, not saved; the editor works), and the state part of every state - the demo runs from source, so
the managed states (download, prepare, switch, roll back, the window) are seen there.

## The update state model (`src/updatestate.js`)

The about page's updates follow one pure function, `updateState(status, { checking })`, over what
`GET /api/system/update` (`updates.status()`) says. It returns `{ id, found, tone, kind, target, progress, error,
notice, how, facts, compare, actions, notes, follow, policy }`; the page only turns ids into words (`about.state.*` - a
short phrase, the badge -, `about.fact.*`, `ERRORS[code].key`). Tested in `frontend/tests/update-state.test.js`; every
state is in the lab (`/ui-lab?only=UpdateStates`, `views/lab/sections/56-UpdateStates.vue`, drawn with the page's own
`UpdateSection` and `UpdateStatus`) - the demo runs from source, so the managed states are only seen there.

| `id` | When | Actions offered (the main one last, `primary`) |
| --- | --- | --- |
| `unsupported` | a source checkout or a container (`how`: how it is updated; `found`: unchecked / current / newer / failed) | check |
| `unchecked` | never looked | check |
| `checking` | the page's own check is under way | - |
| `current` | looked, nothing newer | check (+ roll back) |
| `newer` | a newer release is out | check, (roll back), **download and prepare** |
| `downloading` | fetching it (`progress` 0-100) | - (followed) |
| `preparing` | unpacking it, installing what it needs | - (followed) |
| `ready` | a newer release is prepared (`target`) | check, (roll back), (prepare a still newer one), **switch** - a copy started by hand: no switch, `how: 'unmanaged'` |
| `switching` | a switch was asked for; the tray restarts into it | - (followed; no answer while it restarts is expected) |
| `failed` | `error.stage`: check (`no-repo`, `network:*`), prepare (`checksum`, `incomplete`, `interrupted`, `no-package`, `no-uv`, `not-here`, an exception's name), switch (`did-not-start`) | **retry** of that step where it can help (not for `no-package`, `no-uv`, `not-here`, `no-repo`), check, (roll back) |

Rules: only what `updates.py` can do is offered - preparing needs a managed or hand-started copy, a switch and a
roll-back need the tray (`kind: "managed"`); nothing is offered while something goes on; a prepared release that is
not newer than what runs is not offered (checked by its own version too, `staged_release.version`); a release already
there (prepared, or kept from before a roll-back) is switched to, not fetched again. Going back is an action, not a
state: offered wherever nothing goes on while the previous release is still kept; after a roll-back the kept release is
the newer one and the action says "Switch back to". A failed check while a newer release is known keeps the state and
says the failure beside it (`notice`).

Facts (`facts`, in this order, each only when known): running (a local build with its day), latest release (its day,
pre-release), prepared, switching to / next start (`data/run/next-release`), switch when idle (asked from a
notification), previous release, last checked. `policy`: mode, channel, window (shown only for `auto`), and which modes
a copy can use (`modes: [{ value, disabled, reason }]` - a checkout or a container: off and notify; `reason: 'install'`
on the two it cannot use, which the page says as "Needs an installed copy").

Presentation (`compare`, nothing the state depends on): the two versions the overview sets side by side -
`from` (the running fact: `{ version, release }`, the release only for a build of one's own), `to` (`{ id, release,
known }`: `switching` while a switch is under way, `staged` when ready or after a failed switch, else `latest` - the
newest out, `null` when none is known; `known`: a check has said something), `moves` (the right one is ahead, or a
switch is under way: the arrow), and `others` (the facts said beside them, without the running one, the one on the
right, or another naming the same release).

Names: a release is never shown by its folder name. `releaseText(rel, t, day)` reads `{ name, version, date, local }`
(from `updates.release()`): "2.0.3", or "2.0.2 (local build, Nov 22)" for a folder put there by hand. An action names
the version alone unless it is the version that runs (`actionTarget`): "Roll back to 2.0.2 (local build, Nov 22)" when
2.0.2 runs, "Switch to 2.0.3" otherwise. Under a number in the overview a release says its day: "Released Nov 22" for
the newest out (GitHub's `published`; a release fetched here borrows it when it is that version - its own `date` is the
day it was unpacked), "Local build, Nov 22" for a folder put there by hand.

Server fields added for it (`updates.status()`; nothing removed or changed): `staged_release`, `previous_release`,
`build` + `build_release` (the folder of data/releases this copy runs from), `switching_to` + `switching_release`,
`pending` + `pending_release` (what the tray starts at its next restart), `when_idle`. `GET /api/about` adds `build`
and `build_release`.

What's new: the overview never shows a release's notes. `whatsNew(notes, versions)` says where "What's new in X" leads -
X's entry in this copy's own changelog (`/about/changelog?v=X`, the changelog opens it) when `GET /about/changelog`
lists X (a checkout that is behind), else the release's page (`notes.url`, on GitHub); `null` when there is neither.
A version that came out after this copy was built is in no changelog of its own, so for an installed copy it is
usually the release page.

## Changelog timeline (`views/about/ChangelogTab.vue`, `ChangelogPanel.vue`, `ChangelogNotes.vue`, `src/changelog.js`, `styles/changelog.css`)

```html
<ChangelogTab :version="about.version" />                         <!-- the about page's Changelog tab: reads /api/about/changelog itself -->
<ChangelogTab :data="{ current, versions }" :address="false" />   <!-- the lab: made-up versions, no deep link read -->
```

Every release on one vertical line, newest first, one row each - not a markdown file, not a card per release, and
nothing open until it is asked for. Props: `version` (the running version; default: `current` from the server), `data`
(`{ current, versions }` in place of the request - the lab only), `address` (default `true`: a deep link `?v=` opens
its version once). Emits nothing.

**The data** (`GET /api/about/changelog` -> `{ current, repo, versions }`; `backend/autoapply/changelog.py`
`versions()`). The adapter of the release model (docs/release-architecture.md) - no parsing of CHANGELOG.md, no
highlights.json, nothing from the network:

- *Released versions*: `backend/autoapply/releases.json` (generated by `python scripts/release.py generate` from
  `changes/`, tracked and shipped), read once per change of the file (mtime and size), passed on as written plus
  `unreleased: false`, in the file's order (newest first). A missing or unreadable file gives no releases (said in the
  log), never an error for the page.
- *Unreleased*: `autoapply.release.pending_entry()` - the pending change fragments of a source checkout - imported
  lazily and guarded: missing, failing or with nothing pending, there is no Unreleased entry (a release package never
  has one). When there is one it comes first, `unreleased: true`.
- Each version: `{ version, date, title: { en, zh?, fr? }, intro, known_limits: [md], url, changes: [{ id, type, scope,
  summary: { en, zh?, fr? }, details: md, highlight }], unreleased }`. `type` is `added | changed | deprecated |
  removed | fixed | security`; `changes` are in the release's (manifest) order. Summaries are one line, written in every
  language at development time; intro, details and known limits are English. The pending entry has `title: {}`,
  `date: ""`, `url: ""`.

**How it looks.** A grid per row: the date (month and day; the year is the label above its run) | the line with the
version's node | `v2.0.2` | its title in the interface language (muted, one line, cut with the whole in a tooltip) and
the tags `Latest` (the newest release, `.tag`) and `Current` (the running version, `.tag.info`) | the chevron at the
right edge. The date, node and chevron columns are fixed (`--cl-date`, `--cl-rail`, `--cl-chev`), so nodes and
chevrons stand in one line whatever the words; titles start at one place. Rows are `--h-lg`; no counts, summaries or
index in a row. Nodes: hollow = closed, filled = open, `--primary` with a halo = the running version. What opens under a
row is held to 72ch. Under 560px of box the columns get narrower; nothing moves under anything else.

- **English fallback**: a title or summary without the interface language is shown in English with `lang="en"` and a
  quiet `.cl-en` mark after it ("英文" / "anglais"; never shown in English).
- **Opened**: at most six changes (`changelog.js SHOWN`) - the release's highlights first, then the rest, each in
  release order (`pick`) - grouped by type in the order added, changed, deprecated, removed, fixed, security
  (`byType`; a light label with the type's dot, `TONE`), one summary a line (inline markdown rendered by md.js). Then
  *View the full release notes* (`button.sm`, `aria-haspopup="dialog"`), "n more in the full notes" when there are
  more, and the release page on GitHub. A version with no change says "No changes are recorded for this version."
- **The full notes** (`ChangelogNotes.vue`): a `SideDrawer` titled "Release notes 2.0.2" with the date - the intro
  (md), a section per type (heading with its dot and a rule), each change its summary in bold (interface language,
  English fallback marked) and its details (md, `lang="en"`), then *Known limits* (md list); the release page link at
  the top. In zh / fr one muted line says the details are written in English. Everything comes from the data already
  loaded: it works offline (only the link needs the network). Never cut.
- **Unreleased changes**: a block of its own above the line - a dashed edge, no node, no date - labelled "Unreleased
  changes"; part of the same accordion, closed on entry like the rest, opened like a version.

**The accordion.** One version open at most (`open` = a version or null, in the component). On entry every version is
closed - the newest, the running one and Unreleased too. A press on a row (the whole row is a `button.cl-row`,
`aria-expanded` = what is open, `aria-controls` its panel's slot) opens it and closes the one that was open; a press
on the open one closes it (`toggled`); the focus stays on the row, and the page follows when the one above closing
would move it. **A press does not write the address.** Not native `details`. The panel grows with a `--dur` height
transition (a grid row 0fr -> 1fr); under `prefers-reduced-motion` it is there at once.

**Deep link.** `/about/changelog?v=2.0.2` (the overview's "What's new in X", a link from elsewhere; `v2.0.2` and
`unreleased` work too) opens that version once it is loaded, scrolls it into view (the focus is not moved), and takes
`v` out of the address at once with `router.replace` (the rest of the query kept) - `arrival()` in changelog.js. So a
refresh, back to it, or another tab and back show everything closed; a link followed while the tab is open works the
same. A version the changelog does not have opens nothing and says so (`.callout.warn`, until the next press).

**Finding.** One search (every word, without case or accents, over the summaries in the interface language and in
English, the details, release titles, intros and known limits; a version number shows that version's changes; a title
with the words shows its changes when none match by themselves; the words found are marked, in the drawer too) and one
type filter: a `Menu` from a "Type" button listing *All types* and every type the changelog has, each with how many
changes of it there are under the search (none: disabled); the chosen one is checked and shown as one removable chip
(`.fchip.lg`, its × named "Remove filter: Fixed"). While filtering, the count of versions stands by the search
(`role="status"`); an opened version shows its matching changes (at most six, highlights first) and "n more in the
full notes" (or, when only the intro or a known limit matches, "n matches in the full notes"). Nothing found:
`EmptyState` with *Clear filters*. **A search or a type never opens or closes anything**; no "Expand all", no list of
versions beside the line, no jump select - a deep link is the way to a version.

**Keyboard.** Tab: the search, the Type button (ArrowDown / Enter opens the menu: arrows, Enter, Escape), the chip's ×,
then each row (Enter / Space open and close it) and, in the open one, *View the full release notes* and the link. The
drawer holds the focus and gives it back to its button; Escape closes it.

**When to use.** For the release model's data only (releases.json and the pending fragments). "What's new in X"
elsewhere links to `/about/changelog?v=X`; release notes fetched from GitHub for an update that is not installed are
the overview's.

## Licences (`views/about/LicensesTab.vue`, `backend/autoapply/licenses.py`)

```html
<LicensesTab />      <!-- the about page's Licenses tab: reads /api/about/licenses itself -->
```

The components the program runs on, as a `DataTable` (compact; Name, Version, License - sortable; Dependency, given
up first on a narrow box), a search (name, licence, summary), a `.seg` "All components / Direct dependencies" and a
licence `AaSelect` (as the packages write it, most common first). A row (press or Enter) opens a `SideDrawer`:
summary, version, licence, direct or not, project page, the licence file(s) and the text in a `pre`; "This package
carries no license text" when it has none. A line under the table says where the list comes from.

**The data.** `GET /api/about/licenses` -> `{ components: [{ name, version, license, direct, summary, homepage }] }`:
the program's declared dependencies (`pyproject.toml` beside the program, else its package's metadata, else the fixed
list that was in `about.py`) and, recursively, theirs as far as they are installed (markers and extras honoured),
sorted by name; `license` from `License-Expression`, else a short `License`, else the classifiers.
`GET /api/about/licenses/{name}` -> `{ name, version, license, text, file, files }` from the package's own
`LICENSE* / LICENCE* / COPYING* / NOTICE*` files (in its `.dist-info`, or at the top of the package; several joined
with a heading each) or the whole licence written in its metadata; `text` "" when there is none; 404 for any name not
in the list (any spelling of a listed name works; nothing is looked up from a path).

## Composing the analysis page (`views/analytics/layout.js`, `styles/analysis-settings.css`)

How the cards of Analytics are put together. Nothing here is a shared component: these are the analysis page's own rules,
written down so that a new card follows them.

```js
import { H, bars, pairs, reasons, splitTop, standing, table } from './layout'

// two cards share a row only when they hold about as much
const paired = computed(() => pairs(bars(d.by_channel.length), bars(d.by_direction.length)))
```

```html
<div class="an-row" :class="{ c11: paired }">   <!-- no column class: each card takes the whole row -->
  <div class="card">…</div>
  <div class="card">…</div>
</div>
```

**Rules**

1. A row of cards is `.an-row`; its columns (`.c11` one to one, `.c32` three to two, `.c21` two to one, `.c23` two to
   three - in fact 5 : 7) are given **only when the two cards pair**. Without a column class the cards stand one under
   the other, each the whole width. A row never stretches a short card far past what it holds beside a tall one, and
   never shortens it to end halfway down the row (`align-items: start` is not the fix).
2. Whether two cards pair is decided from the data: `pairs(a, b)` is true when the shorter card's estimated height is at
   least `LEAST` (0.7) of the taller's - at most about a third empty. Estimates come from what the card holds:
   `bars(n, { foot })` (rows of `.hbars`), `reasons(n, { foot })` (rows of `.reason`), `table(n, { row, foot, extra })`
   (a compact table: `row` is `H.row` 40, `H.row2` 52 for two-line rows, `H.entity` 56 for a DataTable of the standard
   density). `H` holds the measured heights of the parts (card head 64, foot with a button 44, foot with a hint 32, …);
   they decide pairing only and need to be right to about a tenth. A chart has a fixed estimate in its panel.
3. Two cards pair only when they are of one kind: two tables, two bar lists, a chart and a summary of the same thing.
   A table beside a block of figures, or figures beside a list, each take a row (AI cost: cost per result, then what
   failures and repeats cost).
4. A group of figures that belongs to a card is **one card of plain figures**: `<div class="kpis inline">` with
   `<Kpi>`s - no border, background or shadow per figure, a smaller number (`--fs-xl`) than the panel's headline tiles,
   four columns of one width (two figures stand at the left as four do), two under a 700px page, one under 420px. Never
   bordered tiles inside a card. A short list may follow the figures in the same card (`.kpis.inline + .rows`).
5. A ranked list shows its first five rows (six when that is all - a control never hides a single row:
   `splitTop(rows, 5)` → `{ shown, rest }`); the rest is behind a `button.ghost.sm` in the card's foot that opens a
   `Popover` with the same table, so the card does not grow and its row does not change.
6. A list that has nothing in it is not drawn when a figure elsewhere says 0 (no open to-dos: the figure says 0, the
   list is left out). Inside a card that must stay, nothing is one line: `<EmptyState class="line" …>` (icon, title and
   at most one short text on one line), not a box-sized empty state.
7. When a paired row becomes one column (`.solo`), a card marked `.an-later` goes after the chart's own table
   (`.an-detail`), so the table opens right under its chart.

**`standing(item, today)`** - where an open to-do stands, for a list: `{ key, tone, day }` with `key` one of `snoozed`
(put off until `day`), `datePassed` / `on` (a date of its own: an interview, an assessment; `warn` within a day),
`closed` / `closes` (the deadline of the posting it is about; `warn` within three days), `open`. The words are
`analytics.backlog.st.<key>` with `{day}` formatted by `dayText`.

**The Outcomes tab, below the cohort figures** (`views/analytics/Pace.vue`):

1. *Pace and to-dos* - one card of four plain figures: posting found → first record (median, with how many waited more
   than three days), application started → first record (median), open to-dos (the oldest one's wait, how many are
   snoozed), to-dos handled in the period (median wait).
2. *To-dos handled, by kind* (`DataTable` bare, compact: kind, handled, median wait; first five, the rest in a popover)
   beside *Longest-waiting to-dos* (`DataTable` bare, standard: `EntityCell` title → `/todos` with the kind and the
   posting under it, a `Status` from `standing`, how long; *View all n* → `/todos` in the head) - side by side when
   `pairs` says so (5 : 7), one under the other below a 900px page or when they differ.
3. The postings missed, on a row of their own.

Backend (`analytics._backlog`, additive): `by_kind[].kinds` (the card kinds a row stands for: `login` + `takeover` are
one "Sign in to a site"), `snoozed` (open to-dos put off now), and per `oldest[]` item `kind_key`, `created_at`,
`due_at`, `date_only`, `snoozed_until` (only while snoozed), `job_id`, `company`, `job_title`, `deadline` (the posting
found from the card's payload or reference: posting, record or application).

## The UI lab

`/ui-lab` (not in the navigation) shows every shared component in its states with made-up data; a section is a file
in `frontend/src/views/lab/sections/` (`NN-Name.vue`; `?only=Name,Other` shows some, `?narrow=480` narrows the page).
A new shared component gets a section. The layout tests (`tests/test_ui_layout.py`) and the source rules
(`frontend/tests/ui-rules.test.js`) look at the lab and the source; see `docs/ui-quality-assurance.md`.

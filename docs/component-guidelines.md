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

Which part of a page is shown. Props: `items` (`{ id, label, count?, disabled? }`), `modelValue` (the selected id),
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

## Words

Every text a person reads is a key in `frontend/src/locales/` (see CONTRIBUTING). The words follow
`docs/ux-writing-glossary.md`: a title names the thing, a button is a verb, a state is a short phrase, a column header
names an attribute. Catalogs are changed with `python frontend/scripts/i18n-apply.py patch.json` (all languages and the
note at once).

## The UI lab

`/ui-lab` (not in the navigation) shows every shared component in its states with made-up data; a section is a file
in `frontend/src/views/lab/sections/` (`NN-Name.vue`; `?only=Name,Other` shows some, `?narrow=480` narrows the page).
A new shared component gets a section. The layout tests (`tests/test_ui_layout.py`) and the source rules
(`frontend/tests/ui-rules.test.js`) look at the lab and the source; see `docs/ui-quality-assurance.md`.

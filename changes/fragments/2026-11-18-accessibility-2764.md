---
id: 2026-11-18-accessibility-2764
type: fixed
scope: ui
summary:
  en: "Narrow screens, contrast in both themes, the keyboard and screen readers"
  zh: "窄屏、两种主题下的对比度、键盘和读屏软件"
  fr: "Écrans étroits, contraste dans les deux thèmes, clavier et lecteurs d’écran"
---

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
- What a figure counts can be opened with a click, a tap or the keyboard; it was a tooltip, there for a mouse only.

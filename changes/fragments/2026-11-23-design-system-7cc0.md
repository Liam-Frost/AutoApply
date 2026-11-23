---
id: 2026-11-23-design-system-7cc0
type: changed
scope: ui
summary:
  en: "One design for every page: tables, buttons, tooltips and menus behave the same everywhere"
  zh: "所有页面统一设计：表格、按钮、提示和菜单在各页的表现一致"
  fr: "Une même conception pour toutes les pages : tableaux, boutons, infobulles et menus partout pareils"
highlight: true
pr: 125
---

- **One design system for the whole interface.** Every page is rebuilt from the same shared pieces, so content no
  longer decides layout. Lists are one kind of table: a column's width comes from its definition, never from the
  longest value in it, every row has the same height, long names are cut with the whole text in a tooltip, and the
  less important columns give way first when the window is narrow - the page itself never scrolls sideways. Buttons,
  fields, selects and tabs of one level are the same height everywhere; an icon alone always has a name; rarely used
  and destructive actions live in a row's menu instead of a red button on every row. The browser's own tooltips are
  gone: one tooltip, one menu and one popover, with the keyboard, in both themes.
- Documentation for contributors: `docs/component-guidelines.md`, `docs/ux-writing-glossary.md`,
  `docs/ui-quality-assurance.md`, `docs/ui-ux-audit.md`; a UI lab at `/ui-lab` shows every shared component in its
  states.

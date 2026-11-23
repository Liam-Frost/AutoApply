---
id: 2026-11-23-menus-confirm-selects-dfab
type: fixed
scope: ui
summary:
  en: "Menus stay open after a scroll, dangerous batch actions are confirmed, select arrows are the right size"
  zh: "滚动后菜单不再立即关闭，危险的批量操作需要确认，下拉框箭头大小正确"
  fr: "Les menus restent ouverts après un défilement, les actions groupées dangereuses sont confirmées, les flèches des listes ont la bonne taille"
pr: [125, 127]
---

- A row's menu could close the moment it opened when it was pressed right after scrolling.
- Deleting several files for good is asked about as the dangerous thing it is; so is withdrawing several applications.
- A select with nothing chosen yet had an arrow three times too big.

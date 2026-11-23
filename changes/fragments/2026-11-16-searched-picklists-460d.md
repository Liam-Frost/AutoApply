---
id: 2026-11-16-searched-picklists-460d
type: fixed
scope: agent
summary:
  en: "A pick-list that has to be searched is searched the way a person does it"
  zh: "需要搜索的下拉列表会像人一样逐键输入搜索"
  fr: "Une liste à rechercher est cherchée comme le ferait une personne"
---

A pick-list that has to be searched (a location or school picker that shows a few entries and a search box) is
searched the way a person does it: the search is typed key by key into whatever the list takes typing in, and the
entry that is the wanted one is chosen - "Vancouver, Canada" for "Vancouver, BC, Canada", never a guess between two
that fit. Before, the search box's value was set by program, which such lists ignore (some close), so the driver
failed and the agent - which did try to search - had no tool that could type; the field came back to you on every
run. The agent also has a plain "type these keys" tool now, for controls none of the helpers know.

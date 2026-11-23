---
id: 2026-11-18-site-knowledge-4d82
type: fixed
scope: agent
summary:
  en: "What the program knows about a site is in one place; the self-check keeps pages it cannot judge"
  zh: "程序对每个网站的了解集中保存；自检保留无法判断的页面"
  fr: "Ce que le programme sait d’un site est en un seul endroit ; l’autovérification garde les pages qu’elle ne peut juger"
---

- The self-check no longer deletes the saved form pages that stop matching, and no longer counts deleting them as a repair. A page that does not match may be out of date or may show that the code lost something, and the page alone cannot say which: it is now kept and marked with since when and what was missing, and is moved aside (not deleted) only when a later sample of the same form page passes. Samples are pruned by count among the passing ones only. The result of a self-check names what fails, what is new and what recovered; the diagnostics list has a line for it. Nobody is asked to do anything about it.
- The cards of the earlier self-check are closed one by one on what the run shows about each - the page matches again, a later sample replaced it, the page is gone, or the system's forms are read by the agent - instead of all at once.
- **What the program knows about a site is kept in one place.** It was in five - notes in a file per site, the steps
  of its form in another, recipes and plugins in a folder, and what was found out about signing in spread over
  settings - under three spellings of the site's name. Each site is now one record under one name: where it signs in,
  which browser its sign-in lives in, the notes, the steps of its form, and what was learned for it. *Analysis ->
  Time & learning* lists the sites, shows all of it for one, and can clear one (its sign-in stays). What earlier
  versions kept is brought over at the first start; the files it is read from are moved into a folder named
  "migrated" beside them, not deleted. Answers stay where they were: an answer is yours, not the site's.

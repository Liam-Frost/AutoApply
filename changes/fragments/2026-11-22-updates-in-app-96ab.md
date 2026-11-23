---
id: 2026-11-22-updates-in-app-96ab
type: added
scope: updates
summary:
  en: "An About page, and updates from inside the program"
  zh: "关于页，以及在程序内更新"
  fr: "Une page À propos, et des mises à jour depuis le programme"
highlight: true
---

**About page and updates** (sidebar, under *System*): the version and how this copy runs, the data folder, this version's changes, links, and the components with their licenses. Updates: look for a new release (stable, or pre-releases too), download it with its checksum checked, prepare it next to the running version (its own dependencies from its lock file; nothing in the package is run), and switch through the tray's restart - the database backed up, the new version tried, what is in progress finished, and the old version kept running if the new one does not start; the version before is kept to go back to. By itself: off, tell me (once a day; the default), prepare it, or update by itself when idle within a window of hours (03:00-05:00 by default). The notification on the phone has *Update when idle*; switching now is on the page. A source checkout or a container is told how to update instead. The update look asks GitHub only and sends nothing about you.

---
id: 2026-11-22-staged-version-start-c616
type: fixed
scope: updates
summary:
  en: "A version staged for the next restart is also used at the next start"
  zh: "为下次重启准备的版本，在下次启动时也会使用"
  fr: "Une version préparée pour le prochain redémarrage sert aussi au prochain démarrage"
---

**A version staged for the next restart is also used at the next start.** Started with nothing running (the shortcut, `start.bat`, after the computer slept), the tray used to start the version that ran last and switch to the staged one only at a restart. It now checks the staged one (database backed up, the release imported), starts it, and starts the previous one if it does not pass or does not come up.

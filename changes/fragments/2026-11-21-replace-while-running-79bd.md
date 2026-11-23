---
id: 2026-11-21-replace-while-running-79bd
type: changed
scope: updates
summary:
  en: "The service can be replaced while it runs, the old version kept if the new one does not come up"
  zh: "服务可以在运行中替换为新版本，新版本无法启动时保留旧版本"
  fr: "Le service peut être remplacé pendant qu’il tourne, l’ancienne version restant si la nouvelle ne démarre pas"
---

**The service can be replaced while it runs.** A new version is staged next to the running one (`scripts/stage_local_release.py`), and *Restart the server* in the tray - or `--restart` on that script - backs up the database, checks the new version, lets the old one hand over what it is working at a safe point, and switches; if the new one does not come up, the old one is started again. What is queued or waiting for you stays in the queue. Not yet: taking back work from a version that died without handing over.

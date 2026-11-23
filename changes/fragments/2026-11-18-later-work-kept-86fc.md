---
id: 2026-11-18-later-work-kept-86fc
type: fixed
scope: server
summary:
  en: "Work that is for later survives saving a setting and a restart"
  zh: "计划稍后执行的工作在保存设置或重启后仍然保留"
  fr: "Le travail prévu pour plus tard survit à l’enregistrement d’un réglage et à un redémarrage"
---

**Work that is for later is still there after you save a setting, and after a restart.** "Try again in half an
hour" - the retry of a site that did not answer, the look for a confirmation e-mail after a submission - was a
timer in the program's memory. Saving any setting rebuilt the schedule and dropped every one of them; so did
closing the program. Such work is now a task in the queue that is not taken before its time: the list of tasks
shows when it is due, and asking for the same work now ("draft it now" while a retry waits) takes that task
forward instead of leaving it to wait.

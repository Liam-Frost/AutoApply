---
id: 2026-11-15-happens-by-itself-b44d
type: changed
scope: applications
summary:
  en: "What should happen by itself does: reading on, drafts at the threshold, regular jobs on time"
  zh: "该自动发生的事会自动发生：继续读取表单、达到分数线即生成草案、定时任务按时运行"
  fr: "Ce qui doit se faire seul se fait : lecture poursuivie, brouillons au seuil, tâches régulières à l’heure"
---

**What should happen by itself does.** A draft whose form still has unread steps is read on without a button; the
button stays as "read now". Every ten minutes, postings whose score has reached the draft threshold and that have no
draft yet get one (six at a time, best first) - also right after the threshold is lowered in the settings; before,
the threshold counted only at the moment a posting was scored. Regular jobs (scanning for postings, reading mail,
the self-check) count their interval from their last run, not from the start of the program: a scan every twelve
hours never came round on a program that is closed or restarted more often than that. The activity page shows the
regular jobs with their last and next run and a "run now", and their intervals can be changed there.

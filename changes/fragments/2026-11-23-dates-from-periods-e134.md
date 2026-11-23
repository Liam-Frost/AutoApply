---
id: 2026-11-23-dates-from-periods-e134
type: added
scope: calendar
summary:
  en: "Deadlines from a stated period and interview end times taken from the email"
  zh: "按邮件写明的期限算出截止日期，并保留邮件给出的面试结束时间"
  fr: "Échéances tirées d’un délai indiqué et heures de fin d’entretien tirées du courriel"
highlight: true
pr: [126, 128]
---

- **A period that fixes a date gives one**: "you have 14 days to complete the assessment" becomes a date counted from
  the day the invitation was sent, on the calendar and with its reminders. A reminder that comes in the middle and says
  "within two weeks" again does not start the period again; an extension the employer announces, or a date a mail
  states outright, does move it.
- **An interview keeps the end its mail gives** ("10:00 to 10:45", or "a 45-minute interview"), converted like its
  start: the calendar draws it that long and the calendar feed carries it. Without one, nothing is claimed.
- Cards that were waiting when this version starts are read once more for both.

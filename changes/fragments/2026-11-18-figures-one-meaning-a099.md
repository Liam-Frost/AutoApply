---
id: 2026-11-18-figures-one-meaning-a099
type: fixed
scope: analytics
summary:
  en: "Figures mean one thing: due today, sent, acknowledged; a task that ended is not a submission"
  zh: "数字口径统一：今天到期、已投递、收到回执；任务结束不等于已投递"
  fr: "Les chiffres ont un seul sens : échéance du jour, envoyées, accusé de réception ; une tâche finie n’est pas un envoi"
---

- A filling run now records how often it handed the form to the applicant. The column for it was there and was never written; the figure is counted from the run's steps, so earlier runs have it too.
- **"Due today" and "due tomorrow" go by the calendar.** At noon, a deadline of 23:59 the same day was "due
  tomorrow" (half a day, rounded up to one), and a deadline that had passed that morning was "due today". Today is
  today, with the time; what is over says so. The overview and the postings page use one function for it.
- **"Sent" is one number, and the three words about what came of it mean the same everywhere.** The overview
  counted the applications whose posting is not archived, the analytics those with a day of sending: two numbers
  for "applications sent" with nothing to say why they differed (and "my applications" showed a third). Sent is now
  every application that stands at "submitted" or later, on all three; a page that shows a part of it says which
  part and how many it leaves out - the overview's chart of stages the archived ones, the analytics those without a
  date. "Acknowledged" (anything came back, an automatic confirmation included), "came to something" (an
  assessment, an interview, or a rejection) and "reached an assessment / interview" replace "heard back", "clear
  outcome" and their variants, and are computed in one place for both pages.
- **A task that ended is not an application that was sent.** In the automation figures, a filling task that found
  the application already sent - and did nothing - counted as a success, and one that pressed Submit and saw no
  confirmation as "filled in, waiting for you". The first counts neither way now; the second is "Submit pressed,
  outcome not known".

---
id: 2026-11-18-run-time-recording-c5ed
type: added
scope: analytics
summary:
  en: "Where a run’s time goes, and how each recruiting system’s forms go, in Analytics"
  zh: "数据分析中显示每次运行的时间花在哪里，以及各招聘系统表单的处理情况"
  fr: "Où passe le temps d’une exécution, et comment se passent les formulaires de chaque système de recrutement"
---

- Analysis → Automation has a table by recruiting system: how reading its forms and filling them went (success rate with the counts under it, forms handed over and submissions awaiting confirmation listed apart), how long the program itself worked, how often a filling run handed the form to you, how often the AI took a page over, and what the model was asked for that system's postings. Every site's form is read by the AI first now; this is where to see on which systems that pays.
- **Where a run's time goes** is recorded for every run: the program working the form (per field), waiting for the
  AI, tools the AI called, waiting for the site, and - shown but never counted - waiting for you. *Analysis -> Time &
  learning* shows it per application system over time, per run, and step by step for one run.

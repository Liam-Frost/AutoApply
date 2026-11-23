---
id: 2026-11-23-analytics-settings-about-ae45
type: changed
scope: ui
summary:
  en: "Analytics, notification settings and About reorganised by what they hold"
  zh: "数据分析、通知设置和关于页按内容重新编排"
  fr: "Analyse, réglages des notifications et À propos réorganisés selon leur contenu"
highlight: true
pr: [127, 128]
---

- **Analysis**: the cards are put together by what they hold, not stretched to one height. The time to a first record
  and the to-dos waiting are one strip of figures; the kinds of to-dos dealt with (the first five, the rest behind
  *Other kinds*) and the to-dos waiting longest (with their state, and *View all*) are two cards of their own; missed
  postings have a row of their own. Two cards share a row only when they hold about as much - on every tab.
- **Settings → Notifications** in five parts: channels, what to notify about, quiet hours, handling it from your phone,
  and calendar and reminders. The time zone is chosen from a list you can search - by city (in English or your
  language), country, zone name or offset ("+08", "UTC-7") - with each zone's offset now, from the program's own time
  zone rules; an old spelling (`US/Pacific`) goes on working, and a saved value that is not a time zone is shown as
  such, never replaced without you. Each kind of calendar item's reminders are chips ("1 day before", "30 minutes
  before") added from the usual choices or any amount in minutes, hours or days, instead of a list of minutes to type.
  Quiet hours are a switch and two times ("22:00 to 08:00 the next day"), what still goes through behind the (i).
- **About** in three tabs. *Overview*: the name, the version, how this copy runs and its links in one compact block;
  then one *Software update* section - where the version stands (up to date, a newer one, downloading, ready to switch,
  switching, failed) with only the actions that state allows, the update settings (a short list of choices, the
  channel, the hours for switching by itself), and *Advanced*, folded: how to update a copy run from source by hand,
  how updates work, the runtime details and *Copy diagnostics*. A version prepared or kept to go back to is named by its
  version ("2.0.2, local build, Nov 22"), not by its folder. *Changelog*: every release on one timeline, all of them
  folded at first - a line each with its date and a short title; opened (one at a time), a release shows its main
  changes in a few lines, in your language, and *View the full release notes* opens the notes as written. Search and
  one filter by kind; a link to a release opens it (the address keeps it). Changes not released yet are a block of
  their own above the releases. *Licences*: every component the program runs on - what it declares and what those
  pull in - searchable, each with its licence's text.

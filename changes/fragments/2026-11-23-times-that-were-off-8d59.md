---
id: 2026-11-23-times-that-were-off-8d59
type: fixed
scope: calendar
summary:
  en: "Times that were off: calendar times on the applications page, quiet hours, the last update check"
  zh: "修正偏差的时间：申请页上的日程时间、静默时段和上次检查更新的时间"
  fr: "Des heures décalées corrigées : l’agenda sur la page des candidatures, les heures calmes, la dernière vérification des mises à jour"
highlight: true
pr: [125, 127]
---

- **A calendar item's time on the applications page was read as UTC**: an interview at 10:00 showed as 18:00 (or
  03:00), eight hours off the calendar. It is the same wall-clock time everywhere now, whatever the time zone of the
  browser; the day of an outcome and the name of an exported file use the local day too.
- **Quiet hours were on the computer's clock**, not yours: with the program running in another time zone (a server),
  they were someone else's night. They follow the calendar time zone now.
- The time an update was last looked for was shown eight hours off.

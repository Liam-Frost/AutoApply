---
id: 2026-11-23-updates-only-go-forwards-03ca
type: fixed
scope: updates
summary:
  en: "Updates only go forwards: nothing switches back to an older version unless you roll back"
  zh: "更新只会前进：除非你主动回退，程序不会切换到更旧的版本"
  fr: "Les mises à jour ne vont que vers l’avant : rien ne revient à une version plus ancienne sauf si vous revenez en arrière"
highlight: true
---

A copy running 2.1.0 showed *Switching to 2.0.2*: a switch asked for the day before, which a later version had
overtaken. A switch now refuses a version that is the one running or older ("not newer"), whether it comes from
the page, from "update when idle" or from the automatic mode; going back stays the About page's *Roll back*. The
page shows a switch as under way only while the tray has not taken it yet, and a switch overtaken by a later
version is forgotten at the next start instead of being reported as "the new version did not start".

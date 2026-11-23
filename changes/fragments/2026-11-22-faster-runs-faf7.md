---
id: 2026-11-22-faster-runs-faf7
type: changed
scope: agent
summary:
  en: "Faster runs: an approval window kept open, a next run that starts where the last stopped, fewer looks"
  zh: "运行更快：待批准的窗口保持打开，下一次运行从上次停下处开始，减少查看页面的次数"
  fr: "Des exécutions plus rapides : fenêtre gardée pour l’approbation, reprise là où la dernière s’est arrêtée, moins de coups d’œil"
---

- **A record that waits for approval keeps its window** for ten minutes (*Settings → Automation → How the agent works*): approved in that time, the agent sends it from that page instead of opening the site again, finding the form and checking every field over. At most three such windows at once; they do not count among the applications worked at once.
- **The next run starts from where the last one stopped**: its brief has the address, the page and what the page showed, so it checks instead of going over every field again.
- **Fewer looks**: after waiting or opening an address, the agent is told what changed and the start of what the page says - in the runs so far, 79% of the calls after a wait and 51% after opening an address were a look at the page, each a whole turn of the model.

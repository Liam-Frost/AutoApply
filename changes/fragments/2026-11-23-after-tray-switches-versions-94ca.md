---
id: 2026-11-23-after-tray-switches-versions-94ca
type: fixed
scope: updates
summary:
  en: "After the tray switches versions, the new version starts completely: bots, network settings, its one-time work"
  zh: "托盘切换版本后，新版本会完整启动：机器人、网络设置和它的一次性工作都会执行"
  fr: "Après un changement de version par la barre des tâches, la nouvelle version démarre entièrement : bots, réglages réseau, son travail unique"
---

The tray switches versions without stopping the work in hand: the new version first joins as a second worker, then
takes over. A version started that way skipped what a plain start does - the Telegram and Discord bots did not run,
the network settings (a proxy) were not applied to its work, a new version's one-time work and the outcome of the
last switch waited for the next cold start. When the tray makes it the primary, it now does all of that once.

---
id: 2026-11-24-page-follows-update-fe84
type: fixed
scope: ui
summary:
  en: "A page left open while AutoApply was updated loads the new version instead of showing the old one"
  zh: "AutoApply 更新后，一直开着的页面会换成新版本，不再停留在旧界面"
  fr: "Une page restée ouverte pendant la mise à jour d’AutoApply passe à la nouvelle version au lieu de garder l’ancienne"
---

After an update the program starts again with the new version, but a page that was open kept showing the earlier one until it was reloaded by hand - what the update brought was not there. The page now notices that the program serves another version: it loads the new one when you open another page, or by itself while it is not being looked at (unless something has been typed in it), and meanwhile a notice says so with *Reload now*.

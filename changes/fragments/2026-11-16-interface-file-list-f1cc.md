---
id: 2026-11-16-interface-file-list-f1cc
type: security
scope: server
summary:
  en: "The interface is served from a list of its built files"
  zh: "界面文件只按构建清单提供"
  fr: "L’interface est servie d’après la liste de ses fichiers"
highlight: true
---

The route that serves the interface answers from a list of the built files instead of putting a path together from
the address. 1.0.2 already kept such a path inside the interface's folder; this form leaves nothing to check, and
code scanning recognises it. A link in that folder that leads out of it is not served.

---
id: 2026-11-15-interface-route-path-b9e4
type: security
scope: server
summary:
  en: "A path through the interface route closed: no address returns files outside its folder"
  zh: "修复界面路由的路径穿越问题：任何地址都无法读到界面目录之外的文件"
  fr: "Un chemin par la route de l’interface fermé : aucune adresse ne renvoie de fichier hors de son dossier"
highlight: true
---

The route that serves the interface could be made to return files outside its folder with an address such as
`/..%2F..%2Fdata/...`. The server is reachable from this computer only and refuses requests from other sites, so this
was open to programs on the same computer; it now serves files of the built interface only.

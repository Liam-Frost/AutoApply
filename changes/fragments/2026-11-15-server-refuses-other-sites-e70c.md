---
id: 2026-11-15-server-refuses-other-sites-e70c
type: security
scope: server
summary:
  en: "The local server refuses requests that do not come from its own pages"
  zh: "本地服务器拒绝不是来自它自己页面的请求"
  fr: "Le serveur local refuse les requêtes qui ne viennent pas de ses propres pages"
highlight: true
---

The local server now refuses requests that do not come from its own pages. It has no login and relies on being reachable
only from this computer; before this change a web page open in the user's browser could send it requests (approve a
pending draft, change a setting), and a domain name pointed at `127.0.0.1` could read from it. Requests with a foreign
`Host` header, and API requests from another site, are answered with 403. The whole origin is compared - scheme, host
and port - so a page served by another program on the same computer is not taken for the program's own page either.

---
id: 2026-11-23-ordinary-browser-waited-slow-7035
type: fixed
scope: agent
summary:
  en: "The ordinary browser is waited for when it is slow to start"
  zh: "普通浏览器启动慢时会等它，不再直接报“连不上浏览器”"
  fr: "Le navigateur ordinaire est attendu quand il tarde à démarrer"
---

The ordinary browser (nodriver) gave Chrome under three seconds to answer and then failed with "Failed to connect to browser", while that Chrome was still starting - on a busy computer, or one whose antivirus reads the browser profile, an application or a sign-in failed before it began. A Chrome that is still starting is now waited for, up to half a minute more.

---
id: 2026-11-16-access-security-settings-569a
type: added
scope: settings
summary:
  en: "Access & security settings: where the server listens, its port and a path prefix"
  zh: "访问与安全设置：服务器监听的位置、端口和路径前缀"
  fr: "Réglages d’accès et de sécurité : où le serveur écoute, son port et un préfixe de chemin"
highlight: true
---

**Settings -> Access & security**: where the server listens (this computer only, every network, one address), the
port, a path prefix for serving it under a reverse proxy, how long a login lasts, the administrator's password, and
"sign out on every device". HTTPS is left to a reverse proxy: tell the program one is in front and the login is only
sent over HTTPS. The address, port and prefix are kept in `data/access.json`, so a wrong value can be repaired with
a text editor; they take effect when the server is restarted.

---
id: 2026-11-25-gmail-through-proxy-52c7
type: fixed
scope: mail
summary:
  en: "Gmail is read through the proxy set in the program, and a check that cannot reach it says so"
  zh: "Gmail 按程序里设置的代理读取；连不上时会如实说明，不再说“网站可能在维护”"
  fr: "Gmail est lu via le proxy réglé dans le programme, et une vérification qui ne peut pas le joindre le dit"
---

Gmail was always read with a direct connection, whatever the proxy setting said: the library it is read with needs one more package to use a proxy, and without it ignores the proxy without a word. Where Google is reached only through a proxy, mail stopped being read - while everything else worked - and each check said the site might be under maintenance. Gmail now goes the way Settings → System and data → Network connection says (the system's proxy, your own, or none), and a check that cannot reach Gmail says that, pointing to where the connection can be tested.

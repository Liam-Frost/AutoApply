---
id: 2026-11-15-security-hardening-81df
type: security
scope: server
summary:
  en: "Hardening: sites told apart by host; prompt keys, location parsing, table import and posting ids made safe"
  zh: "安全加固：按主机名区分网站；提示词键名、地点解析、表格导入和岗位 ID 都更安全"
  fr: "Durcissement : sites distingués par leur hôte ; clés de prompt, lecture des lieux, import de tableau et identifiants sécurisés"
---

- Sites are told apart by the host of an address, never by a name appearing somewhere in it: a look-alike address such
  as `evilgreenhouse.io` or `evil.example/?next=myaccount.google.com` is no longer taken for the real site when a posting
  is recognised or when the program decides that a sign-in has finished.
- A prompt can only be saved or reset under a key from the registry; a crafted key could name another `.md` file.
- Location text from a posting can no longer stall the regular expressions that read it.
- Importing a table of postings takes a file path, so it is available on the command line only
  (`autoapply import-tsv <path>`); the API endpoint for it is gone.
- Identifiers of postings read from careers pages are derived with SHA-256; stored ones are re-keyed once at start-up.

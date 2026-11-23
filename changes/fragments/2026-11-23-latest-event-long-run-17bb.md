---
id: 2026-11-23-latest-event-long-run-17bb
type: security
scope: applications
summary:
  en: "A latest event with a long run of spaces can no longer slow the applications page down"
  zh: "含大量连续空格的最新动态不会再拖慢申请页"
  fr: "Un dernier événement contenant une longue suite d’espaces ne ralentit plus la page des candidatures"
---

The first sentence of an application's latest event (what its row shows) was cut with a pattern whose time grew with
the square of a run of spaces after a full stop; a message from a site or a mail could hold such a run. It is read
in one pass now, with the same rule for where a sentence ends.

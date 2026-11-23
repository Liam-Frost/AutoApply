---
id: 2026-11-23-workday-boards-read-again-ebd7
type: fixed
scope: postings
summary:
  en: "Workday boards are read again: a \"too many requests\" answer is waited out instead of asked again"
  zh: "Workday 招聘页恢复读取：遇到“请求过多”会等待，不再立刻重试"
  fr: "Les pages Workday sont de nouveau lues : une réponse « trop de requêtes » est attendue au lieu d’être relancée"
highlight: true
---

Workday limits the requests of one computer to all its employers' boards together. The scan asked every half
second, retried a refusal within seconds, and then went on to the next board of the same service - so every board
failed with HTTP 429, scan after scan. Workday is now asked at its own, slower pace; after a refusal the whole
service rests (as long as it asks, else a minute, then longer) and is asked more slowly from then on; when it
needs longer than a scan waits, its boards are left for the next scan without a request, and the summary says so
in one line. Intel's board fetches descriptions only for the postings your rules keep, like any other board.

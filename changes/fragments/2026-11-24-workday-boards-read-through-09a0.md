---
id: 2026-11-24-workday-boards-read-through-09a0
type: fixed
scope: postings
summary:
  en: "Workday boards are read through their own pages when Workday refuses the program's requests"
  zh: "Workday 拒绝程序的请求时，改为在浏览器里打开雇主的招聘页读取岗位"
  fr: "Les pages Workday sont lues dans le navigateur quand Workday refuse les requêtes du programme"
highlight: true
---

Workday kept refusing this computer's requests ("too many requests" or a security check) whatever their pace, and 2.1.1's answer - rest, and read again at the next scan - left the boards unread for good: every scan's first request was refused, and a restart forgot the rest. Now a refusal is kept across restarts (half an hour, then longer each time, a day at most) and the service is not asked again before then; meanwhile, in the same scan, each board is read through its own page in the program's browser, the way a person reads it - the page asks Workday for its postings, one request every few seconds. A browser check that passes by itself is given the time; one only a person can answer is not answered, and the summary says so. When the hidden browser is refused, the pages open once more in a window, which opens and closes by itself. A board's last page is no longer followed by a request for an empty one.

---
id: 2026-11-18-postings-intake-93a2
type: fixed
scope: postings
summary:
  en: "Postings: the whole text before scoring, outages and security checks told apart, a much faster intake"
  zh: "岗位：评分前读取完整说明，区分网站宕机与安全检查，处理速度大幅提升"
  fr: "Annonces : le texte complet avant la notation, pannes et contrôles de sécurité distingués, un traitement bien plus rapide"
---

- A posting whose source gives only a summary is no longer scored as if the summary were the posting. A job board's feed often carries a teaser of a few lines; such a posting is now marked, and before it is scored or its overview written its own page is read for the whole text (by a plain request, and in a browser when the page is drawn by script). When the page cannot be read the score is given on the summary, the model is told that it reads one - what a summary does not mention has not been shown to be absent - and the score's reason says "only a summary". The posting's page in the program says so as well. A teaser that is too short to score gets its chance to be completed instead of staying unscored for good, and once the whole text was read a later scan does not put the teaser back.
- Reading one employer's board no longer takes other employers' postings offline. The rule for capped or filtered listings ("not shown for N days") looked at every posting of the same service, so a board that was down or switched off lost its postings to the next board that answered. Both rules now look only at the listing that was read, and the days are counted from the first reading that did not show the posting rather than from when it was last seen - a listing that could not be read for a week has said nothing in that week.
- A source that could not be reached (a timeout, a name that does not resolve) is said to be unreachable; it was
  shown as "this step was not completed".
- **An address that gives no answer is a site that is down, wherever it happens.** A connection that timed out at the
  first page of a sign-in was reported as a failed task and left there, while a site that answered with an error page
  was tried again. Both are the same thing now: tried again by itself (the first time after five minutes), nobody is
  asked to do anything, and it is never counted as a password that failed or a page that could not be worked.
- **A site's security check is told as what it is.** Eight sources on Workday failed every scan with "429 Too Many
  Requests": not a rate limit, but a security check that does not accept requests from this computer's network
  address. Each was asked four times, with growing pauses. Now one such answer is enough: the service is left alone
  for six hours, the scan says so in one line, and requests to one service are paced together even when sources are
  fetched side by side.
- **Postings for other programmes of study are set aside before anything reads them.** A university co-op portal
  lists every faculty's postings, and each says which programmes it is for. That statement is now used: a posting
  whose programmes do not include yours is marked "not applying" with the programmes it names, without being scored.
  "Open to all majors" and postings that name no programme are not touched. Your programme is taken from the first
  entry of your profile's Education section, or set under Settings.
- **Getting through many postings takes a fraction of the time.**
  - Several postings are read by the model at once (four by default) instead of one after the other.
  - The long overview of a posting - most of what the model wrote for each - is written only for postings that score
    6 or more; for the others a button on the posting writes it when you want it.
  - The employers' listings are fetched side by side instead of one after the other.
  - Scanning, scoring and mail no longer hold applications up: they have a worker of their own, forms have the other.
  - When more postings wait than one run takes, the next run follows in a minute, not five.

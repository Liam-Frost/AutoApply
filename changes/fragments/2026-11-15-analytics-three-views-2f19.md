---
id: 2026-11-15-analytics-three-views-2f19
type: changed
scope: analytics
summary:
  en: "Analytics in three views - applications, automation and AI cost - over one time range"
  zh: "数据分析分为申请、自动化和 AI 成本三个视图，共用一个时间范围"
  fr: "L’analyse en trois vues - candidatures, automatisation et coût de l’IA - sur une même période"
highlight: true
---

The page is now three views over one time range (everything, the last 30 or 90 days, or your own dates), each with the
change against the period before where there is one to compare with.

- **Applications.** The funnel counts what an application *has been* (an interview before a rejection still counts as
  an interview), each step a part of the one before; next to it, where every application stands now, adding up to the
  total. Months follow local time. Groups with fewer than five applications show counts, not percentages. Replies by
  the month they arrived are shown apart from outcomes by the month of sending. Missed postings show why and when.
- **Automation.** What the program's tasks did: done, not finished (handed to you, waiting for you, still running) and
  failed are told apart - a filling task that handed the form over is not a failure and not a success. Success rate,
  typical duration, why tasks failed and how far they had got, repeats and retries, and the AI cost per success. Each
  run opens to the model requests it made. There is no "hours saved": the program has no record of how long the same
  work takes by hand.
- **AI cost.** What the model calls used and what that comes to, over time and by model, service and feature; tokens
  by kind (input, cache read, cache write, output) by count and by cost; cost per result (everything a kind of task
  spent, failed runs included, over what it produced); what failures, retries on a backup service and repeated runs
  cost; and the runs and requests far above the others of their kind (by Tukey's fence, not a made-up threshold).

The cards of a row share its height, so tops and bottoms line up; rows are as tall as their content. Detail never
grows an overview card: the numbers behind a chart open in a panel below its row, across the page; the full list of
runs, a single run with its model requests, and the price editor open in a drawer; long tables are paged.

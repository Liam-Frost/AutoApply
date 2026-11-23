---
id: 2026-11-15-ai-requests-recorded-9031
type: added
scope: ai
summary:
  en: "Every AI request recorded: service, model, feature, time and tokens, with its cost at list price"
  zh: "记录每次 AI 请求：服务、模型、功能、耗时和各类 token，费用按标价估算"
  fr: "Chaque requête à l’IA enregistrée : service, modèle, fonction, durée et jetons, avec son coût au prix catalogue"
highlight: true
---

- Every request to an AI service is recorded: service, model, the feature and the task that asked, how long it took,
  how it ended, and tokens by kind. Failed requests are kept too, and a retry on a backup service is tied to the call
  it repeats.
- Tokens are counted one way for every service. Cached tokens that a service includes in its prompt count are taken
  out; reasoning tokens are part of the output and not added to it. What the service reported is kept word for word.
- Cost is an estimate at list price unless the service reports a cost itself (the Claude subscription's command line
  does). Claude models have built-in prices; for other models you enter your own on the page, and earlier requests
  are estimated again. A call within a subscription costs nothing extra: its figure is what it would cost on the
  pay-as-you-go API, and is shown apart from pay-as-you-go cost. A request whose usage or price is not known has no
  cost - it is listed as such and never counted as zero.
- Totals from before (calls and tokens per task) are carried over as history, without a model and without a cost:
  neither was recorded then, and neither is made up.

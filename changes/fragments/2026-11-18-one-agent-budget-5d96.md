---
id: 2026-11-18-one-agent-budget-5d96
type: changed
scope: agent
summary:
  en: "An agent has one budget whatever the AI service, and how much each kind of work gets is a setting"
  zh: "无论用哪家 AI 服务，Agent 都只有一个预算；每类工作可用多少由设置决定"
  fr: "Un agent a un seul budget quel que soit le service d’IA, et la part de chaque type de travail est un réglage"
---

- An agent has one budget, the same whichever AI service does the thinking: so many tool calls, and a moment on the clock by which it ends. Until now each service counted in its own way (model turns, its own turns, requests) and the ChatGPT sign-in did not count at all, with a time limit that started again with every message - an agent that kept calling tools could occupy the place where forms are filled for as long as it liked. When the budget ends the model's run is ended too (the ChatGPT turn is interrupted, the Claude query cancelled), and the result says which it was: finished by itself, out of steps, or out of time. A backup service that takes over goes on with what is left.
- How much each kind of work gets - reading a new form, taking over a fill, signing in, turning a page, checking values, looking up an application's status - is a setting: Settings → Automation → "How much the AI may do at a time".

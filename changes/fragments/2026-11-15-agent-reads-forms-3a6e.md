---
id: 2026-11-15-agent-reads-forms-3a6e
type: changed
scope: agent
summary:
  en: "Multi-step forms are read and filled by the AI agent, Workday first, then every site"
  zh: "多步表单由 AI Agent 读取和填写，先用于 Workday，随后用于所有网站"
  fr: "Les formulaires en plusieurs étapes sont lus et remplis par l’agent IA, Workday d’abord, puis tous les sites"
highlight: true
---

- **Forms that are a walk through several steps are read and filled by the AI agent, not by coded steps.** On such sites
  (Workday for now; the list is the setting `agent.reads`) the coded driver signs in and hands over; the agent looks at
  each page and decides what to do there, and the program's own rules stay what they were: nothing is made up, nothing
  is submitted without the approved draft, every value is read back and compared, the run keeps its evidence. Coded
  reading of these forms broke on every new site - a list that opens late, a notice taken for an error, a field without
  a name - and each break came back to you as one more draft.
- **Every site's form is read by the agent** (`agent.reads` is `["*"]`); the coded drivers sign in and are otherwise
  tools.

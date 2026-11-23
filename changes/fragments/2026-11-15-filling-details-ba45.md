---
id: 2026-11-15-filling-details-ba45
type: fixed
scope: agent
summary:
  en: "Filling: answers missing only after Continue, multi-selects shown as chips, look-alike labels"
  zh: "填写修复：点“继续”后才提示的缺失答案、以标签显示的多选、相似的字段标签"
  fr: "Remplissage : réponses manquantes signalées après « Continuer », choix multiples en pastilles, libellés voisins"
---

- A form that names a missing answer only after "Continue" gets one more round of finishing before the step is handed
  over. An error text that was on the page before the fields were changed no longer counts as a new problem.
- A multi-select that shows its choices as chips is no longer reported as "required, still empty".
- A control is found by its label only when the label is the question. A label that merely contains the question's
  words is another question: "First Name" was filled into "Legal First Name" when its own field was not on the page.

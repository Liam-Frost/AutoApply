---
id: 2026-11-15-forms-walked-by-screen-a51f
type: fixed
scope: agent
summary:
  en: "Multi-step forms are walked by what is on the screen, step by step"
  zh: "多步表单按页面实际显示的内容逐步推进"
  fr: "Les formulaires en plusieurs étapes sont parcourus d’après ce qui est à l’écran, étape par étape"
highlight: true
---

- Forms with several steps that the AI explored (Amazon's application form, for example) are now walked by what is on
  the screen, not by the page numbers recorded in the draft. Such forms resume where an earlier attempt stopped, skip
  steps they already have and put optional offers in between, so "fill page 1, press Next, fill page 2" failed with
  *could not advance to the next page* - often on a page that had nothing to do with the draft, like an offer of text
  message updates. Now each step is handled on its own: fill the questions that are there, read what the form reports,
  let the AI finish what is left, go on with the form's own forward button ("Skip & continue" included), and where there
  is none let the AI find the way. Optional offers are declined. The run stops at the review page, where you submit.
  Answers the form did not ask for again are compared with the review page and listed for you when they cannot be
  confirmed. A step that will not go on is handed to you in the window with the reason, instead of failing the run.
- Whether a form has moved to another step is told by what can be seen of the step (the step the form marks as current,
  its headings, controls and buttons). The first `<form>` of a page was used before; on Amazon's page that is a hidden
  log-out form, so the program never noticed that "Skip & continue" had worked.
- A step the form itself calls a review is recognised before anything is filled in. Controls that a page keeps in
  collapsed or cut-off sections (the summaries on a review page) no longer count as questions that are on the step.

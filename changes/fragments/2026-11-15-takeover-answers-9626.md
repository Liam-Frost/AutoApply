---
id: 2026-11-15-takeover-answers-9626
type: fixed
scope: agent
summary:
  en: "Take-overs get every approved answer, fit an answer to a field’s limit and say where each question is"
  zh: "AI 接管时获得全部已批准的答案，按字段限制改写答案，并标明每个问题的位置"
  fr: "La reprise par l’IA reçoit toutes les réponses approuvées, adapte une réponse à la limite d’un champ et situe chaque question"
---

- A take-over on one step is given every approved answer of the application, not only the ones the driver located on
  that step, so a question the driver cannot find gets its approved value and never a newly made-up one.
- Forms the AI explored have no driver code, so a take-over there no longer leaves a "driver patch suggestion" card that
  nobody could act on (open ones are closed once). What the take-over found is kept in the notes for the site, and
  those notes are now also given to the model that answers the questions of the next draft for the site - a length
  limit a form only shows after typing is respected the next time.
- An approved answer that a form refuses for its length or format is rewritten by the AI take-over to fit, instead of
  being handed back to you on every run. Before, the fixed rule of that prompt was "never alter an answer", so an answer
  of 1,400 characters in a field that takes 200 stopped Amazon's form each time. The rewrite keeps to what the approved
  answer says; you are shown the old and the new text before anything is submitted. What was learned is kept: the draft
  holds the adapted answer and the limit (the next run needs no AI), the notes for the site name the limit, and a
  question with a known limit is answered within it from the start.
- Every question a take-over reports comes with where it is on the page, and is refused when its label is not the
  form's own wording, so the driver finds and fills it by itself the next time - no AI for a form that was walked once.
  A radio question known only by the label of one of its choices is set and read as the whole group.

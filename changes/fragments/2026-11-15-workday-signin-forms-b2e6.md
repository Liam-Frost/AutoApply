---
id: 2026-11-15-workday-signin-forms-b2e6
type: fixed
scope: agent
summary:
  en: "Workday: a signed-in session is recognised and a form is read in one pass"
  zh: "Workday：能识别已登录的会话，表单一次读完"
  fr: "Workday : une session connectée est reconnue et un formulaire est lu d’une traite"
highlight: true
---

- Workday: a session that is signed in is recognised. The candidate home shows "Sign In" for a moment before it shows
  the account menu, and the program looked at whichever came first - so right after a sign-in (yours, or its own with
  the saved password) it concluded that nobody was signed in, tried the sign-in page again, was sent on to the candidate
  home and waited there for an e-mail field: "automatic login failed", however often you signed in. It now waits until
  the page has settled. A sign-in page the program cannot work no longer counts as a wrong password.
- Workday: opening the application form waits for the form to appear, and presses "Use My Last Application" once
  more when the first press came before the page was ready. Before, the program looked for the form a moment after
  the press and gave up with "application flow did not open".
- Workday: a step is read once its fields are there (the progress bar comes first; a draft made in between was empty
  and looked ready - an empty first step is now an error). The résumé upload is recorded when its box has no id. A date
  box that a click cannot reach is given the focus instead. "Résumé successfully uploaded" is no longer taken for an
  error of the form, which stopped the reading on that step.
- Workday forms are read as far as they go in one pass, and the reading goes on by itself. A field the program cannot
  work no longer ends the reading (it is noted in the draft). When the form stops at a question only you can answer,
  your answer starts the reading again from there - before any approval - and is used there; answers you typed into
  an earlier draft of the application are not asked for again. The draft says how far the form was read and which
  steps are still unread. Before, such a draft looked ready, and approving it ended in "the form changed" and yet
  another draft.
- Workday: several rows of one question that the site carries over from your last application (the websites) are left
  as they are when they already hold the entries; retyping them made two rows equal for a moment and the form answered
  "You can't add duplicate website URLs". The draft shows what the rows hold. Questions on questionnaire steps are read
  with their real wording (some came out without any, or with the chosen value as their name), a group of tick boxes
  is one question with several choices, and "First Name" under "Legal Name" and under "Preferred Name" are told apart -
  one answer for both had put the preferred name into the legal name. A list is read from its own box: the choices of
  the field before could be recorded for it, which later looked like a changed form.

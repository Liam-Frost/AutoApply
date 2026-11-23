---
id: 2026-11-18-submission-safety-fc51
type: fixed
scope: applications
summary:
  en: "Submitting is safe: no AI tool sends an application, an early send is seen, an unknown outcome is a state"
  zh: "提交更安全：任何 AI 工具都不会提交申请，提前提交会被发现，结果未知是单独的状态"
  fr: "Envoi sûr : aucun outil de l’IA n’envoie une candidature, un envoi précoce est vu, un résultat inconnu est un état"
---

- **No tool of the AI sends an application - whatever the button is called by, and whichever tool would press it.**
  The AI that reads forms and the one that steps in while filling could not click a button whose text says "Submit".
  That was the whole of it: a button named only by an `aria-label` (an icon) passed; the tools that open a list or
  type clicked whatever they were pointed at first; the key tool would press Space on a focused Submit button, or
  Enter in a field - which sends the form - as long as some list was open anywhere on the page. Every tool that
  clicks or presses a key now asks one question of what it would land on: is this the control that sends the
  application, by any of the ways a control gets its name? Enter is available where it takes an entry of an open
  list, and in a text area. "Next" and "Save and continue" work as before. The tools a learned plugin adds get a
  page that asks the same question, and a plugin that clicks or sends from script inside the page is not learned.
- **If a form is sent before the program means to send it, that is seen and said.** The page itself is watched for
  the application going out (told apart from leaving a step, and from a search box with a "Submit" button). Should
  it happen while a form is being read or filled, the program does not press Submit after it, does not hand you the
  window to send it again, and does not report "failed - fill it in again": the application stands at "outcome of
  the submission not known", with what was pressed named on the card.
- **Who presses Submit is said the same way everywhere.** A draft could say "submitted automatically" in one line
  and, in the steps below it, "this system has no driver yet: you check and press Submit"; the settings page promised
  that a site without dedicated support always stops for you. Neither has been true since which driver fills a form
  stopped deciding who submits. The decision is made in one place, from your settings; the last step of a draft's
  plan is that decision in words, made when you look at the draft (so an old draft says what is true now, and
  changes when you change the setting), and the settings page names the two things that do stop an automatic
  submission: an entry the program could not check and the AI chose, and a form that still reports something for you.
- **"Submit was pressed, and no page said it was received" is a state of its own.** It used to be a failed run - or
  "filled, not confirmed" - and either way the card's main button was "fill in and submit again": the one thing that
  applies twice if the first time went through. Whether Submit was pressed is now a fact the run keeps (also in the
  window you submit in: the page is watched for the form being sent), and the application stands at "outcome of the
  submission not known" until something settles it:
  - the employer's confirmation e-mail, which the program goes on looking for - or looks for now, from the card;
  - "I did submit it";
  - "it did not go through: fill it in again" - asked once more before it is done, and done by nothing else.

  A form that answers the click with its own complaints was not sent, and is a failed run as before. A window that
  closed without Submit being pressed is "filled in, not submitted yet", and its card offers to open the window again.
  Cards that older versions filed as failures of this kind are re-filed when the program starts.

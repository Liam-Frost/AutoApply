---
id: 2026-11-18-program-review-03fe
type: fixed
scope: agent
summary:
  en: "From a review of the whole program: faults patched for one case fixed for all"
  zh: "全面审查程序：只针对个别情况打的补丁改为通用修复"
  fr: "D’une revue de tout le programme : les défauts corrigés pour un seul cas le sont pour tous"
---

**From a review of the whole program** - places where a fault had been patched for the one case that showed it:

- *Why reading a form stopped* was a word of the AI's own, and every word the program did not know meant "sign
  in". It is now one of six (sign-in, CAPTCHA, closed, already applied, site not answering, other), each with one
  consequence; a page that simply could not be worked is no longer a sign-in card.
- *Signing in somewhere resumed every waiting task* - also the ones waiting for another site, which failed again
  and asked again. A task is now resumed by what it waited for.
- *An answer confirmed for one employer* was reused on every other site without a driver of its own as if confirmed
  there too ("Have you worked for us before?"). It is still offered, as a suggestion to check.
- *Two employers sharing one word* in their names ("... Robotics") were taken for one when an e-mail was matched to
  an application.
- *Mail from an employer you applied to* is read even when it uses none of the usual words (another language).
- *The settings page no longer overwrites the program's own record* (which browser a sign-in lives in, which site
  signs in on which, how far the mailbox was read) when a page that was left open is saved.
- *"Has it been submitted?" and "was it applied for before?"* were read from the page by a list of English
  phrases; a confirmation in other words or another language was "not submitted". Where the phrases find nothing and
  the answer matters - after Submit, on a page without the form, when the window is closed - the AI now reads the
  page. It has to quote the page's own sentence, and a quote that is not on the page is not believed.
- A handler that lets a busy page pass no longer lets a mistake in the program pass with it.
- One list of the states in which an application counts as sent, instead of five; the portal's special rules live
  in the portal's driver; two settings nothing read, an unused copy of the browser rules, unused code and a card
  text for a card that is no longer made are gone; site rules saved with "login only" are stored as what they mean.

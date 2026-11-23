---
id: 2026-11-18-answers-and-fields-5a60
type: fixed
scope: applications
summary:
  en: "Answers kept per employer and editable after approval; fields that cannot be checked shown to you"
  zh: "答案按雇主保存，批准后仍可修改；程序无法核对的字段会列给你看"
  fr: "Réponses gardées par employeur et modifiables après approbation ; champs invérifiables signalés"
---

- **An answer you confirmed for one employer is a suggestion for the next, on every system.** On the sites without
  dedicated support this was already so. On Workday, Greenhouse and the others, answers were kept for the whole
  system, as if every employer on it asked the same question: "Have you previously worked for us?", confirmed as
  "Yes" on one employer's form, went to the next employer as your confirmed answer. Answers are now kept per
  employer everywhere; what you answered elsewhere is still offered first - marked as less than certain, saying
  which employer it came from, and not counted as confirmed. Answers kept before this are offered the same way.
  A new employer's first form therefore has a few more answers to look at than before.
- **An entry a site makes by itself is no longer handed to you as bare empty fields.** A form that reads the uploaded
  résumé can turn a personal project into a second "work experience" and then want its job title and city; you got
  two questions, "Job title" and "City", with no way to say that the entry should go. Now the AI holds such an entry
  against your profile: it fills what the profile states, removes an entry the profile plainly contradicts (and says
  so with the draft), and where it cannot tell asks you one question about the whole entry - remove it, or keep it.
  Fields of one of several like-named entries say which entry they belong to and are not filled into whichever comes
  first. And a question the filling ran into can be taken out of the draft ("This is not one to fill in").
- **A field the program cannot check is shown to you instead of passing silently.** A list that shows "+1" for
  "+1 Canada" and does not mark its chosen entry was accepted on the AI's word. It still is - the form is not stopped
  for it - but the field is listed on the card as one to look at, and an application with such a field is not
  submitted automatically.
- **An answer in a draft can be changed after the draft was approved.** The "Edit" button was only there until you
  approved, so a wrong answer noticed afterwards - or one a run failed on - could not be corrected, and neither
  could the résumé. Now every answer can be changed for as long as the application has not gone out. The draft stays
  approved (the change is your own), what was changed is listed with the draft, and "Fill in again and submit" uses
  the answers as they are now. A draft is closed only when it is an old version, when the application was sent, or
  while a run is filling the form from it - and it says which.
- **A list whose button shows less than the entry it holds no longer stops a run.** A phone-code list has "+1 United
  States", "+1 Canada", "+1 Bahamas"...; once one is chosen its button reads "+1". The program took "the button did
  not change to the entry's text" for a failed choice, then took "+1" against "+1 Canada" for a difference from the
  draft, and the AI, asked to look, could only say that the country is not visible - so the run was handed to you
  although the right entry had been chosen. Now the list itself is asked which entry it holds: it is opened, the
  entry it marks as chosen is read, and it is closed again. The approved entry: no difference, nobody is asked.
  Another entry: a difference, and the message says which. The same goes for a location list that shows "Vancouver,
  Canada" for "Vancouver, BC, Canada".

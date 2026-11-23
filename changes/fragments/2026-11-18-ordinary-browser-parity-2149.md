---
id: 2026-11-18-ordinary-browser-parity-2149
type: fixed
scope: agent
summary:
  en: "The ordinary browser fills forms and reads listings the way the automated one does"
  zh: "普通浏览器填写表单、读取岗位列表的方式与自动化浏览器一致"
  fr: "Le navigateur ordinaire remplit les formulaires et lit les listes comme le navigateur automatisé"
---

- In the ordinary browser, several things were not done the way the automated browser does them: filling a box pressed Ctrl+A and Backspace first (in the search box of a list of chosen entries, Backspace on an empty box removes the entry chosen before) - it now selects and replaces the text without keys; typing "key by key" put the whole text in at once, so a list that searches as one types heard nothing - each character is now a key going down and coming up; text was matched with regard to case; and two selector shapes the program's own code writes (`visible=true`, `text=…`) were not understood there - Greenhouse's check for a challenge frame failed on the first.
- A task told to use the ordinary browser ("retry in the ordinary browser" on a scan) now reads every listing in it. Listings are fetched side by side on helper threads, and those were handed the task's metering record only - not the browser it was told to use, not whether the applicant had asked for it, and not its own count of model calls, which missed everything its helpers asked the model. What a task is now goes with every part of its work as one copy of the context (`context.py`), and each helper's model call is its own: several helpers wrote the call they were making into one shared record.
- **Filling a form in the ordinary browser works like filling it in the automated one.** Once a site's work followed
  its sign-in there, the first application stopped with `"Tab" has no attribute "closed"`: that browser had only ever
  been used to sign in and to read. Every test that drives a form now also runs in the ordinary browser (in CI too),
  which is how the rest was found and fixed: asking whether the window is still open, the page's short forms
  (`page.check(...)`), keys such as the space bar, and
  - the browser is now closed in order, so its profile keeps the session as the site last left it; it used to be ended
    outright, which lost what had changed during the run;
  - a profile's own cookies are no longer written over with the saved copy at every start.
- **The university's co-op portal is worked in the ordinary browser for everything**, not only for signing in: a
  browser rule saved by an earlier version sent reading and applying to the automated browser, which the portal turns
  away. When its list of postings is not on the page, the error now says what the page showed.

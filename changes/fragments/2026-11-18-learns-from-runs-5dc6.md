---
id: 2026-11-18-learns-from-runs-5dc6
type: added
scope: agent
summary:
  en: "The program learns from its runs: recipes, plugins and drivers for a site, checked and on trial"
  zh: "程序从运行中学习：为网站生成配方、插件和驱动，先检查再试用"
  fr: "Le programme apprend de ses exécutions : recettes, extensions et pilotes par site, vérifiés et à l’essai"
---

- **The program learns from its runs, and keeps what it learned.** After a run that filled a form, plain arithmetic
  looks for what stood out against earlier runs on the same site - a step several times slower than usual, the AI
  taking over again and again, a field the driver could not fill. Only then is the AI asked to write down what the
  program should do differently there: a *recipe* (data the generic driver follows: how to work a kind of control,
  when to wait) or, where no recipe can say it, a small *plugin* (code).
  - It is kept under `data/learned`, not in the program's folder, so an upgrade does not lose it; after an upgrade it
    is checked again before it is used, and parked - not deleted - if it no longer passes.
  - Before it is in force it has to pass a gate: a plugin may import only what a driver works with, it must load,
    and the site's saved pages must still be read as before.
  - In force, it is on trial: where it fails in a run, the ordinary way takes over in that same run and it is taken
    out; it is also taken out when runs with it keep failing or get slower. Two good runs make it permanent.
  - By default this happens by itself; *Analysis -> Time & learning* has the switch to be asked first, and lists
    each thing learned with why, its text, how its trials went, and buttons to take it out or try it again.
  - The read-back against the approved draft and the rules about submitting are not something a revision can touch.
- A learned plugin has to keep to a contract before it is tried on an application: on a form it was not written for it either declines a field and leaves it alone or fills it and the field holds the value; it reads what is there; it changes nothing else, leaves the page where it is and sends nothing - and so do the tools it offers. A rule of a learned recipe has to name the field it is for.
- **A site without a driver of its own gets one written as soon as an application there has gone through.** The
  first time, the generic driver fills it and the AI steps in where that fails. Afterwards the AI is given that run -
  every take-over, every field the driver could not fill, the notes kept about the site, the steps of its form - and
  writes what the generic driver needs to fill that site without help. It goes through the same check and trial as
  everything else learned (a trial that fails takes it out again), and is asked for once per site.
- **What was learned can include a tool for the AI.** Where the AI had to work something out step by step on a site
  and will need it again, the code it writes may add a tool of its own for the take-over on that site. Such a tool is
  checked like the rest, cannot be about submitting or signing in, and one failure takes it out.
- **A driver the program wrote can be given back to the project.** When a site's driver has held up in its trial, a
  card asks whether to report it: this once, always, not this time, or never (the preference is also under *Analysis
  -> Time & learning*). The program sends nothing itself: saying yes opens GitHub's new-issue page in your browser
  with the text filled in - the site's address, the driver, the program's version; no answer of yours, nothing from
  your profile - and it is yours to read and submit.

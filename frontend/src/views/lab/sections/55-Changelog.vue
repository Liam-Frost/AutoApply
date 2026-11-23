<script setup>
// Lab: the about page's Changelog and Licenses tabs. First the changelog on made-up versions (nothing here is a real
// release), in the shape of GET /api/about/changelog: titles and summaries in two languages, every type of change, a
// release with more than six changes and its highlights in the middle (the highlights come first, six at most), one
// whose title and a summary exist only in English (marked so in French), a release with a single change and no
// details, and unreleased changes. It reads no deep link (address=false). Then both tabs as they read the program's own
// release data (releases.json and the pending change fragments) and its installed packages - that one follows ?v=.
import ChangelogTab from '../../about/ChangelogTab.vue'
import LicensesTab from '../../about/LicensesTab.vue'

// (English and French only: the lab writes no Chinese of its own - in Chinese these fall back to English, marked, as a
// change without its translation would; the real data below has its own)
const w = (en, fr) => (fr ? { en, fr } : { en })
let n = 0
const ch = (type, en, fr, { highlight = false, details = '' } = {}) => ({ id: `2031-01-01-lab-${++n}-0000`, type, scope: 'ui', summary: w(en, fr), details, highlight })
const tag = (v) => `https://github.com/example/app/releases/tag/v${v}`
const MADE_UP = {
  current: '9.0.0',
  versions: [
    { version: 'Unreleased', date: '', unreleased: true, title: {}, intro: '', known_limits: [], url: '',
      changes: [ch('added', 'A made-up change not released yet, with `code`', 'Un changement fictif pas encore publié, avec du `code`', { details: 'A **made-up** change that is not released yet, with a [link](https://example.com).' })] },
    { version: '9.1.0', date: '2031-03-02', unreleased: false, url: tag('9.1.0'),
      title: w('Every type of change, and a title long enough to be cut at the end of its row on a narrow window', 'Tous les types de changement, et un titre assez long pour être coupé au bout de sa ligne'),
      intro: 'A made-up release with every type of change, to show their labels in both themes.\n\nIts second paragraph.',
      known_limits: ['The packages are not signed.', 'An exported calendar is not updated by itself.'],
      changes: [
        ch('changed', 'Dates are written one way everywhere', 'Les dates s’écrivent partout de la même façon', { details: 'Everywhere in the interface.' }),
        ch('deprecated', 'The old setting will go in 10.0', 'L’ancien réglage disparaîtra en 10.0'),
        ch('added', 'Calendar export', 'Export de l’agenda', { highlight: true, details: 'An `.ics` file of what the page shows:\n\n- one event per item\n- reminders included' }),
        ch('removed', 'The legacy importer', 'L’ancien importateur'),
        ch('fixed', 'A menu stays open', 'Un menu reste ouvert', { highlight: true, details: 'It no longer closes the moment it opens.' }),
        ch('fixed', 'A calendar item keeps its time', 'Un élément de l’agenda garde son heure'),
        ch('security', 'Requests from other sites refused', 'Les requêtes d’autres sites refusées', { highlight: true }),
        ch('added', 'A second added thing, only in English'),
      ] },
    { version: '9.0.0', date: '2030-12-24', unreleased: false, url: tag('9.0.0'), title: w('A title only in English'), intro: '', known_limits: [],
      changes: [ch('fixed', 'One fix, without details', 'Une correction, sans détails')] },
  ],
}
</script>

<template>
  <p class="lab-note">Made-up versions (running: 9.0.0, so "Latest" and "Current" are on two rows): titles and summaries in the interface's language (English where there is none, marked), every type, more than six changes (9.1.0: highlights first), a single change without details (9.0.0), unreleased changes. All closed at first; one open at a time.</p>
  <div class="lab-box" data-lab-changelog="made-up"><ChangelogTab :data="MADE_UP" :address="false" /></div>
  <p class="lab-note" style="margin-top: 16px">The program's own release history (releases.json and the pending change fragments; running version from the server); a deep link (?v=) opens its version once</p>
  <div class="lab-box" data-lab-changelog="real"><ChangelogTab /></div>
  <p class="lab-note" style="margin-top: 16px">The program's components and their licences (the installed packages)</p>
  <div class="lab-box" data-lab-licenses="real"><LicensesTab /></div>
</template>

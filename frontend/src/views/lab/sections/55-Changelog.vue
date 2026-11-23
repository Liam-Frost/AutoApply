<script setup>
// Lab: the about page's Changelog and Licenses tabs. First the changelog on made-up versions (nothing here is a real
// release): titles and highlights in three languages, every kind of change, highlights taken from the notes of a
// version without an entry (English, `derived`), one with none at all, one without a date and one without a link, and
// unreleased changes. It keeps its open version to itself (address=false). Then both tabs as they read the program's
// own CHANGELOG.md and highlights.json, and its installed packages - that one keeps the open version in the address.
import ChangelogTab from '../../about/ChangelogTab.vue'
import LicensesTab from '../../about/LicensesTab.vue'

// (English and French only: the lab writes no Chinese of its own - in Chinese these fall back to English, as a
// version without its translation would; the real changelog below has all three)
const w = (en, fr) => ({ en, fr })
const MADE_UP = {
  current: '9.0.0',
  versions: [
    { version: 'Unreleased', date: '', unreleased: true, summary: '', url: 'https://github.com/example/app/compare/v9.1.0...HEAD',
      title: w('Made-up work in progress', 'Travail fictif en cours'),
      highlights: [{ kind: 'added', title: w('A made-up change not released yet', 'Un changement fictif pas encore publié'), text: w('With a `code` part and *emphasis*.', 'Avec du `code` et de l’*emphase*.') }],
      sections: [{ kind: 'added', title: 'Added', text: '', items: ['A **made-up** change that is not released yet, with a [link](https://example.com).'] }] },
    { version: '9.1.0', date: '2031-03-02', unreleased: false, url: 'https://github.com/example/app/compare/v9.0.0...v9.1.0',
      summary: 'A made-up release with every kind of change, to show their labels in both themes.',
      title: w('Every kind of change, and a title long enough to be cut at the end of its row on a narrow window', 'Tous les types de changement, et un titre assez long pour être coupé au bout de sa ligne'),
      highlights: [
        { kind: 'added', title: w('Calendar export', 'Export de l’agenda'), text: w('An .ics file of what the page shows.', 'Un fichier .ics de ce que montre la page.') },
        { kind: 'added', title: w('A second added thing', 'Un deuxième ajout') },
        { kind: 'changed', title: w('Dates written one way', 'Les dates écrites d’une seule façon'), text: w('Everywhere in the interface.', 'Partout dans l’interface.') },
        { kind: 'fixed', title: w('A menu stays open', 'Un menu reste ouvert'), text: w('It no longer closes the moment it opens.', 'Il ne se ferme plus dès qu’il s’ouvre.') },
        { kind: 'security', title: w('Requests from other sites refused', 'Les requêtes d’autres sites refusées') },
        { kind: 'known', title: w('The packages are not signed', 'Les paquets ne sont pas signés') },
      ],
      sections: [
        { kind: 'breaking', title: 'Breaking changes', text: '', items: ['The old export format is no longer read.'] },
        { kind: 'security', title: 'Security', text: '', items: ['A request from another origin is refused.'] },
        { kind: 'added', title: 'Added', text: '', items: ['**Calendar export**: an `.ics` file of what the page shows.\n- One event per item\n- Reminders included', 'A second added thing.'] },
        { kind: 'changed', title: 'Changed', text: '', items: ['Dates are written one way everywhere.'] },
        { kind: 'fixed', title: 'Fixed', text: '', items: ['A menu no longer closes the moment it opens.', 'A calendar item keeps its time.'] },
        { kind: 'deprecated', title: 'Deprecated', text: '', items: ['The old setting will go in 10.0.'] },
        { kind: 'removed', title: 'Removed', text: '', items: ['The legacy importer.'] },
        { kind: 'known', title: 'Known limits', text: '', items: ['The packages are not signed.'] },
        { kind: 'other', title: 'A heading of its own', text: 'A paragraph that is not a bullet.', items: ['And a bullet under it.'] },
      ] },
    { version: '9.0.0', date: '2030-12-24', unreleased: false, url: '', summary: '', title: {},
      highlights: [{ kind: 'added', title: { en: 'Feature taken from the notes' }, derived: true }, { kind: 'fixed', title: { en: 'Fix taken from the notes' }, derived: true }],
      sections: [{ kind: 'added', title: 'Added', text: '', items: ['**Feature taken from the notes**: no entry in highlights.json for this version.'] }, { kind: 'fixed', title: 'Fixed', text: '', items: ['**Fix taken from the notes**, and no link reference.'] }] },
    { version: '8.9.9', date: '', unreleased: false, url: 'https://github.com/example/app/releases/tag/v8.9.9', summary: 'No date is written for this version, and its notes name nothing in bold.', title: {}, highlights: [], sections: [] },
  ],
}
</script>

<template>
  <p class="lab-note">Made-up versions (running: 9.0.0, so "Latest" and "Current" are on two rows): titles and highlights in the interface's language, every kind, highlights taken from the notes (9.0.0), none at all and no date (8.9.9), unreleased changes. All closed at first; one open at a time.</p>
  <div class="lab-box" data-lab-changelog="made-up"><ChangelogTab :data="MADE_UP" :address="false" /></div>
  <p class="lab-note" style="margin-top: 16px">The program's own CHANGELOG.md and highlights.json (running version from the server); the open version is in the address (?v=)</p>
  <div class="lab-box" data-lab-changelog="real"><ChangelogTab /></div>
  <p class="lab-note" style="margin-top: 16px">The program's components and their licences (the installed packages)</p>
  <div class="lab-box" data-lab-licenses="real"><LicensesTab /></div>
</template>

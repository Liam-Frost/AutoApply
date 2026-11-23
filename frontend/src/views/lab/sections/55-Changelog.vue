<script setup>
// Lab: the about page's Changelog and Licenses tabs. First the timeline on made-up versions that have every kind of
// change, a version without a date and one without a link (nothing here is a real release); then both tabs as they
// read the program's own CHANGELOG.md and its installed packages.
import ChangelogTab from '../../about/ChangelogTab.vue'
import LicensesTab from '../../about/LicensesTab.vue'

const MADE_UP = {
  current: '9.1.0',
  versions: [
    { version: 'Unreleased', date: '', unreleased: true, summary: '', url: 'https://github.com/example/app/compare/v9.1.0...HEAD',
      sections: [{ kind: 'added', title: 'Added', text: '', items: ['A **made-up** change that is not released yet, with a [link](https://example.com).'] }] },
    { version: '9.1.0', date: '2031-03-02', unreleased: false, url: 'https://github.com/example/app/compare/v9.0.0...v9.1.0',
      summary: 'A made-up release with every kind of change, to show their labels in both themes.',
      sections: [
        { kind: 'breaking', title: 'Breaking changes', text: '', items: ['The old export format is no longer read.'] },
        { kind: 'security', title: 'Security', text: '', items: ['A request from another origin is refused.'] },
        { kind: 'added', title: 'Added', text: '', items: ['**Calendar export**: an `.ics` file of what the page shows.\n- One event per item\n- Reminders included', 'A second added thing.'] },
        { kind: 'changed', title: 'Changed', text: '', items: ['Dates are written one way everywhere.'] },
        { kind: 'fixed', title: 'Fixed', text: '', items: ['A menu no longer closes the moment it opens.'] },
        { kind: 'deprecated', title: 'Deprecated', text: '', items: ['The old setting will go in 10.0.'] },
        { kind: 'removed', title: 'Removed', text: '', items: ['The legacy importer.'] },
        { kind: 'known', title: 'Known limits', text: '', items: ['The packages are not signed.'] },
        { kind: 'other', title: 'A heading of its own', text: 'A paragraph that is not a bullet.', items: ['And a bullet under it.'] },
      ] },
    { version: '9.0.0', date: '2030-12-24', unreleased: false, url: '', summary: '', sections: [{ kind: 'fixed', title: 'Fixed', text: '', items: ['No link reference for this version.'] }] },
    { version: '8.9.9', date: '', unreleased: false, url: 'https://github.com/example/app/releases/tag/v8.9.9', summary: 'No date is written for this version.', sections: [] },
  ],
}
</script>

<template>
  <p class="lab-note">Made-up versions (current: 9.1.0): every kind of change, the unreleased entry, a version without a link, one without a date</p>
  <div class="lab-box" data-lab-changelog="made-up"><ChangelogTab :data="MADE_UP" /></div>
  <p class="lab-note" style="margin-top: 16px">The program's own CHANGELOG.md (running version from the server)</p>
  <div class="lab-box" data-lab-changelog="real"><ChangelogTab /></div>
  <p class="lab-note" style="margin-top: 16px">The program's components and their licences (the installed packages)</p>
  <div class="lab-box" data-lab-licenses="real"><LicensesTab /></div>
</template>

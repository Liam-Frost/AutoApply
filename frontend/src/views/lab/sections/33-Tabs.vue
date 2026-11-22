<script setup>
// Lab: the row of tabs - counts, a disabled tab, many tabs in a narrow box (one line that scrolls inside itself), and
// the program's own words in the language that is set (the applications page's groups). Every count is made up.
import { computed, ref } from 'vue'
import { t as T } from '../../../i18n/catalog'
import Tabs from '../../../components/Tabs.vue'

const plain = ref('all')
const PLAIN = [
  { id: 'all', label: 'All', count: 24 },
  { id: 'open', label: 'Open', count: 9 },
  { id: 'sent', label: 'Sent', count: 0 },
  { id: 'later', label: 'Later', disabled: true },
  { id: 'archive', label: 'Archive' },
]
const many = ref('t3')
const MANY = Array.from({ length: 14 }, (_, i) => ({ id: 't' + i, label: ['Interviews', 'Assessments', 'Waiting for a code', 'Ready to submit', 'Needs answers'][i % 5] + ' ' + (i + 1), count: (i * 7) % 23, disabled: i === 5 }))
const group = ref('me')
const GROUPS = ['me', 'agent', 'sent', 'progress', 'ended', 'archived']
const words = computed(() => GROUPS.map((g, i) => ({ id: g, label: T('applications.group.' + g), count: [3, 1, 128, 6, 40, 1024][i] })))
</script>

<template>
  <p class="lab-note">Counts in a low weight; "Later" is disabled. The arrows, Home and End move and select; Tab leaves the row. Selected: <b data-t="tab-plain">{{ plain }}</b></p>
  <div class="lab-row" data-tabs="plain"><Tabs id="lab-tabs-plain" v-model="plain" label="Lab: plain tabs" :items="PLAIN" controls="lab-tabs-panel" /></div>
  <div id="lab-tabs-panel" class="lab-box" role="tabpanel" :aria-labelledby="'lab-tabs-plain-' + plain" style="margin-bottom: 12px">Panel of “{{ plain }}”</div>

  <p class="lab-note">Fourteen tabs in a box of 360px: one line, scrolled sideways inside the row (wheel, or the keyboard brings the selected one into view). Selected: <b data-t="tab-many">{{ many }}</b></p>
  <div class="lab-box" data-tabs="narrow" style="width: 360px; max-width: 100%"><Tabs v-model="many" label="Lab: many tabs" :items="MANY" /></div>

  <p class="lab-note" style="margin-top: 12px">The program's own words, in the language that is set</p>
  <div class="lab-row" data-tabs="words"><Tabs v-model="group" :label="$t('applications.groupsLabel')" :items="words" /></div>
</template>

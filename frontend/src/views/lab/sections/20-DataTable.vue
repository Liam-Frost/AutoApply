<script setup>
// Lab: the DataTable in its states. Every row is made up. The same columns are shown with short and with absurd values
// (the widths must not differ), in the three densities, in boxes of several widths (optional columns go, then the
// table scrolls inside its box), empty, with an opened row and with a body that scrolls under its header.
import { computed, ref, shallowReactive } from 'vue'
import DataTable from '../../../components/DataTable.vue'
import DateTimeCell from '../../../components/cells/DateTimeCell.vue'
import EntityCell from '../../../components/cells/EntityCell.vue'
import EmptyState from '../../../components/EmptyState.vue'
import IconButton from '../../../components/IconButton.vue'
import Status from '../../../components/Status.vue'

// (written as escapes: the interface's code holds no Chinese text of its own - tests/i18n.test.js)
const CJK = {
  company: '\u4e0a\u6d77\u4e91\u56fe\u667a\u80fd\u79d1\u6280\u6709\u9650\u516c\u53f8\u534e\u4e1c\u533a\u57df\u7814\u53d1\u4e2d\u5fc3\u4eba\u5de5\u667a\u80fd\u4e0e\u5927\u6570\u636e\u5e73\u53f0\u4e8b\u4e1a\u90e8\u524d\u7aef\u57fa\u7840\u8bbe\u65bd\u4e0e\u8bbe\u8ba1\u7cfb\u7edf\u7ec4',
  title: '\u9ad8\u7ea7\u524d\u7aef\u5f00\u53d1\u5de5\u7a0b\u5e08\uff08\u6570\u636e\u53ef\u89c6\u5316\u4e0e\u8bbe\u8ba1\u7cfb\u7edf\u65b9\u5411\uff0c\u63a5\u53d7\u5e94\u5c4a\u6bd5\u4e1a\u751f\u4e0e\u5b9e\u4e60\u751f\uff0c\u5de5\u4f5c\u5730\u70b9\u4e0a\u6d77\u6216\u8fdc\u7a0b\uff0c\u9700\u8981\u6bcf\u5468\u5230\u5c97\u4e09\u5929\uff09',
  short1: '\u5317\u6781\u661f\u79d1\u6280',
  short2: '\u8f6f\u4ef6\u5de5\u7a0b\u5b9e\u4e60\u751f',
  status: '\u7b49\u5f85\u9a8c\u8bc1',
  site: '\u5b98\u7f51',
}
const LONG = {
  company: 'International Consolidated Aerospace, Defence and Advanced Manufacturing Systems Holdings (North America) Incorporated, Western Canada Regional Engineering and Digital Transformation Centre of Excellence',
  title: 'Senior Staff Software Engineer, Distributed Systems and Developer Productivity Platform (Hybrid, Vancouver or Toronto; 12-month fixed term with a possible extension; co-op and new-graduate applicants welcome)',
  url: 'https://careers.example-enterprise-solutions.com/en-CA/jobs/requisition/R-2026-0001847-senior-staff-software-engineer-distributed-systems?source=university-portal&utm_campaign=fall-recruiting-2026',
  mail: 'talent-acquisition.university-recruiting.north-america.western-region@careers.example-enterprise-solutions.com',
  status: 'Waiting for the verification code that was sent to the mailbox',
}

const cols = [
  { id: 'job', header: 'Company / role', min: 220, flex: 3, sortable: true },
  { id: 'status', header: 'Status', width: 150 },
  { id: 'site', header: 'Where it was found', min: 130, max: 220, priority: 2, headerTip: 'The site the posting was read from' },
  { id: 'contact', header: 'Contact', min: 140, max: 240, priority: 3 },
  { id: 'applied', header: 'Applied', min: 110, max: 140, sortable: true, priority: 1 },
  { id: 'score', header: 'Score', width: 76, align: 'end', class: 'num', sortable: true, priority: 4 },
  { id: 'more', header: '', width: 52, align: 'end' },
]

const short = [
  { id: 1, company: 'Northwind', title: 'Software Engineer Intern', tone: 'ok', status: 'Submitted', site: 'Workday', contact: 'jobs@northwind.example', applied: 'Nov 18', note: '4 days ago', score: 92 },
  { id: 2, company: 'Acme Robotics', title: 'Firmware Co-op', tone: 'warn', status: 'Needs you', site: 'Greenhouse', contact: 'hr@acme.example', applied: 'Nov 12', note: '10 days ago', score: 78 },
  { id: 3, company: 'Globex', title: 'Data Analyst', tone: '', status: 'Draft', site: 'Employer site', contact: '', applied: '', note: '', score: 61 },
  { id: 4, company: CJK.short1, title: CJK.short2, tone: 'info', status: CJK.status, site: CJK.site, contact: 'hr@polaris.example', applied: 'Nov 3', note: '19 days ago', score: 100 },
  { id: 5, company: 'Initech', title: '', tone: 'bad', status: 'Failed', site: 'Lever', contact: 'talent@initech.example', applied: 'Oct 29', note: '24 days ago', score: 7 },
]
// the same rows with values no column was drawn for
const absurd = [
  { id: 1, company: LONG.company, title: LONG.title, tone: 'ok', status: 'Submitted', site: LONG.url, contact: LONG.mail, applied: 'Nov 18', note: '4 days ago', score: 92 },
  { id: 2, company: CJK.company, title: CJK.title, tone: 'warn', status: LONG.status, site: CJK.company, contact: 'hr@acme.example', applied: 'Wednesday, November 12, 2026 at 23:59 (Pacific Standard Time)', note: 'ten days and four hours ago', score: 78 },
  { id: 3, company: LONG.company, title: '', tone: '', status: 'Draft', site: 'Employer site', contact: '', applied: '', note: '', score: 61 },
  { id: 4, company: CJK.short1 + ' / ' + LONG.company, title: CJK.title + ' ' + LONG.title, tone: 'info', status: CJK.status, site: CJK.site, contact: LONG.mail, applied: 'Nov 3', note: '19 days ago', score: 1234567890 },
  { id: 5, company: LONG.url, title: LONG.mail, tone: 'bad', status: 'Failed', site: 'Lever', contact: LONG.url, applied: 'Oct 29', note: '24 days ago', score: 7 },
]

// \u2500\u2500 the whole table: ticking, sorting (the page sorts), opening a row, a row that is a target
const picked = ref(new Set([2]))
const sort = ref({ by: 'score', dir: 'desc' })
const density = ref('comfortable')
const opened = ref(null)
const last = ref('')
const key = { job: (r) => r.company.toLowerCase(), applied: (r) => r.id, score: (r) => r.score }
const sorted = (rows) => {
  const by = key[sort.value.by]
  if (!by) return rows
  return [...rows].sort((a, b) => (by(a) < by(b) ? -1 : by(a) > by(b) ? 1 : 0) * (sort.value.dir === 'desc' ? -1 : 1))
}
const shownShort = computed(() => sorted(short))
const shownAbsurd = computed(() => sorted(absurd))
const toggle = (row) => { opened.value = opened.value === row.id ? null : row.id }

// \u2500\u2500 boxes of several widths: what the table decided in each (read from the component)
const BOXES = [1200, 900, 640, 420]
const tables = shallowReactive({})
const hidden = (w) => (tables[w] ? cols.filter((c) => !tables[w].layout.visible.includes(c.id)).map((c) => c.header || c.id) : [])

// \u2500\u2500 a long list under a header that stays
const many = Array.from({ length: 24 }, (_, i) => ({ ...absurd[i % absurd.length], id: i + 1, score: (i * 37) % 101 }))
const simple = [
  { id: 'name', header: 'Name', min: 160, flex: 2 },
  { id: 'kind', header: 'Kind', width: 120 },
  { id: 'size', header: 'Size', width: 90, align: 'end', class: 'num' },
  { id: 'changed', header: 'Changed', min: 110, max: 150, priority: 1 },
]
const files = [
  { id: 1, name: 'resume-2026-software.pdf', kind: 'Resume', size: '182 KB', changed: 'Nov 20' },
  { id: 2, name: LONG.title + '.docx', kind: 'Cover letter', size: '48 KB', changed: 'Nov 19' },
  { id: 3, name: 'transcript.pdf', kind: '', size: '1,204 KB', changed: '' },
]
</script>

<template>
  <div class="lab-row">
    <span class="lab-note">Density</span>
    <button v-for="d in ['compact', 'standard', 'comfortable']" :key="d" class="sm" :class="{ primary: density === d }" :aria-pressed="density === d" @click="density = d">{{ d }}</button>
    <span class="lab-note">ticked: {{ [...picked].join(', ') || 'none' }} · sort: {{ sort.by }} {{ sort.dir }} · last row pressed: {{ last || 'none' }}</span>
  </div>

  <p class="lab-note">Short values - selectable, sortable, clickable; the chevron opens a row</p>
  <div data-dt="short">
    <DataTable v-model:selected="picked" v-model:sort="sort" :columns="cols" :rows="shownShort" :density="density" selectable clickable label="Applications (short values)"
               :select-label="(r) => 'Select ' + r.company" select-all-label="Select every application" :expanded-key="opened" @row="(r) => (last = r.company)">
      <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" :to="'/ui-lab?only=DataTable,Cells&row=' + row.id" /></template>
      <template #cell-status="{ row }"><Status :tone="row.tone" :label="row.status" /></template>
      <template #cell-applied="{ row }"><DateTimeCell :primary="row.applied" :secondary="row.note" /></template>
      <template #cell-more="{ row }"><IconButton :icon="opened === row.id ? 'chevron_up' : 'chevron'" :label="opened === row.id ? 'Close the details' : 'Open the details'" :pressed="opened === row.id" @click="toggle(row)" /></template>
      <template #expanded="{ row }"><p class="lab-note">Opened on purpose: this row is as high as what it holds.</p><p>{{ row.company }} - {{ row.title || 'no title' }}. A reason, a diagnosis or a mail's text belongs here or on the row's page, never in a cell.</p></template>
    </DataTable>
  </div>

  <p class="lab-note" style="margin-top: 16px">The same columns, absurd values - every column is exactly as wide as above and every row as high</p>
  <div data-dt="absurd">
    <DataTable v-model:selected="picked" v-model:sort="sort" :columns="cols" :rows="shownAbsurd" :density="density" selectable clickable label="Applications (absurd values)"
               :select-label="(r) => 'Select ' + r.company" :expanded-key="opened" @row="(r) => (last = r.company)">
      <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" :to="'/ui-lab?only=DataTable,Cells&row=' + row.id" /></template>
      <template #cell-status="{ row }"><Status :tone="row.tone" :label="row.status" /></template>
      <template #cell-applied="{ row }"><DateTimeCell :primary="row.applied" :secondary="row.note" /></template>
      <template #cell-more="{ row }"><IconButton :icon="opened === row.id ? 'chevron_up' : 'chevron'" :label="opened === row.id ? 'Close the details' : 'Open the details'" :pressed="opened === row.id" @click="toggle(row)" /></template>
      <template #expanded="{ row }"><p>{{ row.company }}</p><p>{{ row.title }}</p></template>
    </DataTable>
  </div>

  <template v-for="d in ['compact', 'standard', 'comfortable']" :key="d">
    <p class="lab-note" style="margin-top: 16px">Density: {{ d }}</p>
    <div :data-dt="'density-' + d">
      <DataTable :columns="cols" :rows="absurd.slice(0, 4)" :density="d" :label="'Density ' + d">
        <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" /></template>
        <template #cell-status="{ row }"><Status :tone="row.tone" :label="row.status" /></template>
        <template #cell-applied="{ row }"><DateTimeCell :primary="row.applied" :secondary="row.note" /></template>
        <template #cell-more><IconButton icon="more" label="More" /></template>
      </DataTable>
    </div>
  </template>

  <template v-for="w in BOXES" :key="w">
    <p class="lab-note" style="margin-top: 16px">
      In a box of {{ w }}px (now {{ tables[w] ? tables[w].layout.total : '?' }}px of table) - hidden: {{ hidden(w).join(', ') || 'nothing' }}{{ tables[w] && tables[w].layout.scroll ? ' - scrolls inside its box' : '' }}
    </p>
    <div :data-dt="'box-' + w" :style="{ width: w + 'px', maxWidth: '100%' }">
      <DataTable :ref="(el) => { if (el) tables[w] = el }" :columns="cols" :rows="absurd" selectable :label="'Box of ' + w">
        <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" /></template>
        <template #cell-status="{ row }"><Status :tone="row.tone" :label="row.status" /></template>
        <template #cell-applied="{ row }"><DateTimeCell :primary="row.applied" :secondary="row.note" /></template>
        <template #cell-more><IconButton icon="more" label="More" /></template>
      </DataTable>
    </div>
  </template>

  <p class="lab-note" style="margin-top: 16px">Nothing to show: the header stays</p>
  <div data-dt="empty">
    <DataTable :columns="cols" :rows="[]" selectable label="Empty table">
      <template #empty><EmptyState icon="inbox" title="No applications yet" text="What you send will be listed here." /></template>
    </DataTable>
  </div>

  <p class="lab-note" style="margin-top: 16px">A long list in 280px: the body scrolls under the header (maxHeight)</p>
  <div data-dt="tall">
    <DataTable :columns="cols" :rows="many" density="compact" :max-height="280" label="Long list">
      <template #cell-job="{ row }"><EntityCell :primary="row.company" /></template>
      <template #cell-status="{ row }"><Status :tone="row.tone" :label="row.status" /></template>
      <template #cell-more><IconButton icon="more" label="More" /></template>
    </DataTable>
  </div>

  <p class="lab-note" style="margin-top: 16px">Inside a card, without a frame of its own (class "bare"); plain values, a number column, an empty value</p>
  <div class="card" data-dt="bare">
    <DataTable class="bare" :columns="simple" :rows="files" density="compact" label="Files" />
  </div>
</template>

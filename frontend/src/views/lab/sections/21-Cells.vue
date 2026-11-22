<script setup>
// Lab: the cells of a DataTable - EntityCell and DateTimeCell in every variant, in a table and on their own in a
// narrow box (they cut themselves wherever they stand). Every value is made up.
import DataTable from '../../../components/DataTable.vue'
import DateTimeCell from '../../../components/cells/DateTimeCell.vue'
import EntityCell from '../../../components/cells/EntityCell.vue'
import Status from '../../../components/Status.vue'
import Trunc from '../../../components/Trunc.vue'

const LONG = 'International Consolidated Aerospace, Defence and Advanced Manufacturing Systems Holdings (North America) Incorporated, Western Canada Regional Engineering and Digital Transformation Centre of Excellence'
const CJK = '\u4e0a\u6d77\u4e91\u56fe\u667a\u80fd\u79d1\u6280\u6709\u9650\u516c\u53f8\u534e\u4e1c\u533a\u57df\u7814\u53d1\u4e2d\u5fc3\u4eba\u5de5\u667a\u80fd\u4e0e\u5927\u6570\u636e\u5e73\u53f0\u4e8b\u4e1a\u90e8\u524d\u7aef\u57fa\u7840\u8bbe\u65bd\u4e0e\u8bbe\u8ba1\u7cfb\u7edf\u7ec4'
const URL = 'https://careers.example-enterprise-solutions.com/en-CA/jobs/requisition/R-2026-0001847-senior-staff-software-engineer?source=university-portal'
const MAIL = 'talent-acquisition.university-recruiting.north-america.western-region@careers.example-enterprise-solutions.com'

const entityCols = [
  { id: 'what', header: 'Variant', width: 200 },
  { id: 'cell', header: 'EntityCell', min: 200, flex: 1 },
  { id: 'narrow', header: 'The same, 160px', width: 160 },
]
const entities = [
  { id: 1, what: 'two lines', primary: 'Northwind', secondary: 'Software Engineer Intern' },
  { id: 2, what: 'no second line: centred', primary: 'Northwind' },
  { id: 3, what: 'a link', primary: 'Acme Robotics', secondary: 'Firmware Co-op', to: '/ui-lab?only=DataTable,Cells' },
  { id: 4, what: 'a mark after the main line', primary: 'Globex', secondary: 'Data Analyst', after: 'New' },
  { id: 5, what: 'long, with a mark and a link', primary: LONG, secondary: LONG, to: '/ui-lab?only=DataTable,Cells', after: 'Interview' },
  { id: 6, what: 'long text without spaces', primary: URL, secondary: MAIL },
  { id: 7, what: 'long CJK text', primary: CJK, secondary: CJK, after: 'New' },
  { id: 8, what: 'long, no second line', primary: LONG },
]

const dateCols = [
  { id: 'what', header: 'Variant', width: 200 },
  { id: 'cell', header: 'DateTimeCell', min: 140, flex: 1 },
  { id: 'narrow', header: 'The same, 96px', width: 96 },
  { id: 'end', header: 'At the end', width: 150, align: 'end' },
]
const dates = [
  { id: 1, what: 'a date alone', primary: 'Nov 18' },
  { id: 2, what: 'with what it is', primary: 'Nov 18, 14:30', secondary: 'Interview' },
  { id: 3, what: 'tone warn', primary: 'Nov 24', secondary: 'in 2 days', tone: 'warn' },
  { id: 4, what: 'tone bad', primary: 'Nov 20', secondary: '2 days overdue', tone: 'bad' },
  { id: 5, what: 'tone muted', primary: 'Oct 2', secondary: 'closed', tone: 'muted' },
  { id: 6, what: 'with a tooltip', primary: 'Dec 1, 09:00', secondary: 'Assessment', tip: 'Tuesday, December 1, 2026 at 09:00 (Pacific time) - online assessment, 90 minutes' },
  { id: 7, what: 'far too long', primary: 'Wednesday, November 12, 2026 at 23:59 (Pacific Standard Time)', secondary: 'ten days, four hours and thirty-one minutes ago', tone: 'warn' },
  { id: 8, what: 'nothing', primary: '' },
]

const plainCols = [
  { id: 'what', header: 'Variant', width: 200 },
  { id: 'value', header: 'A header far longer than the column it stands over is cut like any other text', min: 160, flex: 1, headerTip: 'What this column means, in a sentence' },
  { id: 'count', header: 'Count', width: 110, align: 'end', class: 'num', sortable: true },
  { id: 'state', header: 'State', width: 150, align: 'center' },
]
const plain = [
  { id: 1, what: 'a plain value (no slot)', value: 'Workday', count: 12, tone: 'ok', state: 'Ready' },
  { id: 2, what: 'a long plain value', value: LONG, count: 1111111, tone: 'warn', state: 'Waiting for you' },
  { id: 3, what: 'no value: the marker', value: '', count: null, tone: '', state: 'Off' },
  { id: 4, what: 'a URL', value: URL, count: 0, tone: 'bad', state: 'Failed' },
  { id: 5, what: 'two lines at most (Trunc lines 2)', value: LONG + ' ' + LONG, two: true, count: 7, tone: 'info', state: 'Checking' },
]
</script>

<template>
  <p class="lab-note">EntityCell</p>
  <div data-dt="entity">
    <DataTable :columns="entityCols" :rows="entities" density="standard" label="EntityCell variants">
      <template #cell-cell="{ row }">
        <EntityCell :primary="row.primary" :secondary="row.secondary" :to="row.to"><template v-if="row.after" #after><span class="tag info">{{ row.after }}</span></template></EntityCell>
      </template>
      <template #cell-narrow="{ row }">
        <EntityCell :primary="row.primary" :secondary="row.secondary" :to="row.to"><template v-if="row.after" #after><span class="tag info">{{ row.after }}</span></template></EntityCell>
      </template>
    </DataTable>
  </div>

  <p class="lab-note" style="margin-top: 16px">EntityCell outside a table, in boxes of 240px</p>
  <div class="lab-row" data-dt="entity-free">
    <div v-for="row in entities.slice(2, 7)" :key="row.id" class="lab-box" style="width: 240px">
      <EntityCell :primary="row.primary" :secondary="row.secondary" :to="row.to"><template v-if="row.after" #after><span class="tag info">{{ row.after }}</span></template></EntityCell>
    </div>
  </div>

  <p class="lab-note" style="margin-top: 16px">DateTimeCell</p>
  <div data-dt="date">
    <DataTable :columns="dateCols" :rows="dates" density="standard" label="DateTimeCell variants">
      <template #cell-cell="{ row }"><DateTimeCell :primary="row.primary" :secondary="row.secondary" :tone="row.tone" :tip="row.tip" /></template>
      <template #cell-narrow="{ row }"><DateTimeCell :primary="row.primary" :secondary="row.secondary" :tone="row.tone" :tip="row.tip" /></template>
      <template #cell-end="{ row }"><DateTimeCell :primary="row.primary" :secondary="row.secondary" :tone="row.tone" :tip="row.tip" /></template>
    </DataTable>
  </div>

  <p class="lab-note" style="margin-top: 16px">Plain values, a number column at the end, a centred column, a header that is cut, a header with help</p>
  <div data-dt="plain">
    <DataTable :columns="plainCols" :rows="plain" density="standard" label="Plain cells">
      <template #cell-value="{ row }">
        <Trunc v-if="row.two" :text="row.value" :lines="2" />
        <Trunc v-else-if="row.value" :text="row.value" />
        <span v-else class="none">—</span>
      </template>
      <template #cell-state="{ row }"><Status :tone="row.tone" :label="row.state" /></template>
    </DataTable>
  </div>
</template>

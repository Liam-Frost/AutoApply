<script setup>
import { t as T } from '../../i18n/catalog'
// Outcomes, second part: how quickly the work moves and what waits for the applicant. Three layers, each sized by
// what it holds:
//   1. one card of plain figures - from a posting found (or an application started) to its first record, the to-dos
//      open now, the to-dos handled in the period;
//   2. two lists - the to-dos handled, by kind (the first few; the rest behind a control), and the to-dos that have
//      waited longest - side by side only when they are of about one height (layout.js), else one under the other;
//      a list with nothing in it is not drawn (its figure in layer 1 says 0);
//   3. (AppsPanel) the rest, each card on its own row.
import { computed } from 'vue'
import { hours } from '../../analytics'
import { dayText } from '../../i18n/format'
import CardHead from '../../components/CardHead.vue'
import DataTable from '../../components/DataTable.vue'
import Popover from '../../components/Popover.vue'
import Status from '../../components/Status.vue'
import EntityCell from '../../components/cells/EntityCell.vue'
import Kpi from './Kpi.vue'
import { H, pairs, splitTop, standing, table } from './layout'

const props = defineProps({ first: { type: Object, default: null }, backlog: { type: Object, default: null } })
const f = computed(() => props.first || { n: 0, from_found_hours: null, from_begun_hours: null, slow: 0 })
const b = computed(() => props.backlog || { handled: 0, median_hours: null, by_kind: [], open: 0, snoozed: 0, oldest: [] })

// by kind: the first five (six when that is all), the rest behind a popover - the card does not grow when it opens
const kinds = computed(() => splitTop(b.value.by_kind, 5))
const KIND_COLS = [
  { id: 'label', header: T('analytics.backlog.kind'), min: 120 },
  { id: 'n', header: T('analytics.backlog.handled'), width: 72, align: 'end' },
  { id: 'median', header: T('analytics.backlog.median'), width: 124, align: 'end' },
]
const OLD_COLS = [
  { id: 'item', header: T('analytics.backlog.item'), min: 180 },
  { id: 'state', header: T('analytics.backlog.state'), width: 176, priority: 1 },
  { id: 'waited', header: T('analytics.backlog.waited'), width: 120, align: 'end' },
]
const oldest = computed(() => b.value.oldest.map((o) => ({ ...o, st: standing(o) })))
const stateLabel = (s) => (s.day ? T('analytics.backlog.st.' + s.key, { day: dayText(s.day) }) : T('analytics.backlog.st.' + s.key))
// the posting a to-do is about, when its title does not already say it
const about = (o) => (o.company && !String(o.title).includes(o.company) ? o.company + (o.job_title ? ' · ' + o.job_title : '') : '')

// side by side when of about one height (the compact table's rows are 40px, the list's two-line rows 56px)
const kindsTall = computed(() => (kinds.value.shown.length ? table(kinds.value.shown.length, { foot: kinds.value.rest.length ? H.foot : 0 }) : 0))
const oldTall = computed(() => (oldest.value.length ? table(oldest.value.length, { row: H.entity }) : 0))
const paired = computed(() => pairs(kindsTall.value, oldTall.value))
</script>

<template>
  <!-- 1. the figures -->
  <div class="card an-pace">
    <CardHead :title="$t('analytics.pace.title')">
      <template #help><p>{{ $t('analytics.first.explain') }}</p><p>{{ $t('analytics.backlog.explain') }}</p></template>
    </CardHead>
    <div class="kpis inline">
      <Kpi :value="hours(f.from_found_hours)" :tone="f.from_found_hours == null ? 'na' : ''" :label="$t('analytics.first.fromFound')">
        <div class="d">{{ f.n ? $t('analytics.pace.medianOf', { n: f.n }, f.n) : $t('analytics.pace.noRecords') }}</div>
        <div v-if="f.slow" class="d">{{ $t('analytics.first.slow', { n: f.slow }, f.slow) }}</div>
      </Kpi>
      <Kpi :value="hours(f.from_begun_hours)" :tone="f.from_begun_hours == null ? 'na' : ''" :label="$t('analytics.first.fromBegun')">
        <div class="d">{{ f.n ? $t('analytics.pace.medianOf', { n: f.n }, f.n) : $t('analytics.pace.noRecords') }}</div>
      </Kpi>
      <Kpi :value="b.open" :label="$t('analytics.pace.open')">
        <div v-if="b.oldest.length" class="d">{{ $t('analytics.pace.oldestWaits', { time: hours(b.oldest[0].hours) }) }}</div>
        <div v-if="b.snoozed" class="d">{{ $t('analytics.pace.snoozed', { n: b.snoozed }, b.snoozed) }}</div>
      </Kpi>
      <Kpi :value="b.handled" :label="$t('analytics.pace.handled')">
        <div v-if="b.median_hours != null" class="d">{{ $t('analytics.pace.medianWait', { time: hours(b.median_hours) }) }}</div>
      </Kpi>
    </div>
  </div>

  <!-- 2. the two lists -->
  <div v-if="kinds.shown.length || oldest.length" class="an-row" :class="{ c23: paired }">
    <div v-if="kinds.shown.length" class="card">
      <CardHead :title="$t('analytics.backlog.byKind')" :help="$t('analytics.backlog.byKindHelp')" />
      <DataTable class="bare" :columns="KIND_COLS" :rows="kinds.shown" row-key="kind" density="compact" :label="$t('analytics.backlog.byKind')">
        <template #cell-n="{ row }"><span class="num">{{ row.n }}</span></template>
        <template #cell-median="{ row }"><span class="num atomic">{{ hours(row.median_hours) }}</span></template>
      </DataTable>
      <div v-if="kinds.rest.length" class="card-foot">
        <Popover :label="$t('analytics.backlog.otherKinds')" :width="420">
          <template #trigger="{ toggle, attrs }"><button type="button" class="ghost sm" v-bind="attrs" @click="toggle">{{ $t('analytics.backlog.moreKinds', { n: kinds.rest.length }, kinds.rest.length) }}</button></template>
          <DataTable class="bare" :columns="KIND_COLS" :rows="kinds.rest" row-key="kind" density="compact" :label="$t('analytics.backlog.otherKinds')">
            <template #cell-n="{ row }"><span class="num">{{ row.n }}</span></template>
            <template #cell-median="{ row }"><span class="num atomic">{{ hours(row.median_hours) }}</span></template>
          </DataTable>
        </Popover>
      </div>
    </div>
    <div v-if="oldest.length" class="card">
      <CardHead :title="$t('analytics.backlog.oldest')" :help="$t('analytics.backlog.oldestHelp')">
        <router-link to="/todos" class="btn ghost sm">{{ $t('analytics.backlog.viewAll', { n: b.open }, b.open) }}</router-link>
      </CardHead>
      <DataTable class="bare" :columns="OLD_COLS" :rows="oldest" density="standard" :label="$t('analytics.backlog.oldest')">
        <template #cell-item="{ row }"><EntityCell :primary="row.title" :secondary="about(row) ? row.kind + ' · ' + about(row) : row.kind" to="/todos" /></template>
        <template #cell-state="{ row }"><Status :tone="row.st.tone" :label="stateLabel(row.st)" /></template>
        <template #cell-waited="{ row }"><span class="num atomic">{{ hours(row.hours) }}</span></template>
      </DataTable>
    </div>
  </div>
</template>

<script setup>
import { t as T } from '../i18n/catalog'
// Where postings come from: the employers that are watched, what the last scan read, the school's portal. It was
// three cards of the settings; it is looked at and added to all the time, and belongs with the postings.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import DataTable from '../components/DataTable.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EmployersPanel from '../components/EmployersPanel.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import SectionHead from '../components/SectionHead.vue'
import Status from '../components/Status.vue'
import TechDetails from '../components/TechDetails.vue'
import Trunc from '../components/Trunc.vue'
import { fmtTime, persona, run, toast } from '../ui'

// what each source gave when it was last read, why the rest was dropped, and where its postings stand now (discover.report)
const rep = ref({ at: null, sources: [], total: { read: 0, kept: 0, new: 0, dropped: [], now: {} } })
const open = ref(null)        // the source whose failure and reasons are shown in full (its row opened)
const bm = ref({ href: '' })
const portal = ref({ on: false, base: '', account: null })
async function load() {
  api.get('/sources/report').then((c) => (rep.value = c)).catch((e) => toast(e.message, 'bad'))
  if (persona.features.portal !== 'ubc') return
  api.get('/import/pdportal/bookmarklet').then((c) => (bm.value = c)).catch(() => {})
  const [st, accounts] = await Promise.all([api.get('/settings'), api.get('/accounts').catch(() => [])])
  portal.value = { on: !!st.settings['sources.pdportal'], base: st.settings['app.base_url'], account: accounts.find((a) => a.tenant_key === 'pdportal:ubc') || null }
}
const setPortal = (on) => run(() => api.put('/settings', { settings: { 'sources.pdportal': on } }), on ? T('sources.pdPortalIsRead') : T('sources.pdPortalIsNo'), load)
const portalLogin = () => run(() => api.post('/accounts/takeover', { tenant_key: 'pdportal:ubc', url: 'https://pdportal.apsc.ubc.ca/home.htm', save_credentials: false }), T('sources.aBrowserWindowIs'), load)
const scanNow = () => run(() => api.post('/tasks', { kind: 'discover' }), T('sources.scanStartedYoullBe'), load)
onMounted(load)

// --- the report as a table: one row per source, the figures right-aligned; what does not fit a row (the failure in
// full, every reason a posting was dropped) is in the row opened
const COLUMNS = computed(() => [
  { id: 'source', header: T('sources.source'), min: 160, max: 320, flex: 2 },
  { id: 'last', header: T('sources.lastRead2'), min: 128, max: 168, flex: 0 },
  { id: 'read', header: T('sources.read'), width: 64, align: 'end' },
  { id: 'kept', header: T('sources.col.passed'), headerTip: T('sources.passedTheHardConditions'), width: 88, align: 'end' },
  { id: 'new', header: T('sources.add'), width: 64, align: 'end' },
  { id: 'dropped', header: T('sources.whyTheRestWas'), min: 168, max: 320, flex: 3, priority: 2 },
  { id: 'now', header: T('sources.inTheLibraryNow'), min: 160, max: 240, flex: 1, priority: 1 },
])
const more = (r) => !!r.error || r.dropped.length > 0
const toggle = (r) => { if (more(r)) open.value = open.value === r.name ? null : r.name }
function lastOf(r) {
  if (r.error) return { primary: r.ok_at ? fmtTime(r.ok_at) : '', secondary: r.fails > 1 ? T('sources.failedTimes', { n: r.fails }) : T('sources.readFailed'), tone: 'bad', tip: r.error }
  return { primary: r.ok_at ? fmtTime(r.ok_at) : '', secondary: r.ok_at ? '' : T('sources.notReadYet'), tone: r.ok_at ? '' : 'muted' }
}
</script>

<template>
  <PageHead :title="$t('sources.sourcesAndWatchedEmployers')" :help="$t('sources.thePostingsAreRead')">
    <router-link to="/jobs" class="btn ghost"><Icon name="back" />{{ $t('sources.backToPostings') }}</router-link>
    <button class="primary" @click="scanNow"><Icon name="refresh" />{{ $t('sources.scanNow') }}</button>
  </PageHead>

  <EmployersPanel />

  <div v-if="persona.features.portal === 'ubc'" class="card">
    <SectionHead title="UBC PD Portal" :help="$t('sources.theProgramReadsThe')">
      <Status v-if="portal.account" :tone="portal.account.status === 'ok' ? 'ok' : 'warn'" :label="portal.account.status === 'ok' ? $t('sources.signedIn') : $t('sources.needsSigningInAgain')" />
      <Status v-else tone="warn" :label="$t('sources.neverSignedIn')" />
      <button @click="portalLogin"><Icon name="login" />{{ $t('sources.signInToPd') }}</button>
    </SectionHead>
    <label class="src-toggle"><input type="checkbox" :checked="portal.on" @change="setPortal($event.target.checked)" /> {{ $t('sources.readPdPortalWhen') }} <span class="hint">{{ $t('sources.appliedAsYouChange') }}</span></label>
    <p class="hint">{{ $t('sources.whenThePortalRefuses') }}<router-link to="/settings/system/browser">{{ $t('sources.settingsSystemAndData') }}</router-link>{{ $t('sources.andTurnTheOrdinary') }}</p>
    <details class="tech"><summary>{{ $t('sources.orImportFromYour') }}</summary>
      <ol class="src-steps">
        <li>{{ $t('sources.putThisButton') }}<b>{{ $t('sources.dragToYourBrowsers') }}</b> <a v-if="bm.href" :href="bm.href" class="btn sm primary" @click.prevent="toast($t('sources.dragItToThe'))">{{ $t('sources.importToAutoapply') }}</a></li>
        <li>{{ $t('sources.signInToPd2') }}</li>
        <li>{{ $t('sources.clickImportToAutoapply') }}</li>
      </ol>
      <pre>{{ $t('sources.ifTheBookmarksBar', { p0: portal.base }) }}</pre></details>
  </div>

  <div class="card">
    <SectionHead :title="$t('sources.whatEachSourceGave')"><router-link to="/settings/automation/schedule" class="btn sm ghost">{{ $t('sources.howOftenToScan') }}</router-link></SectionHead>
    <p v-if="!rep.at" class="muted">{{ $t('sources.notScannedYet') }}</p>
    <template v-else>
      <p class="t-secondary src-line">{{ $t('sources.latestScanPostingsWere', { p0: fmtTime(rep.at), p1: rep.total.read, p2: rep.total.kept, p3: rep.total.new }) }}</p>
      <p v-if="rep.total.dropped.length" class="src-line src-chips">{{ $t('sources.droppedByTheHard') }}<span v-for="d in rep.total.dropped" :key="d.key" class="meta small">{{ d.label }} <span class="num t-primary">{{ d.n }}</span></span>
        <router-link to="/settings/goals/filters">{{ $t('sources.tryTheConditionsOn') }}</router-link></p>
      <p v-if="rep.total.now.total" class="src-line src-chips">{{ $t('sources.theInTheLibrary', { p0: rep.total.now.total }) }}<Status tone="ok" :label="$t('sources.atOrAboveThe') + ' ' + rep.total.now.above" /><Status :label="$t('sources.belowTheThreshold') + ' ' + rep.total.now.below" /><Status tone="warn" :label="$t('sources.ruledOutByThe') + ' ' + rep.total.now.excluded" /><Status tone="info" :label="$t('sources.notScoredYet') + ' ' + rep.total.now.unscored" /></p>
      <DataTable :columns="COLUMNS" :rows="rep.sources" row-key="name" density="standard" clickable :expanded-key="open" :label="$t('sources.whatEachSourceGave')"
                 :row-class="(r) => (more(r) ? null : 'src-plain')" @row="toggle">
        <template #cell-source="{ row }">
          <EntityCell :primary="row.name === 'pdportal' ? row.label : row.name" :secondary="row.name === 'pdportal' ? '' : row.label">
            <template v-if="row.priority" #after><span v-tip="$t('sources.priority')" class="mark prio" role="img" :aria-label="$t('sources.priority')"><Icon name="star" /></span></template>
          </EntityCell>
        </template>
        <template #cell-last="{ row }"><DateTimeCell v-bind="lastOf(row)" /></template>
        <template #cell-read="{ row }"><span v-if="row.read != null" class="num">{{ row.read }}</span><span v-else class="none">—</span></template>
        <template #cell-kept="{ row }">
          <span v-if="row.read == null" class="none">—</span>
          <span v-else-if="row.screened" class="num">{{ row.kept }}</span>
          <Trunc v-else class="t-meta" :text="$t('sources.notFiltered')" />
        </template>
        <template #cell-new="{ row }"><span v-if="row.new != null" class="num">{{ row.new }}</span><span v-else class="none">—</span></template>
        <template #cell-dropped="{ row }">
          <div v-if="row.dropped.length" class="src-drop">
            <Trunc class="t-secondary" :text="row.dropped[0].label" /><span class="num t-primary">{{ row.dropped[0].n }}</span>
            <button v-if="row.dropped.length > 1" type="button" class="sm ghost" :aria-expanded="open === row.name" @click="toggle(row)">{{ open === row.name ? $t('sources.collapse') : $t('sources.more', { p0: row.dropped.length - 1 }) }}</button>
          </div>
          <Trunc v-else-if="row.read != null && !row.screened" class="t-meta" :text="$t('sources.thisSourceIsNot')" />
          <span v-else class="none">—</span>
        </template>
        <template #cell-now="{ row }">
          <div v-if="row.now.total" v-tip="$t('sources.belowRuledOutNot', { p0: row.now.below, p1: row.now.excluded, p2: row.now.unscored })" class="src-now">
            <span class="atomic">{{ $t('sources.atTheLine') }} <span class="t-primary num">{{ row.now.above }}</span></span>
            <Trunc class="t-meta" :text="$t('sources.threshold', { p0: (row.lines || [row.line]).join(' / ') })" />
          </div>
          <span v-else class="t-meta">{{ $t('sources.noOpenPostings') }}</span>
        </template>
        <template #expanded="{ row }">
          <div v-if="row.error" class="src-error"><span class="bad-text">{{ row.error }}</span><TechDetails :text="row.error_detail" /></div>
          <div v-if="row.dropped.length" class="src-chips"><span class="t-meta">{{ $t('sources.whyTheRestWas') }}</span><span v-for="d in row.dropped" :key="d.key" class="meta small">{{ d.label }} <span class="num t-primary">{{ d.n }}</span></span></div>
        </template>
      </DataTable>
      <p class="hint src-foot">{{ $t('sources.passedTheHardConditions2') }}<router-link to="/settings/goals/filters">{{ $t('sources.hardConditionsBeforeIntake') }}</router-link>{{ $t('sources.theThresholdsAreIn') }}<router-link to="/settings/automation/prepare">{{ $t('sources.prepareDraftsAutomatically') }}</router-link>{{ $t('sources.onlyNumbersAreKept') }}</p>
    </template>
  </div>
</template>

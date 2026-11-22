<script setup>
import { t as T } from '../i18n/catalog'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import CardHead from '../components/CardHead.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import HelpPop from '../components/HelpPop.vue'
import Icon from '../components/Icon.vue'
import IconButton from '../components/IconButton.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import Tabs from '../components/Tabs.vue'
import Pager from '../components/Pager.vue'
import Status from '../components/Status.vue'
import DataState from '../components/DataState.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run, toast } from '../ui'

const runs = ref([])
const tasks = ref([])
const notes = ref([])
const ov = ref({ mail_recent: [] })
const filter = ref('all')
const route = useRoute()
const TABS = [['plan', T('runs.plan')], ['activity', T('runs.whatWasDone')], ['sched', T('runs.scheduledJobs')], ['notes', T('runs.notificationsAndBots')]]
const tab = ref(TABS.some(([k]) => k === String(route.query.tab)) ? String(route.query.tab) : 'plan')
const sched = ref([])
// The plan: what is being done, what comes next and in which order, what waits for you, what was set aside, what is
// set for later. The record of what was done is the next tab.
const plan = ref(null)
const busy = ref(0)
async function loadPlan() { try { plan.value = await api.get('/queue') } catch (e) { toast(e.message, 'bad') } }
async function control(t, what, ok) {
  if (busy.value) return
  busy.value = t.id
  try { await api.post(`/tasks/${t.id}/${what}`); toast(ok); await Promise.all([loadPlan(), load()]) } catch (e) { toast(e.message, 'bad'); await loadPlan() } finally { busy.value = 0 }
}
async function cancelTask(t) {
  if (!(await ask(T('runs.cancelItIsTaken', { p0: t.label, p1: t.subject ? ' · ' + t.subject : '' }), { ok: T('runs.cancelThisTask'), danger: true }))) return
  await control(t, 'cancel', T('runs.cancelled'))
}
async function drain(on) {
  try { const r = await api.post('/queue/drain', { on }); toast(on ? (r.stopped ? T('runs.noTaskIsRunning2') : T('runs.whatIsBeingDone')) : T('runs.theQueueGoesOn')); await loadPlan() } catch (e) { toast(e.message, 'bad') }
}
const runNow = (j) => run(() => api.post('/tasks', { kind: j.kind }), T('runs.startedTheResultWill'), load)
const setEvery = (j) => run(() => api.put('/settings', { settings: { [j.setting]: Math.max(0, Math.round(Number(j.minutes) || 0)) } }), T('runs.savedTheNextRun'), load)
const every = (m) => (m >= 1440 && m % 1440 === 0 ? T('runs.days', { n: m / 1440 }, m / 1440) : m >= 60 && m % 60 === 0 ? T('runs.h', { p0: m / 60 }) : T('runs.min', { p0: m }))

// ── the plan as five lists of one shape: what the task is, a word on where it stands, one action and a menu
const CANCEL = { id: 'cancel', label: T('runs.cancelThisTask'), icon: 'x', danger: true }
const HOLD = { id: 'hold', label: T('runs.setAside2'), icon: 'pause' }
const lane = (t) => (t.held_by_pause ? T('runs.notStartedWhileAutomatic') : t.by_hand ? T('runs.startedByYou') : t.lane === 'background' ? T('runs.backgroundLine') : t.lane === 'desk' ? T('runs.profileLine') : T('runs.formsLine'))
const groups = computed(() => {
  const p = plan.value
  if (!p) return []
  return [
    { key: 'running', title: T('runs.beingDone'), rows: p.running, none: T('runs.noTaskIsRunning'), always: true,
      sub: (t) => T('runs.startedAt', { p0: fmtTime(t.started_at) }), main: (t) => (t.kind === 'apply' ? { label: T('runs.stop'), go: () => control(t, 'stop', T('runs.stoppedTheAgentEnds')) } : null), menu: () => [] },
    { key: 'next', title: T('runs.next'), rows: p.next, none: T('runs.nothingInTheQueue'), always: true, numbered: true, note: p.next_total ? T('runs.inOrder', { n: p.next_total }, p.next_total) : '',
      foot: p.next_total > p.next.length ? T('runs.onlyTheFirstAre', { p0: p.next.length }) : '',
      sub: lane, main: (t, i) => (i > 0 || t.held_by_pause ? { label: T('runs.doThisFirst'), go: () => control(t, 'first', T('runs.thisOneWillBe')) } : null), menu: () => [HOLD, CANCEL] },
    { key: 'waiting', title: T('runs.waitingForYouBefore'), rows: p.waiting, tone: 'warn',
      sub: (t) => (t.waits_for ? T('runs.waitsFor', { what: t.waits_for }) : t.why), main: () => ({ label: T('runs.dealWithIt'), to: '/todos' }), menu: () => [CANCEL] },
    { key: 'held', title: T('runs.setAside3'), rows: p.held,
      sub: () => T('runs.notStartedUntilYou'), main: (t) => ({ label: T('runs.takeUpAgain'), go: () => control(t, 'take-up', T('runs.backInTheQueue')) }), menu: () => [CANCEL] },
    { key: 'later', title: T('runs.setForALater'), rows: p.later,
      sub: (t) => T('runs.after', { p0: fmtTime(t.due_at) }), main: (t) => ({ label: T('runs.doItNow'), go: () => control(t, 'first', T('runs.itWillBeDone')) }), menu: () => [CANCEL] },
  ].filter((g) => g.always || g.rows.length)
})
const planCols = (g) => [...(g.numbered ? [{ id: 'n', header: T('runs.col.order'), width: 56 }] : []), { id: 'task', header: T('runs.what'), min: 180 }, { id: 'acts', header: '', width: 172, align: 'end' }]
const planPick = (id, t) => (id === 'cancel' ? cancelTask(t) : control(t, 'hold', T('runs.setAside')))

async function read() {
  loadPlan()
  api.get('/schedule').then((r) => { sched.value = r }).catch(() => {})
  ;[runs.value, tasks.value, notes.value, ov.value] = await Promise.all([api.get('/runs'), api.get('/tasks?limit=80'), api.get('/notifications?limit=40'), api.get('/overview')])
}

// ── what was done: a page of rows; a row opens to say what happened in full
const PAGE = 20
const page = ref(0)
const opened = ref(null)
const shown = computed(() => tasks.value.filter((t) => filter.value === 'all' || ['failed', 'waiting_human', 'running', 'queued'].includes(t.status)))
const paged = computed(() => shown.value.slice(page.value * PAGE, (page.value + 1) * PAGE))
watch(filter, () => { page.value = 0; opened.value = null })
watch(shown, (rows) => { if (page.value * PAGE >= rows.length) page.value = Math.max(0, Math.ceil(rows.length / PAGE) - 1) })
const DONE_COLS = [
  { id: 'status', header: T('runs.col.status'), min: 104, max: 150 },
  { id: 'task', header: T('runs.what'), min: 170, flex: 2 },
  { id: 'line', header: T('runs.col.outcome'), min: 180, flex: 3, priority: 1 },
  { id: 'when', header: T('runs.col.when'), width: 124 },
  { id: 'acts', header: '', width: 128, align: 'end' },
]
const stepsOf = (t) => {
  const r = runs.value.find((x) => x.task_id === t.id && x.steps.length)
  return r ? r.steps.map((s) => JSON.stringify(s)).join('\n') + T('runs.nNscreenshotsAndPage', { p0: r.dir }) : ''
}
const tech = (t) => [t.explained.detail, (t.browser_detail || []).join('\n'), t.status === 'done' && t.result && Object.keys(t.result).length ? JSON.stringify(t.result, null, 1) : '', stepsOf(t)].filter(Boolean).join('\n\n')
const line = (t) => t.summary || t.explained.message || (t.status === 'running' ? T('runs.inProgress2') : t.status === 'queued' ? (t.due_at ? T('runs.setForAfter', { p0: fmtTime(t.due_at) }) : T('runs.waitingForEarlierTasks')) : '')
const retry = (t) => run(() => api.post(`/tasks/${t.id}/retry`), T('runs.requeued'), load)
const retryNative = (t) => run(() => api.post(`/tasks/${t.id}/retry`, { browser_backend: 'nodriver' }), T('runs.queuedAgainThisTime'), load)
const stuck = (t) => ['failed', 'waiting_human'].includes(t.status)
const canRetry = (t) => stuck(t) && t.kind !== 'execute'
const canNative = (t) => stuck(t) && ['apply', 'discover'].includes(t.kind)
const NATIVE = [{ id: 'native', label: T('runs.tryAgainInThe'), icon: 'globe', hint: T('runs.forWhenASite') }]
const toggle = (t) => { opened.value = opened.value === t.id ? null : t.id }
const CAT = { task_started: T('runs.start'), todo: T('runs.toDo'), status_update: T('runs.progress'), task_result: T('runs.result'), heard: T('runs.fromYourPhone') }

const SCHED_COLS = [
  { id: 'label', header: T('runs.what'), min: 140, flex: 2 },
  { id: 'every', header: T('runs.howOften'), width: 252 },
  { id: 'last', header: T('runs.lastRun'), width: 132, priority: 1 },
  { id: 'next', header: T('runs.nextRun'), min: 124, max: 190 },
  { id: 'run', header: '', width: 124, align: 'end' },
]

// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load, { every: 4000, when: () => ((plan.value && plan.value.running) || []).length > 0 || (ov.value.running || []).length > 0 })
onMounted(load)
</script>

<template>
  <PageHead :title="$t('runs.activity')">
    <button @click="load"><Icon name="refresh" />{{ $t('runs.refresh') }}</button>
  </PageHead>
  <DataState :s="st" :what="$t('runs.activity')" @retry="load" />
  <template v-if="st.at">

  <div class="tabs-bar">
    <Tabs v-model="tab" :label="$t('runs.activity')" :items="TABS.map(([id, label]) => ({ id, label }))" />
    <span class="grow"></span>
    <div v-if="tab === 'activity'" class="seg" role="group" :aria-label="$t('runs.col.status')">
      <button :class="{ on: filter === 'all' }" :aria-pressed="filter === 'all'" @click="filter = 'all'">{{ $t('runs.all') }}</button>
      <button :class="{ on: filter === 'open' }" :aria-pressed="filter === 'open'" @click="filter = 'open'">{{ $t('runs.incompleteOnly') }}</button>
    </div>
  </div>

  <template v-if="tab === 'plan'">
    <div v-if="!plan" class="card data-wait" role="status"><span class="spin" aria-hidden="true"></span>{{ $t('runs.loading') }}</div>
    <template v-else>
      <!-- where the queue stands: a state, what it means, and the one thing that can be done about it -->
      <div class="card plan-state">
        <div class="plan-what">
          <template v-if="plan.draining && plan.stopped"><Status :label="$t('runs.stopped')" /><p>{{ $t('runs.whatWasBeingDone') }}</p></template>
          <template v-else-if="plan.draining"><Status tone="warn" :label="$t('runs.finishing')" /><p>{{ $t('runs.stopsAfter', { n: plan.running.length }, plan.running.length) }}</p></template>
          <template v-else-if="plan.paused"><Status tone="warn" :label="$t('runs.automaticRunningIsPaused')" /><p>{{ $t('runs.timedScansAutomaticScoring') }}</p></template>
          <template v-else><Status tone="ok" :label="$t('runs.running')" /><p>{{ $t('runs.formsAreReadAnd') }}</p></template>
        </div>
        <div class="plan-side">
          <div class="plan-figure">
            <span class="meta">{{ plan.drafts.cap ? $t('runs.draftsOfCap', { n: plan.drafts.waiting, cap: plan.drafts.cap }) : $t('runs.draftsCount', { n: plan.drafts.waiting }) }}</span>
            <span v-if="plan.drafts.cap && plan.drafts.room === 0" class="tag warn">{{ $t('runs.limitReached') }}</span>
            <HelpPop :label="$t('runs.draftsLabel')">
              <p>{{ $t('runs.draftsHelp') }}</p>
              <i18n-t keypath="runs.draftsLimit" tag="p" scope="global"><template #link><router-link to="/settings/automation/prepare">{{ $t('runs.settingsPrepareDraftsAutomatically') }}</router-link></template></i18n-t>
            </HelpPop>
          </div>
          <span v-if="plan.release?.target" v-tip="$t('runs.releasePending')" class="meta small num">{{ plan.release.active }} → {{ plan.release.target }}</span>
          <button v-if="!plan.draining" @click="drain(true)"><Icon name="pause" />{{ $t('runs.finishWhatIsBeing') }}</button>
          <button v-else class="primary" @click="drain(false)"><Icon name="play" />{{ $t('runs.goOnWithThe') }}</button>
        </div>
      </div>

      <div v-for="g in groups" :key="g.key" class="card">
        <CardHead :title="g.title" :note="g.note || ''" />
        <DataTable v-if="g.rows.length" class="bare" :columns="planCols(g)" :rows="g.rows" :label="g.title">
          <template #cell-n="{ index }"><span class="t-secondary num">{{ index + 1 }}</span></template>
          <template #cell-task="{ row }"><EntityCell :primary="row.subject ? row.label + ' · ' + row.subject : row.label" :secondary="g.sub(row)" /></template>
          <template #cell-acts="{ row, index }">
            <template v-if="g.main(row, index)">
              <router-link v-if="g.main(row, index).to" :to="g.main(row, index).to" class="btn ghost sm">{{ g.main(row, index).label }}</router-link>
              <button v-else class="ghost sm" :disabled="!!busy" @click="g.main(row, index).go()">{{ g.main(row, index).label }}</button>
            </template>
            <Menu v-if="g.menu(row).length" :label="$t('common.more')" :items="g.menu(row)" :disabled="!!busy" @pick="(id) => planPick(id, row)" />
          </template>
        </DataTable>
        <p v-else class="muted plan-none">{{ g.none }}</p>
        <p v-if="g.foot" class="t-meta mt-2">{{ g.foot }}</p>
      </div>
    </template>
  </template>

  <div v-if="tab === 'sched'" class="card">
    <CardHead :title="$t('runs.whatTheProgramDoes')">
      <template #help><p>{{ $t('runs.anIntervalCountsFrom') }}</p><p>{{ $t('runs.besidesEveryMinutesPostings') }}</p></template>
    </CardHead>
    <DataTable class="bare" :columns="SCHED_COLS" :rows="sched" row-key="kind" :label="$t('runs.whatTheProgramDoes')">
      <template #cell-every="{ row }">
        <span class="atomic">{{ $t('runs.every') }}</span>
        <input v-model.number="row.minutes" class="w-num" type="number" min="0" :aria-label="$t('runs.intervalOf', { task: row.label })" @change="setEvery(row)" />
        <span class="atomic">{{ $t('runs.minutes') }}</span>
        <span class="t-meta atomic">{{ row.minutes ? $t('runs.everyNote', { text: every(row.minutes) }) : $t('runs.off') }}</span>
      </template>
      <template #cell-last="{ row }"><DateTimeCell v-if="row.last" :primary="fmtTime(row.last)" /><span v-else class="none">{{ $t('runs.notRunYet') }}</span></template>
      <template #cell-next="{ row }"><Status v-if="row.paused" tone="warn" :label="$t('runs.automaticRunningIsPaused2')" /><DateTimeCell v-else :primary="row.next ? fmtTime(row.next) : ''" /></template>
      <template #cell-run="{ row }"><button class="ghost sm" @click="runNow(row)"><Icon name="play" />{{ $t('runs.runNow') }}</button></template>
    </DataTable>
  </div>

  <template v-if="tab === 'activity'">
    <DataTable :columns="DONE_COLS" :rows="paged" clickable :expanded-key="opened" :label="$t('runs.whatWasDone')" @row="toggle">
      <template #cell-status="{ row }"><span v-if="row.status === 'failed'" v-tip.overflow class="tag bad">{{ row.status_label }}</span><Status v-else :tone="row.tone" :label="row.status_label" /></template>
      <template #cell-task="{ row }"><EntityCell :primary="row.label" :secondary="row.subject" /></template>
      <template #cell-line="{ row }"><span v-if="line(row)" class="t-secondary cut2">{{ line(row) }}</span><span v-else class="none">—</span></template>
      <template #cell-when="{ row }"><DateTimeCell :primary="fmtTime(row.finished_at || row.started_at || row.created_at)" /></template>
      <template #cell-acts="{ row }">
        <button v-if="canRetry(row)" class="ghost sm" @click="retry(row)">{{ $t('runs.tryAgain') }}</button>
        <Menu v-if="canNative(row)" :label="$t('common.more')" :items="NATIVE" @pick="retryNative(row)" />
        <IconButton :icon="opened === row.id ? 'chevron_up' : 'chevron'" :label="opened === row.id ? $t('common.collapse') : $t('runs.details')" :pressed="opened === row.id" @click="toggle(row)" />
      </template>
      <template #expanded="{ row }">
        <p v-if="line(row)" class="done-line">{{ line(row) }}</p>
        <p v-if="row.browser_stages?.length" class="t-secondary">{{ row.browser_stages.join(' · ') }}</p>
        <p v-if="!line(row) && !row.browser_stages?.length && !tech(row)" class="t-meta">{{ $t('runs.noDetails') }}</p>
        <TechDetails :text="tech(row)" />
      </template>
      <template #empty><EmptyState icon="activity" :title="filter === 'all' ? $t('runs.noActivityYet') : $t('runs.noUnfinishedTasks')" /></template>
    </DataTable>
    <Pager v-model:page="page" :size="PAGE" :total="shown.length" />
  </template>

  <div v-if="tab === 'notes'" class="card">
    <div class="list">
      <div v-for="n in notes" :key="n.id" class="item">
        <Status v-if="n.category === 'heard'" tone="info" :label="$t('runs.received')" />
        <Status v-else :tone="n.sent ? 'ok' : ''" :label="n.sent ? $t('runs.sent') : $t('runs.notSent')" />
        <div><div class="note-text">{{ n.text }}</div><TechDetails :text="n.error" /></div>
        <span class="t-meta atomic">{{ CAT[n.category] ? CAT[n.category] + ' · ' : '' }}{{ fmtTime(n.created_at) }}</span>
      </div>
    </div>
    <EmptyState v-if="!notes.length" icon="bell" :title="$t('runs.noNotificationsSentYet')" :text="$t('runs.connectTelegramOrDiscord')" />
  </div>

  </template>
</template>

<script setup>
import { t as T } from '../i18n/catalog'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run, toast } from '../ui'

const runs = ref([])
const tasks = ref([])
const notes = ref([])
const ov = ref({ mail_recent: [] })
const filter = ref('all')
const route = useRoute()
const tab = ref(['plan', 'activity', 'sched', 'notes'].includes(String(route.query.tab)) ? String(route.query.tab) : 'plan')
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
  if (!(await ask(T('runs.cancelItIsTaken', { p0: t.label, p1: t.subject ? ' · ' + t.subject : '' }), { ok: T('runs.cancelThisTask') }))) return
  await control(t, 'cancel', T('runs.cancelled'))
}
async function drain(on) {
  try { const r = await api.post('/queue/drain', { on }); toast(on ? (r.stopped ? T('runs.noTaskIsRunning2') : T('runs.whatIsBeingDone')) : T('runs.theQueueGoesOn')); await loadPlan() } catch (e) { toast(e.message, 'bad') }
}
const runNow = (j) => run(() => api.post('/tasks', { kind: j.kind }), T('runs.startedTheResultWill'), load)
const setEvery = (j) => run(() => api.put('/settings', { settings: { [j.setting]: Math.max(0, Math.round(Number(j.minutes) || 0)) } }), T('runs.savedTheNextRun'), load)
const every = (m) => (m >= 1440 && m % 1440 === 0 ? T('runs.dayS', { p0: m / 1440 }) : m >= 60 && m % 60 === 0 ? T('runs.h', { p0: m / 60 }) : T('runs.min', { p0: m }))

async function read() {
  loadPlan()
  api.get('/schedule').then((r) => { sched.value = r }).catch(() => {})
  ;[runs.value, tasks.value, notes.value, ov.value] = await Promise.all([api.get('/runs'), api.get('/tasks?limit=80'), api.get('/notifications?limit=40'), api.get('/overview')])
}
const shown = computed(() => tasks.value.filter((t) => filter.value === 'all' || ['failed', 'waiting_human', 'running', 'queued'].includes(t.status)))
const stepsOf = (t) => {
  const r = runs.value.find((x) => x.task_id === t.id && x.steps.length)
  return r ? r.steps.map((s) => JSON.stringify(s)).join('\n') + T('runs.nNscreenshotsAndPage', { p0: r.dir }) : ''
}
const tech = (t) => [t.explained.detail, (t.browser_detail || []).join('\n'), t.status === 'done' && t.result && Object.keys(t.result).length ? JSON.stringify(t.result, null, 1) : '', stepsOf(t)].filter(Boolean).join('\n\n')
const line = (t) => t.summary || t.explained.message || (t.status === 'running' ? T('runs.inProgress2') : t.status === 'queued' ? (t.due_at ? T('runs.setForAfter', { p0: fmtTime(t.due_at) }) : T('runs.waitingForEarlierTasks')) : '')
const retry = (t) => run(() => api.post(`/tasks/${t.id}/retry`), T('runs.requeued'), load)
const retryNative = (t) => run(() => api.post(`/tasks/${t.id}/retry`, { browser_backend: 'nodriver' }), T('runs.queuedAgainThisTime'), load)
const CAT = { task_started: T('runs.start'), todo: T('runs.toDo'), status_update: T('runs.progress'), task_result: T('runs.result'), heard: T('runs.fromYourPhone') }

// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load, { every: 4000, when: () => ((plan.value && plan.value.running) || []).length > 0 || (ov.value.running || []).length > 0 })
onMounted(load)
</script>

<template>
  <PageHead :title="$t('runs.activity')" :sub="$t('runs.whatTheProgramIs')">
    <button @click="load"><Icon name="refresh" />{{ $t('runs.refresh') }}</button>
  </PageHead>
  <DataState :s="st" :what="$t('runs.activity')" @retry="load" />
  <template v-if="st.at">

  <div class="row" style="margin-bottom: 12px">
    <div class="seg">
      <button :class="{ on: tab === 'plan' }" @click="tab = 'plan'">{{ $t('runs.plan') }}</button>
      <button :class="{ on: tab === 'activity' }" @click="tab = 'activity'">{{ $t('runs.whatWasDone') }}</button>
      <button :class="{ on: tab === 'sched' }" @click="tab = 'sched'">{{ $t('runs.scheduledJobs') }}</button>
      <button :class="{ on: tab === 'notes' }" @click="tab = 'notes'">{{ $t('runs.notificationsAndBots') }}</button>
    </div>
    <span class="grow"></span>
    <div v-if="tab === 'activity'" class="seg">
      <button :class="{ on: filter === 'all' }" @click="filter = 'all'">{{ $t('runs.all') }}</button>
      <button :class="{ on: filter === 'open' }" @click="filter = 'open'">{{ $t('runs.incompleteOnly') }}</button>
    </div>
  </div>

  <template v-if="tab === 'plan'">
    <div v-if="!plan" class="card"><div class="empty"><div class="t">{{ $t('runs.loading') }}</div></div></div>
    <template v-else>
      <div class="card">
        <div class="row" style="align-items: flex-start; flex-wrap: wrap; gap: 12px">
          <div class="grow">
            <div v-if="plan.draining && plan.stopped"><b>{{ $t('runs.stopped') }}</b> {{ $t('runs.whatWasBeingDone') }}</div>
            <div v-else-if="plan.draining"><b>{{ $t('runs.finishing') }}</b> {{ $t('runs.itStopsOnceThe', { p0: plan.running.length }) }}</div>
            <div v-else-if="plan.paused"><b>{{ $t('runs.automaticRunningIsPaused') }}</b> {{ $t('runs.timedScansAutomaticScoring') }}</div>
            <div v-else><b>{{ $t('runs.running') }}</b> {{ $t('runs.formsAreReadAnd') }}</div>
            <div class="small muted" style="margin-top: 4px">{{ $t('runs.draftsWaitingForYou', { p0: plan.drafts.waiting }) }}<template v-if="plan.drafts.cap"> {{ $t('runs.limit', { p0: plan.drafts.cap }) }}<template v-if="plan.drafts.room === 0">{{ $t('runs.theLimitIsReached') }}</template></template>{{ $t('runs.theLimitIsChanged') }}<router-link to="/settings/automation/prepare">{{ $t('runs.settingsPrepareDraftsAutomatically') }}</router-link>{{ $t('runs.text') }}</div>
          </div>
          <div v-if="plan.release?.target" class="hint">{{ plan.release.active }} → {{ plan.release.target }}</div>
          <button v-if="!plan.draining" @click="drain(true)"><Icon name="pause" />{{ $t('runs.finishWhatIsBeing') }}</button>
          <button v-else class="primary" @click="drain(false)"><Icon name="play" />{{ $t('runs.goOnWithThe') }}</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">{{ $t('runs.beingDone') }}</div>
        <div class="list">
          <div v-for="t in plan.running" :key="t.id" class="item">
            <span class="badge info" style="min-width: 64px; justify-content: center">{{ $t('runs.inProgress') }}</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
              <div class="sub">{{ $t('runs.startedAt', { p0: fmtTime(t.started_at) }) }}</div></div>
            <div v-if="t.kind === 'apply'" class="right"><button class="sm" :disabled="!!busy" @click="control(t, 'stop', $t('runs.stoppedTheAgentEnds'))">{{ $t('runs.stop') }}</button></div>
          </div>
        </div>
        <div v-if="!plan.running.length" class="muted">{{ $t('runs.noTaskIsRunning') }}</div>
      </div>

      <div class="card">
        <div class="card-title">{{ $t('runs.next') }}<span v-if="plan.next_total" class="muted" style="font-weight: 400">{{ $t('runs.inThisOrder', { p0: plan.next_total }) }}</span></div>
        <div class="list">
          <div v-for="(t, i) in plan.next" :key="t.id" class="item">
            <span class="badge" style="min-width: 40px; justify-content: center">{{ i + 1 }}</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
              <div class="sub"><template v-if="t.held_by_pause">{{ $t('runs.notStartedWhileAutomatic') }}</template><template v-else-if="t.by_hand">{{ $t('runs.startedByYou') }}</template><template v-else>{{ t.lane === 'background' ? $t('runs.backgroundLine') : t.lane === 'desk' ? $t('runs.profileLine') : $t('runs.formsLine') }}</template></div></div>
            <div class="right row" style="flex-wrap: nowrap">
              <button v-if="i > 0 || t.held_by_pause" class="sm ghost" :disabled="!!busy" @click="control(t, 'first', $t('runs.thisOneWillBe'))">{{ $t('runs.doThisFirst') }}</button>
              <button class="sm ghost" :disabled="!!busy" @click="control(t, 'hold', $t('runs.setAside'))">{{ $t('runs.setAside2') }}</button>
              <button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">{{ $t('runs.cancel') }}</button>
            </div>
          </div>
        </div>
        <div v-if="!plan.next.length" class="muted">{{ $t('runs.nothingInTheQueue') }}</div>
        <div v-else-if="plan.next_total > plan.next.length" class="small muted" style="margin-top: 6px">{{ $t('runs.onlyTheFirstAre', { p0: plan.next.length }) }}</div>
      </div>

      <div v-if="plan.waiting.length" class="card">
        <div class="card-title">{{ $t('runs.waitingForYouBefore') }}</div>
        <div class="list">
          <div v-for="t in plan.waiting" :key="t.id" class="item">
            <span class="badge warn" style="min-width: 64px; justify-content: center">{{ $t('runs.waitingForYou') }}</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
              <div class="sub">{{ t.waits_for ? $t('runs.waitingFor') + t.waits_for : t.why }}</div></div>
            <div class="right row" style="flex-wrap: nowrap"><router-link to="/todos" class="btn sm">{{ $t('runs.dealWithIt') }}</router-link><button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">{{ $t('runs.cancel') }}</button></div>
          </div>
        </div>
      </div>

      <div v-if="plan.held.length" class="card">
        <div class="card-title">{{ $t('runs.setAside3') }}</div>
        <div class="list">
          <div v-for="t in plan.held" :key="t.id" class="item">
            <span class="badge" style="min-width: 64px; justify-content: center">{{ $t('runs.setAside2') }}</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div><div class="sub">{{ $t('runs.notStartedUntilYou') }}</div></div>
            <div class="right row" style="flex-wrap: nowrap"><button class="sm" :disabled="!!busy" @click="control(t, 'take-up', $t('runs.backInTheQueue'))">{{ $t('runs.takeUpAgain') }}</button><button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">{{ $t('runs.cancel') }}</button></div>
          </div>
        </div>
      </div>

      <div v-if="plan.later.length" class="card">
        <div class="card-title">{{ $t('runs.setForALater') }}</div>
        <div class="list">
          <div v-for="t in plan.later" :key="t.id" class="item">
            <span class="badge" style="min-width: 64px; justify-content: center">{{ $t('runs.timed') }}</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div><div class="sub">{{ $t('runs.after', { p0: fmtTime(t.due_at) }) }}</div></div>
            <div class="right row" style="flex-wrap: nowrap"><button class="sm ghost" :disabled="!!busy" @click="control(t, 'first', $t('runs.itWillBeDone'))">{{ $t('runs.doItNow') }}</button><button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">{{ $t('runs.cancel') }}</button></div>
          </div>
        </div>
      </div>
    </template>
  </template>

  <div v-if="tab === 'sched'" class="card">
    <div class="card-title">{{ $t('runs.whatTheProgramDoes') }}</div>
    <p class="card-sub">{{ $t('runs.anIntervalCountsFrom') }}</p>
    <div class="table-wrap" style="max-height: none">
      <table>
        <thead><tr><th>{{ $t('runs.what') }}</th><th>{{ $t('runs.howOften') }}</th><th>{{ $t('runs.lastRun') }}</th><th>{{ $t('runs.nextRun') }}</th><th></th></tr></thead>
        <tbody>
          <tr v-for="j in sched" :key="j.kind">
            <td>{{ j.label }}</td>
            <td class="nowrap">{{ $t('runs.every') }} <input v-model.number="j.minutes" type="number" min="0" style="width: 84px" @change="setEvery(j)" /> {{ $t('runs.minutes') }}
              <span class="muted small">{{ j.minutes ? `（${every(j.minutes)}）` : $t('runs.off') }}</span></td>
            <td><span v-if="j.last">{{ fmtTime(j.last) }}</span><span v-else class="muted">{{ $t('runs.notRunYet') }}</span></td>
            <td><span v-if="j.paused" class="tag warn">{{ $t('runs.automaticRunningIsPaused2') }}</span><span v-else-if="j.next">{{ fmtTime(j.next) }}</span><span v-else class="muted">—</span></td>
            <td style="text-align: right"><button class="ghost sm" @click="runNow(j)"><Icon name="play" />{{ $t('runs.runNow') }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="small muted" style="margin-top: 10px">{{ $t('runs.besidesEveryMinutesPostings') }}</p>
  </div>

  <div v-if="tab === 'activity'" class="card">
    <div class="list">
      <div v-for="t in shown" :key="t.id" class="item">
        <span class="badge" :class="t.tone" style="min-width: 64px; justify-content: center">{{ t.status_label }}</span>
        <div>
          <div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
          <div v-if="line(t)" class="sub">{{ line(t) }}</div>
          <div v-if="t.browser_stages?.length" class="sub">{{ t.browser_stages.join(' · ') }}</div>
          <TechDetails :text="tech(t)" />
        </div>
        <div class="right">
          <div class="small muted nowrap">{{ fmtTime(t.finished_at || t.started_at || t.created_at) }}</div>
          <button v-if="['failed', 'waiting_human'].includes(t.status) && t.kind !== 'execute'" class="sm ghost" style="margin-top: 4px" @click="retry(t)">{{ $t('runs.tryAgain') }}</button>
          <button v-if="['failed', 'waiting_human'].includes(t.status) && ['apply', 'discover'].includes(t.kind)" class="sm ghost" style="margin-top: 4px" :title="$t('runs.forWhenASite')" @click="retryNative(t)">{{ $t('runs.tryAgainInThe') }}</button>
        </div>
      </div>
    </div>
    <EmptyState v-if="!shown.length" icon="activity" :title="filter === 'all' ? $t('runs.noActivityYet') : $t('runs.noUnfinishedTasks')" />
  </div>

  <div v-if="tab === 'notes'" class="card">
    <div class="list">
      <div v-for="n in notes" :key="n.id" class="item">
        <span v-if="n.category === 'heard'" class="badge info">{{ $t('runs.received') }}</span>
        <span v-else class="badge" :class="n.sent ? 'ok' : ''">{{ n.sent ? $t('runs.sent') : $t('runs.notSent') }}</span>
        <div><div class="sub" style="white-space: pre-line; color: var(--text)">{{ n.text }}</div><div v-if="n.error" class="err small">{{ n.error }}</div></div>
        <span class="small muted nowrap">{{ CAT[n.category] || '' }} · {{ fmtTime(n.created_at) }}</span>
      </div>
    </div>
    <EmptyState v-if="!notes.length" icon="bell" :title="$t('runs.noNotificationsSentYet')" :text="$t('runs.connectTelegramOrDiscord')" />
  </div>

  </template>
</template>

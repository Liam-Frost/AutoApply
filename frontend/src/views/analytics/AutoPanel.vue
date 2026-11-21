<script setup>
import { t as T } from '../../i18n/catalog'
// Automation: what the program's tasks did. A task that is "done" has not always succeeded - a filling task is done
// when it has handed the form over - so the outcome is shown in three groups: done, not finished (your move, or still
// running), failed.
// The overview stays compact: the numbers behind the chart open in a panel below its row, the full list of runs and
// the detail of one run open in a drawer.
import Explain from '../../components/Explain.vue'
import { computed, reactive, ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { change, compact, dur, hours, money, pct, rangeQuery } from '../../analytics'
import { i18n } from '../../i18n/catalog'
import { run as runAction } from '../../ui'
import DetailPanel from '../../components/DetailPanel.vue'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'
import Pager from '../../components/Pager.vue'
import SeriesTable from '../../components/SeriesTable.vue'
import SideDrawer from '../../components/SideDrawer.vue'
import SplitBar from '../../components/SplitBar.vue'
import StackChart from '../../components/StackChart.vue'
import TechDetails from '../../components/TechDetails.vue'
import RunDetail from './RunDetail.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, required: true }, range: { type: Object, required: true } })
const t = computed(() => props.d.total)
const SERIES = [{ key: 'success', label: T('analytics.auto.done2'), color: 'var(--ok)' }, { key: 'unfinished', label: T('analytics.auto.notFinishedWaitingFor'), color: 'var(--warn)' }, { key: 'failed', label: T('analytics.auto.failed2'), color: 'var(--bad)' }]
const trend = computed(() => props.d.trend.map((b) => ({ key: b.key, label: b.label, tip: b.key, values: { success: b.success, unfinished: b.unfinished, failed: b.failed } })))
const parts = (k) => [{ key: 'success', label: T('analytics.auto.done2'), value: k.success, color: 'var(--ok)' }, { key: 'unfinished', label: T('analytics.auto.notFinished'), value: k.unfinished, color: 'var(--warn)' },
  { key: 'failed', label: T('analytics.auto.failed2'), value: k.failed + k.interrupted, color: 'var(--bad)' }]
const rate = (v) => (v == null ? '—' : Math.round(v * 100) + '%')
// a question asked in several applications, written into the profile with its answer (the agent answers it from then on)
const remembered = reactive(new Set())
const remember = (r) => runAction(() => api.post('/analytics/asked-again/remember', { question: r.question, answer: String(r.answer) }), i18n.global.t('analytics.asked.done'), () => remembered.add(r.question))
const maxEnd = computed(() => Math.max(1, ...((props.d.agent_runs && props.d.agent_runs.ends) || []).map((e) => e.n)))
// by recruiting system: what the short figures stand for, in whole sentences
const count = (v) => String(Math.round(v))
const TONE = { success: 'ok', handed: 'warn', unknown: 'warn', waiting: 'warn', rerun: 'warn', running: 'info', failed: 'bad', interrupted: 'bad', cancelled: '', skipped: '' }
const unfinishedTip = computed(() => T('analytics.auto.filledInAndWaiting', { p0: t.value.handed, p1: t.value.unknown, p2: t.value.waiting, p3: t.value.rerun, p4: t.value.running }))
const TITLE = { day: T('analytics.auto.runsPerDay'), week: T('analytics.auto.runsPerWeek'), month: T('analytics.auto.runsPerMonth') }
const failed = computed(() => t.value.failed + t.value.interrupted)
const TOP_REASONS = 5      // on the overview; the rest is one line, and all of them are in the detail view
const topReasons = computed(() => props.d.reasons.slice(0, TOP_REASONS))
const restReasons = computed(() => props.d.reasons.slice(TOP_REASONS).reduce((a, r) => a + r.n, 0))

const table = ref(false)        // the numbers behind the chart, in a panel below the row

// the drawer: the full list of runs (a page at a time, from the server), or one run
const SIZE = 15
const drawer = reactive({ open: false, run: null, fromList: false, outcome: '', page: 0, total: 0, rows: null, error: '', reasons: false })
let seq = 0
async function loadList() {
  const mine = ++seq
  drawer.error = ''
  try {
    const r = await api.get('/analytics/automation/runs' + rangeQuery(props.range, { kind: props.params.kind, outcome: drawer.outcome, offset: drawer.page * SIZE, limit: SIZE }))
    if (mine === seq) Object.assign(drawer, { rows: r.rows, total: r.total })
  } catch (e) { if (mine === seq) drawer.error = e.message || T('analytics.auto.couldNotReadThe') }
}
function openList() { Object.assign(drawer, { open: true, run: null, fromList: false, outcome: '', page: 0, rows: null }); loadList() }
function openRun(r, fromList = false) { Object.assign(drawer, { open: true, run: r, fromList }) }
function close() { drawer.open = false; drawer.run = null; drawer.reasons = false }
watch(() => [drawer.page, drawer.outcome], () => { if (drawer.open && !drawer.run) loadList() })
// another range or another kind of task: what the drawer shows would be out of date
watch(() => [props.d, props.params.kind], close)
const pickOutcome = (v) => { drawer.outcome = v; drawer.page = 0 }
</script>

<template>
  <template v-if="t.total">
    <div class="kpis">
      <div class="kpi"><div class="n">{{ t.total }}</div><div class="l">{{ $t('analytics.auto.taskRuns') }}</div><div v-if="d.previous" class="d">{{ change(t.total, d.previous.total) || $t('analytics.auto.noTasksInThe') }}</div></div>
      <div class="kpi">
        <div class="n" :class="{ na: t.success_rate == null }">{{ rate(t.success_rate) }}</div><div class="l">{{ $t('analytics.auto.successRate') }}</div><div class="d">{{ $t('analytics.auto.of', { p0: t.success, p1: t.settled }) }}</div>
        <Explain>{{ $t('analytics.auto.completedRanToAn') }}</Explain></div>
      <div class="kpi"><div class="n">{{ t.unfinished }}</div><div class="l">{{ $t('analytics.auto.notFinishedNotFailures') }}</div><div class="d">{{ $t('analytics.auto.ofThemWaitingFor', { p0: t.handed + t.waiting + t.unknown }) }}</div>
        <Explain>{{ unfinishedTip }}</Explain></div>
      <div class="kpi">
        <div class="n">{{ t.failed + t.interrupted }}</div><div class="l">{{ $t('analytics.auto.failed') }}</div><div class="d">{{ t.interrupted ? $t('analytics.auto.ofThemInterrupted', { p0: t.interrupted }) : $t('analytics.auto.noneInterrupted') }}</div>
        <Explain>{{ $t('analytics.auto.failedTheTaskStopped') }}</Explain></div>
    </div>

    <div class="an-bar" style="margin-bottom: 12px">
      <span class="small muted">{{ $t('analytics.auto.onlyOneKindOf') }}</span>
      <AaSelect v-model="params.kind" small><option value="">{{ $t('analytics.auto.allTasks') }}</option><option v-for="k in d.kinds" :key="k.kind" :value="k.kind">{{ k.label }}</option></AaSelect>
    </div>

    <div class="an-row c32 tight">
      <div class="card">
        <div class="card-head">
          <span class="card-title">{{ TITLE[d.bucket] }}</span>
          <button class="ghost sm" :aria-expanded="table" @click="table = !table"><Icon :name="table ? 'chevron_up' : 'table'" />{{ table ? $t('analytics.auto.hideDetail') : $t('analytics.auto.showTheDataTable') }}</button>
        </div>
        <p class="card-sub">{{ $t('analytics.auto.byTheDayA') }}</p>
        <StackChart :buckets="trend" :series="SERIES" :format="count" :height="168" />
      </div>
      <div class="card">
        <div class="card-head"><span class="card-title">{{ $t('analytics.auto.mainReasonsForFailure') }}</span><span class="small muted">{{ $t('analytics.auto.failures', { p0: failed }) }}</span></div>
        <p class="card-sub">{{ $t('analytics.auto.groupedByReasonMost') }}</p>
        <template v-if="d.reasons.length">
          <div v-for="r in topReasons" :key="r.key" class="reason" :title="r.messages.map((m) => m.message).join('；')">
            <span class="lab">{{ r.reason }}</span><span class="bar"><i :style="{ width: pct(r.n, d.reasons[0].n) + '%' }"></i></span><span class="n">{{ r.n }}</span>
          </div>
          <div v-if="restReasons" class="reason rest"><span class="lab">{{ $t('analytics.auto.otherReasons', { p0: d.reasons.length - TOP_REASONS }) }}</span><span></span><span class="n">{{ restReasons }}</span></div>
          <div class="card-foot"><button class="ghost sm" @click="drawer.reasons = true"><Icon name="table" />{{ $t('analytics.auto.showAllReasons') }}</button></div>
        </template>
        <EmptyState v-else icon="check" :title="$t('analytics.auto.noFailedTasksIn')" />
      </div>
      <Transition name="an-fade">
        <DetailPanel v-if="table" :title="TITLE[d.bucket]" :sub="$t('analytics.auto.theSameDataAs')" @close="table = false">
          <SeriesTable :buckets="trend" :series="SERIES" :format="count" />
        </DetailPanel>
      </Transition>
    </div>

    <div class="card">
      <div class="card-title">{{ $t('analytics.auto.howEachKindOf') }}</div>
      <p class="card-sub">{{ $t('analytics.auto.durationIsTheMedian') }}</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">{{ $t('analytics.auto.task') }}</th><th class="num">{{ $t('analytics.auto.runs') }}</th><th style="width: 210px">{{ $t('analytics.auto.result') }}</th><th class="num">{{ $t('analytics.auto.successRate') }}</th><th class="num">{{ $t('analytics.auto.typicalTime') }}</th><th class="num">{{ $t('analytics.auto.restarted') }}</th><th class="num">{{ $t('analytics.auto.aiRequests') }}</th><th class="num">{{ $t('analytics.auto.aiCost') }}</th><th class="num">{{ $t('analytics.auto.costPerSuccess') }}</th></tr></thead>
          <tbody>
            <tr v-for="k in d.by_kind" :key="k.kind">
              <td class="grow"><span class="name" :title="k.label">{{ k.label }}</span></td>
              <td class="num">{{ k.total }}</td>
              <td style="width: 210px"><SplitBar :parts="parts(k)" :legend="false" /><div class="small muted nowrap" style="margin-top: 4px">{{ $t('analytics.auto.doneNotFinishedFailed', { p0: k.success, p1: k.unfinished, p2: k.failed + k.interrupted }) }}</div></td>
              <td class="num">{{ rate(k.success_rate) }}</td>
              <td class="num" :title="k.waits_for_you ? $t('analytics.auto.runsHandedToYou') : ''">{{ dur(k.median_s) }}</td>
              <td class="num">{{ k.retried }}</td>
              <td class="num">{{ k.requests ? compact(k.requests) : '—' }}</td>
              <td class="num" :title="k.cost_unknown_requests ? $t('analytics.auto.requestsHaveNoCost', { p0: k.cost_unknown_requests }) : ''">{{ money(k.cost, k.cost != null && k.cost_unknown_requests > 0) }}</td>
              <td class="num" :title="k.cost_per_success != null && k.cost_unknown_requests ? $t('analytics.auto.someRequestsHaveNo') : ''">{{ money(k.cost_per_success, k.cost_unknown_requests > 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint" style="margin-top: 10px">
        {{ $t('analytics.auto.repeatedForTheSame', { p0: d.repeats.objects, p1: d.repeats.extra_runs, p2: d.repeats.auto_retries, p3: d.repeats.restarted }) }}
      </p>
    </div>

    <div v-if="d.applications && d.applications.worked" class="card">
      <div class="card-title">{{ $t('analytics.auto.byApplication') }}
        <Explain>{{ $t('analytics.auto.theFiguresAboveCount') }}</Explain></div>
      <p class="card-sub">{{ $t('analytics.auto.theAgentWorkedApplications', { p0: d.applications.worked }) }}</p>
      <div class="kpis">
        <div class="kpi"><div class="n" :class="{ na: d.applications.prepared.rate == null }">{{ rate(d.applications.prepared.rate) }}</div><div class="l">{{ $t('analytics.auto.prepared') }}</div>
          <div class="d">{{ $t('analytics.auto.of2', { p0: d.applications.prepared.n, p1: d.applications.prepared.of }) }}</div>
          <Explain>{{ $t('analytics.auto.applicationsBroughtToWhere') }}</Explain></div>
        <div class="kpi"><div class="n" :class="{ na: d.applications.alone.rate == null }">{{ rate(d.applications.alone.rate) }}</div><div class="l">{{ $t('analytics.auto.withoutYouSignIns') }}</div>
          <div class="d">{{ $t('analytics.auto.of2', { p0: d.applications.alone.n, p1: d.applications.alone.of }) }}</div>
          <Explain>{{ $t('analytics.auto.ofThePreparedApplications') }}</Explain></div>
        <div class="kpi"><div class="n" :class="{ na: d.applications.sent.rate == null }">{{ rate(d.applications.sent.rate) }}</div><div class="l">{{ $t('analytics.auto.sentWithEvidenceOf') }}</div>
          <div class="d">{{ $t('analytics.auto.of2', { p0: d.applications.sent.n, p1: d.applications.sent.of }) }}</div>
          <Explain>{{ $t('analytics.auto.ofTheApplicationsYou') }}</Explain></div>
        <div class="kpi"><div class="n" :class="{ na: d.applications.median_s == null }">{{ dur(d.applications.median_s) }}</div><div class="l">{{ $t('analytics.auto.timeForOneApplication') }}</div>
          <div class="d">{{ d.applications.median_tokens ? $t('analytics.auto.aboutTokensOfAi', { p0: compact(d.applications.median_tokens) }) : $t('analytics.auto.noAiUseOn') }}</div>
          <Explain>{{ $t('analytics.auto.allRunsOfOne') }}</Explain></div>
      </div>
    </div>

    <div v-if="d.agent_runs && d.agent_runs.applications" class="card">
      <div class="card-title">{{ $t('analytics.auto.howAnApplicationGets') }}
        <Explain>{{ $t('analytics.auto.fromEachApplicationsOwn') }}</Explain></div>
      <p class="card-sub">{{ $t('analytics.auto.applicationsHadRunsIn', { p0: d.agent_runs.applications, p1: d.agent_runs.runs }) }}<template v-if="d.agent_runs.idle_runs">{{ $t('analytics.auto.moreRunsDidNot', { p0: d.agent_runs.idle_runs }) }}</template>。</p>
      <div class="kpis">
        <div class="kpi"><div class="n">{{ d.agent_runs.runs_per_application.median ?? '—' }}</div><div class="l">{{ $t('analytics.auto.runsPerApplicationMedian') }}</div>
          <div class="d">{{ $t('analytics.auto.meanAtMost', { p0: d.agent_runs.runs_per_application.mean, p1: d.agent_runs.runs_per_application.max }) }}</div></div>
        <div class="kpi"><div class="n" :class="{ na: d.agent_runs.again.rate == null }">{{ rate(d.agent_runs.again.rate) }}</div><div class="l">{{ $t('analytics.auto.stepsSpentGoingOver') }}</div>
          <div class="d">{{ $t('analytics.auto.steps', { p0: d.agent_runs.again.steps, p1: d.agent_runs.again.of }) }}</div>
          <Explain>{{ $t('analytics.auto.toolCallsOfEvery') }}</Explain></div>
      </div>
      <div class="an-row c11 tight" style="margin: 0">
        <div>
          <div class="small muted" style="margin-bottom: 6px">{{ $t('analytics.auto.howEachRunEnded') }}</div>
          <div class="hbars tight" style="--lab: 9em">
            <template v-for="e in d.agent_runs.ends" :key="e.key">
              <span class="lab">{{ e.label }}</span>
              <div class="track"><div class="fill" :style="{ width: pct(e.n, maxEnd) + '%' }"></div></div>
              <span class="num">{{ e.n }}</span>
            </template>
          </div>
        </div>
        <div>
          <div class="small muted" style="margin-bottom: 6px">{{ $t('analytics.auto.upToReadyTo') }}</div>
          <table class="an-table">
            <thead><tr><th>{{ $t('analytics.auto.applicantTrackingSystem') }}</th><th class="num">{{ $t('analytics.auto.apply') }}</th><th class="num">{{ $t('analytics.auto.done') }}</th><th class="num">{{ $t('analytics.auto.stepsMedian') }}</th><th class="num">{{ $t('analytics.auto.timeMedian') }}</th></tr></thead>
            <tbody><tr v-for="r in d.agent_runs.by_system" :key="r.key"><td>{{ r.label }}</td><td class="num">{{ r.apps }}</td><td class="num">{{ r.done }}</td>
              <td class="num">{{ r.median_steps ?? '—' }}</td><td class="num">{{ r.median_seconds == null ? '—' : dur(r.median_seconds) }}</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="d.asked_again && d.asked_again.total" class="card">
      <div class="card-head"><span class="card-title">{{ $t('analytics.asked.title') }}<Explain>{{ $t('analytics.asked.explain') }}</Explain></span>
        <span class="badge warn">{{ d.asked_again.total }}</span></div>
      <p class="card-sub">{{ $t('analytics.asked.sub') }}</p>
      <table class="an-table">
        <thead><tr><th>{{ $t('analytics.asked.question') }}</th><th class="num">{{ $t('analytics.asked.times') }}</th><th>{{ $t('analytics.asked.answer') }}</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in d.asked_again.rows" :key="r.question">
            <td :title="r.applications.map((a) => a.company).join(', ')">{{ r.question }}</td>
            <td class="num">{{ r.times }}</td>
            <td>{{ r.answer ?? '—' }}</td>
            <td class="nowrap">
              <span v-if="r.in_profile || remembered.has(r.question)" class="tag ok">{{ $t('analytics.asked.inProfile') }}</span>
              <button v-else-if="r.answer != null && r.answer !== ''" class="sm" @click="remember(r)">{{ $t('analytics.asked.remember') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="d.unknown_settled && (d.unknown_settled.settled || d.unknown_settled.open_total)" class="card">
      <div class="card-title">{{ $t('analytics.unknown.title') }}<Explain>{{ $t('analytics.unknown.explain') }}</Explain></div>
      <div class="kpis">
        <div class="kpi"><div class="n" :class="{ na: d.unknown_settled.median_hours == null }">{{ hours(d.unknown_settled.median_hours) }}</div><div class="l">{{ $t('analytics.unknown.median') }}</div>
          <div class="d">{{ $t('analytics.unknown.settled', { n: d.unknown_settled.settled, out: d.unknown_settled.went_out, mail: d.unknown_settled.by_mail }) }}</div></div>
        <div class="kpi"><div class="n">{{ d.unknown_settled.open_total }}</div><div class="l">{{ $t('analytics.unknown.open') }}</div>
          <div v-for="o in d.unknown_settled.open" :key="o.id" class="d"><router-link :to="`/applications/${o.id}`">{{ o.company }}</router-link> · {{ hours(o.hours) }}</div></div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><span class="card-title">{{ $t('analytics.auto.recentRuns') }}</span>
        <button v-if="d.recent_total > d.recent.length" class="ghost sm" @click="openList"><Icon name="table" />{{ $t('analytics.auto.showAllRuns', { p0: d.recent_total }) }}</button></div>
      <p class="card-sub">{{ $t('analytics.auto.theLastRunsClick', { p0: d.recent.length }) }}</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">{{ $t('analytics.auto.task') }}</th><th>{{ $t('analytics.auto.start') }}</th><th>{{ $t('analytics.auto.result') }}</th><th class="num">{{ $t('analytics.auto.duration') }}</th><th class="num">{{ $t('analytics.auto.aiRequests') }}</th><th class="num">Token</th><th class="num">{{ $t('analytics.auto.aiCost') }}</th><th>{{ $t('analytics.auto.whyItDidNot') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in d.recent" :key="r.id" class="clickable" tabindex="0" @click="openRun(r)" @keydown.enter="openRun(r)">
              <td class="grow"><span class="one" style="font-weight: 550">{{ r.label }}</span><span v-if="r.subject" class="one small muted" :title="r.subject">{{ r.subject }}</span></td>
              <td class="nowrap">{{ fmt(r.at) }}</td>
              <td><span class="badge" :class="TONE[r.outcome]">{{ r.outcome_label }}</span></td>
              <td class="num">{{ dur(r.duration_s) }}</td>
              <td class="num">{{ r.requests || '—' }}</td>
              <td class="num">{{ r.tokens ? compact(r.tokens) : '—' }}</td>
              <td class="num">{{ r.requests ? money(r.cost, r.cost_partial && r.cost != null) : '—' }}</td>
              <td class="note"><span v-if="r.reason" class="one" :title="r.stage ? $t('analytics.auto.stoppedAt', { p0: r.reason, p1: r.stage }) : r.reason">{{ r.reason_label || r.reason }}</span><span v-else class="muted">—</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
  <div v-else class="card">
    <EmptyState icon="activity" :title="params.kind ? $t('analytics.auto.noTasksOfThis') : $t('analytics.auto.theProgramRanNo')" :text="$t('analytics.auto.tryAnotherTimeRange')">
      <button v-if="params.kind" @click="params.kind = ''">{{ $t('analytics.auto.showAllTasks') }}</button>
    </EmptyState>
  </div>

  <SideDrawer v-if="drawer.open && drawer.run" :title="drawer.run.label" :sub="drawer.run.subject" :back="drawer.fromList ? $t('analytics.auto.backToTheList') : ''" @close="close" @back="drawer.run = null">
    <RunDetail :run="drawer.run" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.reasons" :title="$t('analytics.auto.allReasonsForFailure')" :sub="$t('analytics.auto.failuresInThisPeriod', { p0: failed, p1: d.reasons.length })" @close="close">
    <div v-for="r in d.reasons" :key="r.key" class="reason-full">
      <div class="reason" style="border: 0"><span class="lab" style="font-weight: 650">{{ r.reason }}<span class="muted small" style="font-weight: 400; margin-left: 8px">{{ r.kinds.join('、') }}</span></span>
        <span class="bar"><i :style="{ width: pct(r.n, d.reasons[0].n) + '%' }"></i></span><span class="n">{{ r.n }}</span></div>
      <div v-for="m in r.messages" :key="m.message" class="msg">
        <div><span class="n">{{ $t('analytics.auto.text', { p0: m.n }) }}</span>{{ m.message }}</div>
        <TechDetails v-if="m.raw && m.raw !== m.message" :text="m.raw" :label="$t('analytics.auto.theTextAsRecorded')" />
      </div>
    </div>
  </SideDrawer>
  <SideDrawer v-else-if="drawer.open" :title="$t('analytics.auto.allRuns')" :sub="$t('analytics.auto.inAllNewestFirst', { p0: drawer.total })" @close="close">
    <div class="an-bar" style="margin-bottom: 12px">
      <div class="seg"><button v-for="[k, l] in [['', $t('analytics.auto.all')], ['success', $t('analytics.auto.done2')], ['unfinished', $t('analytics.auto.notFinished')], ['failed', $t('analytics.auto.failed2')]]" :key="k" :class="{ on: drawer.outcome === k }" @click="pickOutcome(k)">{{ l }}</button></div>
    </div>
    <div v-if="drawer.error" class="err">{{ drawer.error }}</div>
    <div v-else-if="!drawer.rows" class="skel" style="height: 200px"></div>
    <EmptyState v-else-if="!drawer.rows.length" icon="activity" :title="$t('analytics.auto.noRunsMatch')" />
    <template v-else>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">{{ $t('analytics.auto.task') }}</th><th>{{ $t('analytics.auto.start') }}</th><th>{{ $t('analytics.auto.result') }}</th><th class="num">{{ $t('analytics.auto.duration') }}</th><th class="num">{{ $t('analytics.auto.aiRequests') }}</th><th class="num">{{ $t('analytics.auto.aiCost') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in drawer.rows" :key="r.id" class="clickable" tabindex="0" @click="openRun(r, true)" @keydown.enter="openRun(r, true)">
              <td class="grow"><span class="one" style="font-weight: 550">{{ r.label }}</span><span v-if="r.subject" class="one small muted" :title="r.subject">{{ r.subject }}</span></td>
              <td class="nowrap">{{ fmt(r.at) }}</td>
              <td><span class="badge" :class="TONE[r.outcome]">{{ r.outcome_label }}</span></td>
              <td class="num">{{ dur(r.duration_s) }}</td>
              <td class="num">{{ r.requests || '—' }}</td>
              <td class="num">{{ r.requests ? money(r.cost, r.cost_partial && r.cost != null) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager v-model:page="drawer.page" :size="SIZE" :total="drawer.total" />
    </template>
  </SideDrawer>
</template>

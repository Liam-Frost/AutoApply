<script setup>
import { t as T } from '../../i18n/catalog'
// Automation: what the program's tasks did. A task that is "done" has not always succeeded - a filling task is done
// when it has handed the form over - so the outcome is shown in three groups: done, not finished (your move, or still
// running), failed.
// The overview stays compact: the numbers behind the chart open in a panel below its row, the full list of runs and
// the detail of one run open in a drawer. Figures that belong together are one card of plain figures, never tiles in a
// card; two cards share a row only when they hold about as much (layout.js) - the chart beside a long list of failure
// reasons, but over a short one.
import { computed, reactive, ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { change, compact, dur, hours, money, pct, rangeQuery } from '../../analytics'
import { i18n } from '../../i18n/catalog'
import { run as runAction } from '../../ui'
import CardHead from '../../components/CardHead.vue'
import DetailPanel from '../../components/DetailPanel.vue'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'
import InfoTip from '../../components/InfoTip.vue'
import Pager from '../../components/Pager.vue'
import Popover from '../../components/Popover.vue'
import SeriesTable from '../../components/SeriesTable.vue'
import SideDrawer from '../../components/SideDrawer.vue'
import SplitBar from '../../components/SplitBar.vue'
import StackChart from '../../components/StackChart.vue'
import Status from '../../components/Status.vue'
import TechDetails from '../../components/TechDetails.vue'
import Trunc from '../../components/Trunc.vue'
import EntityCell from '../../components/cells/EntityCell.vue'
import Kpi from './Kpi.vue'
import RunDetail from './RunDetail.vue'
import { H, bars, pairs, reasons, table as tall } from './layout'

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
// the chart (its legend and foot) beside the reasons only when they fill about as much
const CHART = H.card + 168 + H.legend + H.foot + 52      // (the stacked chart, its axis, legend and foot)
const reasonPair = computed(() => pairs(CHART, props.d.reasons.length ? reasons(topReasons.value.length + (restReasons.value ? 1 : 0), { foot: H.foot }) : H.card + 40))
// how each run ended beside the recruiting systems' table
const runEnds = computed(() => (props.d.agent_runs && props.d.agent_runs.ends) || [])
const bySystem = computed(() => (props.d.agent_runs && props.d.agent_runs.by_system) || [])
const runsPair = computed(() => pairs(bars(runEnds.value.length), tall(bySystem.value.length)))

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
      <Kpi :value="t.total" :label="$t('analytics.auto.taskRuns')"><div v-if="d.previous" class="d">{{ change(t.total, d.previous.total) || $t('analytics.auto.noTasksInThe') }}</div></Kpi>
      <Kpi :value="rate(t.success_rate)" :tone="t.success_rate == null ? 'na' : ''" :label="$t('analytics.auto.successRate')" :help="$t('analytics.auto.completedRanToAn')"><div class="d">{{ $t('analytics.auto.of', { p0: t.success, p1: t.settled }) }}</div></Kpi>
      <Kpi :value="t.unfinished" :label="$t('analytics.auto.notFinishedNotFailures')" :help="unfinishedTip"><div class="d">{{ $t('analytics.auto.ofThemWaitingFor', { p0: t.handed + t.waiting + t.unknown }) }}</div></Kpi>
      <Kpi :value="failed" :label="$t('analytics.auto.failed')" :help="$t('analytics.auto.failedTheTaskStopped')"><div class="d">{{ t.interrupted ? $t('analytics.auto.ofThemInterrupted', { p0: t.interrupted }) : $t('analytics.auto.noneInterrupted') }}</div></Kpi>
    </div>

    <div class="an-bar">
      <span id="an-kind" class="t-meta">{{ $t('analytics.auto.onlyOneKindOf') }}</span>
      <AaSelect v-model="params.kind" small aria-labelledby="an-kind"><option value="">{{ $t('analytics.auto.allTasks') }}</option><option v-for="k in d.kinds" :key="k.kind" :value="k.kind">{{ k.label }}</option></AaSelect>
    </div>

    <div class="an-row" :class="reasonPair ? 'c32 tight' : 'solo'">
      <div class="card">
        <CardHead :title="TITLE[d.bucket]" :help="$t('analytics.auto.byTheDayA')" />
        <StackChart :buckets="trend" :series="SERIES" :format="count" :height="168" />
        <div class="card-foot"><button class="ghost sm" :aria-expanded="table" @click="table = !table"><Icon :name="table ? 'chevron_up' : 'table'" />{{ table ? $t('analytics.auto.hideDetail') : $t('analytics.auto.showTheDataTable') }}</button></div>
      </div>
      <!-- (over the chart's whole width, the reasons come after the chart's own table) -->
      <div class="card an-later">
        <CardHead :title="$t('analytics.auto.mainReasonsForFailure')" :help="$t('analytics.auto.groupedByReasonMost')" :note="$t('analytics.auto.failures', { p0: failed })" />
        <template v-if="d.reasons.length">
          <div v-for="r in topReasons" :key="r.key" class="reason">
            <Trunc class="lab" :text="r.reason" /><span class="bar"><i :style="{ width: pct(r.n, d.reasons[0].n) + '%' }"></i></span><span class="n">{{ r.n }}</span>
          </div>
          <div v-if="restReasons" class="reason rest"><span class="lab">{{ $t('analytics.auto.otherReasons', { p0: d.reasons.length - TOP_REASONS }) }}</span><span></span><span class="n">{{ restReasons }}</span></div>
          <div class="card-foot"><button class="ghost sm" @click="drawer.reasons = true"><Icon name="table" />{{ $t('analytics.auto.showAllReasons') }}</button></div>
        </template>
        <EmptyState v-else class="line" icon="check" :title="$t('analytics.auto.noFailedTasksIn')" />
      </div>
      <Transition name="an-fade">
        <DetailPanel v-if="table" :title="TITLE[d.bucket]" :sub="$t('analytics.auto.theSameDataAs')" @close="table = false">
          <SeriesTable :buckets="trend" :series="SERIES" :format="count" />
        </DetailPanel>
      </Transition>
    </div>

    <div class="card">
      <CardHead :title="$t('analytics.auto.howEachKindOf')">
        <template #help>
          <p>{{ $t('analytics.auto.durationIsTheMedian') }}</p>
          <p>{{ $t('analytics.auto.repeatedForTheSame', { p0: d.repeats.objects, p1: d.repeats.extra_runs, p2: d.repeats.auto_retries, p3: d.repeats.restarted }) }}</p>
        </template>
      </CardHead>
      <div class="an-scroll">
        <table class="an-table two">
          <colgroup><col /><col class="w-n" /><col class="w-bar" /><col class="w-m" /><col class="w-wide" /><col class="w-n opt-a" /><col class="w-wide opt-a" /><col class="w-wide" /><col class="w-l opt-b" /></colgroup>
          <thead><tr><th v-tip.overflow>{{ $t('analytics.auto.task') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.runs') }}</th><th v-tip.overflow>{{ $t('analytics.auto.result') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.successRate') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.typicalTime') }}</th><th v-tip.overflow class="num opt-a">{{ $t('analytics.auto.restarted') }}</th><th v-tip.overflow class="num opt-a">{{ $t('analytics.auto.aiRequests') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.aiCost') }}</th><th v-tip.overflow class="num opt-b">{{ $t('analytics.auto.costPerSuccess') }}</th></tr></thead>
          <tbody>
            <tr v-for="k in d.by_kind" :key="k.kind">
              <td><Trunc as="div" class="t-name" :text="k.label" /></td>
              <td class="num">{{ k.total }}</td>
              <td><SplitBar :parts="parts(k)" :legend="false" /><Trunc as="div" class="t-sub" :text="$t('analytics.auto.doneNotFinishedFailed', { p0: k.success, p1: k.unfinished, p2: k.failed + k.interrupted })" /></td>
              <td class="num">{{ rate(k.success_rate) }}</td>
              <td class="num"><InfoTip v-if="k.waits_for_you" :text="$t('analytics.auto.runsHandedToYou')" />{{ dur(k.median_s) }}</td>
              <td class="num opt-a">{{ k.retried }}</td>
              <td class="num opt-a">{{ k.requests ? compact(k.requests) : '—' }}</td>
              <td class="num"><InfoTip v-if="k.cost_unknown_requests" :text="$t('analytics.auto.requestsHaveNoCost', { p0: k.cost_unknown_requests })" />{{ money(k.cost, k.cost != null && k.cost_unknown_requests > 0) }}</td>
              <td class="num opt-b"><InfoTip v-if="k.cost_per_success != null && k.cost_unknown_requests" :text="$t('analytics.auto.someRequestsHaveNo')" />{{ money(k.cost_per_success, k.cost_unknown_requests > 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="d.applications && d.applications.worked" class="card">
      <CardHead :title="$t('analytics.auto.byApplication')">
        <template #help>
          <p>{{ $t('analytics.auto.theFiguresAboveCount') }}</p>
          <p>{{ $t('analytics.auto.theAgentWorkedApplications', { p0: d.applications.worked }) }}</p>
        </template>
      </CardHead>
      <div class="kpis inline">
        <Kpi :value="rate(d.applications.prepared.rate)" :tone="d.applications.prepared.rate == null ? 'na' : ''" :label="$t('analytics.auto.prepared')" :help="$t('analytics.auto.applicationsBroughtToWhere')">
          <div class="d">{{ $t('analytics.auto.of2', { p0: d.applications.prepared.n, p1: d.applications.prepared.of }) }}</div></Kpi>
        <Kpi :value="rate(d.applications.alone.rate)" :tone="d.applications.alone.rate == null ? 'na' : ''" :label="$t('analytics.auto.withoutYouSignIns')" :help="$t('analytics.auto.ofThePreparedApplications')">
          <div class="d">{{ $t('analytics.auto.of2', { p0: d.applications.alone.n, p1: d.applications.alone.of }) }}</div></Kpi>
        <Kpi :value="rate(d.applications.sent.rate)" :tone="d.applications.sent.rate == null ? 'na' : ''" :label="$t('analytics.auto.sentWithEvidenceOf')" :help="$t('analytics.auto.ofTheApplicationsYou')">
          <div class="d">{{ $t('analytics.auto.of2', { p0: d.applications.sent.n, p1: d.applications.sent.of }) }}</div></Kpi>
        <Kpi :value="dur(d.applications.median_s)" :tone="d.applications.median_s == null ? 'na' : ''" :label="$t('analytics.auto.timeForOneApplication')" :help="$t('analytics.auto.allRunsOfOne')">
          <div class="d">{{ d.applications.median_tokens ? $t('analytics.auto.aboutTokensOfAi', { p0: compact(d.applications.median_tokens) }) : $t('analytics.auto.noAiUseOn') }}</div></Kpi>
      </div>
    </div>

    <template v-if="d.agent_runs && d.agent_runs.applications">
      <div class="card">
        <CardHead :title="$t('analytics.auto.howAnApplicationGets')" :help="$t('analytics.auto.fromEachApplicationsOwn')" />
        <p class="card-sub">{{ $t('analytics.auto.applicationsHadRunsIn', { p0: d.agent_runs.applications, p1: d.agent_runs.runs }) }}<template v-if="d.agent_runs.idle_runs">{{ $t('analytics.auto.moreRunsDidNot', { p0: d.agent_runs.idle_runs }) }}</template></p>
        <div class="kpis inline">
          <Kpi :value="d.agent_runs.runs_per_application.median ?? '—'" :label="$t('analytics.auto.runsPerApplicationMedian')">
            <div class="d">{{ $t('analytics.auto.meanAtMost', { p0: d.agent_runs.runs_per_application.mean, p1: d.agent_runs.runs_per_application.max }) }}</div></Kpi>
          <Kpi :value="rate(d.agent_runs.again.rate)" :tone="d.agent_runs.again.rate == null ? 'na' : ''" :label="$t('analytics.auto.stepsSpentGoingOver')" :help="$t('analytics.auto.toolCallsOfEvery')">
            <div class="d">{{ $t('analytics.auto.steps', { p0: d.agent_runs.again.steps, p1: d.agent_runs.again.of }) }}</div></Kpi>
        </div>
      </div>
      <!-- the same runs, two ways: how each ended, and by recruiting system - two cards, side by side when of a size -->
      <div v-if="runEnds.length || bySystem.length" class="an-row" :class="{ c11: runsPair }">
        <div v-if="runEnds.length" class="card">
          <CardHead :title="$t('analytics.auto.howEachRunEnded')" />
          <div class="hbars tight even lab-md">
            <template v-for="e in runEnds" :key="e.key">
              <Trunc class="lab" :text="e.label" />
              <div class="track"><div class="fill" :style="{ width: pct(e.n, maxEnd) + '%' }"></div></div>
              <span class="num">{{ e.n }}</span>
            </template>
          </div>
        </div>
        <div v-if="bySystem.length" class="card">
          <CardHead :title="$t('analytics.auto.upToReadyTo')" />
          <div class="an-scroll">
            <table class="an-table">
              <colgroup><col /><col class="w-n" /><col class="w-xs" /><col class="w-wide" /><col class="w-wide" /></colgroup>
              <thead><tr><th v-tip.overflow>{{ $t('analytics.auto.applicantTrackingSystem') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.apply') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.done') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.stepsMedian') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.timeMedian') }}</th></tr></thead>
              <tbody><tr v-for="r in bySystem" :key="r.key"><td><Trunc :text="r.label" /></td><td class="num">{{ r.apps }}</td><td class="num">{{ r.done }}</td>
                <td class="num">{{ r.median_steps ?? '—' }}</td><td class="num">{{ r.median_seconds == null ? '—' : dur(r.median_seconds) }}</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </template>

    <div v-if="d.asked_again && d.asked_again.total" class="card">
      <CardHead :title="$t('analytics.asked.title')" :note="d.asked_again.total">
        <template #help><p>{{ $t('analytics.asked.explain') }}</p><p>{{ $t('analytics.asked.sub') }}</p></template>
      </CardHead>
      <div class="an-scroll">
        <table class="an-table two">
          <colgroup><col /><col class="w-n" /><col class="w-ans" /><col class="w-do" /></colgroup>
          <thead><tr><th v-tip.overflow>{{ $t('analytics.asked.question') }}</th><th v-tip.overflow class="num">{{ $t('analytics.asked.times') }}</th><th v-tip.overflow>{{ $t('analytics.asked.answer') }}</th><th v-tip.overflow :aria-label="$t('analytics.asked.remember')"></th></tr></thead>
          <tbody>
            <tr v-for="r in d.asked_again.rows" :key="r.question">
              <td><Trunc :lines="2" :text="r.question" /></td>
              <td class="num">
                <Popover v-if="r.applications && r.applications.length" :label="$t('analytics.asked.where')" :width="260" align="end">
                  <template #trigger="{ toggle, attrs }"><button type="button" class="fig-link" v-bind="attrs" @click="toggle">{{ r.times }}</button></template>
                  <div class="an-label">{{ $t('analytics.asked.where') }}</div>
                  <ul class="plain-list"><li v-for="(a, i) in r.applications" :key="i">{{ a.company }}</li></ul>
                </Popover>
                <template v-else>{{ r.times }}</template>
              </td>
              <td><Trunc v-if="r.answer != null && r.answer !== ''" :lines="2" :text="String(r.answer)" /><span v-else class="none">—</span></td>
              <td class="act">
                <Status v-if="r.in_profile || remembered.has(r.question)" tone="ok" :label="$t('analytics.asked.inProfile')" />
                <button v-else-if="r.answer != null && r.answer !== ''" class="sm" @click="remember(r)">{{ $t('analytics.asked.remember') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="d.unknown_settled && (d.unknown_settled.settled || d.unknown_settled.open_total)" class="card">
      <CardHead :title="$t('analytics.unknown.title')" :help="$t('analytics.unknown.explain')" />
      <div class="kpis inline">
        <Kpi :value="hours(d.unknown_settled.median_hours)" :tone="d.unknown_settled.median_hours == null ? 'na' : ''" :label="$t('analytics.unknown.median')">
          <div class="d">{{ $t('analytics.unknown.settled', { n: d.unknown_settled.settled, out: d.unknown_settled.went_out, mail: d.unknown_settled.by_mail }) }}</div></Kpi>
        <Kpi :value="d.unknown_settled.open_total" :label="$t('analytics.unknown.open')" />
      </div>
      <!-- the ones still not known: a short list under the figures, each with how long it has waited -->
      <div v-if="d.unknown_settled.open.length" class="rows an-open">
        <div v-for="o in d.unknown_settled.open" :key="o.id" class="r">
          <EntityCell :primary="o.company" :secondary="o.title" :to="`/applications/${o.id}`" />
          <span class="end num atomic t-secondary">{{ hours(o.hours) }}</span>
        </div>
      </div>
    </div>

    <div class="card">
      <CardHead :title="$t('analytics.auto.recentRuns')" :help="$t('analytics.auto.theLastRunsClick', { p0: d.recent.length })">
        <button v-if="d.recent_total > d.recent.length" class="ghost sm" @click="openList"><Icon name="table" />{{ $t('analytics.auto.showAllRuns', { p0: d.recent_total }) }}</button>
      </CardHead>
      <div class="an-scroll">
        <table class="an-table two">
          <colgroup><col /><col class="w-date" /><col class="w-state" /><col class="w-dur" /><col class="w-wide opt-a" /><col class="w-n opt-a" /><col class="w-num" /><col class="w-note opt-b" /></colgroup>
          <thead><tr><th v-tip.overflow>{{ $t('analytics.auto.task') }}</th><th v-tip.overflow>{{ $t('analytics.auto.start') }}</th><th v-tip.overflow>{{ $t('analytics.auto.result') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.duration') }}</th><th v-tip.overflow class="num opt-a">{{ $t('analytics.auto.aiRequests') }}</th><th v-tip.overflow class="num opt-a">{{ $t('analytics.page.tokens') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.aiCost') }}</th><th v-tip.overflow class="opt-b">{{ $t('analytics.auto.whyItDidNot') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in d.recent" :key="r.id" class="clickable" tabindex="0" @click="openRun(r)" @keydown.enter="openRun(r)">
              <td><Trunc as="div" class="t-name" :text="r.label" /><Trunc as="div" class="t-sub" :text="r.subject || '—'" /></td>
              <td class="atomic">{{ fmt(r.at) }}</td>
              <td><Status :tone="TONE[r.outcome]" :label="r.outcome_label" /></td>
              <td class="num">{{ dur(r.duration_s) }}</td>
              <td class="num opt-a">{{ r.requests || '—' }}</td>
              <td class="num opt-a">{{ r.tokens ? compact(r.tokens) : '—' }}</td>
              <td class="num">{{ r.requests ? money(r.cost, r.cost_partial && r.cost != null) : '—' }}</td>
              <td class="opt-b"><span v-if="r.reason" v-tip.overflow="r.stage ? $t('analytics.auto.stoppedAt', { p0: r.reason, p1: r.stage }) : r.reason" class="cut2">{{ r.reason_label || r.reason }}</span><span v-else class="none">—</span></td>
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
      <div class="reason head"><span class="lab"><span class="t-primary">{{ r.reason }}</span> <span class="t-meta">{{ r.kinds.join(' · ') }}</span></span>
        <span class="bar"><i :style="{ width: pct(r.n, d.reasons[0].n) + '%' }"></i></span><span class="n">{{ r.n }}</span></div>
      <div v-for="m in r.messages" :key="m.message" class="msg">
        <div><span class="n">{{ $t('analytics.auto.text', { p0: m.n }) }}</span>{{ m.message }}</div>
        <TechDetails v-if="m.raw && m.raw !== m.message" :text="m.raw" :label="$t('analytics.auto.theTextAsRecorded')" />
      </div>
    </div>
  </SideDrawer>
  <SideDrawer v-else-if="drawer.open" :title="$t('analytics.auto.allRuns')" :sub="$t('analytics.auto.inAllNewestFirst', { p0: drawer.total })" @close="close">
    <div class="an-bar">
      <div class="seg" role="group" :aria-label="$t('analytics.auto.result')"><button v-for="[k, l] in [['', $t('analytics.auto.all')], ['success', $t('analytics.auto.done2')], ['unfinished', $t('analytics.auto.notFinished')], ['failed', $t('analytics.auto.failed2')]]" :key="k" :class="{ on: drawer.outcome === k }" :aria-pressed="drawer.outcome === k" @click="pickOutcome(k)">{{ l }}</button></div>
    </div>
    <div v-if="drawer.error" class="err">{{ drawer.error }}</div>
    <div v-else-if="!drawer.rows" class="skel tall"></div>
    <EmptyState v-else-if="!drawer.rows.length" icon="activity" :title="$t('analytics.auto.noRunsMatch')" />
    <template v-else>
      <div class="an-scroll">
        <table class="an-table two">
          <colgroup><col /><col class="w-date" /><col class="w-state" /><col class="w-dur" /><col class="w-n opt-b" /><col class="w-num" /></colgroup>
          <thead><tr><th v-tip.overflow>{{ $t('analytics.auto.task') }}</th><th v-tip.overflow>{{ $t('analytics.auto.start') }}</th><th v-tip.overflow>{{ $t('analytics.auto.result') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.duration') }}</th><th v-tip.overflow class="num opt-b">{{ $t('analytics.auto.aiRequests') }}</th><th v-tip.overflow class="num">{{ $t('analytics.auto.aiCost') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in drawer.rows" :key="r.id" class="clickable" tabindex="0" @click="openRun(r, true)" @keydown.enter="openRun(r, true)">
              <td><Trunc as="div" class="t-name" :text="r.label" /><Trunc as="div" class="t-sub" :text="r.subject || '—'" /></td>
              <td class="atomic">{{ fmt(r.at) }}</td>
              <td><Status :tone="TONE[r.outcome]" :label="r.outcome_label" /></td>
              <td class="num">{{ dur(r.duration_s) }}</td>
              <td class="num opt-b">{{ r.requests || '—' }}</td>
              <td class="num">{{ r.requests ? money(r.cost, r.cost_partial && r.cost != null) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager v-model:page="drawer.page" :size="SIZE" :total="drawer.total" />
    </template>
  </SideDrawer>
</template>

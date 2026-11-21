<script setup>
import { t as T } from '../../i18n/catalog'
// Applications: what came of them. Every figure here is about the applications SENT in the chosen range (a cohort);
// the one exception - replies by the month they arrived - says so where it is shown.
import { computed, ref, watch } from 'vue'
import { change, hours, pct } from '../../analytics'
import { dayText } from '../../i18n/format'
import ColumnChart from '../../components/ColumnChart.vue'
import EmptyState from '../../components/EmptyState.vue'
import Explain from '../../components/Explain.vue'
import Icon from '../../components/Icon.vue'
import Pager from '../../components/Pager.vue'
import SplitBar from '../../components/SplitBar.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, default: () => ({ bucket: '' }) } })
const t = computed(() => props.d.total)
const STATE_COLOR = { silent: 'var(--chart-other)', receipt: 'var(--chart-soft)', assessment: 'var(--chart-1)', interview: 'var(--chart-deep)', offer: 'var(--ok)', rejected: 'var(--bad)', other: 'var(--neutral-soft)' }
const states = computed(() => props.d.states.map((s) => ({ ...s, color: STATE_COLOR[s.key] })))
// how many were sent along the stretch of time the page is set to: by day, week or month (the server picks by the
// length of the stretch unless one is chosen here)
const SENT_TITLE = { hour: T('analytics.apps.applicationsPerHourToday'), day: T('analytics.apps.applicationsPerDay'), week: T('analytics.apps.applicationsPerWeek'), month: T('analytics.apps.applicationsPerMonth') }
const SENT_SUB = { hour: T('analytics.apps.byTheHourThey'), day: T('analytics.apps.byTheDayThey'), week: T('analytics.apps.byTheWeekThey'), month: T('analytics.apps.byTheMonthSent') }
const STEP_HEAD = { hour: T('analytics.apps.hour'), day: T('analytics.apps.date'), week: T('analytics.apps.weekItsMonday'), month: T('analytics.apps.month') }
const steps = computed(() => (props.d.by_time ? props.d.by_time.rows : []))
const size = computed(() => (props.d.by_time ? props.d.by_time.bucket : 'month'))
// (every step has its label; the chart shows as many of them as it has room for)
const monthly = computed(() => steps.value.map((m) => ({ label: m.label, value: m.n, tip: T('analytics.apps.sentIn', { p0: m.key }) })))
const wait = computed(() => (props.d.median_wait_days == null ? '—' : props.d.median_wait_days ? T('analytics.apps.nDays', { n: props.d.median_wait_days }, props.d.median_wait_days) : T('analytics.apps.sameDay')))
const rateOf = (r) => (r.thin ? '—' : pct(r.decided, r.n) + '%')

// the months as a chart or as a table: one or the other in the same card, never one under the other
const asTable = ref(false)
const page = ref(0)
const SIZE = 6
const months = computed(() => [...steps.value].reverse())
watch(() => props.d.by_time, () => { page.value = 0 })
</script>

<template>
  <template v-if="t.n">
    <div class="kpis">
      <div class="kpi"><div class="n">{{ t.n }}</div><div class="l">{{ $t('analytics.apps.applicationsSubmitted') }}</div><div v-if="d.previous" class="d">{{ change(t.n, d.previous.n) || $t('analytics.apps.nothingSentInThe') }}</div></div>
      <div class="kpi">
        <div class="n">{{ pct(t.replied, t.n) }}%</div><div class="l">{{ $t('analytics.apps.acknowledged') }}</div><div class="d">{{ $t('analytics.apps.of', { p0: t.replied, p1: t.n }) }}</div>
        <Explain>{{ $t('analytics.apps.acknowledgedAnythingCameBack') }}</Explain></div>
      <div class="kpi">
        <div class="n">{{ pct(t.decided, t.n) }}%</div><div class="l">{{ $t('analytics.apps.cameToSomething') }}</div><div class="d">{{ $t('analytics.apps.of', { p0: t.decided, p1: t.n }) }}</div>
        <Explain>{{ $t('analytics.apps.cameToSomethingIt') }}</Explain></div>
      <div class="kpi">
        <div class="n" :class="{ ok: t.progressed }">{{ pct(t.progressed, t.n) }}%</div><div class="l">{{ $t('analytics.apps.reachedAnAssessmentInterview') }}</div><div class="d">{{ $t('analytics.apps.of', { p0: t.progressed, p1: t.n }) }}</div>
        <Explain>{{ $t('analytics.apps.theShareOfApplications') }}</Explain></div>
      <div class="kpi">
        <div class="n" :class="{ na: d.median_wait_days == null }">{{ wait }}</div><div class="l">{{ $t('analytics.apps.typicalWaitForA') }}</div><div class="d">{{ d.waited ? $t('analytics.apps.withARecord', { n: d.waited }, d.waited) : $t('analytics.apps.noRecordsToCompute') }}</div>
        <Explain>{{ $t('analytics.apps.daysFromSendingTo') }}</Explain></div>
    </div>
    <p v-if="d.coverage" class="small muted" style="margin: -4px 0 14px">{{ $t('analytics.apps.applicationsHaveBeenSent', { p0: d.coverage.sent, p1: d.coverage.dated }) }}<template v-if="d.coverage.undated">{{ $t('analytics.apps.anotherAreKnownTo', { p0: d.coverage.undated }) }}<router-link to="/applications">{{ $t('analytics.apps.underMyApplications') }}</router-link>{{ $t('analytics.apps.theDateCanBe') }}</template>。</p>

    <div class="an-row c32">
      <div class="card">
        <div class="card-title">{{ $t('analytics.apps.applicationFunnel') }}</div>
        <p class="card-sub">{{ $t('analytics.apps.eachStepIsA') }}</p>
        <div class="hbars tight even" style="--lab: 13em">
          <template v-for="r in d.funnel" :key="r.key">
            <span class="lab" :title="r.label">{{ r.label }}</span>
            <div class="track rate" :title="$t('analytics.apps.ofThoseSent', { p0: r.label, p1: r.value, p2: pct(r.value, t.n) })"><div class="fill" :class="{ zero: !r.value }" :style="{ width: pct(r.value, t.n) + '%' }"></div></div>
            <span class="num">{{ r.value }} <span class="muted small" style="font-weight: 400">{{ pct(r.value, t.n) }}%</span></span>
          </template>
        </div>
      </div>
      <div class="card">
        <div class="card-title">{{ $t('analytics.apps.whereTheyStandNow') }}</div>
        <p class="card-sub">{{ $t('analytics.apps.eachApplicationIsCounted') }}</p>
        <SplitBar :parts="states" rows />
        <div v-if="d.rejected_after_progress" class="card-foot"><span class="hint">{{ $t('analytics.apps.ofTheRejectedHad', { p0: d.rejected_after_progress }) }}</span></div>
      </div>
    </div>

    <div class="an-row c11">
      <div class="card">
        <div class="card-head">
          <span class="card-title">{{ SENT_TITLE[size] }}</span>
          <div v-if="size !== 'hour'" class="seg" :aria-label="$t('analytics.apps.byWhichLengthOf')"><button v-for="[k, l] in [['', $t('analytics.apps.auto')], ['day', $t('analytics.apps.day')], ['week', $t('analytics.apps.week')], ['month', $t('analytics.apps.month2')]]" :key="k" :class="{ on: params.bucket === k }" @click="params.bucket = k">{{ l }}</button></div>
          <div class="seg" role="tablist" :aria-label="$t('analytics.apps.viewAs')">
            <button role="tab" :aria-selected="!asTable" :class="{ on: !asTable }" @click="asTable = false"><Icon name="chart" />{{ $t('analytics.apps.chart') }}</button>
            <button role="tab" :aria-selected="asTable" :class="{ on: asTable }" @click="asTable = true"><Icon name="table" />{{ $t('analytics.apps.table') }}</button>
          </div>
        </div>
        <p class="card-sub">{{ SENT_SUB[size] }}</p>
        <ColumnChart v-if="!asTable" :data="monthly" :unit="$t('analytics.apps.items')" :table="false" />
        <template v-else>
          <table class="an-table">
            <thead><tr><th>{{ STEP_HEAD[size] }}</th><th class="num">{{ $t('analytics.apps.sent') }}</th><th class="num">{{ $t('analytics.apps.ofWhichCameTo') }}</th><th class="num">{{ $t('analytics.apps.repliesReceivedInIt') }}</th></tr></thead>
            <tbody><tr v-for="m in months.slice(page * SIZE, (page + 1) * SIZE)" :key="m.key"><td>{{ m.key }}</td><td class="num">{{ m.n }}</td><td class="num">{{ m.decided }}</td><td class="num">{{ m.replies }}</td></tr></tbody>
          </table>
          <Pager v-model:page="page" :size="SIZE" :total="months.length" />
          <div class="card-foot"><span class="hint">{{ $t('analytics.apps.theFirstTwoColumns') }}</span></div>
        </template>
      </div>
      <div class="card">
        <div class="card-title">{{ $t('analytics.apps.doHigherScoredPostings') }}</div>
        <p class="card-sub">{{ $t('analytics.apps.theShareOfApplications2') }}</p>
        <div class="hbars tight even" style="--lab: 5.5em">
          <template v-for="r in d.by_score" :key="r.label">
            <span class="lab">{{ /\d/.test(r.label) ? $t('analytics.apps.scoreBand', { p0: r.label }) : r.label }}</span>
            <div class="track rate" :title="$t('analytics.apps.sentCameToSomething', { p0: r.label, p1: r.n, p2: r.decided, p3: r.progressed })"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
        <div class="card-foot"><span class="hint">{{ $t('analytics.apps.groupsWithFewerThan', { p0: d.min_sample }) }}</span></div>
      </div>
    </div>

    <div class="an-row c11">
      <div class="card">
        <div class="card-title">{{ $t('analytics.apps.whereApplyingComesTo') }}</div>
        <p class="card-sub">{{ $t('analytics.apps.byChannelTheShare') }}</p>
        <div class="hbars tight even">
          <template v-for="r in d.by_channel" :key="r.label">
            <span class="lab" :title="r.label">{{ r.label }}</span>
            <div class="track rate" :title="$t('analytics.apps.sentCameToSomething2', { p0: r.label, p1: r.n, p2: r.decided })"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
      <div class="card">
        <div class="card-title">{{ $t('analytics.apps.whichDirectionComesTo') }}</div>
        <p class="card-sub">{{ $t('analytics.apps.byDirectionTheShare') }}</p>
        <div class="hbars tight even">
          <template v-for="r in d.by_direction" :key="r.label">
            <span class="lab" :title="r.label">{{ r.label }}</span>
            <div class="track rate" :title="$t('analytics.apps.sentCameToSomething2', { p0: r.label, p1: r.n, p2: r.decided })"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
    </div>
  </template>
  <div v-else class="card"><EmptyState icon="activity" :title="$t('analytics.apps.noApplicationsSentIn')" :text="$t('analytics.apps.tryADifferentTime')" /></div>

  <div v-if="d.first_record || d.backlog" class="an-row c11">
    <div v-if="d.first_record" class="card">
      <div class="card-title">{{ $t('analytics.first.title') }}<Explain>{{ $t('analytics.first.explain') }}</Explain></div>
      <p class="card-sub">{{ $t('analytics.first.sub', { n: d.first_record.n }, d.first_record.n) }}</p>
      <div class="kpis">
        <div class="kpi"><div class="n" :class="{ na: d.first_record.from_found_hours == null }">{{ hours(d.first_record.from_found_hours) }}</div><div class="l">{{ $t('analytics.first.fromFound') }}</div>
          <div v-if="d.first_record.slow" class="d">{{ $t('analytics.first.slow', { n: d.first_record.slow }, d.first_record.slow) }}</div></div>
        <div class="kpi"><div class="n" :class="{ na: d.first_record.from_begun_hours == null }">{{ hours(d.first_record.from_begun_hours) }}</div><div class="l">{{ $t('analytics.first.fromBegun') }}</div></div>
      </div>
    </div>
    <div v-if="d.backlog" class="card">
      <div class="card-title">{{ $t('analytics.backlog.title') }}<Explain>{{ $t('analytics.backlog.explain') }}</Explain></div>
      <p class="card-sub">{{ $t('analytics.backlog.sub', { handled: d.backlog.handled, open: d.backlog.open }) }}</p>
      <div class="an-row c11 tight" style="margin: 0">
        <table v-if="d.backlog.by_kind.length" class="an-table">
          <thead><tr><th>{{ $t('analytics.backlog.kind') }}</th><th class="num">{{ $t('analytics.backlog.handled') }}</th><th class="num">{{ $t('analytics.backlog.median') }}</th></tr></thead>
          <tbody><tr v-for="r in d.backlog.by_kind" :key="r.kind"><td>{{ r.label }}</td><td class="num">{{ r.n }}</td><td class="num">{{ hours(r.median_hours) }}</td></tr></tbody>
        </table>
        <div v-if="d.backlog.oldest.length">
          <div class="small muted" style="margin-bottom: 6px">{{ $t('analytics.backlog.oldest') }}</div>
          <router-link v-for="o in d.backlog.oldest" :key="o.id" to="/todos" class="small" style="display: flex; gap: 8px; padding: 3px 0">
            <span class="grow clamp2">{{ o.title }}</span><span class="muted nowrap">{{ hours(o.hours) }}</span></router-link>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><span class="card-title">{{ $t('analytics.apps.goodPostingsYouMissed') }}</span><span class="badge" :class="d.missed_total ? 'warn' : 'ok'">{{ $t('analytics.apps.text', { p0: d.missed_total }) }}</span></div>
    <p class="card-sub">{{ $t('analytics.apps.scoredOrHigherAnd') }}</p>
    <div v-if="(d.missed_reasons || []).length" class="row" style="flex-wrap: wrap; gap: 6px; margin-bottom: 10px">
      <span class="small muted">{{ $t('analytics.missed.why') }}</span>
      <span v-for="r in d.missed_reasons" :key="r.key" class="tag">{{ $t('analytics.missed.reason.' + r.key) }} {{ r.n }}</span>
    </div>
    <div v-if="d.missed.length" class="missed">
      <router-link v-for="m in d.missed" :key="m.id" :to="{ path: '/jobs', query: { open: m.id } }">
        <span class="score hi">{{ m.score.toFixed(1) }}</span>
        <div style="min-width: 0"><div class="main">{{ m.company }}</div><div class="sub">{{ m.title }}<template v-if="m.reason"> · {{ $t('analytics.missed.reason.' + m.reason) }}</template></div></div>
        <span class="right"><span class="badge" :class="m.stage === 'expired' ? 'warn' : ''">{{ m.stage === 'expired' ? $t('analytics.apps.deadlinePassed') : $t('analytics.apps.takenDown') }}</span><div v-if="m.deadline" class="small muted" style="margin-top: 2px">{{ $t('analytics.missed.due', { day: dayText(m.deadline) }) }}</div></span>
      </router-link>
    </div>
    <EmptyState v-else icon="check" :title="$t('analytics.apps.noHighScoringPostings')" />
    <p v-if="d.missed_total > d.missed.length" class="hint" style="margin-top: 10px">{{ $t('analytics.apps.onlyTheBestScored', { p0: d.missed.length }) }}</p>
  </div>
</template>

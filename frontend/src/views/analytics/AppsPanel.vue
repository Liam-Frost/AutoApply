<script setup>
import { dirLabel } from '../../directions'
import { t as T } from '../../i18n/catalog'
// Applications: what came of them. Every figure here is about the applications SENT in the chosen range (a cohort);
// the one exception - replies by the month they arrived - says so where it is shown. Below that, how quickly the work
// moves and what waits for the applicant (Pace.vue), then the good postings that were missed.
// Two cards share a row only when they hold about as much (layout.js): the bars by score, by channel and by direction
// have as many rows as the data has groups.
import { computed, ref, watch } from 'vue'
import { change, pct } from '../../analytics'
import { dayText } from '../../i18n/format'
import CardHead from '../../components/CardHead.vue'
import ColumnChart from '../../components/ColumnChart.vue'
import EmptyState from '../../components/EmptyState.vue'
import Pager from '../../components/Pager.vue'
import SplitBar from '../../components/SplitBar.vue'
import Status from '../../components/Status.vue'
import Tabs from '../../components/Tabs.vue'
import Trunc from '../../components/Trunc.vue'
import EntityCell from '../../components/cells/EntityCell.vue'
import Kpi from './Kpi.vue'
import Pace from './Pace.vue'
import { H, bars, pairs, table } from './layout'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, default: () => ({ bucket: '' }) } })
const t = computed(() => props.d.total)
const STATE_COLOR = { silent: 'var(--chart-other)', receipt: 'var(--chart-soft)', assessment: 'var(--chart-1)', interview: 'var(--chart-deep)', offer: 'var(--ok)', rejected: 'var(--bad)', other: 'var(--neutral-soft)' }
const states = computed(() => props.d.states.map((s) => ({ ...s, color: STATE_COLOR[s.key] })))
// how many were sent along the stretch of time the page is set to: by day, week or month (the server picks by the
// length of the stretch unless one is chosen in the page's toolbar)
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

// the chart (or its table) beside the bars by score; the bars by channel beside those by direction
const CHART = H.card + 183      // (the column chart, its axis and labels)
const timeTall = computed(() => (asTable.value ? table(Math.min(SIZE, months.value.length), { foot: months.value.length > SIZE ? H.foot : 0 }) : CHART))
const scorePair = computed(() => pairs(timeTall.value, bars(props.d.by_score.length, { foot: H.hint })))
const groupPair = computed(() => pairs(bars(props.d.by_channel.length), bars(props.d.by_direction.length)))
</script>

<template>
  <template v-if="t.n">
    <div class="kpis">
      <Kpi :value="t.n" :label="$t('analytics.apps.applicationsSubmitted')">
        <template v-if="d.coverage" #help>
          <p>{{ $t('analytics.apps.coverage', { sent: d.coverage.sent, dated: d.coverage.dated }) }}</p>
          <p v-if="d.coverage.undated">{{ $t('analytics.apps.coverageUndated', { n: d.coverage.undated }, d.coverage.undated) }} <router-link to="/applications">{{ $t('analytics.apps.openApplications') }}</router-link></p>
        </template>
        <div v-if="d.previous" class="d">{{ change(t.n, d.previous.n) || $t('analytics.apps.nothingSentInThe') }}</div>
      </Kpi>
      <Kpi :value="pct(t.replied, t.n) + '%'" :label="$t('analytics.apps.acknowledged')" :help="$t('analytics.apps.acknowledgedAnythingCameBack')"><div class="d">{{ $t('analytics.apps.of', { p0: t.replied, p1: t.n }) }}</div></Kpi>
      <Kpi :value="pct(t.decided, t.n) + '%'" :label="$t('analytics.apps.cameToSomething')" :help="$t('analytics.apps.cameToSomethingIt')"><div class="d">{{ $t('analytics.apps.of', { p0: t.decided, p1: t.n }) }}</div></Kpi>
      <Kpi :value="pct(t.progressed, t.n) + '%'" :label="$t('analytics.apps.reachedAnAssessmentInterview')" :help="$t('analytics.apps.theShareOfApplications')"><div class="d">{{ $t('analytics.apps.of', { p0: t.progressed, p1: t.n }) }}</div></Kpi>
      <Kpi :value="wait" :tone="d.median_wait_days == null ? 'na' : ''" :label="$t('analytics.apps.typicalWaitForA')" :help="$t('analytics.apps.daysFromSendingTo')"><div class="d">{{ d.waited ? $t('analytics.apps.withARecord', { n: d.waited }, d.waited) : $t('analytics.apps.noRecordsToCompute') }}</div></Kpi>
    </div>

    <div class="an-row c32">
      <div class="card">
        <CardHead :title="$t('analytics.apps.applicationFunnel')" :help="$t('analytics.apps.eachStepIsA')" />
        <div class="hbars tight even lab-xl">
          <template v-for="r in d.funnel" :key="r.key">
            <Trunc class="lab" :text="r.label" />
            <div v-tip="$t('analytics.apps.ofThoseSent', { p0: r.label, p1: r.value, p2: pct(r.value, t.n) })" class="track rate"><div class="fill" :class="{ zero: !r.value }" :style="{ width: pct(r.value, t.n) + '%' }"></div></div>
            <span class="num">{{ r.value }} <span class="of">{{ pct(r.value, t.n) }}%</span></span>
          </template>
        </div>
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.apps.whereTheyStandNow')" :help="$t('analytics.apps.eachApplicationIsCounted')" />
        <SplitBar :parts="states" rows />
        <div v-if="d.rejected_after_progress" class="card-foot"><span class="hint">{{ $t('analytics.apps.ofTheRejectedHad', { p0: d.rejected_after_progress }) }}</span></div>
      </div>
    </div>

    <div class="an-row" :class="{ c11: scorePair }">
      <div class="card">
        <CardHead :title="SENT_TITLE[size]" :help="asTable ? $t('analytics.apps.theFirstTwoColumns') : SENT_SUB[size]">
          <Tabs :model-value="asTable ? 'table' : 'chart'" :label="$t('analytics.apps.viewAs')" :items="[{ id: 'chart', icon: 'chart', label: $t('analytics.apps.chart') }, { id: 'table', icon: 'table', label: $t('analytics.apps.table') }]" @update:model-value="(v) => (asTable = v === 'table')" />
        </CardHead>
        <ColumnChart v-if="!asTable" :data="monthly" :unit="$t('analytics.apps.items')" :table="false" />
        <template v-else>
          <div class="an-scroll">
            <table class="an-table">
              <colgroup><col /><col class="w-num" /><col class="w-wide" /><col class="w-wide" /></colgroup>
              <thead><tr><th v-tip.overflow>{{ STEP_HEAD[size] }}</th><th v-tip.overflow class="num">{{ $t('analytics.apps.sent') }}</th><th v-tip.overflow class="num">{{ $t('analytics.apps.ofWhichCameTo') }}</th><th v-tip.overflow class="num">{{ $t('analytics.apps.repliesReceivedInIt') }}</th></tr></thead>
              <tbody><tr v-for="m in months.slice(page * SIZE, (page + 1) * SIZE)" :key="m.key"><td class="atomic">{{ m.key }}</td><td class="num">{{ m.n }}</td><td class="num">{{ m.decided }}</td><td class="num">{{ m.replies }}</td></tr></tbody>
            </table>
          </div>
          <Pager v-model:page="page" :size="SIZE" :total="months.length" />
        </template>
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.apps.doHigherScoredPostings')" :help="$t('analytics.apps.theShareOfApplications2')" />
        <div class="hbars tight even lab-sm">
          <template v-for="r in d.by_score" :key="r.label">
            <span class="lab">{{ /\d/.test(r.label) ? $t('analytics.apps.scoreBand', { p0: r.label }) : r.label }}</span>
            <div v-tip="$t('analytics.apps.sentCameToSomething', { p0: r.label, p1: r.n, p2: r.decided, p3: r.progressed })" class="track rate"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="of">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
        <div class="card-foot"><span class="hint">{{ $t('analytics.apps.groupsWithFewerThan', { p0: d.min_sample }) }}</span></div>
      </div>
    </div>

    <div class="an-row" :class="{ c11: groupPair }">
      <div class="card">
        <CardHead :title="$t('analytics.apps.whereApplyingComesTo')" :help="$t('analytics.apps.byChannelTheShare')" />
        <div class="hbars tight even">
          <template v-for="r in d.by_channel" :key="r.label">
            <Trunc class="lab" :text="r.label" />
            <div v-tip="$t('analytics.apps.sentCameToSomething2', { p0: r.label, p1: r.n, p2: r.decided })" class="track rate"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="of">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.apps.whichDirectionComesTo')" :help="$t('analytics.apps.byDirectionTheShare')" />
        <div class="hbars tight even">
          <template v-for="r in d.by_direction" :key="r.label">
            <Trunc class="lab" :text="dirLabel(r.label)" />
            <div v-tip="$t('analytics.apps.sentCameToSomething2', { p0: dirLabel(r.label), p1: r.n, p2: r.decided })" class="track rate"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="of">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
    </div>
  </template>
  <div v-else class="card"><EmptyState icon="activity" :title="$t('analytics.apps.noApplicationsSentIn')" :text="$t('analytics.apps.tryADifferentTime')" /></div>

  <Pace :first="d.first_record" :backlog="d.backlog" />

  <div class="card">
    <CardHead :title="$t('analytics.apps.goodPostingsYouMissed')" :help="$t('analytics.apps.scoredOrHigherAnd')" :note="d.missed_total" />
    <div v-if="(d.missed_reasons || []).length" class="an-facts">
      <span class="t-meta">{{ $t('analytics.missed.why') }}</span>
      <span v-for="r in d.missed_reasons" :key="r.key" class="meta">{{ $t('analytics.missed.reason.' + r.key) }} <b class="num">{{ r.n }}</b></span>
    </div>
    <div v-if="d.missed.length" class="missed">
      <router-link v-for="m in d.missed" :key="m.id" :to="{ path: '/jobs', query: { open: m.id } }">
        <span class="score hi">{{ m.score.toFixed(1) }}</span>
        <EntityCell :primary="m.company" :secondary="m.reason ? m.title + ' · ' + $t('analytics.missed.reason.' + m.reason) : m.title" />
        <span class="when"><Status :tone="m.stage === 'expired' ? 'warn' : ''" :label="m.stage === 'expired' ? $t('analytics.apps.deadlinePassed') : $t('analytics.apps.takenDown')" /><span v-if="m.deadline" class="t-meta atomic">{{ $t('analytics.missed.due', { day: dayText(m.deadline) }) }}</span></span>
      </router-link>
    </div>
    <EmptyState v-else class="line" icon="check" :title="$t('analytics.apps.noHighScoringPostings')" />
    <div v-if="d.missed_total > d.missed.length" class="card-foot"><span class="hint">{{ $t('analytics.apps.onlyTheBestScored', { p0: d.missed.length }) }}</span></div>
  </div>
</template>

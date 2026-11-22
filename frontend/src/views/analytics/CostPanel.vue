<script setup>
import { t as T } from '../../i18n/catalog'
// AI use and cost. A cost here is an estimate at list price unless the service reported one; a call on a subscription
// adds nothing to a bill, and its figure says what the same call would cost on the pay-as-you-go API. What cannot be
// told (no price for the model, no usage reported, records from before requests were kept) is shown as such, apart.
// The overview stays compact: the numbers behind the chart open in a panel below its row; the full lists, one run and
// the price editor open in a drawer.
import { computed, reactive, ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { change, colorOf, compact, money, ms, pct, share } from '../../analytics'
import CardHead from '../../components/CardHead.vue'
import DetailPanel from '../../components/DetailPanel.vue'
import EmptyState from '../../components/EmptyState.vue'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import IconButton from '../../components/IconButton.vue'
import InfoTip from '../../components/InfoTip.vue'
import Pager from '../../components/Pager.vue'
import SeriesTable from '../../components/SeriesTable.vue'
import SideDrawer from '../../components/SideDrawer.vue'
import SplitBar from '../../components/SplitBar.vue'
import StackChart from '../../components/StackChart.vue'
import Status from '../../components/Status.vue'
import Trunc from '../../components/Trunc.vue'
import { run } from '../../ui'
import Kpi from './Kpi.vue'
import RunDetail from './RunDetail.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, required: true } })
const emit = defineEmits(['reload'])
const t = computed(() => props.d.total)
const metric = ref('cost')     // what the trend shows: cost or tokens - two charts' worth of data, never two axes on one
const hasCost = computed(() => t.value.cost != null)
watch(hasCost, (v) => { if (!v) metric.value = 'tokens' }, { immediate: true })
const series = computed(() => props.d.series.map((s, i) => ({ ...s, color: colorOf(i, s.key) })))
const trend = computed(() => props.d.trend.map((b) => ({ key: b.key, label: b.label, tip: b.key, values: metric.value === 'cost' ? b.values : b.token_values,
  note: metric.value === 'cost' && b.unpriced ? T('analytics.cost.moreRequestsHaveNo', { p0: b.unpriced }) : '' })))
const fmtTrend = computed(() => (metric.value === 'cost' ? (v) => money(v) : compact))
const trendTitle = computed(() => (metric.value === 'cost' ? T('analytics.cost.costOverTime') : T('analytics.cost.tokensOverTime')))
const BUCKET = { day: T('analytics.cost.byTheDayOf'), week: T('analytics.cost.byTheDayOf2'), month: T('analytics.cost.byTheDayOf3') }
const KIND_COLOR = { input: 'var(--chart-1)', cache_read: 'var(--chart-3)', cache_write: 'var(--chart-4)', output: 'var(--chart-2)', unsplit: 'var(--chart-other)' }
const tokenParts = computed(() => [...props.d.token_kinds.map((k) => ({ key: k.key, label: k.label, value: k.tokens, color: KIND_COLOR[k.key] })),
  ...(t.value.tokens.unsplit ? [{ key: 'unsplit', label: T('analytics.cost.inputCachedPartNot'), value: t.value.tokens.unsplit, color: KIND_COLOR.unsplit }] : [])])
const costParts = computed(() => props.d.token_kinds.filter((k) => k.cost != null).map((k) => ({ key: k.key, label: k.label, value: k.cost, color: KIND_COLOR[k.key] })))
const metered = computed(() => t.value.by_billing.metered || 0)
const included = computed(() => (t.value.by_billing.subscription || 0) + (t.value.by_billing.local || 0))
const BILL_COLOR = { metered: 'var(--chart-2)', subscription: 'var(--chart-1)', local: 'var(--chart-3)', unknown: 'var(--chart-other)' }
const billParts = computed(() => Object.entries(t.value.by_billing).map(([k, v]) => ({ key: k, label: props.d.billing_labels[k] || k, value: v, color: BILL_COLOR[k] || BILL_COLOR.unknown })))
// the headline for "cost per result": the kind of task that cost the most and has a figure; otherwise the average per call
const headline = computed(() => {
  const u = [...props.d.units].filter((x) => x.per_result != null).sort((a, b) => b.cost - a.cost)[0]
  if (u) return { value: money(u.per_result, u.partial), label: u.per_label, sub: T('analytics.cost.runsFailedResults', { p0: u.runs, p1: u.failed_runs, p2: u.results }), tip: T('analytics.cost.everythingThisKindOf') }
  const per = hasCost.value && t.value.calls ? Math.round(t.value.cost / t.value.calls) : null
  return { value: money(per), label: T('analytics.cost.avgPerCall'), sub: T('analytics.cost.calls2', { p0: t.value.calls }), tip: T('analytics.cost.estimatedCostCallsOne') }
})
// where a model's cost figure comes from: said when the pointer rests on it
const costSource = (m) => (m.cost == null ? '' : m.reported ? T('analytics.cost.costReportedByThe') : m.price && m.price.source === 'user_price' ? T('analytics.cost.estimatedFromThePrice2') : T('analytics.cost.estimatedFromTheBuilt'))
const cacheShare = computed(() => pct(t.value.tokens.cache_read, t.value.tokens_total))
const rate = (v) => (v == null ? '—' : Math.round(v * 100) + '%')
const filtered = computed(() => props.params.provider || props.params.model || props.params.feature)
const clear = () => Object.assign(props.params, { provider: '', model: '', feature: '' })
const W = computed(() => props.d.waste)
const anyWaste = computed(() => W.value.failed_requests.requests || W.value.backup_attempts.requests || W.value.failed_tasks.requests || W.value.repeated_tasks.requests)

const table = ref(false)       // the numbers behind the chart, in a panel below the row
const TOP = 5                   // rows of each "top" list on the overview; the rest is behind "show all"
const SIZE = 10

// the drawer: one of the two lists, one run, or the prices
const drawer = reactive({ kind: '', run: null, fromList: false, page: 0 })
function openList(kind) { Object.assign(drawer, { kind, run: null, fromList: false, page: 0 }) }
function openRun(row, fromList = false) {
  const id = row.task_id
  if (!id) return
  drawer.run = { id, label: row.outcome ? row.label : T('analytics.cost.theRunThisRequest'), subject: row.subject || '', at: row.at, outcome: row.outcome, outcome_label: row.outcome_label,
    requests: row.requests, tokens: row.outcome ? row.tokens : undefined, cost: row.outcome ? row.cost : undefined }
  drawer.fromList = fromList
  if (!drawer.kind) drawer.kind = 'run'
}
function close() { Object.assign(drawer, { kind: '', run: null }) }
function back() { drawer.run = null; if (drawer.kind === 'run') drawer.kind = '' }
watch(() => props.d, () => { if (drawer.kind !== 'prices') close() })      // other data: what a list shows would be out of date

// the user's own prices
const prices = reactive({ rows: [] })
function editPrices() {
  const have = props.d.pricing.user.map((p) => ({ model: p.model, input: p.input, output: p.output, cache_read: p.cache_read ?? '', cache_write: p.cache_write ?? '' }))
  const missing = props.d.by_model.filter((m) => m.model && !m.price && !m.reported && !have.some((h) => h.model === m.model)).map((m) => ({ model: m.model, input: '', output: '', cache_read: '', cache_write: '' }))
  prices.rows = [...have, ...missing]
  Object.assign(drawer, { kind: 'prices', run: null })
}
async function savePrices() {
  const rows = prices.rows.filter((r) => r.model && r.input !== '' && r.output !== '')
  const r = await run(() => api.put('/analytics/ai/prices', { prices: rows }), (x) => T('analytics.cost.pricesSavedRequestsWere', { p0: x.repriced }))
  if (r) { close(); emit('reload') }
}
</script>

<template>
  <div v-if="t.unpriced_requests" class="callout warn">
    <Icon name="alert" />
    <div class="grow">{{ $t('analytics.cost.requestsUsedAModel', { p0: t.unpriced_requests }) }}<Trunc v-if="d.pricing.missing.length" as="div" class="t-meta" data-notr :text="d.pricing.missing.join(', ')" /></div>
    <button class="sm" @click="editPrices">{{ $t('analytics.cost.enterPrices') }}</button>
  </div>

  <div class="an-bar">
    <AaSelect v-model="params.provider" small :aria-label="$t('analytics.cost.service')"><option value="">{{ $t('analytics.cost.allServices') }}</option><option v-for="o in d.filters.providers" :key="o.key" :value="o.key">{{ o.label }}</option></AaSelect>
    <AaSelect v-model="params.model" small :aria-label="$t('analytics.cost.model')"><option value="">{{ $t('analytics.cost.allModels') }}</option><option v-for="o in d.filters.models" :key="o.key" :value="o.key">{{ o.label }}</option></AaSelect>
    <AaSelect v-model="params.feature" small :aria-label="$t('analytics.cost.feature')"><option value="">{{ $t('analytics.cost.allFeatures') }}</option><option v-for="o in d.filters.features" :key="o.key" :value="o.key">{{ o.label }}</option></AaSelect>
    <button v-if="filtered" class="ghost sm" @click="clear">{{ $t('analytics.cost.clearFilters') }}</button>
  </div>

  <template v-if="t.requests">
    <div class="kpis">
      <Kpi :value="money(t.cost, hasCost && t.unpriced_requests > 0)" :tone="hasCost ? '' : 'na'" :label="$t('analytics.cost.estCost')" :help="$t('analytics.cost.estimatedFromThePrice')">
        <div class="d">{{ hasCost ? $t('analytics.cost.payAsYouGo', { p0: money(metered), p1: money(included) }) : $t('analytics.cost.noCostCanBe') }}</div>
        <div v-if="d.previous && hasCost" class="d">{{ change(t.cost, d.previous.cost) }}</div></Kpi>
      <Kpi :value="compact(t.requests)" :label="$t('analytics.cost.aiRequests')" :help="$t('analytics.cost.oneRequestOneCall')">
        <div class="d">{{ $t('analytics.cost.modelTurnsNotSuccessful', { p0: compact(t.turns), p1: t.failed_requests }) }}</div>
        <div v-if="d.previous" class="d">{{ change(t.requests, d.previous.requests) }}</div></Kpi>
      <Kpi :value="compact(t.tokens_total)" :label="$t('analytics.page.tokens')" :help="$t('analytics.cost.inputCacheReadCache')">
        <div class="d">{{ $t('analytics.cost.readFromTheCache', { p0: cacheShare }) }}<template v-if="t.no_usage_requests"> {{ $t('analytics.cost.requestsWithoutUsage', { p0: t.no_usage_requests }) }}</template></div>
        <div v-if="d.previous" class="d">{{ change(t.tokens_total, d.previous.tokens_total) }}</div></Kpi>
      <Kpi :value="headline.value" :tone="headline.value === '—' ? 'na' : ''" :label="headline.label" :help="headline.tip"><div class="d">{{ headline.sub }}</div></Kpi>
    </div>

    <div class="an-row c21">
      <div class="card">
        <CardHead :title="trendTitle" :help="$t('analytics.cost.clickALegendEntry', { p0: BUCKET[d.bucket] })">
          <div class="seg" role="group" :aria-label="$t('analytics.cost.trendShows')"><button :class="{ on: metric === 'cost' }" :aria-pressed="metric === 'cost'" :disabled="!hasCost" @click="metric = 'cost'">{{ $t('analytics.cost.cost') }}</button><button :class="{ on: metric === 'tokens' }" :aria-pressed="metric === 'tokens'" @click="metric = 'tokens'">{{ $t('analytics.page.tokens') }}</button></div>
          <AaSelect v-model="params.group" class="an-group" :aria-label="$t('analytics.cost.groupBy')"><option v-for="[k, l] in [['model', $t('analytics.cost.byModel')], ['feature', $t('analytics.cost.byFeature')], ['provider', $t('analytics.cost.byService')]]" :key="k" :value="k">{{ l }}</option></AaSelect>
        </CardHead>
        <StackChart :buckets="trend" :series="series" :format="fmtTrend" :height="190" />
        <div class="card-foot">
          <button class="ghost sm" :aria-expanded="table" @click="table = !table"><Icon :name="table ? 'chevron_up' : 'table'" />{{ table ? $t('analytics.cost.hideDetail') : $t('analytics.cost.showTheDataTable') }}</button>
        </div>
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.cost.tokenBreakdown')" :help="$t('analytics.cost.countAndCostAre')" />
        <div class="an-label">{{ $t('analytics.cost.byCount') }}</div>
        <SplitBar :parts="tokenParts" :format="compact" single />
        <template v-if="costParts.length">
          <div class="an-label gap">{{ $t('analytics.cost.byCost') }}</div>
          <SplitBar :parts="costParts" :format="(v) => money(v)" single />
        </template>
        <div class="card-foot"><span class="hint">{{ costParts.length ? $t('analytics.cost.costIsDividedIn', { p0: d.token_cost_requests }) : $t('analytics.cost.theseRequestsHaveNo') }}</span></div>
      </div>
      <Transition name="an-fade">
        <DetailPanel v-if="table" :title="trendTitle" :sub="$t('analytics.cost.theSameDataAs')" @close="table = false">
          <SeriesTable :buckets="trend" :series="series" :format="fmtTrend" />
        </DetailPanel>
      </Transition>
    </div>

    <div class="an-row c32">
      <div class="card">
        <CardHead :title="$t('analytics.cost.models')" :help="$t('analytics.cost.modelNamesComeFrom')">
          <button class="ghost sm" @click="editPrices"><Icon name="edit" />{{ $t('analytics.cost.prices') }}</button>
        </CardHead>
        <div class="an-scroll">
          <table class="an-table two">
            <colgroup><col /><col class="w-n" /><col class="w-n" /><col class="w-wide" /><col class="w-xs" /><col class="w-num opt-b" /><col class="w-num opt-b" /></colgroup>
            <thead><tr><th>{{ $t('analytics.cost.model') }}</th><th class="num">{{ $t('analytics.cost.requests') }}</th><th class="num">{{ $t('analytics.page.tokens') }}</th><th class="num">{{ $t('analytics.cost.cost') }}</th><th class="num">{{ $t('analytics.cost.share') }}</th><th class="num opt-b">{{ $t('analytics.cost.avgPerRequest') }}</th><th class="num opt-b">{{ $t('analytics.cost.typicalTime') }}</th></tr></thead>
            <tbody>
              <tr v-for="m in d.by_model" :key="m.provider + m.model">
                <td><Trunc as="div" class="t-name" data-notr :text="m.model || '—'" /><Trunc as="div" class="t-sub" :text="m.provider_label + ' · ' + m.billing_label" /></td>
                <td class="num">{{ compact(m.requests) }}</td>
                <td class="num">{{ compact(m.tokens) }}</td>
                <td class="num"><InfoTip v-if="m.cost == null || m.unpriced_requests > 0" :text="m.cost == null ? $t('analytics.cost.thisModelHasNo') : $t('analytics.cost.someRequestsHaveNo')" /><span v-tip="costSource(m)">{{ money(m.cost, m.cost != null && m.unpriced_requests > 0) }}</span></td>
                <td class="num">{{ share(m.share) }}</td>
                <td class="num opt-b">{{ money(m.avg_cost) }}</td>
                <td class="num opt-b">{{ ms(m.median_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.cost.servicesAndHowThey')" :help="$t('analytics.cost.aSubscriptionIsA')" />
        <div class="an-scroll">
          <table class="an-table two">
            <colgroup><col /><col class="w-n" /><col class="w-num" /></colgroup>
            <thead><tr><th>{{ $t('analytics.cost.service') }}</th><th class="num">{{ $t('analytics.cost.requests') }}</th><th class="num">{{ $t('analytics.cost.estCost') }}</th></tr></thead>
            <tbody>
              <tr v-for="p in d.by_provider" :key="p.provider">
                <td><Trunc as="div" class="t-name" :text="p.provider_label" /><Status :tone="p.billing === 'metered' ? 'warn' : p.billing === 'unknown' ? '' : 'ok'" :label="p.billing_label" /></td>
                <td class="num">{{ compact(p.requests) }}</td>
                <td class="num">{{ money(p.cost, p.cost != null && p.unpriced_requests > 0) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <template v-if="billParts.length">
          <div class="an-label gap">{{ $t('analytics.cost.estimatedCostByHow') }}</div>
          <SplitBar :parts="billParts" :format="(v) => money(v)" single />
        </template>
      </div>
    </div>

    <div class="card">
      <CardHead :title="$t('analytics.cost.costByFeature')" :help="$t('analytics.cost.oneCallCanContain')" />
      <div class="an-scroll">
        <table class="an-table">
          <colgroup><col /><col class="w-xs" /><col class="w-n opt-a" /><col class="w-n" /><col class="w-n opt-b" /><col class="w-num" /><col class="w-bar opt-b" /><col class="w-num" /></colgroup>
          <thead><tr><th>{{ $t('analytics.cost.feature') }}</th><th class="num">{{ $t('analytics.cost.calls') }}</th><th class="num opt-a">{{ $t('analytics.cost.requests') }}</th><th class="num">{{ $t('analytics.cost.successRate') }}</th><th class="num opt-b">{{ $t('analytics.page.tokens') }}</th><th class="num">{{ $t('analytics.cost.cost') }}</th><th class="opt-b">{{ $t('analytics.cost.shareOfAllCost') }}</th><th class="num">{{ $t('analytics.cost.avgPerCall') }}</th></tr></thead>
          <tbody>
            <tr v-for="f in d.by_feature" :key="f.feature" class="clickable" :class="{ picked: params.feature === f.feature }" tabindex="0" @click="params.feature = params.feature === f.feature ? '' : f.feature" @keydown.enter="params.feature = params.feature === f.feature ? '' : f.feature">
              <td><Trunc as="div" class="t-name" :text="f.label" /></td>
              <td class="num">{{ compact(f.calls) }}</td>
              <td class="num opt-a">{{ compact(f.requests) }}</td>
              <td class="num">{{ rate(f.ok_rate) }}</td>
              <td class="num opt-b">{{ compact(f.tokens) }}</td>
              <td class="num">{{ money(f.cost, f.cost != null && f.unpriced_requests > 0) }}</td>
              <td class="opt-b"><div v-if="f.share != null" class="sharecell"><span class="share"><i :style="{ width: Math.max(f.share ? 2 : 0, Math.round(f.share * 100)) + '%' }"></i></span><span class="pc">{{ share(f.share) }}</span></div><span v-else class="none">—</span></td>
              <td class="num">{{ money(f.avg_cost_per_call) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="an-row c11 wide">
      <div class="card">
        <CardHead :title="$t('analytics.cost.costPerResult')" :help="$t('analytics.cost.everythingAKindOf')" />
        <div v-if="d.units.length" class="an-scroll">
          <table class="an-table two">
            <colgroup><col /><col class="w-xs" /><col class="w-xs opt-c" /><col class="w-xs" /><col class="w-num" /><col class="w-wide" /></colgroup>
            <thead><tr><th>{{ $t('analytics.cost.task') }}</th><th class="num">{{ $t('analytics.cost.runs') }}</th><th class="num opt-c">{{ $t('analytics.cost.failed') }}</th><th class="num">{{ $t('analytics.cost.results') }}</th><th class="num">{{ $t('analytics.cost.aiCost') }}</th><th class="num">{{ $t('analytics.cost.perResult') }}</th></tr></thead>
            <tbody>
              <tr v-for="u in d.units" :key="u.kind">
                <td><Trunc as="div" class="t-name" :text="u.label" /><Trunc as="div" class="t-sub" :text="u.unit" /></td>
                <td class="num">{{ u.runs }}</td><td class="num opt-c">{{ u.failed_runs }}</td><td class="num">{{ u.results }}</td>
                <td class="num">{{ money(u.cost, u.partial) }}</td>
                <td class="num"><InfoTip v-if="u.partial || !u.results" :text="u.partial ? $t('analytics.cost.someRequestsHaveNo') : $t('analytics.cost.noResultsInThis')" />{{ money(u.per_result, u.partial) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="activity" :title="$t('analytics.cost.noTaskUsedA')" :text="$t('analytics.cost.callsOutsideATask')" />
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.cost.spentOnFailuresAnd')" :help="$t('analytics.cost.whatFailedRequestsRetries')" />
        <template v-if="anyWaste">
          <div class="figs two">
            <div><div class="v" :class="{ na: W.failed_requests.cost == null }">{{ money(W.failed_requests.cost) }}</div><div class="k"><span>{{ $t('analytics.cost.requestsThatDidNot2', { p0: W.failed_requests.requests }) }}<template v-if="W.failed_requests.unknown">{{ $t('analytics.cost.withUnknownCost', { p0: W.failed_requests.unknown }) }}</template></span><InfoTip :text="$t('analytics.cost.requestsThatDidNot')" /></div></div>
            <div><div class="v" :class="{ na: W.backup_attempts.cost == null }">{{ money(W.backup_attempts.cost) }}</div><div class="k"><span>{{ $t('analytics.cost.repeatedOnABackup', { p0: W.backup_attempts.requests }) }}</span><InfoTip :text="$t('analytics.cost.requestsMadeAgainOn')" /></div></div>
            <div><div class="v" :class="{ na: W.failed_tasks.cost == null }">{{ money(W.failed_tasks.cost) }}</div><div class="k"><span>{{ $t('analytics.cost.requestsBelongToFailed', { p0: W.failed_tasks.requests }) }}</span><InfoTip :text="$t('analytics.cost.everyRequestMadeBy')" /></div></div>
            <div><div class="v" :class="{ na: W.repeated_tasks.cost == null }">{{ money(W.repeated_tasks.cost) }}</div><div class="k"><span>{{ $t('analytics.cost.requestsBelongToRepeated', { p0: W.repeated_tasks.requests }) }}</span><InfoTip :text="$t('analytics.cost.requestsMadeByTasks')" /></div></div>
          </div>
          <template v-if="W.by_feature.length">
            <div class="an-label gap">{{ $t('analytics.cost.whereFailedTasksSpent') }}</div>
            <div class="hbars tight even lab-md">
              <template v-for="f in W.by_feature" :key="f.feature">
                <Trunc class="lab" :text="f.label" />
                <div class="track"><div class="fill bad" :style="{ width: pct(f.cost || 0, W.by_feature[0].cost || 1) + '%' }"></div></div>
                <span class="num">{{ money(f.cost) }}</span>
              </template>
            </div>
          </template>
          <div class="card-foot"><span class="hint">{{ $t('analytics.cost.theseOverlapTheyCannot') }}</span></div>
        </template>
        <EmptyState v-else icon="check" :title="$t('analytics.cost.noFailedOrRepeated')" />
      </div>
    </div>

    <div class="an-row c11 wide">
      <div class="card">
        <CardHead :title="$t('analytics.cost.mostExpensiveRuns')" :help="$t('analytics.cost.highWellAboveMost')" />
        <div v-if="d.costly.length" class="an-scroll">
          <table class="an-table two">
            <colgroup><col /><col class="w-date opt-c" /><col class="w-n opt-c" /><col class="w-num" /><col class="w-n" /></colgroup>
            <thead><tr><th>{{ $t('analytics.cost.task') }}</th><th class="opt-c">{{ $t('analytics.cost.start') }}</th><th class="num opt-c">{{ $t('analytics.page.tokens') }}</th><th class="num">{{ $t('analytics.cost.cost') }}</th><th class="num">{{ $t('analytics.cost.timesTheMedian') }}</th></tr></thead>
            <tbody>
              <tr v-for="c in d.costly.slice(0, TOP)" :key="c.task_id" class="clickable" tabindex="0" @click="openRun(c)" @keydown.enter="openRun(c)">
                <td><div class="t-line"><Trunc class="t-name" :text="c.label" /><span v-if="c.outlier" class="tag warn">{{ $t('analytics.cost.high') }}</span></div><Trunc as="div" class="t-sub" :text="c.subject || '—'" /></td>
                <td class="atomic opt-c">{{ fmt(c.at) }}</td>
                <td class="num opt-c"><span v-tip="$t('analytics.cost.requests2', { p0: c.requests })">{{ compact(c.tokens) }}</span></td><td class="num">{{ money(c.cost) }}</td>
                <td class="num">{{ c.times_median == null ? '—' : $t('analytics.cost.times', { p0: c.times_median }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="activity" :title="$t('analytics.cost.noTasksWithA')" />
        <div v-if="d.costly.length > TOP" class="card-foot"><button class="ghost sm" @click="openList('costly')"><Icon name="table" />{{ $t('analytics.cost.showAll', { p0: d.costly.length }) }}</button></div>
      </div>
      <div class="card">
        <CardHead :title="$t('analytics.cost.requestsThatUsedUnusually')" :help="$t('analytics.cost.comparedWithOtherRequests')" />
        <div v-if="d.heavy.length" class="an-scroll">
          <table class="an-table two">
            <colgroup><col /><col class="w-date opt-c" /><col class="w-n" /><col class="w-num" /><col class="w-num" /></colgroup>
            <thead><tr><th>{{ $t('analytics.cost.feature') }}</th><th class="opt-c">{{ $t('analytics.cost.time') }}</th><th class="num">{{ $t('analytics.page.tokens') }}</th><th class="num">{{ $t('analytics.cost.medianOfItsKind') }}</th><th class="num">{{ $t('analytics.cost.cost') }}</th></tr></thead>
            <tbody>
              <tr v-for="h in d.heavy.slice(0, TOP)" :key="h.id" :class="{ clickable: h.task_id }" :tabindex="h.task_id ? 0 : -1" @click="openRun(h)" @keydown.enter="openRun(h)">
                <td><Trunc as="div" class="t-name" :text="h.label" /><Trunc as="div" class="t-sub" data-notr :text="h.model || '—'" /></td>
                <td class="atomic opt-c">{{ fmt(h.at) }}</td>
                <td class="num">{{ compact(h.tokens) }}</td><td class="num">{{ compact(h.median) }}</td><td class="num">{{ money(h.cost) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="check" :title="$t('analytics.cost.noUnusuallyLargeRequests')" />
        <div class="card-foot">
          <button v-if="d.heavy.length > TOP" class="ghost sm" @click="openList('heavy')"><Icon name="table" />{{ $t('analytics.cost.showAll', { p0: d.heavy.length }) }}</button>
          <span v-else-if="d.heavy.length" class="hint">{{ $t('analytics.cost.ofTheRequestsIn', { p0: t.requests, p1: d.heavy.length }) }}</span>
        </div>
      </div>
    </div>
  </template>
  <div v-else class="card">
    <EmptyState icon="activity" :title="filtered ? $t('analytics.cost.noModelRequestsMatch') : $t('analytics.cost.noIndividuallyRecordedModel')"
                :text="filtered ? '' : $t('analytics.cost.fromThisVersionOn')">
      <button v-if="filtered" @click="clear">{{ $t('analytics.cost.clearFilters') }}</button>
    </EmptyState>
  </div>

  <SideDrawer v-if="drawer.run" :title="drawer.run.label" :sub="drawer.run.subject" :back="drawer.fromList ? $t('analytics.cost.backToTheList') : ''" @close="close" @back="back">
    <RunDetail :run="drawer.run" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.kind === 'costly'" :title="$t('analytics.cost.mostExpensiveRuns')" :sub="$t('analytics.cost.inAllMostExpensive', { p0: d.costly.length })" @close="close">
    <div class="an-scroll">
      <table class="an-table two">
        <colgroup><col /><col class="w-date" /><col class="w-state opt-b" /><col class="w-n" /><col class="w-num" /><col class="w-n" /></colgroup>
        <thead><tr><th>{{ $t('analytics.cost.task') }}</th><th>{{ $t('analytics.cost.start') }}</th><th class="opt-b">{{ $t('analytics.cost.result') }}</th><th class="num">{{ $t('analytics.page.tokens') }}</th><th class="num">{{ $t('analytics.cost.cost') }}</th><th class="num">{{ $t('analytics.cost.timesTheMedian') }}</th></tr></thead>
        <tbody>
          <tr v-for="c in d.costly.slice(drawer.page * SIZE, (drawer.page + 1) * SIZE)" :key="c.task_id" class="clickable" tabindex="0" @click="openRun(c, true)" @keydown.enter="openRun(c, true)">
            <td><div class="t-line"><Trunc class="t-name" :text="c.label" /><span v-if="c.outlier" class="tag warn">{{ $t('analytics.cost.high') }}</span></div><Trunc as="div" class="t-sub" :text="c.subject || '—'" /></td>
            <td class="atomic">{{ fmt(c.at) }}</td>
            <td class="opt-b"><Status :tone="{ success: 'ok', failed: 'bad', interrupted: 'bad' }[c.outcome] || 'warn'" :label="c.outcome_label" /></td>
            <td class="num">{{ compact(c.tokens) }}</td><td class="num">{{ money(c.cost) }}</td>
            <td class="num">{{ c.times_median == null ? '—' : $t('analytics.cost.times', { p0: c.times_median }) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pager v-model:page="drawer.page" :size="SIZE" :total="d.costly.length" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.kind === 'heavy'" :title="$t('analytics.cost.requestsThatUsedUnusually')" :sub="$t('analytics.cost.inAllLargestFirst', { p0: d.heavy.length })" @close="close">
    <div class="an-scroll">
      <table class="an-table two">
        <colgroup><col /><col class="w-date" /><col class="w-xs opt-b" /><col class="w-n" /><col class="w-num" /><col class="w-num" /></colgroup>
        <thead><tr><th>{{ $t('analytics.cost.feature') }}</th><th>{{ $t('analytics.cost.time') }}</th><th class="num opt-b">{{ $t('analytics.cost.turns') }}</th><th class="num">{{ $t('analytics.page.tokens') }}</th><th class="num">{{ $t('analytics.cost.medianOfItsKind') }}</th><th class="num">{{ $t('analytics.cost.cost') }}</th></tr></thead>
        <tbody>
          <tr v-for="h in d.heavy.slice(drawer.page * SIZE, (drawer.page + 1) * SIZE)" :key="h.id" :class="{ clickable: h.task_id }" :tabindex="h.task_id ? 0 : -1" @click="openRun(h, true)" @keydown.enter="openRun(h, true)">
            <td><Trunc as="div" class="t-name" :text="h.label" /><Trunc as="div" class="t-sub" data-notr :text="h.model || '—'" /></td>
            <td class="atomic">{{ fmt(h.at) }}</td>
            <td class="num opt-b">{{ h.turns }}</td><td class="num">{{ compact(h.tokens) }}</td><td class="num">{{ compact(h.median) }}</td><td class="num">{{ money(h.cost) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pager v-model:page="drawer.page" :size="SIZE" :total="d.heavy.length" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.kind === 'prices'" :title="$t('analytics.cost.modelPrices')" @close="close">
    <div class="an-bar"><span class="t-secondary">{{ $t('analytics.cost.pricesUnit') }}</span><HelpPop :text="$t('analytics.cost.usDollarsPerMillion', { p0: d.pricing.version })" :label="$t('analytics.cost.modelPrices')" /></div>
    <div v-if="prices.rows.length" class="an-scroll">
      <table class="an-table form">
        <colgroup><col /><col class="w-wide" /><col class="w-wide" /><col class="w-wide" /><col class="w-wide" /><col class="w-act" /></colgroup>
        <thead><tr><th>{{ $t('analytics.cost.modelNameAsIn') }}</th><th>{{ $t('analytics.cost.input') }}</th><th>{{ $t('analytics.cost.output') }}</th><th>{{ $t('analytics.cost.cacheRead') }}</th><th>{{ $t('analytics.cost.cacheWrite') }}</th><th :aria-label="$t('analytics.cost.remove')"></th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in prices.rows" :key="i">
            <td><input v-model.trim="r.model" :placeholder="$t('analytics.cost.modelName')" :aria-label="$t('analytics.cost.modelName')" /></td>
            <td><input v-model="r.input" type="number" min="0" step="any" :aria-label="$t('analytics.cost.inputPrice')" /></td>
            <td><input v-model="r.output" type="number" min="0" step="any" :aria-label="$t('analytics.cost.outputPrice')" /></td>
            <td><input v-model="r.cache_read" type="number" min="0" step="any" :aria-label="$t('analytics.cost.cacheReadPrice')" /></td>
            <td><input v-model="r.cache_write" type="number" min="0" step="any" :aria-label="$t('analytics.cost.cacheWritePrice')" /></td>
            <td class="act"><IconButton icon="trash" :label="$t('analytics.cost.remove')" @click="prices.rows.splice(i, 1)" /></td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else icon="edit" :title="$t('analytics.cost.noPricesOfYour')" :text="$t('analytics.cost.addAModelAnd')" />
    <template #footer>
      <div class="actions">
        <button @click="prices.rows.push({ model: '', input: '', output: '', cache_read: '', cache_write: '' })"><Icon name="plus" />{{ $t('analytics.cost.addAModel') }}</button>
        <button class="primary" @click="savePrices"><Icon name="check" />{{ $t('analytics.cost.savePrices') }}</button>
      </div>
    </template>
  </SideDrawer>
</template>

<script setup>
// AI use and cost. A cost here is an estimate at list price unless the service reported one; a call on a subscription
// adds nothing to a bill, and its figure says what the same call would cost on the pay-as-you-go API. What cannot be
// told (no price for the model, no usage reported, records from before requests were kept) is shown as such, apart.
// The overview stays compact: the numbers behind the chart open in a panel below its row; the full lists, one run and
// the price editor open in a drawer.
import { computed, reactive, ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { change, colorOf, compact, money, ms, pct, share } from '../../analytics'
import DetailPanel from '../../components/DetailPanel.vue'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'
import Pager from '../../components/Pager.vue'
import SeriesTable from '../../components/SeriesTable.vue'
import SideDrawer from '../../components/SideDrawer.vue'
import SplitBar from '../../components/SplitBar.vue'
import StackChart from '../../components/StackChart.vue'
import { run } from '../../ui'
import RunDetail from './RunDetail.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, required: true } })
const emit = defineEmits(['reload'])
const t = computed(() => props.d.total)
const metric = ref('cost')     // what the trend shows: cost or tokens - two charts' worth of data, never two axes on one
const hasCost = computed(() => t.value.cost != null)
watch(hasCost, (v) => { if (!v) metric.value = 'tokens' }, { immediate: true })
const series = computed(() => props.d.series.map((s, i) => ({ ...s, color: colorOf(i, s.key) })))
const trend = computed(() => props.d.trend.map((b) => ({ key: b.key, label: b.label, tip: b.key, values: metric.value === 'cost' ? b.values : b.token_values,
  note: metric.value === 'cost' && b.unpriced ? `另有 ${b.unpriced} 次请求算不出费用` : '' })))
const fmtTrend = computed(() => (metric.value === 'cost' ? (v) => money(v) : compact))
const trendTitle = computed(() => (metric.value === 'cost' ? '成本随时间的变化' : 'Token 用量随时间的变化'))
const BUCKET = { day: '按调用发生的日期（本地时间），每天一根柱子。', week: '按调用发生的日期（本地时间），每周一根柱子，标的是那一周的周一。', month: '按调用发生的日期（本地时间），每个月一根柱子。' }
const KIND_COLOR = { input: 'var(--chart-1)', cache_read: 'var(--chart-3)', cache_write: 'var(--chart-4)', output: 'var(--chart-2)', unsplit: 'var(--chart-other)' }
const tokenParts = computed(() => [...props.d.token_kinds.map((k) => ({ key: k.key, label: k.label, value: k.tokens, color: KIND_COLOR[k.key] })),
  ...(t.value.tokens.unsplit ? [{ key: 'unsplit', label: '输入（没有区分缓存）', value: t.value.tokens.unsplit, color: KIND_COLOR.unsplit }] : [])])
const costParts = computed(() => props.d.token_kinds.filter((k) => k.cost != null).map((k) => ({ key: k.key, label: k.label, value: k.cost, color: KIND_COLOR[k.key] })))
const metered = computed(() => t.value.by_billing.metered || 0)
const included = computed(() => (t.value.by_billing.subscription || 0) + (t.value.by_billing.local || 0))
const BILL_COLOR = { metered: 'var(--chart-2)', subscription: 'var(--chart-1)', local: 'var(--chart-3)', unknown: 'var(--chart-other)' }
const billParts = computed(() => Object.entries(t.value.by_billing).map(([k, v]) => ({ key: k, label: props.d.billing_labels[k] || k, value: v, color: BILL_COLOR[k] || BILL_COLOR.unknown })))
// the headline for "cost per result": the kind of task that cost the most and has a figure; otherwise the average per call
const headline = computed(() => {
  const u = [...props.d.units].filter((x) => x.per_result != null).sort((a, b) => b.cost - a.cost)[0]
  if (u) return { value: money(u.per_result, u.partial), label: u.per_label, sub: `${u.runs} 次执行，${u.failed_runs} 次失败，得到 ${u.results} 个成果`, tip: '这类任务的全部 AI 花费（失败和重跑的也算）÷ 得到的成果数。其他任务的见下面“每个成果的成本”。' }
  const per = hasCost.value && t.value.calls ? Math.round(t.value.cost / t.value.calls) : null
  return { value: money(per), label: '平均每次调用', sub: `${t.value.calls} 次调用`, tip: '估算成本 ÷ 调用次数。一次调用可以包含多次请求（代理的多轮、换到备用服务的重试）。' }
})
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
  drawer.run = { id, label: row.outcome ? row.label : '这次请求所属的执行', subject: row.subject || '', at: row.at, outcome: row.outcome, outcome_label: row.outcome_label,
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
  const r = await run(() => api.put('/analytics/ai/prices', { prices: rows }), (x) => `价格已保存，重新估算了 ${x.repriced} 次请求`)
  if (r) { close(); emit('reload') }
}
</script>

<template>
  <div v-if="t.legacy" class="callout">
    <Icon name="info" />
    <div>这段时间里有 {{ t.legacy.tasks }} 个任务是在“逐次记录模型请求”之前跑的：共 {{ t.legacy.calls }} 次调用，输入 {{ compact(t.legacy.input) }}、输出 {{ compact(t.legacy.output) }} Token。
      当时没有记录用的是哪个模型、多少来自缓存，所以算不出费用；下面的数字都不包含它们。</div>
  </div>
  <div v-if="t.unpriced_requests" class="callout warn">
    <Icon name="alert" />
    <div>有 {{ t.unpriced_requests }} 次请求的模型没有价格，Token 计入了，费用没有计入<template v-if="d.pricing.missing.length">：<span data-notr>{{ d.pricing.missing.join('、') }}</span></template>。
      <button class="sm" style="margin-left: 6px" @click="editPrices">填上价格</button></div>
  </div>

  <div class="an-bar" style="margin-bottom: 12px">
    <AaSelect v-model="params.provider" small><option value="">全部服务</option><option v-for="o in d.filters.providers" :key="o.key" :value="o.key">{{ o.label }}</option></AaSelect>
    <AaSelect v-model="params.model" small><option value="">全部模型</option><option v-for="o in d.filters.models" :key="o.key" :value="o.key">{{ o.label }}</option></AaSelect>
    <AaSelect v-model="params.feature" small><option value="">全部功能</option><option v-for="o in d.filters.features" :key="o.key" :value="o.key">{{ o.label }}</option></AaSelect>
    <button v-if="filtered" class="ghost sm" @click="clear">清除筛选</button>
  </div>

  <template v-if="t.requests">
    <div class="kpis">
      <div class="kpi" title="按价格表估算（服务自己报了费用的用它报的）。订阅内的调用不另收费，这里是它按 API 标价折合的金额。算不出费用的请求不计入。">
        <div class="n" :class="{ na: !hasCost }">{{ money(t.cost, hasCost && t.unpriced_requests > 0) }}</div><div class="l">估算成本</div>
        <div class="d">{{ hasCost ? `按量计费 ${money(metered)} · 订阅内折合 ${money(included)}` : '这些请求都算不出费用' }}</div>
        <div v-if="d.previous && hasCost" class="d">{{ change(t.cost, d.previous.cost) }}</div></div>
      <div class="kpi" title="一次请求 = 向 AI 服务发一次。订阅的命令行一次请求里可以有多轮模型往返。">
        <div class="n">{{ compact(t.requests) }}</div><div class="l">次 AI 请求</div>
        <div class="d">{{ compact(t.turns) }} 轮模型往返 · {{ t.failed_requests }} 次没成功</div>
        <div v-if="d.previous" class="d">{{ change(t.requests, d.previous.requests) }}</div></div>
      <div class="kpi" title="输入 + 缓存读取 + 缓存写入 + 输出。缓存的部分不重复计入输入，推理的部分不重复计入输出。">
        <div class="n">{{ compact(t.tokens_total) }}</div><div class="l">Token</div>
        <div class="d">{{ cacheShare }}% 是从缓存读的<template v-if="t.no_usage_requests"> · {{ t.no_usage_requests }} 次请求没有用量</template></div>
        <div v-if="d.previous" class="d">{{ change(t.tokens_total, d.previous.tokens_total) }}</div></div>
      <div class="kpi" :title="headline.tip"><div class="n" :class="{ na: headline.value === '—' }">{{ headline.value }}</div><div class="l">{{ headline.label }}</div><div class="d">{{ headline.sub }}</div></div>
    </div>

    <div class="an-row c21">
      <div class="card">
        <div class="card-title">{{ trendTitle }}</div>
        <p class="card-sub">{{ BUCKET[d.bucket] }}点图例可以把一项拿掉。</p>
        <div class="an-bar" style="margin-bottom: 14px; gap: 8px">
          <div class="seg"><button :class="{ on: metric === 'cost' }" :disabled="!hasCost" @click="metric = 'cost'">成本</button><button :class="{ on: metric === 'tokens' }" @click="metric = 'tokens'">Token</button></div>
          <div class="seg"><button v-for="[k, l] in [['model', '按模型'], ['feature', '按功能'], ['provider', '按服务']]" :key="k" :class="{ on: params.group === k }" @click="params.group = k">{{ l }}</button></div>
          <div class="seg"><button v-for="[k, l] in [['', '自动'], ['day', '按天'], ['week', '按周'], ['month', '按月']]" :key="k" :class="{ on: params.bucket === k }" @click="params.bucket = k">{{ l }}</button></div>
        </div>
        <StackChart :buckets="trend" :series="series" :format="fmtTrend" :height="190" />
        <div class="card-foot">
          <button class="ghost sm" :aria-expanded="table" @click="table = !table"><Icon :name="table ? 'chevron_up' : 'table'" />{{ table ? '收起明细' : '查看数据表格' }}</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Token 的构成</div>
        <p class="card-sub">数量和花费不是一回事：输出最贵，从缓存读最便宜。</p>
        <div class="small muted" style="margin-bottom: 4px">按数量</div>
        <SplitBar :parts="tokenParts" :format="compact" single />
        <template v-if="costParts.length">
          <div class="small muted" style="margin: 16px 0 4px">按花费</div>
          <SplitBar :parts="costParts" :format="(v) => money(v)" single />
        </template>
        <div class="card-foot"><span class="hint">{{ costParts.length ? `花费按价格表的比例分摊，只统计分得清缓存的 ${d.token_cost_requests} 次请求。` : '这些请求没有价格，分不出各部分的花费。' }}</span></div>
      </div>
      <Transition name="an-fade">
        <DetailPanel v-if="table" :title="trendTitle" sub="和上面的图是同一份数据：同样的时间范围、分组和筛选，最新的在前。" @close="table = false">
          <SeriesTable :buckets="trend" :series="series" :format="fmtTrend" />
        </DetailPanel>
      </Transition>
    </div>

    <div class="an-row c32">
      <div class="card">
        <div class="card-head"><span class="card-title">各个模型</span><button class="ghost sm" @click="editPrices"><Icon name="edit" />价格</button></div>
        <p class="card-sub">模型名来自真实的调用记录。</p>
        <div class="an-scroll">
          <table class="an-table">
            <thead><tr><th class="grow">模型</th><th class="num">请求</th><th class="num">Token</th><th class="num">成本</th><th class="num">占比</th><th class="num">平均每次请求</th><th class="num">通常耗时</th></tr></thead>
            <tbody>
              <tr v-for="m in d.by_model" :key="m.provider + m.model">
                <td class="grow"><span class="one" style="font-weight: 550" :title="m.model" data-notr>{{ m.model || '—' }}</span><span class="one small muted"><span>{{ m.provider_label }}</span> · <span>{{ m.billing_label }}</span></span></td>
                <td class="num">{{ compact(m.requests) }}</td>
                <td class="num">{{ compact(m.tokens) }}</td>
                <td class="num" :title="m.cost == null ? '这个模型没有价格，服务也没有报费用' : m.reported ? '服务自己报的费用' : m.price && m.price.source === 'user_price' ? '按你填的价格估算' : '按内置价格表估算'">{{ money(m.cost, m.cost != null && m.unpriced_requests > 0) }}</td>
                <td class="num">{{ share(m.share) }}</td>
                <td class="num">{{ money(m.avg_cost) }}</td>
                <td class="num">{{ ms(m.median_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="card-title">各个服务，怎么付费</div>
        <p class="card-sub">订阅是固定月费，多调用不多收钱；按量计费的才会出现在账单上。</p>
        <div class="an-scroll">
          <table class="an-table">
            <thead><tr><th class="grow">服务</th><th>付费方式</th><th class="num">请求</th><th class="num">估算成本</th></tr></thead>
            <tbody>
              <tr v-for="p in d.by_provider" :key="p.provider">
                <td class="grow"><span class="one" style="font-weight: 550">{{ p.provider_label }}</span></td>
                <td><span class="badge" :class="p.billing === 'metered' ? 'warn' : p.billing === 'unknown' ? '' : 'ok'">{{ p.billing_label }}</span></td>
                <td class="num">{{ compact(p.requests) }}</td>
                <td class="num">{{ money(p.cost, p.cost != null && p.unpriced_requests > 0) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <template v-if="billParts.length">
          <div class="small muted" style="margin: 16px 0 4px">估算成本按付费方式分</div>
          <SplitBar :parts="billParts" :format="(v) => money(v)" single />
        </template>
      </div>
    </div>

    <div class="card">
      <div class="card-title">钱花在哪项功能上</div>
      <p class="card-sub">一次调用可以包含多次请求。成功率看调用的最后一次尝试是否成功。点一行只看这项功能。</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">功能</th><th class="num">调用</th><th class="num">请求</th><th class="num">成功率</th><th class="num">Token</th><th class="num">成本</th><th style="width: 190px">占全部成本</th><th class="num">平均每次调用</th></tr></thead>
          <tbody>
            <tr v-for="f in d.by_feature" :key="f.feature" class="clickable" tabindex="0" @click="params.feature = params.feature === f.feature ? '' : f.feature" @keydown.enter="params.feature = params.feature === f.feature ? '' : f.feature">
              <td class="grow"><span class="one" style="font-weight: 550" :title="f.label">{{ f.label }}</span></td>
              <td class="num">{{ compact(f.calls) }}</td>
              <td class="num">{{ compact(f.requests) }}</td>
              <td class="num">{{ rate(f.ok_rate) }}</td>
              <td class="num">{{ compact(f.tokens) }}</td>
              <td class="num">{{ money(f.cost, f.cost != null && f.unpriced_requests > 0) }}</td>
              <td><div v-if="f.share != null" class="sharecell"><span class="share"><i :style="{ width: Math.max(f.share ? 2 : 0, Math.round(f.share * 100)) + '%' }"></i></span><span class="pc">{{ share(f.share) }}</span></div><template v-else>—</template></td>
              <td class="num">{{ money(f.avg_cost_per_call) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="an-row c11">
      <div class="card">
        <div class="card-title">每个成果的成本</div>
        <p class="card-sub">一类任务在这段时间的全部 AI 花费（失败的、重跑的都算）÷ 它得到的成果数。只算分子的成功请求会把成本算低。</p>
        <div v-if="d.units.length" class="an-scroll">
          <table class="an-table">
            <thead><tr><th class="grow">任务</th><th class="num">执行</th><th class="num">其中失败</th><th class="num">成果</th><th class="num">AI 成本</th><th class="num">每个成果</th></tr></thead>
            <tbody>
              <tr v-for="u in d.units" :key="u.kind">
                <td class="grow"><span class="one" style="font-weight: 550" :title="u.label">{{ u.label }}</span><span class="one small muted" :title="u.unit">{{ u.unit }}</span></td>
                <td class="num">{{ u.runs }}</td><td class="num">{{ u.failed_runs }}</td><td class="num">{{ u.results }}</td>
                <td class="num">{{ money(u.cost, u.partial) }}</td>
                <td class="num" :title="u.partial ? '有请求算不出费用（多半是没有得到回答的失败请求），实际只会比这个数高' : !u.results ? '这段时间没有得到成果' : ''">{{ money(u.per_result, u.partial) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="activity" title="这段时间没有任务用到模型" text="不在任务里的调用（比如连接测试）不算成果。" />
      </div>
      <div class="card">
        <div class="card-title">失败和重复花掉的</div>
        <p class="card-sub">失败的请求、换到备用服务的重试、失败的任务、重跑的任务，各用掉了多少。</p>
        <template v-if="anyWaste">
          <div class="figs two">
            <div title="没成功的请求。服务没有返回用量的那些，费用不知道，不算在金额里。"><div class="v" :class="{ na: W.failed_requests.cost == null }">{{ money(W.failed_requests.cost) }}</div><div class="k">{{ W.failed_requests.requests }} 次没成功的请求<template v-if="W.failed_requests.unknown">（{{ W.failed_requests.unknown }} 次费用不明）</template></div></div>
            <div title="主服务不可用时，在备用服务上重做的那些请求。"><div class="v" :class="{ na: W.backup_attempts.cost == null }">{{ money(W.backup_attempts.cost) }}</div><div class="k">{{ W.backup_attempts.requests }} 次在备用服务上重做</div></div>
            <div title="最后失败了的任务，它用掉的全部请求。"><div class="v" :class="{ na: W.failed_tasks.cost == null }">{{ money(W.failed_tasks.cost) }}</div><div class="k">{{ W.failed_tasks.requests }} 次请求属于失败的任务</div></div>
            <div title="同一个对象不是第一次执行的那些任务，它们用掉的请求。"><div class="v" :class="{ na: W.repeated_tasks.cost == null }">{{ money(W.repeated_tasks.cost) }}</div><div class="k">{{ W.repeated_tasks.requests }} 次请求属于重跑的任务</div></div>
          </div>
          <template v-if="W.by_feature.length">
            <div class="small muted" style="margin: 16px 0 8px">失败的任务把钱花在了哪项功能上</div>
            <div class="hbars tight even" style="--lab: 9em">
              <template v-for="f in W.by_feature" :key="f.feature">
                <span class="lab" :title="f.label">{{ f.label }}</span>
                <div class="track"><div class="fill bad" :style="{ width: pct(f.cost || 0, W.by_feature[0].cost || 1) + '%' }"></div></div>
                <span class="num">{{ money(f.cost) }}</span>
              </template>
            </div>
          </template>
          <div class="card-foot"><span class="hint">这几项互相有重叠，不能相加。</span></div>
        </template>
        <EmptyState v-else icon="check" title="这段时间没有失败或重做的请求" />
      </div>
    </div>

    <div class="an-row c11">
      <div class="card">
        <div class="card-title">花费最高的执行</div>
        <p class="card-sub">“偏高”= 比同类任务的大多数高出一截（超过上四分位数 + 1.5 倍四分位距，同类至少 8 次才判断），不是一个随手定的数。</p>
        <div v-if="d.costly.length" class="an-scroll">
          <table class="an-table">
            <thead><tr><th class="grow">任务</th><th>开始</th><th class="num">Token</th><th class="num">成本</th><th class="num">是同类中位数的</th></tr></thead>
            <tbody>
              <tr v-for="c in d.costly.slice(0, TOP)" :key="c.task_id" class="clickable" tabindex="0" @click="openRun(c)" @keydown.enter="openRun(c)">
                <td class="grow"><span class="one" style="font-weight: 550">{{ c.label }}<span v-if="c.outlier" class="badge warn" style="margin-left: 6px">偏高</span></span><span class="one small muted" :title="c.subject">{{ c.subject || '—' }}</span></td>
                <td class="nowrap">{{ fmt(c.at) }}</td>
                <td class="num" :title="`${c.requests} 次请求`">{{ compact(c.tokens) }}</td><td class="num">{{ money(c.cost) }}</td>
                <td class="num">{{ c.times_median == null ? '—' : c.times_median + ' 倍' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="activity" title="还没有能算出费用的任务" />
        <div v-if="d.costly.length > TOP" class="card-foot"><button class="ghost sm" @click="openList('costly')"><Icon name="table" />查看全部 {{ d.costly.length }} 条</button></div>
      </div>
      <div class="card">
        <div class="card-title">Token 用得特别多的请求</div>
        <p class="card-sub">和同一项功能的其他请求比，同样的判断方法；同一项功能至少要有 8 次请求才判断。</p>
        <div v-if="d.heavy.length" class="an-scroll">
          <table class="an-table">
            <thead><tr><th class="grow">功能</th><th>时间</th><th class="num">Token</th><th class="num">同类中位数</th><th class="num">成本</th></tr></thead>
            <tbody>
              <tr v-for="h in d.heavy.slice(0, TOP)" :key="h.id" :class="{ clickable: h.task_id }" :tabindex="h.task_id ? 0 : -1" @click="openRun(h)" @keydown.enter="openRun(h)">
                <td class="grow"><span class="one" style="font-weight: 550">{{ h.label }}</span><span class="one small muted" data-notr :title="h.model">{{ h.model || '—' }}</span></td>
                <td class="nowrap">{{ fmt(h.at) }}</td>
                <td class="num">{{ compact(h.tokens) }}</td><td class="num">{{ compact(h.median) }}</td><td class="num">{{ money(h.cost) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="check" title="没有明显偏高的请求" />
        <div class="card-foot">
          <button v-if="d.heavy.length > TOP" class="ghost sm" @click="openList('heavy')"><Icon name="table" />查看全部 {{ d.heavy.length }} 条</button>
          <span v-else-if="d.heavy.length" class="hint">这段时间的 {{ t.requests }} 次请求里，有 {{ d.heavy.length }} 次明显偏高。</span>
        </div>
      </div>
    </div>
  </template>
  <div v-else class="card">
    <EmptyState icon="activity" :title="filtered ? '没有符合筛选条件的模型请求' : '这段时间没有逐次记录的模型请求'"
                :text="filtered ? '' : '从这个版本开始，每次模型请求都会记下用量和费用；之后的调用会出现在这里。'">
      <button v-if="filtered" @click="clear">清除筛选</button>
    </EmptyState>
  </div>

  <SideDrawer v-if="drawer.run" :title="drawer.run.label" :sub="drawer.run.subject" :back="drawer.fromList ? '返回列表' : ''" @close="close" @back="back">
    <RunDetail :run="drawer.run" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.kind === 'costly'" title="花费最高的执行" :sub="`共 ${d.costly.length} 条，从高到低。点一行看这次执行的模型请求。`" @close="close">
    <div class="an-scroll">
      <table class="an-table">
        <thead><tr><th class="grow">任务</th><th>开始</th><th>结果</th><th class="num">Token</th><th class="num">成本</th><th class="num">是同类中位数的</th></tr></thead>
        <tbody>
          <tr v-for="c in d.costly.slice(drawer.page * SIZE, (drawer.page + 1) * SIZE)" :key="c.task_id" class="clickable" tabindex="0" @click="openRun(c, true)" @keydown.enter="openRun(c, true)">
            <td class="grow"><span class="one" style="font-weight: 550">{{ c.label }}<span v-if="c.outlier" class="badge warn" style="margin-left: 6px">偏高</span></span><span class="one small muted" :title="c.subject">{{ c.subject || '—' }}</span></td>
            <td class="nowrap">{{ fmt(c.at) }}</td>
            <td><span class="badge" :class="{ success: 'ok', failed: 'bad', interrupted: 'bad' }[c.outcome] || 'warn'">{{ c.outcome_label }}</span></td>
            <td class="num">{{ compact(c.tokens) }}</td><td class="num">{{ money(c.cost) }}</td>
            <td class="num">{{ c.times_median == null ? '—' : c.times_median + ' 倍' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pager v-model:page="drawer.page" :size="SIZE" :total="d.costly.length" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.kind === 'heavy'" title="Token 用得特别多的请求" :sub="`共 ${d.heavy.length} 条，从多到少。`" @close="close">
    <div class="an-scroll">
      <table class="an-table">
        <thead><tr><th class="grow">功能</th><th>时间</th><th class="num">轮数</th><th class="num">Token</th><th class="num">同类中位数</th><th class="num">成本</th></tr></thead>
        <tbody>
          <tr v-for="h in d.heavy.slice(drawer.page * SIZE, (drawer.page + 1) * SIZE)" :key="h.id" :class="{ clickable: h.task_id }" :tabindex="h.task_id ? 0 : -1" @click="openRun(h, true)" @keydown.enter="openRun(h, true)">
            <td class="grow"><span class="one" style="font-weight: 550">{{ h.label }}</span><span class="one small muted" data-notr :title="h.model">{{ h.model || '—' }}</span></td>
            <td class="nowrap">{{ fmt(h.at) }}</td>
            <td class="num">{{ h.turns }}</td><td class="num">{{ compact(h.tokens) }}</td><td class="num">{{ compact(h.median) }}</td><td class="num">{{ money(h.cost) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pager v-model:page="drawer.page" :size="SIZE" :total="d.heavy.length" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.kind === 'prices'" title="模型价格" @close="close">
    <p class="card-sub">美元，每一百万 Token。Claude 的各个模型有内置的标价（版本 {{ d.pricing.version }}），不用填；这里填内置价格表里没有的模型。按人民币计价的服务请自己换算成美元。
      缓存的两项不填时，读取按输入价的 10%、写入按 125% 算。保存后会把以前没有价格的请求补算一遍；服务自己报过费用的不动。</p>
    <div class="an-scroll">
      <table class="an-table">
        <thead><tr><th>模型名（和调用记录里的一样）</th><th>输入</th><th>输出</th><th>缓存读取</th><th>缓存写入</th><th></th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in prices.rows" :key="i">
            <td><input v-model.trim="r.model" placeholder="模型名" style="width: 220px" /></td>
            <td><input v-model="r.input" type="number" min="0" step="any" style="width: 90px" aria-label="输入价格" /></td>
            <td><input v-model="r.output" type="number" min="0" step="any" style="width: 90px" aria-label="输出价格" /></td>
            <td><input v-model="r.cache_read" type="number" min="0" step="any" style="width: 90px" aria-label="缓存读取价格" /></td>
            <td><input v-model="r.cache_write" type="number" min="0" step="any" style="width: 90px" aria-label="缓存写入价格" /></td>
            <td><button class="ghost sm" @click="prices.rows.splice(i, 1)">删掉</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-if="!prices.rows.length" icon="edit" title="还没有自己填的价格" text="加一个模型，填上它每一百万 Token 的输入和输出价格。" />
    <div class="row" style="margin-top: 12px">
      <button @click="prices.rows.push({ model: '', input: '', output: '', cache_read: '', cache_write: '' })">加一个模型</button>
      <button class="primary" @click="savePrices">保存价格</button>
    </div>
  </SideDrawer>
</template>

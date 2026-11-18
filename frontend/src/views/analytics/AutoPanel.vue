<script setup>
// Automation: what the program's tasks did. A task that is "done" has not always succeeded - a filling task is done
// when it has handed the form over - so the outcome is shown in three groups: done, not finished (your move, or still
// running), failed.
// The overview stays compact: the numbers behind the chart open in a panel below its row, the full list of runs and
// the detail of one run open in a drawer.
import Explain from '../../components/Explain.vue'
import { computed, reactive, ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { change, compact, dur, money, pct, rangeQuery } from '../../analytics'
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
const SERIES = [{ key: 'success', label: '完成', color: 'var(--ok)' }, { key: 'unfinished', label: '没做完（等你，或还在跑）', color: 'var(--warn)' }, { key: 'failed', label: '失败', color: 'var(--bad)' }]
const trend = computed(() => props.d.trend.map((b) => ({ key: b.key, label: b.label, tip: b.key, values: { success: b.success, unfinished: b.unfinished, failed: b.failed } })))
const parts = (k) => [{ key: 'success', label: '完成', value: k.success, color: 'var(--ok)' }, { key: 'unfinished', label: '没做完', value: k.unfinished, color: 'var(--warn)' },
  { key: 'failed', label: '失败', value: k.failed + k.interrupted, color: 'var(--bad)' }]
const rate = (v) => (v == null ? '—' : Math.round(v * 100) + '%')
// by recruiting system: what the short figures stand for, in whole sentences
const runsTip = (y) => `运行 ${y.runs.total} 次：提交成功 ${y.runs.success}，失败 ${y.runs.failed}，准备好等你 ${y.runs.handed}，点了提交、结果待确认 ${y.runs.unknown}，等你处理 ${y.runs.waiting}，预算内没做完、接着做 ${y.runs.goes_on}，还在跑 ${y.runs.running}`
const runsLine = (y) => (y.runs.total ? `提交 ${y.runs.success} · 等你 ${y.runs.handed + y.runs.waiting} · 待确认 ${y.runs.unknown} · 接着做 ${y.runs.goes_on} · 失败 ${y.runs.failed}` : '—')
const tokensTip = (y) => (y.ai.tokens_per_posting ? `${y.ai.requests} 次请求；平均每个岗位 ${compact(y.ai.tokens_per_posting)} token` : '')
const unknownTip = (y) => `有 ${y.ai.cost_unknown_requests} 次请求算不出费用（没有价格，或是改造前的记录），没有计入`
const count = (v) => String(Math.round(v))
const TONE = { success: 'ok', handed: 'warn', unknown: 'warn', waiting: 'warn', rerun: 'warn', running: 'info', failed: 'bad', interrupted: 'bad', cancelled: '', skipped: '' }
const unfinishedTip = computed(() => `填好等你提交 ${t.value.handed}，点了提交、结果待确认 ${t.value.unknown}，等你处理（登录、验证码）${t.value.waiting}，改为可见窗口重跑 ${t.value.rerun}，进行中 ${t.value.running}`)
const TITLE = { day: '每天跑了多少', week: '每周跑了多少', month: '每个月跑了多少' }
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
  } catch (e) { if (mine === seq) drawer.error = e.message || '没有读到数据' }
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
      <div class="kpi"><div class="n">{{ t.total }}</div><div class="l">次任务执行</div><div v-if="d.previous" class="d">{{ change(t.total, d.previous.total) || '上一段没有任务，无从比较' }}</div></div>
      <div class="kpi">
        <div class="n" :class="{ na: t.success_rate == null }">{{ rate(t.success_rate) }}</div><div class="l">成功率</div><div class="d">{{ t.success }} / {{ t.settled }} 次</div>
        <Explain>完成的次数 ÷ 自己跑到头的次数（完成 + 失败 + 被中断）。等你处理和还在跑的不算进分母：它们还没有结果。“填写申请表”的一次完成，指这一次运行把申请提交出去了；发现申请早已投出而什么都没做的任务不算成功也不算失败。这是任务的成功率，不是申请的结果：申请后来怎样，看“求职成效”。</Explain></div>
      <div class="kpi"><div class="n">{{ t.unfinished }}</div><div class="l">次没做完，不算失败</div><div class="d">其中 {{ t.handed + t.waiting + t.unknown }} 次在等你</div>
        <Explain>{{ unfinishedTip }}</Explain></div>
      <div class="kpi">
        <div class="n">{{ t.failed + t.interrupted }}</div><div class="l">次失败</div><div class="d">{{ t.interrupted ? `其中 ${t.interrupted} 次是被中断` : '没有被中断的' }}</div>
        <Explain>失败 = 任务自己出错停下；被中断 = 程序在任务途中被关闭。</Explain></div>
    </div>

    <div class="an-bar" style="margin-bottom: 12px">
      <span class="small muted">只看一类任务</span>
      <AaSelect v-model="params.kind" small><option value="">全部任务</option><option v-for="k in d.kinds" :key="k.kind" :value="k.kind">{{ k.label }}</option></AaSelect>
    </div>

    <div class="an-row c32 tight">
      <div class="card">
        <div class="card-head">
          <span class="card-title">{{ TITLE[d.bucket] }}</span>
          <button class="ghost sm" :aria-expanded="table" @click="table = !table"><Icon :name="table ? 'chevron_up' : 'table'" />{{ table ? '收起明细' : '查看数据表格' }}</button>
        </div>
        <p class="card-sub">按任务开始的日期（本地时间）。点图例可以把一项拿掉。</p>
        <StackChart :buckets="trend" :series="SERIES" :format="count" :height="168" />
      </div>
      <div class="card">
        <div class="card-head"><span class="card-title">主要失败原因</span><span class="small muted">{{ failed }} 次失败</span></div>
        <p class="card-sub">按原因归类，从多到少</p>
        <template v-if="d.reasons.length">
          <div v-for="r in topReasons" :key="r.key" class="reason" :title="r.messages.map((m) => m.message).join('；')">
            <span class="lab">{{ r.reason }}</span><span class="bar"><i :style="{ width: pct(r.n, d.reasons[0].n) + '%' }"></i></span><span class="n">{{ r.n }}</span>
          </div>
          <div v-if="restReasons" class="reason rest"><span class="lab">其他 {{ d.reasons.length - TOP_REASONS }} 类原因</span><span></span><span class="n">{{ restReasons }}</span></div>
          <div class="card-foot"><button class="ghost sm" @click="drawer.reasons = true"><Icon name="table" />查看全部原因</button></div>
        </template>
        <EmptyState v-else icon="check" title="这段时间没有失败的任务" />
      </div>
      <Transition name="an-fade">
        <DetailPanel v-if="table" :title="TITLE[d.bucket]" sub="和上面的图是同一份数据，最新的在前。" @close="table = false">
          <SeriesTable :buckets="trend" :series="SERIES" :format="count" />
        </DetailPanel>
      </Transition>
    </div>

    <div class="card">
      <div class="card-title">各类任务的表现</div>
      <p class="card-sub">耗时取完成和失败的任务的中位数；AI 成本是这类任务的全部花费（失败的也算），除以完成的次数。</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">任务</th><th class="num">次数</th><th style="width: 210px">结果</th><th class="num">成功率</th><th class="num">通常耗时</th><th class="num">重启过</th><th class="num">AI 请求</th><th class="num">AI 成本</th><th class="num">每次完成的成本</th></tr></thead>
          <tbody>
            <tr v-for="k in d.by_kind" :key="k.kind">
              <td class="grow"><span class="name" :title="k.label">{{ k.label }}</span></td>
              <td class="num">{{ k.total }}</td>
              <td style="width: 210px"><SplitBar :parts="parts(k)" :legend="false" /><div class="small muted nowrap" style="margin-top: 4px">{{ k.success }} 完成 · {{ k.unfinished }} 没做完 · {{ k.failed + k.interrupted }} 失败</div></td>
              <td class="num">{{ rate(k.success_rate) }}</td>
              <td class="num" :title="k.waits_for_you ? '交给你提交的那几次不算在内：它们的时长里有等你操作的时间' : ''">{{ dur(k.median_s) }}</td>
              <td class="num">{{ k.retried }}</td>
              <td class="num">{{ k.requests ? compact(k.requests) : '—' }}</td>
              <td class="num" :title="k.cost_unknown_requests ? `有 ${k.cost_unknown_requests} 次请求算不出费用（没有价格，或是改造前的记录），没有计入` : ''">{{ money(k.cost, k.cost != null && k.cost_unknown_requests > 0) }}</td>
              <td class="num" :title="k.cost_per_success != null && k.cost_unknown_requests ? '有请求算不出费用，实际只会比这个数高' : ''">{{ money(k.cost_per_success, k.cost_unknown_requests > 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint" style="margin-top: 10px">
        同一个对象被重复执行：{{ d.repeats.objects }} 个对象多跑了 {{ d.repeats.extra_runs }} 次；其中程序自己安排的重试 {{ d.repeats.auto_retries }} 次，被中断后重新开始 {{ d.repeats.restarted }} 次。
        这里没有“节省了多少小时”：程序没有记录人工做同样的事要多久，不拿估计数冒充。
      </p>
    </div>

    <div v-if="d.systems && d.systems.length" class="card">
      <div class="card-title">按招聘系统
        <Explain>一次运行算在它处理的那个岗位所属的招聘系统上。成功率：提交成功的次数 ÷ 自己跑到头的次数（提交成功 + 失败 + 被中断）。准备好等你批准或回答、点了提交但结果待确认、预算内没做完下次接着做的，不算成功也不算失败，单独列出。AI 用量是这段时间里为这个系统的岗位问过模型的全部，失败的也算。</Explain></div>
      <p class="card-sub">每份申请都由 Agent 从岗位页做到确认页。它在哪类网站上顺利、在哪类网站上费劲，看这张表。</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">招聘系统</th><th class="num">岗位</th><th class="num">提交成功率</th><th>运行的结果</th><th class="num">一次运行耗时</th><th class="num">AI 用量</th><th class="num">AI 成本</th></tr></thead>
          <tbody>
            <tr v-for="y in d.systems" :key="y.ats">
              <td class="grow"><span class="name" :title="y.label">{{ y.label }}</span></td>
              <td class="num">{{ y.postings }}</td>
              <td class="num" :title="runsTip(y)">{{ y.runs.settled ? rate(y.runs.success_rate) : '—' }}<div v-if="y.runs.settled" class="small muted nowrap">{{ y.runs.success }} / {{ y.runs.settled }}</div></td>
              <td class="small nowrap">{{ runsLine(y) }}</td>
              <td class="num">{{ dur(y.runs.median_s) }}</td>
              <td class="num" :title="tokensTip(y)">{{ y.ai.tokens ? compact(y.ai.tokens) : '—' }}</td>
              <td class="num" :title="y.ai.cost_unknown_requests ? unknownTip(y) : ''">{{ money(y.ai.cost, y.ai.cost != null && y.ai.cost_unknown_requests > 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint" style="margin-top: 10px">次数少的时候百分比说明不了什么，所以每个成功率下面都写着“几次里成了几次”。</p>
    </div>

    <div class="card">
      <div class="card-head"><span class="card-title">最近的执行</span>
        <button v-if="d.recent_total > d.recent.length" class="ghost sm" @click="openList"><Icon name="table" />查看全部 {{ d.recent_total }} 次</button></div>
      <p class="card-sub">最近 {{ d.recent.length }} 次。点一行看它用到的每一次模型请求。</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">任务</th><th>开始</th><th>结果</th><th class="num">耗时</th><th class="num">AI 请求</th><th class="num">Token</th><th class="num">AI 成本</th><th>没完成的原因</th></tr></thead>
          <tbody>
            <tr v-for="r in d.recent" :key="r.id" class="clickable" tabindex="0" @click="openRun(r)" @keydown.enter="openRun(r)">
              <td class="grow"><span class="one" style="font-weight: 550">{{ r.label }}</span><span v-if="r.subject" class="one small muted" :title="r.subject">{{ r.subject }}</span></td>
              <td class="nowrap">{{ fmt(r.at) }}</td>
              <td><span class="badge" :class="TONE[r.outcome]">{{ r.outcome_label }}</span></td>
              <td class="num">{{ dur(r.duration_s) }}</td>
              <td class="num">{{ r.requests || '—' }}</td>
              <td class="num">{{ r.tokens ? compact(r.tokens) : '—' }}</td>
              <td class="num">{{ r.requests ? money(r.cost, r.cost_partial && r.cost != null) : '—' }}</td>
              <td class="note"><span v-if="r.reason" class="one" :title="r.stage ? `${r.reason}（停在：${r.stage}）` : r.reason">{{ r.reason_label || r.reason }}</span><span v-else class="muted">—</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
  <div v-else class="card">
    <EmptyState icon="activity" :title="params.kind ? '这段时间没有这类任务' : '这段时间程序没有跑过任务'" text="换一个时间范围，或者看全部任务。">
      <button v-if="params.kind" @click="params.kind = ''">看全部任务</button>
    </EmptyState>
  </div>

  <SideDrawer v-if="drawer.open && drawer.run" :title="drawer.run.label" :sub="drawer.run.subject" :back="drawer.fromList ? '返回列表' : ''" @close="close" @back="drawer.run = null">
    <RunDetail :run="drawer.run" />
  </SideDrawer>
  <SideDrawer v-else-if="drawer.reasons" title="全部失败原因" :sub="`这段时间 ${failed} 次失败，分成 ${d.reasons.length} 类。每一类下面是程序当时给出的说明和记录下来的原文。`" @close="close">
    <div v-for="r in d.reasons" :key="r.key" class="reason-full">
      <div class="reason" style="border: 0"><span class="lab" style="font-weight: 650">{{ r.reason }}<span class="muted small" style="font-weight: 400; margin-left: 8px">{{ r.kinds.join('、') }}</span></span>
        <span class="bar"><i :style="{ width: pct(r.n, d.reasons[0].n) + '%' }"></i></span><span class="n">{{ r.n }}</span></div>
      <div v-for="m in r.messages" :key="m.message" class="msg">
        <div><span class="n">{{ m.n }} 次</span>{{ m.message }}</div>
        <TechDetails v-if="m.raw && m.raw !== m.message" :text="m.raw" label="记录下来的原文" />
      </div>
    </div>
  </SideDrawer>
  <SideDrawer v-else-if="drawer.open" title="全部执行" :sub="`共 ${drawer.total} 次，最新的在前。时间范围和任务类型跟着页面上的选择。`" @close="close">
    <div class="an-bar" style="margin-bottom: 12px">
      <div class="seg"><button v-for="[k, l] in [['', '全部'], ['success', '完成'], ['unfinished', '没做完'], ['failed', '失败']]" :key="k" :class="{ on: drawer.outcome === k }" @click="pickOutcome(k)">{{ l }}</button></div>
    </div>
    <div v-if="drawer.error" class="err">{{ drawer.error }}</div>
    <div v-else-if="!drawer.rows" class="skel" style="height: 200px"></div>
    <EmptyState v-else-if="!drawer.rows.length" icon="activity" title="没有符合条件的执行" />
    <template v-else>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th class="grow">任务</th><th>开始</th><th>结果</th><th class="num">耗时</th><th class="num">AI 请求</th><th class="num">AI 成本</th></tr></thead>
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

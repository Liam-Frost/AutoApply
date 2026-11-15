<script setup>
// Automation: what the program's tasks did. A task that is "done" has not always succeeded - a filling task is done
// when it has handed the form over - so the outcome is shown in three groups: done, not finished (your move, or still
// running), failed.
// The overview stays compact: the numbers behind the chart open in a panel below its row, the full list of runs and
// the detail of one run open in a drawer.
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
import RunDetail from './RunDetail.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, required: true }, range: { type: Object, required: true } })
const t = computed(() => props.d.total)
const SERIES = [{ key: 'success', label: '完成', color: 'var(--ok)' }, { key: 'unfinished', label: '没做完（等你，或还在跑）', color: 'var(--warn)' }, { key: 'failed', label: '失败', color: 'var(--bad)' }]
const trend = computed(() => props.d.trend.map((b) => ({ key: b.key, label: b.label, tip: b.key, values: { success: b.success, unfinished: b.unfinished, failed: b.failed } })))
const parts = (k) => [{ key: 'success', label: '完成', value: k.success, color: 'var(--ok)' }, { key: 'unfinished', label: '没做完', value: k.unfinished, color: 'var(--warn)' },
  { key: 'failed', label: '失败', value: k.failed + k.interrupted, color: 'var(--bad)' }]
const rate = (v) => (v == null ? '—' : Math.round(v * 100) + '%')
const count = (v) => String(Math.round(v))
const maxReason = computed(() => Math.max(1, ...props.d.reasons.map((r) => r.n)))
const maxStage = computed(() => Math.max(1, ...props.d.stages.map((r) => r.n)))
const TONE = { success: 'ok', handed: 'warn', waiting: 'warn', rerun: 'warn', running: 'info', failed: 'bad', interrupted: 'bad', cancelled: '' }
const unfinishedTip = computed(() => `填好等你提交 ${t.value.handed}，等你处理（登录、验证码）${t.value.waiting}，改为可见窗口重跑 ${t.value.rerun}，进行中 ${t.value.running}`)
const TITLE = { day: '每天跑了多少', week: '每周跑了多少', month: '每个月跑了多少' }

const table = ref(false)        // the numbers behind the chart, in a panel below the row

// the drawer: the full list of runs (a page at a time, from the server), or one run
const SIZE = 15
const drawer = reactive({ open: false, run: null, fromList: false, outcome: '', page: 0, total: 0, rows: null, error: '' })
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
function close() { drawer.open = false; drawer.run = null }
watch(() => [drawer.page, drawer.outcome], () => { if (drawer.open && !drawer.run) loadList() })
// another range or another kind of task: what the drawer shows would be out of date
watch(() => [props.d, props.params.kind], close)
const pickOutcome = (v) => { drawer.outcome = v; drawer.page = 0 }
</script>

<template>
  <template v-if="t.total">
    <div class="kpis">
      <div class="kpi"><div class="n">{{ t.total }}</div><div class="l">次任务执行</div><div v-if="d.previous" class="d">{{ change(t.total, d.previous.total) || '上一段没有任务，无从比较' }}</div></div>
      <div class="kpi" title="完成的次数 ÷ 自己跑到头的次数（完成 + 失败 + 被中断）。等你处理和还在跑的不算进分母：它们还没有结果。">
        <div class="n" :class="{ na: t.success_rate == null }">{{ rate(t.success_rate) }}</div><div class="l">成功率</div><div class="d">{{ t.success }} / {{ t.settled }} 次</div></div>
      <div class="kpi" :title="unfinishedTip"><div class="n">{{ t.unfinished }}</div><div class="l">次没做完，不算失败</div><div class="d">其中 {{ t.handed + t.waiting }} 次在等你</div></div>
      <div class="kpi" title="失败 = 任务自己出错停下；被中断 = 程序在任务途中被关闭。">
        <div class="n">{{ t.failed + t.interrupted }}</div><div class="l">次失败</div><div class="d">{{ t.interrupted ? `其中 ${t.interrupted} 次是被中断` : '没有被中断的' }}</div></div>
    </div>

    <div class="an-bar" style="margin-bottom: 12px">
      <span class="small muted">只看一类任务</span>
      <AaSelect v-model="params.kind" small><option value="">全部任务</option><option v-for="k in d.kinds" :key="k.kind" :value="k.kind">{{ k.label }}</option></AaSelect>
    </div>

    <div class="an-row c32">
      <div class="card">
        <div class="card-title">{{ TITLE[d.bucket] }}</div>
        <p class="card-sub">按任务开始的日期（本地时间）。点图例可以把一项拿掉。</p>
        <StackChart :buckets="trend" :series="SERIES" :format="count" :height="190" />
        <div class="card-foot">
          <button class="ghost sm" :aria-expanded="table" @click="table = !table"><Icon :name="table ? 'chevron_up' : 'table'" />{{ table ? '收起明细' : '查看数据表格' }}</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">失败的原因</div>
        <p class="card-sub">这段时间 {{ t.failed + t.interrupted }} 次失败，按原因归并</p>
        <div v-if="d.reasons.length" class="hbars tight even" style="--lab: 55%; --numw: 2em">
          <template v-for="r in d.reasons" :key="r.reason">
            <span class="lab two" :title="r.reason + '（' + r.kinds.join('、') + '）'">{{ r.reason }}</span>
            <div class="track"><div class="fill bad" :style="{ width: pct(r.n, maxReason) + '%' }"></div></div>
            <span class="num">{{ r.n }}</span>
          </template>
        </div>
        <EmptyState v-else icon="check" title="这段时间没有失败的任务" />
        <template v-if="d.stages.length">
          <div class="card-title" style="margin-top: 18px; font-size: var(--fs-md)">失败时做到了哪一步</div>
          <div class="hbars tight even" style="margin-top: 10px; --lab: 55%; --numw: 2em">
            <template v-for="r in d.stages" :key="r.stage">
              <span class="lab" :title="r.stage">{{ r.stage }}</span>
              <div class="track"><div class="fill bad" :style="{ width: pct(r.n, maxStage) + '%' }"></div></div>
              <span class="num">{{ r.n }}</span>
            </template>
          </div>
          <div class="card-foot"><span class="hint">步骤从这个版本开始记录；之前的任务只有填表有步骤，其余显示为“没有记录到哪一步”。</span></div>
        </template>
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
          <thead><tr><th class="grow">任务</th><th class="num">次数</th><th style="min-width: 190px">结果</th><th class="num">成功率</th><th class="num">通常耗时</th><th class="num">重启过</th><th class="num">AI 请求</th><th class="num">AI 成本</th><th class="num">每次完成的成本</th></tr></thead>
          <tbody>
            <tr v-for="k in d.by_kind" :key="k.kind">
              <td class="grow"><span class="name" :title="k.label">{{ k.label }}</span></td>
              <td class="num">{{ k.total }}</td>
              <td><SplitBar :parts="parts(k)" :legend="false" /><div class="small muted nowrap" style="margin-top: 4px">{{ k.success }} 完成 · {{ k.unfinished }} 没做完 · {{ k.failed + k.interrupted }} 失败</div></td>
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
              <td class="note"><span v-if="r.reason" class="one" :title="r.stage ? `${r.reason}（停在：${r.stage}）` : r.reason">{{ r.reason }}</span><span v-else class="muted">—</span></td>
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

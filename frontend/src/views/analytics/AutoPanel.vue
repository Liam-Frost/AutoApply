<script setup>
// Automation: what the program's tasks did. A task that is "done" has not always succeeded - a filling task is done
// when it has handed the form over - so the outcome is shown in three groups: done, not finished (your move, or still
// running), failed.
import { computed, reactive, ref } from 'vue'
import { api, fmt } from '../../api'
import { change, compact, dur, money, ms, pct } from '../../analytics'
import EmptyState from '../../components/EmptyState.vue'
import SplitBar from '../../components/SplitBar.vue'
import StackChart from '../../components/StackChart.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, required: true } })
const t = computed(() => props.d.total)
const SERIES = [{ key: 'success', label: '完成', color: 'var(--ok)' }, { key: 'unfinished', label: '没做完（等你，或还在跑）', color: 'var(--warn)' }, { key: 'failed', label: '失败', color: 'var(--bad)' }]
const trend = computed(() => props.d.trend.map((b) => ({ key: b.key, label: b.label, tip: b.key, values: { success: b.success, unfinished: b.unfinished, failed: b.failed } })))
const parts = (k) => [{ key: 'success', label: '完成', value: k.success, color: 'var(--ok)' }, { key: 'unfinished', label: '没做完', value: k.unfinished, color: 'var(--warn)' },
  { key: 'failed', label: '失败', value: k.failed + k.interrupted, color: 'var(--bad)' }]
const rate = (v) => (v == null ? '—' : Math.round(v * 100) + '%')
const maxReason = computed(() => Math.max(1, ...props.d.reasons.map((r) => r.n)))
const maxStage = computed(() => Math.max(1, ...props.d.stages.map((r) => r.n)))
const TONE = { success: 'ok', handed: 'warn', waiting: 'warn', rerun: 'warn', running: 'info', failed: 'bad', interrupted: 'bad', cancelled: '' }
const unfinishedTip = computed(() => `填好等你提交 ${t.value.handed}，等你处理（登录、验证码）${t.value.waiting}，改为可见窗口重跑 ${t.value.rerun}，进行中 ${t.value.running}`)

// drill-down: the model requests of one task
const open = reactive({ id: null, rows: null, error: '' })
async function toggle(r) {
  if (open.id === r.id) { open.id = null; return }
  Object.assign(open, { id: r.id, rows: null, error: '' })
  try { open.rows = (await api.get('/analytics/ai/requests?task_id=' + r.id)).requests } catch (e) { open.error = e.message }
}
const all = ref(false)       // the list of executions starts short
const recent = computed(() => (all.value ? props.d.recent : props.d.recent.slice(0, 12)))
const STATUS = { ok: '成功', error: '出错', refused: '被拒绝', timeout: '超时', rate_limited: '额度或限流', unavailable: '服务不可用', unknown: '没有记录' }
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

    <div class="an-grid">
      <div class="card w7">
        <div class="card-title">{{ { day: '每天跑了多少', week: '每周跑了多少', month: '每个月跑了多少' }[d.bucket] }}</div>
        <p class="card-sub">按任务开始的日期（本地时间）</p>
        <StackChart :buckets="trend" :series="SERIES" :format="(v) => String(Math.round(v))" table-label="日期" />
      </div>
      <div class="card w5">
        <div class="card-title">失败的原因</div>
        <p class="card-sub">这段时间 {{ t.failed + t.interrupted }} 次失败，按原因归并</p>
        <div v-if="d.reasons.length" class="hbars tight">
          <template v-for="r in d.reasons" :key="r.reason">
            <span class="lab wrap">{{ r.reason }}</span>
            <div class="track"><div class="fill bad" :style="{ width: pct(r.n, maxReason) + '%' }"></div></div>
            <span class="num">{{ r.n }}</span>
          </template>
        </div>
        <EmptyState v-else icon="check" title="这段时间没有失败的任务" />
        <template v-if="d.stages.length">
          <div class="card-title" style="margin-top: 18px; font-size: var(--fs-md)">失败时做到了哪一步</div>
          <div class="hbars tight" style="margin-top: 10px">
            <template v-for="r in d.stages" :key="r.stage">
              <span class="lab">{{ r.stage }}</span>
              <div class="track"><div class="fill bad" :style="{ width: pct(r.n, maxStage) + '%' }"></div></div>
              <span class="num">{{ r.n }}</span>
            </template>
          </div>
          <p class="hint" style="margin-top: 10px">步骤从这个版本开始记录；之前的任务只有填表有步骤，其余显示为“没有记录到哪一步”。</p>
        </template>
      </div>
    </div>

    <div class="card">
      <div class="card-title">各类任务的表现</div>
      <p class="card-sub">耗时取完成和失败的任务的中位数；AI 成本是这类任务的全部花费（失败的也算），除以完成的次数。</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th>任务</th><th class="num">次数</th><th style="min-width: 150px">结果</th><th class="num">成功率</th><th class="num">通常耗时</th><th class="num">重启过</th><th class="num">AI 请求</th><th class="num">AI 成本</th><th class="num">每次完成的成本</th></tr></thead>
          <tbody>
            <tr v-for="k in d.by_kind" :key="k.kind">
              <td class="name">{{ k.label }}</td>
              <td class="num">{{ k.total }}</td>
              <td><SplitBar :parts="parts(k)" :legend="false" /><div class="small muted" style="margin-top: 3px">{{ k.success }} 完成 · {{ k.unfinished }} 没做完 · {{ k.failed + k.interrupted }} 失败</div></td>
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
      <div class="card-title">最近的执行</div>
      <p class="card-sub">点一行看它用到的每一次模型请求。</p>
      <div class="an-scroll">
        <table class="an-table">
          <thead><tr><th>任务</th><th>开始</th><th>结果</th><th class="num">耗时</th><th class="num">AI 请求</th><th class="num">Token</th><th class="num">AI 成本</th><th>没完成的原因</th></tr></thead>
          <tbody>
            <template v-for="r in recent" :key="r.id">
              <tr class="clickable" @click="toggle(r)">
                <td><div class="name">{{ r.label }}</div><div v-if="r.subject" class="small muted">{{ r.subject }}</div></td>
                <td class="nowrap">{{ fmt(r.at) }}</td>
                <td><span class="badge" :class="TONE[r.outcome]">{{ r.outcome_label }}</span></td>
                <td class="num">{{ dur(r.duration_s) }}</td>
                <td class="num">{{ r.requests || '—' }}</td>
                <td class="num">{{ r.tokens ? compact(r.tokens) : '—' }}</td>
                <td class="num">{{ r.requests ? money(r.cost, r.cost_partial && r.cost != null) : '—' }}</td>
                <td><span v-if="r.reason">{{ r.reason }}</span><div v-if="r.stage && r.reason" class="small muted">停在：{{ r.stage }}</div></td>
              </tr>
              <tr v-if="open.id === r.id" class="sub-row">
                <td colspan="8">
                  <div v-if="open.error" class="err">{{ open.error }}</div>
                  <div v-else-if="!open.rows" class="muted small">正在读取…</div>
                  <div v-else-if="!open.rows.length" class="muted small">这次执行没有用到模型。</div>
                  <table v-else class="an-table">
                    <thead><tr><th>功能</th><th>模型</th><th>状态</th><th class="num">轮数</th><th class="num">输入</th><th class="num">缓存读取</th><th class="num">缓存写入</th><th class="num">输出</th><th class="num">耗时</th><th class="num">成本</th></tr></thead>
                    <tbody>
                      <tr v-for="q in open.rows" :key="q.id">
                        <td>{{ q.legacy ? '改造前的合计' : q.label }}<span v-if="q.attempt" class="badge" style="margin-left: 6px">备用服务第 {{ q.attempt }} 次</span></td>
                        <td><span data-notr>{{ q.model || '没有记录' }}</span><div class="small muted">{{ q.provider_label }}</div></td>
                        <td><span class="badge" :class="q.status === 'ok' ? 'ok' : q.status === 'unknown' ? '' : 'bad'" :title="q.error">{{ STATUS[q.status] || q.status }}</span></td>
                        <td class="num">{{ q.turns }}</td>
                        <td class="num">{{ q.input == null ? '—' : compact(q.input) }}</td>
                        <td class="num">{{ q.cache_read == null ? '—' : compact(q.cache_read) }}</td>
                        <td class="num">{{ q.cache_write == null ? '—' : compact(q.cache_write) }}</td>
                        <td class="num">{{ q.output == null ? '—' : compact(q.output) }}</td>
                        <td class="num">{{ ms(q.latency_ms) }}</td>
                        <td class="num">{{ money(q.cost) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <button v-if="d.recent.length > 12" class="ghost sm" style="margin-top: 8px" @click="all = !all">{{ all ? '收起' : `再看 ${d.recent.length - 12} 次` }}</button>
    </div>
  </template>
  <div v-else class="card">
    <EmptyState icon="activity" :title="params.kind ? '这段时间没有这类任务' : '这段时间程序没有跑过任务'" text="换一个时间范围，或者看全部任务。">
      <button v-if="params.kind" @click="params.kind = ''">看全部任务</button>
    </EmptyState>
  </div>
</template>

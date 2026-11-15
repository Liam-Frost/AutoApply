<script setup>
// One run of a task: what it came to, and every model request it made. Shown in a drawer, from the automation view
// and from the lists of the AI cost view. `run` needs an id (the task's) and whatever of the row is known.
import { ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { compact, dur, money, ms } from '../../analytics'

const props = defineProps({ run: { type: Object, required: true } })
const rows = ref(null)
const error = ref('')
const TONE = { success: 'ok', handed: 'warn', waiting: 'warn', rerun: 'warn', running: 'info', failed: 'bad', interrupted: 'bad', cancelled: '' }
const STATUS = { ok: '成功', error: '出错', refused: '被拒绝', timeout: '超时', rate_limited: '额度或限流', unavailable: '服务不可用', unknown: '没有记录' }

watch(() => props.run.id, async (id) => {
  rows.value = null
  error.value = ''
  try {
    const got = (await api.get('/analytics/ai/requests?task_id=' + id)).requests
    if (props.run.id === id) rows.value = got       // an answer for a run that is no longer shown is dropped
  } catch (e) { if (props.run.id === id) error.value = e.message || '没有读到数据' }
}, { immediate: true })
</script>

<template>
  <div class="facts" style="margin-bottom: 16px">
    <div v-if="run.outcome"><div class="k">结果</div><div class="v"><span class="badge" :class="TONE[run.outcome]">{{ run.outcome_label }}</span></div></div>
    <div v-if="run.at"><div class="k">开始</div><div class="v">{{ fmt(run.at) }}</div></div>
    <div v-if="run.duration_s != null"><div class="k">耗时</div><div class="v">{{ dur(run.duration_s) }}</div></div>
    <div v-if="run.requests != null"><div class="k">AI 请求</div><div class="v">{{ run.requests || 0 }}</div></div>
    <div v-if="run.tokens != null"><div class="k">Token</div><div class="v">{{ run.tokens ? compact(run.tokens) : '—' }}</div></div>
    <div v-if="run.cost !== undefined"><div class="k">AI 成本</div><div class="v">{{ money(run.cost, run.cost_partial && run.cost != null) }}</div></div>
  </div>
  <div v-if="run.reason" class="callout" :class="run.outcome === 'failed' || run.outcome === 'interrupted' ? 'bad' : 'warn'">
    <div><b>{{ run.reason }}</b><div v-if="run.stage" class="small">停在：{{ run.stage }}</div></div>
  </div>

  <div class="card-title" style="font-size: var(--fs-md); margin: 4px 0 8px">这次执行的模型请求</div>
  <div v-if="error" class="err">{{ error }}</div>
  <div v-else-if="!rows" class="skel" style="height: 90px"></div>
  <p v-else-if="!rows.length" class="muted">这次执行没有用到模型。</p>
  <div v-else class="an-scroll">
    <table class="an-table">
      <thead><tr><th>功能</th><th>模型</th><th>状态</th><th class="num">轮数</th><th class="num">输入</th><th class="num">缓存读取</th><th class="num">缓存写入</th><th class="num">输出</th><th class="num">耗时</th><th class="num">成本</th></tr></thead>
      <tbody>
        <tr v-for="q in rows" :key="q.id">
          <td>{{ q.legacy ? '改造前的合计' : q.label }}<div v-if="q.attempt" class="small muted">备用服务第 {{ q.attempt }} 次</div></td>
          <td><span data-notr>{{ q.model || '—' }}</span><div class="small muted">{{ q.provider_label }}</div></td>
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
  </div>
</template>

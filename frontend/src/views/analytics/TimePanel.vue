<script setup>
// Where the time of the form-filling runs goes, and what the program has learned from it.
// One system at a time for the trend (the forms of two systems are not comparable); every run of the window in the
// list; one run opened shows its steps in order. What was learned is listed with why, how its trials went, and
// the buttons to take it out or let it in.
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import { ms } from '../../analytics'
import { ask, toast } from '../../ui'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'
import Pager from '../../components/Pager.vue'
import SeriesTable from '../../components/SeriesTable.vue'
import StackChart from '../../components/StackChart.vue'

const props = defineProps({ d: { type: Object, required: true } })
const emit = defineEmits(['reload'])

// what a run's time is spent on; the applicant's own waiting is shown but never added to a run's time
const KINDS = [
  { key: 'driver', label: '程序操作表单', color: 'var(--chart-1)' },
  { key: 'ai', label: '等 AI 回答', color: 'var(--chart-2)' },
  { key: 'tool', label: 'AI 调用工具', color: 'var(--chart-3)' },
  { key: 'site', label: '等网站响应', color: 'var(--chart-4)' },
]
const KIND_LABEL = { ...Object.fromEntries(KINDS.map((k) => [k.key, k.label])), human: '等你' }
const KIND_COLOR = { ...Object.fromEntries(KINDS.map((k) => [k.key, k.color])), human: 'var(--chart-other)' }
const STATUS = {
  proposed: ['等你确认', 'warn'], trial: ['试用中', 'info'], active: ['已生效', 'ok'], reverted: ['已撤回', 'bad'], parked: ['没有通过检查', ''], rejected: ['你没有采用', ''],
}
const KIND_OF = { recipe: '配方', plugin: '代码' }
const FINDING = {
  slow: (f) => `“${stepName(f.step)}”用了 ${ms(f.ms)}，平时约 ${ms(f.usual_ms)}`,
  tool_failed_repeatedly: (f) => `工具 ${f.step} 调用 ${f.of} 次，失败 ${f.failed} 次`,
  fields_not_filled_by_the_driver: (f) => `驱动没能填好的字段：${(f.fields || []).join('、')}`,
  taken_over_repeatedly: (f) => `同一次运行里 AI 接手了 ${f.times} 次`,
}

const system = ref('')
const sys = computed(() => props.d.systems.find((s) => s.ats === system.value) || props.d.systems[0] || null)
watch(() => props.d.systems, (list) => { if (!list.find((s) => s.ats === system.value)) system.value = list[0] ? list[0].ats : '' }, { immediate: true })
const trend = computed(() => (sys.value ? sys.value.trend.map((w) => ({ key: w.week, label: w.week.slice(5), tip: `${w.week} 起的一周（${w.runs} 次）`,
  values: Object.fromEntries(KINDS.map((k) => [k.key, w[k.key] || 0])) })) : []))

const page = ref(0)
const SIZE = 10
const runs = computed(() => props.d.runs.filter((r) => !system.value || r.ats === system.value))
const shownRuns = computed(() => runs.value.slice(page.value * SIZE, (page.value + 1) * SIZE))
watch(system, () => { page.value = 0; open.value = null })

const open = ref(null)
async function toggle(r) {
  if (open.value && open.value.id === r.id) { open.value = null; return }
  try { open.value = await api.get(`/analytics/timing/runs/${r.id}`) } catch (e) { toast(e.message, 'bad') }
}
const stepName = (n) => ({ field: '填一个字段', load: '打开页面', window: '窗口等你操作' }[n] || String(n).replace(/^step:/, ''))
const span = computed(() => {
  if (!open.value) return { rows: [], total: 1 }
  const rows = open.value.spans.filter((s) => s.ms >= 200 || s.ok === false || s.ok === 'False')
  const total = Math.max(1, ...open.value.spans.map((s) => s.t + s.ms))
  return { rows, total }
})

const rev = ref(null)
async function showRev(v) {
  if (rev.value && rev.value.id === v.id) { rev.value = null; return }
  try { rev.value = await api.get(`/learned/${v.id}`) } catch (e) { toast(e.message, 'bad') }
}
async function decide(v, action, question) {
  if (question && !(await ask(question, { ok: '确定', danger: false }))) return
  try { await api.post(`/learned/${v.id}/${action}`); rev.value = null; emit('reload') } catch (e) { toast(e.message, 'bad') }
}
async function setMode(mode) {
  try { await api.put('/settings', { settings: { 'learned.mode': mode } }); emit('reload') } catch (e) { toast(e.message, 'bad') }
}
async function setEnabled(on) {
  try { await api.put('/settings', { settings: { 'learned.enabled': on } }); emit('reload') } catch (e) { toast(e.message, 'bad') }
}
const before = (v) => (v.baseline && v.baseline.median_ms ? ms(v.baseline.median_ms) : '—')
</script>

<template>
  <div>
    <div v-if="!d.count" class="card">
      <EmptyState icon="clock" title="这段时间里还没有带耗时记录的填表运行" text="从这个版本开始，每次填表都会记录时间花在了哪里：程序操作、等 AI、AI 调用工具、等网站。投出下一份申请后这里就有内容了。" />
    </div>

    <template v-else>
      <div class="kpis">
        <div class="kpi"><div class="n">{{ d.count }}</div><div class="l">次填表运行</div></div>
        <div class="kpi" title="不含等你操作的时间。取中位数：一半的运行比它快，一半比它慢。"><div class="n">{{ sys ? ms(sys.median_ms) : '—' }}</div><div class="l">{{ sys ? sys.ats : '' }} 每次用时（中位数）</div></div>
        <div class="kpi" title="驱动没能做完、由 AI 接手的次数，平均到每次运行。越少越好：每次接手都要等 AI。"><div class="n">{{ sys ? sys.takeovers : '—' }}</div><div class="l">每次运行里 AI 接手的次数</div></div>
        <div class="kpi"><div class="n">{{ d.learned.filter((v) => v.status === 'active' || v.status === 'trial').length }}</div><div class="l">项学到的做法在起作用</div></div>
      </div>

      <div class="an-bar" style="margin-bottom: 12px">
        <span class="small muted">招聘系统</span>
        <AaSelect v-model="system" small aria-label="招聘系统"><option v-for="s in d.systems" :key="s.ats" :value="s.ats">{{ s.ats }}（{{ s.runs }} 次）</option></AaSelect>
      </div>

      <div class="an-row c32 tight">
        <div class="card">
          <div class="card-title">每次运行的时间花在哪里</div>
          <div class="card-sub">每周各类用时的中位数。等你操作的时间不算在内。</div>
          <StackChart :buckets="trend" :series="KINDS" :format="ms" :height="168" />
        </div>
        <div class="card">
          <div class="card-title">图里的数字</div>
          <SeriesTable :buckets="trend" :series="KINDS" :format="ms" table-label="周" :size="6" />
        </div>
      </div>

      <div class="card">
        <div class="card-title">每一次运行</div>
        <div class="card-sub">点一行看这次运行每一步的耗时。</div>
        <div class="an-scroll">
          <table class="an-table">
            <thead><tr><th>时间</th><th>申请</th><th class="num">用时</th><th v-for="k in KINDS" :key="k.key" class="num">{{ k.label }}</th><th class="num">AI 接手</th><th>结果</th></tr></thead>
            <tbody>
              <template v-for="r in shownRuns" :key="r.id">
                <tr style="cursor: pointer" @click="toggle(r)">
                  <td class="nowrap">{{ r.at.slice(0, 16).replace('T', ' ') }}</td>
                  <td class="name" data-notr>{{ r.subject }}</td>
                  <td class="num" style="font-weight: 650">{{ ms(r.working_ms) }}</td>
                  <td v-for="k in KINDS" :key="k.key" class="num">{{ ms(r.totals[k.key]) }}</td>
                  <td class="num">{{ r.takeovers }}</td>
                  <td><span class="tag" :class="r.ok ? 'ok' : 'warn'">{{ r.ok ? '填完了' : '没填完' }}</span><span v-if="r.learned.length" class="tag info" style="margin-left: 4px">用了学到的做法</span></td>
                </tr>
                <tr v-if="open && open.id === r.id">
                  <td colspan="9" style="background: var(--surface-2)">
                    <div v-if="open.review.findings.length" class="small" style="margin-bottom: 8px">
                      <b>这次运行里不寻常的地方：</b>
                      <ul style="margin: 4px 0 0 18px"><li v-for="(f, i) in open.review.findings" :key="i">{{ (FINDING[f.what] || (() => f.what))(f) }}</li></ul>
                    </div>
                    <div v-else class="small muted" style="margin-bottom: 8px">这次运行没有明显偏离平时的地方{{ open.review.usual.runs ? '' : '（这个网站的记录还太少，没法比较）' }}。</div>
                    <div v-if="open.learned.length" class="small" style="margin-bottom: 8px">这次用到的学到的做法：<span v-for="l in open.learned" :key="l.id" class="tag info" style="margin-right: 4px">{{ l.title }}</span></div>
                    <div class="tl">
                      <div v-for="(s, i) in span.rows" :key="i" class="tl-row" :title="`${KIND_LABEL[s.k]} · ${ms(s.ms)}`">
                        <span class="tl-name"><span class="tl-dot" :style="{ background: KIND_COLOR[s.k] }"></span>{{ stepName(s.n) }}<span v-if="s.label" class="muted" data-notr> · {{ s.label }}</span></span>
                        <span class="tl-track"><span class="tl-bar" :class="{ failed: s.ok === false || s.ok === 'False' }" :style="{ left: (s.t / span.total) * 100 + '%', width: Math.max(0.4, (s.ms / span.total) * 100) + '%', background: KIND_COLOR[s.k] }"></span></span>
                        <span class="tl-ms">{{ ms(s.ms) }}</span>
                      </div>
                    </div>
                    <div class="small muted" style="margin-top: 6px">只列出 0.2 秒以上或没有成功的步骤。</div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <Pager v-if="runs.length > SIZE" v-model:page="page" :total="runs.length" :size="SIZE" />
      </div>
    </template>

    <div class="card">
      <div class="card-title">程序从运行里学到的做法</div>
      <p class="muted">一次运行里有明显偏离平时的地方（某一步特别慢、AI 反复接手、驱动填不好某个字段）时，程序会让 AI 写下下次该怎么做：一份“配方”，或者一小段代码。它先通过检查，然后在之后的运行里试用；试用中出错就在同一次运行里退回原来的做法，并自动撤回。这些都保存在数据文件夹里，升级程序不会丢。</p>
      <div class="an-bar" style="margin-bottom: 12px">
        <label class="row" style="gap: 6px"><input type="checkbox" :checked="d.enabled" @change="setEnabled($event.target.checked)" />让程序从运行里学习</label>
        <span class="small muted">学到之后</span>
        <AaSelect :value="d.mode" small aria-label="学到之后" @change="setMode($event.target.value)"><option value="auto">通过检查就自动试用</option><option value="ask">先问我</option></AaSelect>
      </div>
      <EmptyState v-if="!d.learned.length" icon="wrench" title="还没有学到什么" text="有运行出现不寻常的地方之后，这里会列出程序学到的每一项做法、原因和效果。" />
      <div v-else class="an-scroll">
        <table class="an-table">
          <thead><tr><th>做法</th><th>用在</th><th>状态</th><th class="num">试用</th><th class="num">之前用时</th><th class="num">现在用时</th><th></th></tr></thead>
          <tbody>
            <template v-for="v in d.learned" :key="v.id">
              <tr style="cursor: pointer" @click="showRev(v)">
                <td class="name">{{ v.title }} <span class="tag">{{ KIND_OF[v.kind] }}</span></td>
                <td data-notr>{{ v.target.replace(/^site-/, '') }}</td>
                <td><span class="tag" :class="(STATUS[v.status] || [])[1]">{{ (STATUS[v.status] || [v.status])[0] }}</span></td>
                <td class="num">{{ v.good }} / {{ v.trials }}</td>
                <td class="num">{{ before(v) }}</td>
                <td class="num">{{ v.median_ms ? ms(v.median_ms) : '—' }}</td>
                <td class="nowrap" @click.stop>
                  <button v-if="v.status === 'proposed'" class="sm primary" @click="decide(v, 'approve')">采用</button>
                  <button v-if="v.status === 'proposed' || v.status === 'parked'" class="sm ghost" @click="decide(v, 'reject')">不采用</button>
                  <button v-if="v.status === 'trial' || v.status === 'active'" class="sm ghost danger" @click="decide(v, 'revert', `撤回“${v.title}”？程序会回到原来的做法。`)">撤回</button>
                  <button v-if="v.status === 'reverted' || v.status === 'parked'" class="sm ghost" @click="decide(v, 'retry')">再试一次</button>
                </td>
              </tr>
              <tr v-if="rev && rev.id === v.id">
                <td colspan="7" style="background: var(--surface-2)">
                  <div class="small"><b>为什么：</b>{{ rev.why }}</div>
                  <div v-if="rev.expected" class="small" style="margin-top: 4px"><b>预期：</b>{{ rev.expected }}</div>
                  <div class="small muted" style="margin-top: 4px">{{ rev.why_status }}<template v-if="rev.from_run"> · 来自第 {{ rev.from_run }} 次运行</template> · 在 {{ rev.version || '?' }} 版上通过检查</div>
                  <pre class="code" data-notr style="margin-top: 8px; max-height: 260px; overflow: auto">{{ rev.content }}</pre>
                  <div v-if="rev.history && rev.history.length" class="small muted" style="margin-top: 6px">
                    <span v-for="(h, i) in rev.history" :key="i">{{ i ? ' → ' : '' }}{{ (STATUS[h.status] || [h.status])[0] }}（{{ (h.at || '').slice(5, 16).replace('T', ' ') }}）</span>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

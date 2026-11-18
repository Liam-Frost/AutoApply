<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run, toast } from '../ui'

const runs = ref([])
const tasks = ref([])
const notes = ref([])
const ov = ref({ drivers: [], mail_recent: [] })
const filter = ref('all')
const route = useRoute()
const tab = ref(['plan', 'activity', 'sched', 'notes', 'systems'].includes(String(route.query.tab)) ? String(route.query.tab) : 'plan')
const sched = ref([])
// The plan: what is being done, what comes next and in which order, what waits for you, what was set aside, what is
// set for later. The record of what was done is the next tab.
const plan = ref(null)
const busy = ref(0)
async function loadPlan() { try { plan.value = await api.get('/queue') } catch (e) { toast(e.message, 'bad') } }
async function control(t, what, ok) {
  if (busy.value) return
  busy.value = t.id
  try { await api.post(`/tasks/${t.id}/${what}`); toast(ok); await Promise.all([loadPlan(), load()]) } catch (e) { toast(e.message, 'bad'); await loadPlan() } finally { busy.value = 0 }
}
async function cancelTask(t) {
  if (!(await ask(`取消“${t.label}${t.subject ? ' · ' + t.subject : ''}”？它会从队列里拿掉，不会执行。`, { ok: '取消这个任务' }))) return
  await control(t, 'cancel', '已取消')
}
async function drain(on) {
  try { const r = await api.post('/queue/drain', { on }); toast(on ? (r.stopped ? '现在没有任务在执行，已停下，可以关闭或重启' : '会做完手上的任务，不再开始新的；停下后会通知你') : '队列继续'); await loadPlan() } catch (e) { toast(e.message, 'bad') }
}
const runNow = (j) => run(() => api.post('/tasks', { kind: j.kind }), '已开始，结果会出现在“活动”里', load)
const setEvery = (j) => run(() => api.put('/settings', { settings: { [j.setting]: Math.max(0, Math.round(Number(j.minutes) || 0)) } }), '已保存，下一次运行时间已按新的间隔重排', load)
const every = (m) => (m >= 1440 && m % 1440 === 0 ? `${m / 1440} 天` : m >= 60 && m % 60 === 0 ? `${m / 60} 小时` : `${m} 分钟`)

async function read() {
  loadPlan()
  api.get('/schedule').then((r) => { sched.value = r }).catch(() => {})
  ;[runs.value, tasks.value, notes.value, ov.value] = await Promise.all([api.get('/runs'), api.get('/tasks?limit=80'), api.get('/notifications?limit=40'), api.get('/overview')])
}
const shown = computed(() => tasks.value.filter((t) => filter.value === 'all' || ['failed', 'waiting_human', 'running', 'queued'].includes(t.status)))
const stepsOf = (t) => {
  const r = runs.value.find((x) => x.task_id === t.id && x.steps.length)
  return r ? r.steps.map((s) => JSON.stringify(s)).join('\n') + `\n\n截图和页面快照：${r.dir}` : ''
}
const tech = (t) => [t.explained.detail, (t.browser_detail || []).join('\n'), t.status === 'done' && t.result && Object.keys(t.result).length ? JSON.stringify(t.result, null, 1) : '', stepsOf(t)].filter(Boolean).join('\n\n')
const line = (t) => t.summary || t.explained.message || (t.status === 'running' ? '正在进行…' : t.status === 'queued' ? (t.due_at ? `定在 ${fmtTime(t.due_at)} 之后再做` : '等前面的任务完成') : '')
const retry = (t) => run(() => api.post(`/tasks/${t.id}/retry`), '已重新排队', load)
const retryNative = (t) => run(() => api.post(`/tasks/${t.id}/retry`, { browser_backend: 'nodriver' }), '已重新排队，这一次用普通浏览器', load)
const CAT = { task_started: '开始', todo: '待办', status_update: '进展', task_result: '结果' }
const sysName = (d) => ({ greenhouse: 'Greenhouse', ashby: 'Ashby', workday: 'Workday', pdportal: 'UBC PD Portal', generic: '其他网站（通用方式）', lever: 'Lever' }[d.ats] || d.ats)
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load, { every: 4000, when: () => ((plan.value && plan.value.running) || []).length > 0 || (ov.value.running || []).length > 0 })
onMounted(load)
</script>

<template>
  <PageHead title="活动记录" sub="程序正在做什么、接下来做什么，以及做过的每一件事和结果。">
    <button @click="load"><Icon name="refresh" />刷新</button>
  </PageHead>
  <DataState :s="st" what="活动记录" @retry="load" />
  <template v-if="st.at">

  <div class="row" style="margin-bottom: 12px">
    <div class="seg">
      <button :class="{ on: tab === 'plan' }" @click="tab = 'plan'">工作计划</button>
      <button :class="{ on: tab === 'activity' }" @click="tab = 'activity'">做过的事</button>
      <button :class="{ on: tab === 'sched' }" @click="tab = 'sched'">定时任务</button>
      <button :class="{ on: tab === 'notes' }" @click="tab = 'notes'">发出的通知</button>
      <button :class="{ on: tab === 'systems' }" @click="tab = 'systems'">各招聘系统的表现</button>
    </div>
    <span class="grow"></span>
    <div v-if="tab === 'activity'" class="seg">
      <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部</button>
      <button :class="{ on: filter === 'open' }" @click="filter = 'open'">只看没完成的</button>
    </div>
  </div>

  <template v-if="tab === 'plan'">
    <div v-if="!plan" class="card"><div class="empty"><div class="t">正在读取…</div></div></div>
    <template v-else>
      <div class="card">
        <div class="row" style="align-items: flex-start; flex-wrap: wrap; gap: 12px">
          <div class="grow">
            <div v-if="plan.draining && plan.stopped"><b>已停下。</b> 手上的任务都做完了，不会再开始新的。现在可以放心关闭或重启程序；重新启动后队列会接着做。</div>
            <div v-else-if="plan.draining"><b>正在收尾。</b> 做完手上的 {{ plan.running.length }} 个任务就停，不再开始新的；停下后会通知你。</div>
            <div v-else-if="plan.paused"><b>自动运行已暂停。</b> 定时扫描、自动评分、自动生成草案和自动重试都停着；你亲手点的操作（批准、生成草案、查邮件）照常执行。</div>
            <div v-else><b>运行中。</b> 表单的读取和填写一次做一个；扫描、评分、查邮件在另一条线上同时进行。</div>
            <div class="small muted" style="margin-top: 4px">等你处理的草案（正在生成或等你审批）：{{ plan.drafts.waiting }}<template v-if="plan.drafts.cap"> / 上限 {{ plan.drafts.cap }}<template v-if="plan.drafts.room === 0">，已到上限，程序暂时不再自己开始新的草案</template></template>。上限在<router-link to="/settings/automation/prepare">设置 → 自动准备草案</router-link>里改。</div>
          </div>
          <button v-if="!plan.draining" @click="drain(true)"><Icon name="pause" />做完手上的就停</button>
          <button v-else class="primary" @click="drain(false)"><Icon name="play" />继续做队列里的任务</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">正在做</div>
        <div class="list">
          <div v-for="t in plan.running" :key="t.id" class="item">
            <span class="badge info" style="min-width: 64px; justify-content: center">进行中</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
              <div class="sub">开始于 {{ fmtTime(t.started_at) }}。</div></div>
            <div v-if="['recon', 'execute', 'revise', 'reanswer'].includes(t.kind)" class="right"><button class="sm" :disabled="!!busy" @click="control(t, 'stop', '已叫停，Agent 会在下一步操作之前停下')">叫停</button></div>
          </div>
        </div>
        <div v-if="!plan.running.length" class="muted">现在没有任务在执行。</div>
      </div>

      <div class="card">
        <div class="card-title">接下来<span v-if="plan.next_total" class="muted" style="font-weight: 400">（{{ plan.next_total }} 个，按这个顺序做）</span></div>
        <div class="list">
          <div v-for="(t, i) in plan.next" :key="t.id" class="item">
            <span class="badge" style="min-width: 40px; justify-content: center">{{ i + 1 }}</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
              <div class="sub"><template v-if="t.held_by_pause">自动运行暂停期间不会开始</template><template v-else-if="t.by_hand">你亲手开始的</template><template v-else>{{ t.lane === 'background' ? '后台线' : t.lane === 'desk' ? '资料线' : '表单线' }}</template></div></div>
            <div class="right row" style="flex-wrap: nowrap">
              <button v-if="i > 0 || t.held_by_pause" class="sm ghost" :disabled="!!busy" @click="control(t, 'first', '会先做这一个')">先做这个</button>
              <button class="sm ghost" :disabled="!!busy" @click="control(t, 'hold', '已暂缓')">暂缓</button>
              <button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">取消</button>
            </div>
          </div>
        </div>
        <div v-if="!plan.next.length" class="muted">队列里没有等着做的任务。</div>
        <div v-else-if="plan.next_total > plan.next.length" class="small muted" style="margin-top: 6px">只列出前 {{ plan.next.length }} 个。</div>
      </div>

      <div v-if="plan.waiting.length" class="card">
        <div class="card-title">等你处理后才能继续</div>
        <div class="list">
          <div v-for="t in plan.waiting" :key="t.id" class="item">
            <span class="badge warn" style="min-width: 64px; justify-content: center">等你</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
              <div class="sub">{{ t.waits_for ? '在等：' + t.waits_for : t.why }}</div></div>
            <div class="right row" style="flex-wrap: nowrap"><router-link to="/todos" class="btn sm">去处理</router-link><button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">取消</button></div>
          </div>
        </div>
      </div>

      <div v-if="plan.held.length" class="card">
        <div class="card-title">暂缓的</div>
        <div class="list">
          <div v-for="t in plan.held" :key="t.id" class="item">
            <span class="badge" style="min-width: 64px; justify-content: center">暂缓</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div><div class="sub">不会开始，直到你让它继续。</div></div>
            <div class="right row" style="flex-wrap: nowrap"><button class="sm" :disabled="!!busy" @click="control(t, 'take-up', '已放回队列')">继续</button><button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">取消</button></div>
          </div>
        </div>
      </div>

      <div v-if="plan.later.length" class="card">
        <div class="card-title">定了时间、到点再做的</div>
        <div class="list">
          <div v-for="t in plan.later" :key="t.id" class="item">
            <span class="badge" style="min-width: 64px; justify-content: center">定时</span>
            <div><div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div><div class="sub">{{ fmtTime(t.due_at) }} 之后</div></div>
            <div class="right row" style="flex-wrap: nowrap"><button class="sm ghost" :disabled="!!busy" @click="control(t, 'first', '会马上做')">现在就做</button><button class="sm ghost" :disabled="!!busy" @click="cancelTask(t)">取消</button></div>
          </div>
        </div>
      </div>
    </template>
  </template>

  <div v-if="tab === 'sched'" class="card">
    <div class="card-title">程序自己定时做的事</div>
    <p class="card-sub">间隔从上一次运行算起，关掉程序再打开不会重新计时；到点时程序没开着，打开后两分钟内补跑。间隔直接在这里改，改完就生效；填 0 关闭。</p>
    <div class="table-wrap" style="max-height: none">
      <table>
        <thead><tr><th>做什么</th><th>多久一次</th><th>上一次</th><th>下一次</th><th></th></tr></thead>
        <tbody>
          <tr v-for="j in sched" :key="j.kind">
            <td>{{ j.label }}</td>
            <td class="nowrap">每 <input v-model.number="j.minutes" type="number" min="0" style="width: 84px" @change="setEvery(j)" /> 分钟
              <span class="muted small">{{ j.minutes ? `（${every(j.minutes)}）` : '（已关闭）' }}</span></td>
            <td><span v-if="j.last">{{ fmtTime(j.last) }}</span><span v-else class="muted">还没跑过</span></td>
            <td><span v-if="j.paused" class="tag warn">自动运行已暂停</span><span v-else-if="j.next">{{ fmtTime(j.next) }}</span><span v-else class="muted">—</span></td>
            <td style="text-align: right"><button class="ghost sm" @click="runNow(j)"><Icon name="play" />现在跑一次</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="small muted" style="margin-top: 10px">另外，每 10 分钟检查一次：评分已达到“自动生成草案”分数、但还没有草案的岗位，会开始生成草案（一次最多 6 个）；表单还有步骤没读到的草案，会接着往下读。草案批准后立刻开始填写，不用等定时。</p>
  </div>

  <div v-if="tab === 'activity'" class="card">
    <div class="list">
      <div v-for="t in shown" :key="t.id" class="item">
        <span class="badge" :class="t.tone" style="min-width: 64px; justify-content: center">{{ t.status_label }}</span>
        <div>
          <div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
          <div v-if="line(t)" class="sub">{{ line(t) }}</div>
          <div v-if="t.browser_stages?.length" class="sub">{{ t.browser_stages.join(' · ') }}</div>
          <TechDetails :text="tech(t)" />
        </div>
        <div class="right">
          <div class="small muted nowrap">{{ fmtTime(t.finished_at || t.started_at || t.created_at) }}</div>
          <button v-if="['failed', 'waiting_human'].includes(t.status) && t.kind !== 'execute'" class="sm ghost" style="margin-top: 4px" @click="retry(t)">再试一次</button>
          <button v-if="['failed', 'waiting_human'].includes(t.status) && ['recon', 'discover', 'revise'].includes(t.kind)" class="sm ghost" style="margin-top: 4px" title="网站把程序自带的浏览器挡在外面时用（nodriver）" @click="retryNative(t)">换普通浏览器重试</button>
        </div>
      </div>
    </div>
    <EmptyState v-if="!shown.length" icon="activity" :title="filter === 'all' ? '还没有任何活动' : '没有未完成的任务'" />
  </div>

  <div v-if="tab === 'notes'" class="card">
    <div class="list">
      <div v-for="n in notes" :key="n.id" class="item">
        <span class="badge" :class="n.sent ? 'ok' : ''">{{ n.sent ? '已发送' : '未发送' }}</span>
        <div><div class="sub" style="white-space: pre-line; color: var(--text)">{{ n.text }}</div><div v-if="n.error" class="err small">{{ n.error }}</div></div>
        <span class="small muted nowrap">{{ CAT[n.category] || '' }} · {{ fmtTime(n.created_at) }}</span>
      </div>
    </div>
    <EmptyState v-if="!notes.length" icon="bell" title="还没有发出过通知" text="在设置里配置 Telegram 后，进展和待办会推送给你。" />
  </div>

  <div v-if="tab === 'systems'" class="card">
    <p class="muted">每种招聘系统上，读取申请表和填写提交各成功了几次。连续成功次数达到设置里的门槛后，才允许对这个系统开启“自动通过”。</p>
    <table>
      <thead><tr><th>招聘系统</th><th>读取申请表</th><th>填写并提交</th><th>连续成功提交</th></tr></thead>
      <tbody>
        <tr v-for="d in ov.drivers" :key="d.ats">
          <td><b>{{ sysName(d) }}</b></td>
          <td>{{ d.recon_ok }} 次成功<span v-if="d.recon_fail" class="muted"> · {{ d.recon_fail }} 次没成功</span></td>
          <td>{{ d.exec_ok }} 次成功<span v-if="d.exec_fail" class="muted"> · {{ d.exec_fail }} 次没成功</span></td>
          <td>{{ d.streak }}</td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!ov.drivers.length" icon="activity" title="还没有运行过" />
  </div>
  </template>
</template>

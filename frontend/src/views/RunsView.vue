<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
import { fmtTime, run } from '../ui'

const runs = ref([])
const tasks = ref([])
const notes = ref([])
const ov = ref({ drivers: [], mail_recent: [] })
const filter = ref('all')
const tab = ref('activity')

async function load() {
  ;[runs.value, tasks.value, notes.value, ov.value] = await Promise.all([api.get('/runs'), api.get('/tasks?limit=80'), api.get('/notifications?limit=40'), api.get('/overview')])
}
const shown = computed(() => tasks.value.filter((t) => filter.value === 'all' || ['failed', 'waiting_human', 'running', 'queued'].includes(t.status)))
const stepsOf = (t) => {
  const r = runs.value.find((x) => x.task_id === t.id && x.steps.length)
  return r ? r.steps.map((s) => JSON.stringify(s)).join('\n') + `\n\n截图和页面快照：${r.dir}` : ''
}
const tech = (t) => [t.explained.detail, t.status === 'done' && t.result && Object.keys(t.result).length ? JSON.stringify(t.result, null, 1) : '', stepsOf(t)].filter(Boolean).join('\n\n')
const line = (t) => t.summary || t.explained.message || (t.status === 'running' ? '正在进行…' : t.status === 'queued' ? '等前面的任务完成' : '')
const retry = (t) => run(() => api.post(`/tasks/${t.id}/retry`), '已重新排队', load)
const CAT = { task_started: '开始', todo: '待办', status_update: '进展', task_result: '结果' }
const sysName = (d) => ({ greenhouse: 'Greenhouse', ashby: 'Ashby', workday: 'Workday', pdportal: 'UBC PD Portal', generic: '其他网站（通用方式）', lever: 'Lever' }[d.ats] || d.ats)
onMounted(load)
</script>

<template>
  <PageHead title="活动记录" sub="程序做过的每一件事和结果。">
    <button @click="load"><Icon name="refresh" />刷新</button>
  </PageHead>

  <div class="row" style="margin-bottom: 12px">
    <div class="seg">
      <button :class="{ on: tab === 'activity' }" @click="tab = 'activity'">活动</button>
      <button :class="{ on: tab === 'notes' }" @click="tab = 'notes'">发出的通知</button>
      <button :class="{ on: tab === 'systems' }" @click="tab = 'systems'">各招聘系统的表现</button>
    </div>
    <span class="grow"></span>
    <div v-if="tab === 'activity'" class="seg">
      <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部</button>
      <button :class="{ on: filter === 'open' }" @click="filter = 'open'">只看没完成的</button>
    </div>
  </div>

  <div v-if="tab === 'activity'" class="card">
    <div class="list">
      <div v-for="t in shown" :key="t.id" class="item">
        <span class="badge" :class="t.tone" style="min-width: 64px; justify-content: center">{{ t.status_label }}</span>
        <div>
          <div class="main">{{ t.label }}<span v-if="t.subject" class="muted" style="font-weight: 400"> · {{ t.subject }}</span></div>
          <div v-if="line(t)" class="sub">{{ line(t) }}</div>
          <TechDetails :text="tech(t)" />
        </div>
        <div class="right">
          <div class="small muted nowrap">{{ fmtTime(t.finished_at || t.started_at || t.created_at) }}</div>
          <button v-if="['failed', 'waiting_human'].includes(t.status) && t.kind !== 'execute'" class="sm ghost" style="margin-top: 4px" @click="retry(t)">再试一次</button>
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

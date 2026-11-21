<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { api } from '../api'
import ColumnChart from '../components/ColumnChart.vue'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import Explain from '../components/Explain.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import { deadlineLabel } from '../dates'
import { fmtTime, run } from '../ui'
import { dayRange, shortDayOf, shortDayText } from '../i18n/format'

const ov = inject('overview')
const reload = inject('reloadOverview')
const todos = ref([])
const drafts = ref([])

const c = computed(() => ov.value.stage_counts || {})
const n = (...keys) => keys.reduce((a, k) => a + (c.value[k] || 0), 0)
const TODO_TITLE = { takeover: '登录', login: '登录', captcha: '完成人机验证', answer: '回答问题', submit: '检查并提交', failed: '没有提交成功', config: '设置', mail_unmatched: '邮件没对上岗位', driver_patch: '自动修复记录', driver: '自检' }
const todoText = (t) => (t.site ? `${TODO_TITLE[t.kind] || ''} ${t.site.name}` : t.title)
const pending = computed(() => drafts.value.filter((x) => x.review_status === 'pending'))

// Where every application that was sent stands now (one series: magnitude by stage).
const pipeline = computed(() => [
  { key: 'submitted', label: '已投，等确认信' }, { key: 'confirmed', label: '对方已确认收到' }, { key: 'assessment', label: '笔试 / OA / VA' },
  { key: 'interview', label: '面试' }, { key: 'offer', label: '收到 Offer' }, { key: 'rejected', label: '已被拒' },
].map((r) => ({ ...r, value: c.value[r.key] || 0 })))
const pipeMax = computed(() => Math.max(1, ...pipeline.value.map((r) => r.value)))
const sentTotal = computed(() => pipeline.value.reduce((a, r) => a + r.value, 0))
// Everything that has gone out, with the same three words as the analytics page and from the same code
// (analytics.sent_summary): acknowledged, come to something, gone on. The chart of stages below shows a part of it -
// the applications whose posting is not archived - and says so.
const sent = ref({ sent: 0, dated: 0, undated: 0, archived: 0, heard: 0, decided: 0, progressed: 0 })
const share = (k) => (sent.value.sent ? Math.round((k / sent.value.sent) * 100) : 0)

const weekly = computed(() => (ov.value.weekly || []).map((w) => {
  const d = new Date(w.week + 'T00:00:00')
  const e = new Date(d.getTime() + 6 * 86400000)
  return { label: shortDayOf(d), value: w.n, tip: dayRange(d, e) }
}))
const weekTotal = computed(() => weekly.value.reduce((a, w) => a + w.value, 0))
const thisWeek = computed(() => (weekly.value.length ? weekly.value[weekly.value.length - 1].value : 0))

async function read() {
  ;[todos.value, drafts.value, sent.value] = await Promise.all([api.get('/todos'), api.get('/drafts'), api.get('/analytics/sent')])
  todos.value = todos.value.filter((t) => !t.snoozed_until)       // what was put off until later is not "waiting for you" until then
}
const scan = () => run(() => api.post('/tasks', { kind: 'discover' }), '开始扫描新岗位，完成后会通知你', reload)
const mail = () => run(() => api.post('/tasks', { kind: 'mail' }), '开始检查邮箱', reload)
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load)
onMounted(load)
</script>

<template>
  <PageHead title="概览" sub="现在需要你做什么，以及申请进行到哪一步。">
    <button @click="mail"><Icon name="mail" />检查邮箱</button>
    <button @click="scan"><Icon name="search" />扫描新岗位</button>
  </PageHead>
  <DataState :s="st" what="概览" @retry="load" />
  <template v-if="st.at">

  <div class="grid-4" style="margin-bottom: 16px">
    <router-link to="/todos" class="stat" :class="{ attn: ov.open_todos }"><div class="n">{{ ov.open_todos || 0 }}</div><div class="l">件事需要你处理</div></router-link>
    <router-link to="/drafts" class="stat" :class="{ attn: ov.pending_drafts }"><div class="n">{{ ov.pending_drafts || 0 }}</div><div class="l">份草案等你审批</div></router-link>
    <router-link to="/jobs" class="stat"><div class="n">{{ n('not_applied') }}</div><div class="l">个岗位还没投</div></router-link>
    <router-link to="/applications" class="stat"><div class="n">{{ sent.sent }}</div><div class="l">个申请已投出 · 收到回执 {{ share(sent.heard) }}% · 有实质结果 {{ share(sent.decided) }}%</div></router-link>
  </div>
  <Explain label="“已投出”“收到回执”“有实质结果”怎么算的" style="margin: -8px 0 14px">
    已投出：现在处于“已提交”或之后任何一步的全部申请，一共 {{ sent.sent }} 份。收到回执：对方有过任何回应，包括自动发的确认信（{{ sent.heard }} 份）。有实质结果：进入过笔试或面试、拿到 Offer，或者被拒；自动确认信不算（{{ sent.decided }} 份）。
    <template v-if="sent.archived">其中 {{ sent.archived }} 份的岗位已经归档，不在下面“申请进行到哪一步”的图里，那张图画的是其余 {{ sent.sent - sent.archived }} 份。</template>
    <router-link :to="{ path: '/analytics', query: { view: 'apps' } }">数据分析 → 求职成效</router-link>用同样的三个词，但按投递日期统计：有投递日期的是 {{ sent.dated }} 份<template v-if="sent.undated">，另外 {{ sent.undated }} 份知道投出了、没有记下是哪一天，不在那一页的数字里</template>。
  </Explain>

  <div class="cols">
    <div class="card">
      <div class="row"><span class="card-title grow">需要你处理</span><router-link :to="{ path: '/runs', query: { tab: 'notes' } }" class="small">最近的通知</router-link><router-link v-if="todos.length" to="/todos" class="small">全部</router-link></div>
      <div class="list">
        <router-link v-for="t in todos.slice(0, 4)" :key="'t' + t.id" to="/todos" class="item" style="color: inherit; text-decoration: none">
          <Icon name="bell" style="width: 18px; height: 18px; color: var(--warn); margin-top: 2px" />
          <div><div class="main">{{ todoText(t) }}</div><div class="sub clamp2">{{ t.explained.message }}</div></div>
          <span class="small muted nowrap">{{ fmtTime(t.created_at) }}</span>
        </router-link>
        <router-link v-for="d in pending.slice(0, 4)" :key="'d' + d.id" :to="'/drafts/' + d.id" class="item" style="color: inherit; text-decoration: none">
          <Icon name="draft" style="width: 18px; height: 18px; color: var(--primary); margin-top: 2px" />
          <div><div class="main">{{ d.company }} · {{ d.title }}</div><div class="sub">{{ d.unresolved ? `有 ${d.unresolved} 个问题需要你回答` : '草案已备好，等你审批' }}</div></div>
          <span class="small muted nowrap">截止 {{ shortDayText(d.deadline) || '—' }}</span>
        </router-link>
      </div>
      <EmptyState v-if="!todos.length && !pending.length" icon="check" title="没有需要你处理的事" text="有新的草案或需要登录时，会出现在这里，也会发到 Telegram。" />
    </div>

    <div class="card">
      <div class="row"><span class="card-title grow">快截止的岗位</span><router-link to="/jobs" class="small">全部未投</router-link></div>
      <div class="list">
        <router-link v-for="j in ov.closing_soon || []" :key="j.id" :to="{ path: '/jobs', query: { open: j.id } }" class="item" style="color: inherit; text-decoration: none">
          <span class="score" :class="j.score >= 7.5 ? 'hi' : j.score >= 6 ? 'mid' : 'lo'" style="min-width: 28px">{{ j.score == null ? '—' : j.score.toFixed(1) }}</span>
          <div><div class="main">{{ j.company }}</div><div class="sub">{{ j.title }}<span v-if="!j.has_link"> · 还没有申请链接</span></div></div>
          <span class="small nowrap" :class="deadlineLabel(j.deadline).tone ? '' : 'muted'" :style="deadlineLabel(j.deadline).tone === 'soon' ? 'color: var(--warn); font-weight: 600' : deadlineLabel(j.deadline).tone === 'past' ? 'color: var(--bad)' : ''">{{ deadlineLabel(j.deadline).text }}</span>
        </router-link>
      </div>
      <EmptyState v-if="!(ov.closing_soon || []).length" icon="clock" title="没有快截止的未投岗位" />
    </div>
  </div>

  <div class="cols">
    <div class="card">
      <div class="card-title">每周投出的申请</div>
      <p class="muted small" style="margin: 2px 0 14px">最近 12 周共 {{ weekTotal }} 个，本周 {{ thisWeek }} 个</p>
      <ColumnChart v-if="weekly.length" :data="weekly" unit=" 个" table-label="周" />
    </div>

    <div class="card">
      <div class="card-title">投出的申请现在到哪一步</div>
      <p class="muted small" style="margin: 2px 0 14px">共 {{ sentTotal }} 个；另有 {{ n('drafting', 'needs_input', 'draft_ready', 'applying', 'needs_you', 'failed') }} 个正在准备或投递中</p>
      <div class="hbars">
        <template v-for="r in pipeline" :key="r.key">
          <span class="lab">{{ r.label }}</span>
          <div class="track" :title="`${r.label}：${r.value} 个`"><div class="fill" :class="{ zero: !r.value }" :style="{ width: (r.value / pipeMax) * 100 + '%' }"></div></div>
          <span class="num">{{ r.value }}</span>
        </template>
      </div>
      <p class="hint" style="margin-top: 14px">没投的：不投递 {{ n('skipped') }} · 已下线 {{ n('offline') }} · 已截止 {{ n('expired') }}</p>
    </div>
  </div>

  <div class="cols">
    <div class="card">
      <div class="card-title">最近的邮件动态</div>
      <div class="list">
        <div v-for="(m, i) in (ov.mail_recent || []).slice(0, 5)" :key="i" class="item">
          <span class="badge" :class="{ ok: ['interview', 'assessment', 'offer'].includes(m.category) && m.event !== 'cancelled', bad: m.category === 'rejection', info: m.category === 'confirmation', warn: m.category === 'info_request' || m.event === 'cancelled' }">{{ m.label }}</span>
          <div><div class="main">{{ m.job || m.subject }}</div><div class="sub clamp2" :title="m.summary">{{ m.summary }}</div></div>
          <span class="small muted nowrap">{{ fmtTime(m.received_at) }}</span>
        </div>
      </div>
      <EmptyState v-if="!(ov.mail_recent || []).length" icon="mail" title="还没有读到相关邮件" text="在设置里连接邮箱后，确认信、面试和拒信会自动更新到岗位上。" />
    </div>

    <div class="card">
      <div class="card-title">最近投出的申请</div>
      <div class="list">
        <router-link v-for="a in (ov.recent_applications || []).slice(0, 7)" :key="a.job_id" :to="{ path: '/jobs', query: { open: a.job_id } }" class="item" style="color: inherit; text-decoration: none">
          <span class="badge" :class="a.stage_tone">{{ a.stage_label }}</span>
          <div class="main">{{ a.company }} <span class="muted" style="font-weight: 400">· {{ a.title }}</span></div>
          <span class="small muted nowrap">{{ fmtTime(a.submitted_at) }}</span>
        </router-link>
      </div>
      <EmptyState v-if="!(ov.recent_applications || []).length" icon="send" title="还没有投出申请" />
    </div>
  </div>
  </template>
</template>

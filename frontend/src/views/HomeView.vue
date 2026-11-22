<script setup>
import { t as T } from '../i18n/catalog'
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import ColumnChart from '../components/ColumnChart.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import CardHead from '../components/CardHead.vue'
import HelpPop from '../components/HelpPop.vue'
import PageHead from '../components/PageHead.vue'
import Status from '../components/Status.vue'
import DataState from '../components/DataState.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import { dataState, useRefresh } from '../data'
import { deadlineLabel } from '../dates'
import { fmtTime, run } from '../ui'
import { dayRange, shortDayOf, shortDayText } from '../i18n/format'

const router = useRouter()
const ov = inject('overview')
const reload = inject('reloadOverview')
const todos = ref([])
const drafts = ref([])

const c = computed(() => ov.value.stage_counts || {})
const n = (...keys) => keys.reduce((a, k) => a + (c.value[k] || 0), 0)
const TODO_TITLE = { takeover: T('home.signIn'), login: T('home.signIn'), captcha: T('home.completeTheCaptcha'), answer: T('home.answerQuestions'), submit: T('home.reviewAndSubmit'), failed: T('home.submissionFailed'), config: T('home.settings'), mail_unmatched: T('home.emailDidntMatchA'), driver_patch: T('home.autoFixLog'), driver: T('home.selfCheck') }
const todoText = (t) => (t.site ? `${TODO_TITLE[t.kind] || ''} ${t.site.name}` : t.title)
const pending = computed(() => drafts.value.filter((x) => x.review_status === 'pending'))

// ── the four lists, as rows of a table each: what it is, and one date
// What waits for the applicant: to-dos first, then the records that wait for approval.
const needs = computed(() => [
  ...todos.value.slice(0, 4).map((t) => ({ key: 't' + t.id, icon: 'bell', tone: 'warn', primary: todoText(t), secondary: (t.explained && t.explained.message) || '', to: '/todos', when: fmtTime(t.created_at), what: '' })),
  ...pending.value.slice(0, 4).map((d) => ({ key: 'd' + d.id, icon: 'draft', tone: 'info', primary: d.company, secondary: d.title, to: '/drafts/' + d.id, when: shortDayText(d.deadline), what: d.unresolved ? T('home.questionsNeedYourAnswer', { n: d.unresolved }, d.unresolved) : T('home.draftReadyForYour') })),
])
const NEED_COLS = [{ id: 'what', header: T('home.col.item'), min: 160, flex: 3 }, { id: 'state', header: T('home.col.state'), min: 120, max: 220, flex: 2, priority: 1 }, { id: 'when', header: T('home.col.date'), width: 128, align: 'end' }]
const CLOSING_COLS = [{ id: 'score', header: T('home.col.score'), width: 56 }, { id: 'job', header: T('home.col.posting'), min: 140 }, { id: 'deadline', header: T('home.col.deadline'), width: 128, align: 'end' }]
const MAIL_COLS = [{ id: 'kind', header: T('home.col.kind'), min: 104, max: 200, flex: 2 }, { id: 'mail', header: T('home.col.email'), min: 140, flex: 3 }, { id: 'when', header: T('home.col.received'), width: 128, align: 'end', priority: 1 }]
const RECENT_COLS = [{ id: 'stage', header: T('home.col.stage'), min: 104, max: 200, flex: 2 }, { id: 'job', header: T('home.col.posting'), min: 140, flex: 3 }, { id: 'when', header: T('home.col.applied'), width: 128, align: 'end', priority: 1 }]
const closing = computed(() => (ov.value.closing_soon || []).map((j) => ({ ...j, due: deadlineLabel(j.deadline) })))
const mails = computed(() => (ov.value.mail_recent || []).slice(0, 5).map((m, i) => ({ ...m, key: i })))
const recent = computed(() => (ov.value.recent_applications || []).slice(0, 7))
// A mail that moves the hiring on wears its kind's colour (as on the calendar); the rest is an ordinary state.
const MAIL_KIND = { interview: 'ev-interview', assessment: 'ev-assessment', offer: 'ev-offer' }
const mailTone = (m) => (m.event === 'cancelled' || m.category === 'info_request' ? 'warn' : m.category === 'rejection' ? 'bad' : m.category === 'confirmation' ? 'info' : '')
const openJob = (id) => router.push({ path: '/jobs', query: { open: id } })
const jobTo = (id) => ({ path: '/jobs', query: { open: id } })

// Where every application that was sent stands now (one series: magnitude by stage).
const pipeline = computed(() => [
  { key: 'submitted', label: T('home.appliedAwaitingConfirmation') }, { key: 'confirmed', label: T('home.receiptConfirmedByEmployer') }, { key: 'assessment', label: T('home.writtenTestOaVa') },
  { key: 'interview', label: T('home.interview') }, { key: 'offer', label: T('home.offerReceived') }, { key: 'rejected', label: T('home.rejected') },
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
const scan = () => run(() => api.post('/tasks', { kind: 'discover' }), T('home.scanningForNewPostings'), reload)
const mail = () => run(() => api.post('/tasks', { kind: 'mail' }), T('home.startCheckingEmail'), reload)
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load)
onMounted(load)
</script>

<template>
  <PageHead :title="$t('home.overview')">
    <button @click="mail"><Icon name="mail" />{{ $t('home.checkYourEmail') }}</button>
    <button @click="scan"><Icon name="refresh" />{{ $t('home.scanForNewJobs') }}</button>
  </PageHead>
  <DataState :s="st" :what="$t('home.overview')" @retry="load" />
  <template v-if="st.at">

  <!-- four figures: a number and what it counts. (The fourth used to carry two rates in its label and a paragraph under the row.) -->
  <div class="grid-4 home-stats">
    <router-link to="/todos" class="stat" :class="{ attn: ov.open_todos }"><div class="n">{{ ov.open_todos || 0 }}</div><div class="l">{{ $t('home.itemsNeedYou') }}</div></router-link>
    <router-link :to="{ path: '/applications', query: { group: 'me' } }" class="stat" :class="{ attn: ov.apps_need_me }"><div class="n">{{ ov.apps_need_me || 0 }}</div><div class="l">{{ $t('home.applicationsWaiting') }}</div></router-link>
    <router-link to="/jobs" class="stat"><div class="n">{{ n('not_applied') }}</div><div class="l">{{ $t('home.postingsNotAppliedTo') }}</div></router-link>
    <div class="stat stat-box">
      <router-link to="/applications" class="stat-link"><div class="n">{{ sent.sent }}</div></router-link>
      <div class="l">{{ $t('home.submitted') }}
        <HelpPop :label="$t('home.howSentAcknowledgedAnd')" :width="380">
          <p>{{ $t('home.sentEveryApplicationThat', { p0: sent.sent, p1: sent.heard, p2: sent.decided }) }}</p>
          <p v-if="sent.archived">{{ $t('home.thePostingsOfOf', { p0: sent.archived, p1: sent.sent - sent.archived }) }}</p>
          <i18n-t :keypath="sent.undated ? 'home.analyticsCountsUndated' : 'home.analyticsCounts'" tag="p" scope="global">
            <template #link><router-link :to="{ path: '/analytics', query: { view: 'apps' } }">{{ $t('home.analyticsOutcomes') }}</router-link></template>
            <template #dated>{{ sent.dated }}</template>
            <template #undated>{{ sent.undated }}</template>
          </i18n-t>
        </HelpPop>
      </div>
      <div class="d">{{ $t('home.rates', { heard: share(sent.heard), decided: share(sent.decided) }) }}</div>
    </div>
  </div>

  <div class="cols fit">
    <div class="card">
      <CardHead :title="$t('home.needsYourAction')">
        <router-link :to="{ path: '/runs', query: { tab: 'notes' } }" class="btn ghost sm">{{ $t('home.recentNotices') }}</router-link>
        <router-link v-if="todos.length" to="/todos" class="btn ghost sm">{{ $t('home.all') }}</router-link>
      </CardHead>
      <DataTable v-if="needs.length" class="bare" :columns="NEED_COLS" :rows="needs" row-key="key" clickable :label="$t('home.needsYourAction')" @row="(r) => router.push(r.to)">
        <template #cell-what="{ row }"><Icon :name="row.icon" class="home-ico" :class="row.tone" /><EntityCell :primary="row.primary" :secondary="row.secondary" :to="row.to" /></template>
        <template #cell-state="{ row }"><Status v-if="row.what" tone="info" :label="row.what" /><span v-else class="none">—</span></template>
        <template #cell-when="{ row }"><DateTimeCell :primary="row.when" :secondary="row.key[0] === 'd' && row.when ? $t('home.col.deadline') : ''" /></template>
      </DataTable>
      <EmptyState v-else icon="check" :title="$t('home.nothingNeedsYouRight')" :text="$t('home.newDraftsAndSign')" />
    </div>

    <div class="card">
      <CardHead :title="$t('home.postingsClosingSoon')">
        <router-link to="/jobs" class="btn ghost sm">{{ $t('home.allNotApplied') }}</router-link>
      </CardHead>
      <DataTable v-if="closing.length" class="bare" :columns="CLOSING_COLS" :rows="closing" clickable :label="$t('home.postingsClosingSoon')" @row="(j) => openJob(j.id)">
        <template #cell-score="{ row }"><span class="score num" :class="row.score >= 7.5 ? 'hi' : row.score >= 6 ? 'mid' : 'lo'">{{ row.score == null ? '—' : row.score.toFixed(1) }}</span></template>
        <template #cell-job="{ row }">
          <EntityCell :primary="row.company" :secondary="row.title" :to="jobTo(row.id)"><template v-if="!row.has_link" #after><span class="meta small">{{ $t('home.noLink') }}</span></template></EntityCell>
        </template>
        <template #cell-deadline="{ row }"><DateTimeCell :primary="shortDayText(row.deadline)" :secondary="row.due.text" :tone="row.due.tone === 'soon' ? 'warn' : row.due.tone === 'past' ? 'bad' : ''" /></template>
      </DataTable>
      <EmptyState v-else icon="clock" :title="$t('home.noUnappliedPostingsClosing')" />
    </div>
  </div>

  <div class="cols fit">
    <div class="card">
      <CardHead :title="$t('home.applicationsPerWeek')" />
      <p class="card-sub">{{ $t('home.inTheLastWeeks', { p0: weekTotal, p1: thisWeek }) }}</p>
      <ColumnChart v-if="weekly.length" :data="weekly" :unit="$t('home.items')" :table-label="$t('home.week')" />
    </div>

    <div class="card">
      <CardHead :title="$t('home.whereYourApplicationsStand')" />
      <p class="card-sub">{{ $t('home.totalMoreBeingPrepared', { p0: sentTotal, p1: n('drafting', 'needs_input', 'draft_ready', 'applying', 'needs_you', 'failed') }) }}</p>
      <div class="hbars">
        <template v-for="r in pipeline" :key="r.key">
          <span class="lab">{{ r.label }}</span>
          <div v-tip="$t('home.text', { p0: r.label, p1: r.value })" class="track"><div class="fill" :class="{ zero: !r.value }" :style="{ width: (r.value / pipeMax) * 100 + '%' }"></div></div>
          <span class="num">{{ r.value }}</span>
        </template>
      </div>
      <p class="hint home-note">{{ $t('home.notAppliedSkippedTaken', { p0: n('skipped'), p1: n('offline'), p2: n('expired') }) }}</p>
    </div>
  </div>

  <div class="cols fit">
    <div class="card">
      <CardHead :title="$t('home.recentEmailActivity')" />
      <DataTable v-if="mails.length" class="bare" :columns="MAIL_COLS" :rows="mails" row-key="key" :label="$t('home.recentEmailActivity')">
        <template #cell-kind="{ row }">
          <span v-if="MAIL_KIND[row.category] && row.event !== 'cancelled'" v-tip.overflow class="ev-kind cut" :class="MAIL_KIND[row.category]">{{ row.label }}</span>
          <Status v-else :tone="mailTone(row)" :label="row.label" />
        </template>
        <template #cell-mail="{ row }"><EntityCell :primary="row.job || row.subject" :secondary="row.summary" /></template>
        <template #cell-when="{ row }"><DateTimeCell :primary="fmtTime(row.received_at)" /></template>
      </DataTable>
      <EmptyState v-else icon="mail" :title="$t('home.noRelatedEmailsFound')" :text="$t('home.onceAMailboxIs')" />
    </div>

    <div class="card">
      <CardHead :title="$t('home.recentApplications')" />
      <DataTable v-if="recent.length" class="bare" :columns="RECENT_COLS" :rows="recent" row-key="job_id" clickable :label="$t('home.recentApplications')" @row="(a) => openJob(a.job_id)">
        <template #cell-stage="{ row }"><Status :tone="row.stage_tone" :label="row.stage_label" /></template>
        <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" :to="jobTo(row.job_id)" /></template>
        <template #cell-when="{ row }"><DateTimeCell :primary="fmtTime(row.submitted_at)" /></template>
      </DataTable>
      <EmptyState v-else icon="send" :title="$t('home.noApplicationsSentYet')" />
    </div>
  </div>
  </template>
</template>

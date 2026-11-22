<script setup>
import { t as T } from '../i18n/catalog'
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
const TODO_TITLE = { takeover: T('home.signIn'), login: T('home.signIn'), captcha: T('home.completeTheCaptcha'), answer: T('home.answerQuestions'), submit: T('home.reviewAndSubmit'), failed: T('home.submissionFailed'), config: T('home.settings'), mail_unmatched: T('home.emailDidntMatchA'), driver_patch: T('home.autoFixLog'), driver: T('home.selfCheck') }
const todoText = (t) => (t.site ? `${TODO_TITLE[t.kind] || ''} ${t.site.name}` : t.title)
const pending = computed(() => drafts.value.filter((x) => x.review_status === 'pending'))

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
  <PageHead :title="$t('home.overview')" :sub="$t('home.whatYouNeedTo')">
    <button @click="mail"><Icon name="mail" />{{ $t('home.checkYourEmail') }}</button>
    <button @click="scan"><Icon name="search" />{{ $t('home.scanForNewJobs') }}</button>
  </PageHead>
  <DataState :s="st" :what="$t('home.overview')" @retry="load" />
  <template v-if="st.at">

  <div class="grid-4" style="margin-bottom: 16px">
    <router-link to="/todos" class="stat" :class="{ attn: ov.open_todos }"><div class="n">{{ ov.open_todos || 0 }}</div><div class="l">{{ $t('home.itemsNeedYou') }}</div></router-link>
    <router-link :to="{ path: '/applications', query: { group: 'me' } }" class="stat" :class="{ attn: ov.apps_need_me }"><div class="n">{{ ov.apps_need_me || 0 }}</div><div class="l">{{ $t('home.applicationsWaiting') }}</div></router-link>
    <router-link to="/jobs" class="stat"><div class="n">{{ n('not_applied') }}</div><div class="l">{{ $t('home.postingsNotAppliedTo') }}</div></router-link>
    <router-link to="/applications" class="stat"><div class="n">{{ sent.sent }}</div><div class="l">{{ $t('home.applicationsSentAcknowledgedCame', { p0: share(sent.heard), p1: share(sent.decided) }) }}</div></router-link>
  </div>
  <Explain :label="$t('home.howSentAcknowledgedAnd')" style="margin: -8px 0 14px">
    {{ $t('home.sentEveryApplicationThat', { p0: sent.sent, p1: sent.heard, p2: sent.decided }) }}
    <template v-if="sent.archived">{{ $t('home.thePostingsOfOf', { p0: sent.archived, p1: sent.sent - sent.archived }) }}</template>
    <router-link :to="{ path: '/analytics', query: { view: 'apps' } }">{{ $t('home.analyticsOutcomes') }}</router-link>{{ $t('home.usesTheSameThree', { p0: sent.dated }) }}<template v-if="sent.undated">{{ $t('home.anotherAreKnownTo', { p0: sent.undated }) }}</template>。
  </Explain>

  <div class="cols">
    <div class="card">
      <div class="row"><span class="card-title grow">{{ $t('home.needsYourAction') }}</span><router-link :to="{ path: '/runs', query: { tab: 'notes' } }" class="small">{{ $t('home.recentNotices') }}</router-link><router-link v-if="todos.length" to="/todos" class="small">{{ $t('home.all') }}</router-link></div>
      <div class="list">
        <router-link v-for="t in todos.slice(0, 4)" :key="'t' + t.id" to="/todos" class="item" style="color: inherit; text-decoration: none">
          <Icon name="bell" style="width: 18px; height: 18px; color: var(--warn); margin-top: 2px" />
          <div><div class="main">{{ todoText(t) }}</div><div class="sub clamp2">{{ t.explained.message }}</div></div>
          <span class="small muted nowrap">{{ fmtTime(t.created_at) }}</span>
        </router-link>
        <router-link v-for="d in pending.slice(0, 4)" :key="'d' + d.id" :to="'/drafts/' + d.id" class="item" style="color: inherit; text-decoration: none">
          <Icon name="draft" style="width: 18px; height: 18px; color: var(--primary); margin-top: 2px" />
          <div><div class="main">{{ d.company }} · {{ d.title }}</div><div class="sub">{{ d.unresolved ? $t('home.questionsNeedYourAnswer', { p0: d.unresolved }) : $t('home.draftReadyForYour') }}</div></div>
          <span class="small muted nowrap">{{ $t('home.due', { p0: shortDayText(d.deadline) || '—' }) }}</span>
        </router-link>
      </div>
      <EmptyState v-if="!todos.length && !pending.length" icon="check" :title="$t('home.nothingNeedsYouRight')" :text="$t('home.newDraftsAndSign')" />
    </div>

    <div class="card">
      <div class="row"><span class="card-title grow">{{ $t('home.postingsClosingSoon') }}</span><router-link to="/jobs" class="small">{{ $t('home.allNotApplied') }}</router-link></div>
      <div class="list">
        <router-link v-for="j in ov.closing_soon || []" :key="j.id" :to="{ path: '/jobs', query: { open: j.id } }" class="item" style="color: inherit; text-decoration: none">
          <span class="score" :class="j.score >= 7.5 ? 'hi' : j.score >= 6 ? 'mid' : 'lo'" style="min-width: 28px">{{ j.score == null ? '—' : j.score.toFixed(1) }}</span>
          <div><div class="main">{{ j.company }}</div><div class="sub">{{ j.title }}<span v-if="!j.has_link"> {{ $t('home.noApplicationLinkYet') }}</span></div></div>
          <span class="small nowrap" :class="deadlineLabel(j.deadline).tone ? '' : 'muted'" :style="deadlineLabel(j.deadline).tone === 'soon' ? 'color: var(--warn); font-weight: 600' : deadlineLabel(j.deadline).tone === 'past' ? 'color: var(--bad)' : ''">{{ deadlineLabel(j.deadline).text }}</span>
        </router-link>
      </div>
      <EmptyState v-if="!(ov.closing_soon || []).length" icon="clock" :title="$t('home.noUnappliedPostingsClosing')" />
    </div>
  </div>

  <div class="cols">
    <div class="card">
      <div class="card-title">{{ $t('home.applicationsPerWeek') }}</div>
      <p class="muted small" style="margin: 2px 0 14px">{{ $t('home.inTheLastWeeks', { p0: weekTotal, p1: thisWeek }) }}</p>
      <ColumnChart v-if="weekly.length" :data="weekly" :unit="$t('home.items')" :table-label="$t('home.week')" />
    </div>

    <div class="card">
      <div class="card-title">{{ $t('home.whereYourApplicationsStand') }}</div>
      <p class="muted small" style="margin: 2px 0 14px">{{ $t('home.totalMoreBeingPrepared', { p0: sentTotal, p1: n('drafting', 'needs_input', 'draft_ready', 'applying', 'needs_you', 'failed') }) }}</p>
      <div class="hbars">
        <template v-for="r in pipeline" :key="r.key">
          <span class="lab">{{ r.label }}</span>
          <div class="track" :title="$t('home.text', { p0: r.label, p1: r.value })"><div class="fill" :class="{ zero: !r.value }" :style="{ width: (r.value / pipeMax) * 100 + '%' }"></div></div>
          <span class="num">{{ r.value }}</span>
        </template>
      </div>
      <p class="hint" style="margin-top: 14px">{{ $t('home.notAppliedSkippedTaken', { p0: n('skipped'), p1: n('offline'), p2: n('expired') }) }}</p>
    </div>
  </div>

  <div class="cols">
    <div class="card">
      <div class="card-title">{{ $t('home.recentEmailActivity') }}</div>
      <div class="list">
        <div v-for="(m, i) in (ov.mail_recent || []).slice(0, 5)" :key="i" class="item">
          <span class="badge" :class="{ ok: ['interview', 'assessment', 'offer'].includes(m.category) && m.event !== 'cancelled', bad: m.category === 'rejection', info: m.category === 'confirmation', warn: m.category === 'info_request' || m.event === 'cancelled' }">{{ m.label }}</span>
          <div><div class="main">{{ m.job || m.subject }}</div><div class="sub clamp2" :title="m.summary">{{ m.summary }}</div></div>
          <span class="small muted nowrap">{{ fmtTime(m.received_at) }}</span>
        </div>
      </div>
      <EmptyState v-if="!(ov.mail_recent || []).length" icon="mail" :title="$t('home.noRelatedEmailsFound')" :text="$t('home.onceAMailboxIs')" />
    </div>

    <div class="card">
      <div class="card-title">{{ $t('home.recentApplications') }}</div>
      <div class="list">
        <router-link v-for="a in (ov.recent_applications || []).slice(0, 7)" :key="a.job_id" :to="{ path: '/jobs', query: { open: a.job_id } }" class="item" style="color: inherit; text-decoration: none">
          <span class="badge" :class="a.stage_tone">{{ a.stage_label }}</span>
          <div class="main">{{ a.company }} <span class="muted" style="font-weight: 400">· {{ a.title }}</span></div>
          <span class="small muted nowrap">{{ fmtTime(a.submitted_at) }}</span>
        </router-link>
      </div>
      <EmptyState v-if="!(ov.recent_applications || []).length" icon="send" :title="$t('home.noApplicationsSentYet')" />
    </div>
  </div>
  </template>
</template>

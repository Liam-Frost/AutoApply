<script setup>
import { t as T } from '../i18n/catalog'
import { computed, inject, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run as runAction, toast } from '../ui'
import { t } from '../i18n/catalog'
import { dateOf, dateTimeOf, dayText } from '../i18n/format'

const todos = ref([])
const saveCred = ref(true)
const picked = ref({})      // to-do id -> the application chosen for an e-mail that names no posting
const reloadOverview = inject('reloadOverview', () => {})

// How each kind of to-do is presented: icon, tone, the title and the one-line explanation.
const VIEW = {
  takeover: { icon: 'login', tone: '', title: (t) => (t.payload && t.payload.provider ? T('todos.title.reLogin', { provider: t.payload.provider }) : T('todos.title.login', { site: t.site ? t.site.name : t.title })),
              what: (t) => (t.payload && t.payload.provider
                ? (t.payload.for
                  ? T('todos.what.expiredWhile', { for: t.payload.for, provider: t.payload.provider })
                  : T('todos.what.expired', { provider: t.payload.provider }))
                : t.explained.message || T('todos.thisSiteNeedsYou')) },
  login: { icon: 'login', tone: '', title: (t) => T('todos.title.login', { site: t.site ? t.site.name : t.title }), what: (t) => t.explained.message },
  captcha: { icon: 'shield', tone: '', title: (t) => T('todos.title.captcha', { title: t.title }), what: () => T('todos.theSiteWantsTo') },
  answer: { icon: 'edit', tone: 'info', title: (t) => t.title, what: (t) => t.body || T('todos.theDraftHasRequired') },
  submit: {
    icon: 'send',
    tone: 'info',
    title: (t) => t.title,
    // (a submission whose outcome is not known says so in its own words, not "look it over and press submit")
    what: (t) => (t.application && t.application.status === 'submit_unknown' ? t.explained.message
      : T('todos.theAgentHasFilled')),
  },
  failed: { icon: 'alert', tone: 'bad', title: (t) => t.title, what: (t) => t.explained.message },
  config: { icon: 'settings', tone: '', title: (t) => t.title, what: (t) => t.explained.message },
  mail_unmatched: { icon: 'mail', tone: 'info', title: () => T('todos.anEmailDidntMatch'), what: (t) => `「${t.title}」${t.body ? ' — ' + t.body : ''}` },
  // something with a date of its own: an interview, an assessment to finish, an offer to answer, a contact to get back to
  followup: { icon: 'bell', tone: 'info', title: (t) => t.title, what: (t) => t.body || '' },
  // the applicant's own item with a date (added on the calendar page)
  note: { icon: 'clock', tone: 'info', title: (t) => t.title, what: (t) => t.body || '' },
}
// The agent is waiting, in the site's own page, for something only the applicant has: these are answered here.
VIEW.code = { icon: 'login', tone: 'warn', title: (t) => t.title, what: (t) => t.body || '' }
VIEW.confirm = { icon: 'login', tone: 'warn', title: (t) => t.title, what: (t) => t.body || '' }
// ... and when it waited and the applicant was not there: said again, and taken up at once when they are
VIEW.resume = { icon: 'login', tone: 'warn', title: (t) => (RESUME[t.payload.need] || RESUME.confirm)[0](t), what: (t) => t.body || '' }
const RESUME = {
  code: [(t) => T('todos.title.code', { title: t.title }), T('todos.imHereNowSend'), T('todos.theAgentWaitedMinutes')],
  confirm: [(t) => T('todos.title.confirm', { title: t.title }), T('todos.imHereNowGo'), T('todos.theAgentWaitedMinutes2')],
  window: [(t) => T('todos.title.window', { title: t.title }), T('todos.openTheWindowIll'), T('todos.thisStepIsYours')],
}
// the employer took the posting down: nothing to do - unless the applicant knows better
// a mail the program wrote for the applicant, waiting to be looked at and sent from their mailbox
// the profile changed and prepared applications still say the old thing: they are stopped until the applicant decides
VIEW.facts_changed = { icon: 'edit', tone: 'warn', title: (t) => t.title, what: () => '' }
VIEW.mail_out = { icon: 'mail', tone: 'info', title: (t) => t.title, what: (t) => t.body || '' }
VIEW.gone = { icon: 'bell', tone: '', title: (t) => t.title, what: (t) => t.body || '' }
VIEW.blocked = { icon: 'alert', tone: 'bad', title: (t) => T('todos.title.blocked', { title: t.title }),
  what: () => T('todos.theApplicationPageWont') }

// Sorting and filtering. Urgency comes from the server: 0 a window is waiting for you now, 1 the deadline is within 3 days, 2 when you can, 3 just so you know.
const CATS = [['all', T('todos.all')], ['dated', T('todos.withADate')], ['login', T('todos.signInOrVerify')], ['answer', T('todos.needsAnswers')], ['submit', T('todos.readyToSubmit')], ['problem', T('todos.somethingWentWrong')], ['info', T('todos.notifyOnly')]]
const URGENCY = [T('todos.handleNow'), T('todos.closingSoon'), T('todos.whenYouHaveTime'), T('todos.justANoticeNothing')]
const SORTS = { urgency: T('todos.byPriority'), newest: T('todos.newestFirst'), deadline: T('todos.byDeadline'), score: T('todos.byScore') }
const cat = ref('all')
const sort = ref(localStorage.getItem('todos.sort') || 'urgency')
const q = ref('')
// What the applicant put off until later is out of the way until then - and can be looked at, and brought back, below.
const active = computed(() => todos.value.filter((t) => !t.snoozed_until))
const later = computed(() => todos.value.filter((t) => t.snoozed_until).sort((a, b) => (a.snoozed_until < b.snoozed_until ? -1 : 1)))
const showLater = ref(false)
const count = (c) => active.value.filter((t) => c === 'all' || t.category === c).length
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  const rows = active.value.filter((t) => (cat.value === 'all' || t.category === cat.value)
    && (!needle || `${t.title} ${t.body} ${t.job ? t.job.company + ' ' + t.job.title : ''} ${t.site ? t.site.name : ''}`.toLowerCase().includes(needle)))
  const big = 1e9
  const key = { urgency: (t) => [t.urgency, t.days_left ?? big, -(t.job?.score ?? 0), -t.id], newest: (t) => [-t.id], deadline: (t) => [t.days_left ?? big, t.urgency, -t.id],
    score: (t) => [-(t.job?.score ?? -1), t.urgency, -t.id] }[sort.value]
  return rows.sort((a, b) => { const x = key(a), y = key(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0 })
})
// with the default order the list is cut into sections, so "what first" is visible without reading every card
const sections = computed(() => {
  if (sort.value !== 'urgency') return [{ label: '', rows: shown.value }]
  return URGENCY.map((label, u) => ({ label, u, rows: shown.value.filter((t) => t.urgency === u) })).filter((x) => x.rows.length)
})
const setSort = (v) => { sort.value = v; try { localStorage.setItem('todos.sort', v) } catch { /* ignore */ } }
const infoIds = computed(() => shown.value.filter((t) => t.category === 'info').map((t) => t.id))
const left = (c) => (c.days_left == null ? '' : c.days_left < 0 ? t('todos.deadline.past') : c.days_left === 0 ? t('todos.deadline.today') : t('todos.deadline.left', { n: c.days_left }, c.days_left))
// a card's own date, in words: the day (and the time, when the mail gave one)
// (a due time is the applicant's local time, written without a zone)
const dueText = (c) => (c.due_at ? (c.date_only ? dateOf(new Date(c.due_at.slice(0, 10) + 'T00:00')) : dateTimeOf(new Date(c.due_at.slice(0, 16)))) : '')
// how far away it is, next to the date: "today", "3 days left"
const dueLeft = (c) => (c.days_left == null ? '' : c.days_left < 0 ? t('todos.due.past') : c.days_left === 0 ? t('todos.due.today') : t('todos.deadline.left', { n: c.days_left }, c.days_left))
const dueTone = (t) => (t.days_left == null ? '' : t.days_left < 0 ? 'bad' : t.days_left <= 1 ? 'warn' : '')
// "show me this again": tomorrow morning, in three days, next Monday - or a day of the applicant's choosing
const menu = ref(0)          // the card whose "later" choices are open
const day = ref('')
function at9(d) { d.setHours(9, 0, 0, 0); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T09:00` }
function inDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return at9(d) }
function nextMonday() { const d = new Date(); d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); return at9(d) }
const snooze = (t, until) => { menu.value = 0; return act(() => api.post(`/todos/${t.id}/snooze`, { until }), until ? T('todos.snoozedTo', { day: dayText(until) }) : T('todos.backAmongTheTo')) }
const snoozeDay = (t) => (day.value ? snooze(t, day.value + 'T09:00') : null)
const dueEdit = ref({ id: 0, value: '' })
const openDue = (t) => { dueEdit.value = { id: t.id, value: t.due_at ? t.due_at.slice(0, 16) : '' } }
const saveDue = (t) => act(async () => { await api.post(`/todos/${t.id}/due`, { due: dueEdit.value.value || null }); dueEdit.value = { id: 0, value: '' } }, T('todos.theDateIsUpdated'))
const scoreCls = (x) => (x == null ? '' : x >= 9 ? 'hi' : x >= 7.5 ? 'mid' : '')

// a card that says something is not set up (or no longer works): where that is put right
const FIX = {
  'config:gmail': ['/settings/accounts/mailbox', T('todos.openTheMailboxSettings')], 'config:resume': ['/files', T('todos.openTheLibrary')], 'config:pdportal-blocked': ['/settings/system/browser', T('todos.openTheBrowserCompatibility')],
  'config:llm-limit': ['/settings/accounts/ai', T('todos.seeTheAiServices')], 'config:llm': ['/settings/accounts/ai', T('todos.openTheAiService')],
  'config:profile': ['/profile?tab=init', T('todos.generateOrFillIn')],
}
const view = (t) => VIEW[t.kind] || { icon: 'bell', tone: '', title: (x) => x.title, what: (x) => x.explained.message }

async function read() { todos.value = await api.get('/todos'); reloadOverview() }
const act = (fn, ok) => runAction(fn, ok, load)
const takeover = (t) => act(() => api.post('/accounts/takeover', { tenant_key: t.payload.tenant_key, url: t.payload.url, job_url: t.payload.job_url, save_credentials: !!t.remembers && saveCred.value }),
  T('todos.aBrowserWindowIs'))
const done = (t) => act(() => api.post(`/todos/${t.id}/done`, {}), T('todos.resumed'))
const codes = ref({})        // what is being typed into each code card
const giveCode = (t) => act(async () => {
  const r = await api.post(`/todos/${t.id}/code`, { code: codes.value[t.id] })
  delete codes.value[t.id]
  if (!r.given) throw new Error(T('todos.theAgentIsNo'))
}, T('todos.givenToTheAgent'))
const factPick = ref({})      // to-do id -> the applications ticked on a "profile changed" card
const factsLeft = (t) => (t.payload.applications || []).filter((r) => !(t.payload.decided || []).includes(r.application_id))
const factsPicked = (t) => factsLeft(t).filter((r) => (factPick.value[t.id] || {})[r.application_id] !== false).map((r) => r.application_id)
const factsDecide = (t, action) => act(() => api.post(`/facts/${t.id}`, { action, application_ids: factsPicked(t) }), action === 'redo' ? T('todos.queuedTheAgentChanges') : T('todos.allRightSentAs'))
const sentTitles = (t) => (t.payload.sent || []).map((r) => r.title).join(', ')
const factTick = (t, id, on) => { factPick.value = { ...factPick.value, [t.id]: { ...(factPick.value[t.id] || {}), [id]: on } } }
const writeReply = (t) => act(() => api.post(`/todos/${t.id}/reply`), T('todos.theReplyIsBeing'))
const confirmed = (t) => act(() => api.post(`/todos/${t.id}/done`, {}), T('todos.theAgentIsGoing'))
const resumeNow = (t) => act(() => api.post(`/todos/${t.id}/done`, {}), T('todos.theAgentStartsNow'))
// (a card that work is waiting for is not closed by "not now": the server puts it off until tomorrow, and says so)
const dismiss = (t) => act(async () => { const r = await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }); if (r && r.snoozed_until) toast(T('todos.anApplicationIsWaiting')) }, T('todos.allRight'))
// "not applying after all" on a card about an application that did not get done: the posting is marked so, and the application put away
const notApplying = (t) => act(async () => { await api.patch(`/jobs/${t.job.id}`, { status: 'skipped' }); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }, T('todos.markedAsNotApplying'))
// What a card about an application offers follows from where the application stands, not from the card.
// Submit was pressed and the outcome is not known: filling it in again would be a second application if the first went through.
const unknown = (t) => !!(t.application && t.application.status === 'submit_unknown')
const checkMail = (t) => act(() => api.post(`/applications/${t.application.id}/check-mail`), T('todos.lookingInTheMailbox'))
async function againNotSubmitted(t) {
  if (!(await ask(T('todos.areYouSureThis'), { ok: T('todos.itWasNotSubmitted2') }))) return
  await act(async () => { await api.post(`/applications/${t.application.id}/not-submitted`); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }, T('todos.theAgentHasStarted'))
}
const linkMail = (t) => act(() => api.post(`/todos/${t.id}/link`, { application_id: picked.value[t.id] }), T('todos.linkedTheApplicationsStatus'))
const ackAll = () => act(() => api.post('/todos/bulk', { ids: infoIds.value }), T('todos.closedNotes', { n: infoIds.value.length }, infoIds.value.length))
const moreBudget = (t) => act(() => api.post(`/applications/${t.application.id}/budget?request_id=todo-${t.id}`), T('todos.anotherBudgetIsGiven'))
const tryAgainFor = async (t, backend) => { await api.post(`/jobs/${t.job.id}/draft`, backend ? { browser_backend: backend } : {}); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }
const tryAgain = (t) => act(() => tryAgainFor(t), T('todos.theAgentHasStarted'))
const appliedMyself = (t) => act(() => api.post(`/jobs/${t.payload.job_id}/mark-submitted`), T('todos.markedAsAppliedWell'))
const skipJob = (t) => act(async () => { await api.patch(`/jobs/${t.payload.job_id}`, { status: 'skipped' }); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }) }, T('todos.markedAsNotApplying'))
const markSubmitted = (t) => act(() => api.post(`/applications/${(t.application && t.application.id) || t.payload.application_id}/mark-submitted`), T('todos.markedAsAppliedWell'))
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(() => { loadRang(); return load() }, { every: 15000 })
// the reminders that went off in the last hours (the calendar's, alarms.py): what is about to happen, at the top
const rang = ref([])
const loadRang = () => api.get('/calendar/alarms/recent').then((r) => (rang.value = r)).catch(() => {})
onMounted(() => { load(); loadRang() })
</script>

<template>
  <PageHead :title="$t('todos.needsYou')" :sub="$t('todos.thingsTheAppCant')" />
  <div v-if="rang.length" class="callout" style="margin-bottom: 12px">
    <Icon name="clock" />
    <div class="grow">
      <b>{{ $t('calendar.rang.title') }}</b>
      <div v-for="x in rang" :key="x.id" class="row small" style="gap: 8px; margin-top: 4px; flex-wrap: wrap">
        <span>{{ x.subject || x.title }}<template v-if="x.subject"> · {{ x.title }}</template></span>
        <span class="muted">{{ x.all_day ? dayText(x.start) : dateTimeOf(new Date(x.start)) }}</span>
        <a v-if="x.link" :href="x.link" target="_blank" rel="noopener" class="btn sm primary"><Icon name="external" />{{ $t('calendar.open') }}</a>
        <router-link :to="{ path: '/calendar', query: { view: 'day', date: x.start.slice(0, 10) } }" class="btn sm ghost">{{ $t('calendar.rang.openDay') }}</router-link>
      </div>
    </div>
  </div>
  <DataState :s="st" :what="$t('todos.toDo')" @retry="load" />
  <template v-if="st.at">

  <template v-if="todos.length">
    <div class="seg" style="margin-bottom: 12px">
      <button v-for="[k, l] in CATS" :key="k" :class="{ on: cat === k }" :disabled="k !== 'all' && !count(k)" @click="cat = k">{{ l }}<span class="n">{{ count(k) }}</span></button>
    </div>
    <div class="filters">
      <input v-model="q" :placeholder="$t('todos.searchCompaniesPostingsOr')" style="width: 240px" />
      <AaSelect :model-value="sort" :aria-label="$t('todos.sortBy')" @update:model-value="setSort"><option v-for="(l, k) in SORTS" :key="k" :value="k">{{ l }}</option></AaSelect>
      <span class="grow"></span>
      <button v-if="infoIds.length > 1" class="sm" @click="ackAll"><Icon name="check" />{{ $t('todos.allRead', { n: infoIds.length }, infoIds.length) }}</button>
      <span class="muted small nowrap">{{ $t('todos.count', { n: shown.length }, shown.length) }}</span>
    </div>
  </template>

  <template v-for="sec in sections" :key="sec.label">
  <div v-if="sec.label" class="todo-sec" :class="'u' + sec.u">{{ sec.label }}<span>{{ sec.rows.length }}</span></div>
  <div v-for="t in sec.rows" :key="t.id" class="card todo" :class="'u' + t.urgency">
    <div class="ico" :class="view(t).tone"><Icon :name="view(t).icon" /></div>
    <div>
      <div class="head">
        <span class="title grow">{{ view(t).title(t) }}</span>
        <span v-if="t.due_at" class="tag" :class="dueTone(t)" :title="t.payload && t.payload.due_text ? $t('todos.inTheMail', { text: t.payload.due_text }) : ''">{{ dueText(t) }}<template v-if="dueLeft(t)"> · {{ dueLeft(t) }}</template></span>
        <span v-if="t.site && t.site.system" class="badge">{{ t.site.system }}</span>
        <span class="small muted">{{ fmtTime(t.created_at) }}</span>
      </div>
      <router-link v-if="t.job" :to="{ path: '/jobs', query: { open: t.job.id } }" class="todo-job">
        <span v-if="t.job.score != null" class="score" :class="scoreCls(t.job.score)">{{ t.job.score.toFixed(1) }}</span>
        <span class="ell">{{ t.job.company }} · {{ t.job.title }}</span>
        <span v-if="left(t)" class="tag" :class="t.days_left <= 3 ? 'warn' : ''">{{ left(t) }}</span>
      </router-link>
      <p class="what" style="white-space: pre-line">{{ view(t).what(t) }}</p>
      <p v-if="t.kind === 'mail_unmatched' && t.payload && t.payload.site && t.payload.site.length" class="callout"><Icon name="info" /><span>{{ $t('todos.siteCouldNotTell', { shown: t.payload.site.join('; ') }) }}</span></p>
      <p v-else-if="t.kind === 'mail_unmatched' && t.candidates && !t.candidates_near" class="small muted">{{ $t('todos.theSendingEmployerWas') }}</p>
      <p v-if="t.payload && t.payload.trying" class="callout"><Icon name="clock" /><span>{{ $t('todos.theSignInWindow') }}</span></p>
      <p v-else-if="t.payload && t.payload.last_try" class="callout warn"><Icon name="alert" /><span>{{ $t('todos.lastTryFailed', { why: t.payload.last_try }) }}</span></p>

      <div class="acts">
        <template v-if="['takeover', 'login'].includes(t.kind) && t.payload && t.payload.tenant_key">
          <button class="primary" @click="takeover(t)"><Icon name="login" />{{ t.payload.provider ? $t('todos.signInTo', { provider: t.payload.provider }) : $t('todos.signIn') }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.notNow') }}</button>
          <label v-if="t.remembers" class="small muted" style="margin-left: 8px"><input v-model="saveCred" type="checkbox" /> {{ $t('todos.rememberMyPasswordAnd') }}</label>
          <span v-else-if="t.payload.tenant_key.startsWith('idp:')" class="small muted" style="margin-left: 8px">{{ $t('todos.onlyTheSignIn') }}</span>
          <span v-else class="small muted" style="margin-left: 8px">{{ $t('todos.inThisSignIn') }}</span>
        </template>
        <template v-else-if="t.kind === 'code'">
          <input v-model="codes[t.id]" :placeholder="$t('todos.enterTheCodeHere')" inputmode="numeric" autocomplete="one-time-code" style="width: 180px" @keyup.enter="codes[t.id] && giveCode(t)" />
          <button class="primary" :disabled="!codes[t.id]" @click="giveCode(t)"><Icon name="check" />{{ $t('todos.giveItToThe') }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.iCantRightNow') }}</button>
          <span class="small muted" style="margin-left: 8px">{{ $t('todos.theAgentIsWaiting') }}</span>
        </template>
        <template v-else-if="t.kind === 'confirm'">
          <button class="primary" @click="confirmed(t)"><Icon name="check" />{{ $t('todos.doneGoOn') }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.iCantRightNow') }}</button>
          <span v-if="t.payload && t.payload.window" class="small muted" style="margin-left: 8px">{{ $t('todos.theBrowserWindowIs') }}</span>
          <span v-else class="small muted" style="margin-left: 8px">{{ $t('todos.onceYouHaveDone') }}</span>
        </template>
        <template v-else-if="t.kind === 'resume'">
          <button class="primary" @click="resumeNow(t)"><Icon name="refresh" />{{ (RESUME[t.payload.need] || RESUME.confirm)[1] }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.notNow') }}</button>
          <span class="small muted" style="margin-left: 8px">{{ (RESUME[t.payload.need] || RESUME.confirm)[2] }}</span>
        </template>
        <template v-else-if="t.kind === 'facts_changed'">
          <div style="width: 100%">
            <div class="small" style="margin-bottom: 8px">
              <div v-for="(c, i) in t.payload.changes || []" :key="i"><span class="muted">{{ c.key || $t('todos.thisLine') }}: </span><s class="muted">{{ c.old }}</s> → <b>{{ c.new || $t('todos.removed') }}</b></div>
            </div>
            <div v-for="r in factsLeft(t)" :key="r.application_id" style="margin-bottom: 8px">
              <label class="row" style="gap: 6px"><input type="checkbox" :checked="(factPick[t.id] || {})[r.application_id] !== false" @change="factTick(t, r.application_id, $event.target.checked)" />
                <router-link :to="'/applications/' + r.application_id">{{ r.title }}</router-link>
                <span v-if="r.told_while_working" class="tag">{{ $t('todos.beingWorkedItHas') }}</span></label>
              <ul class="small muted" style="margin: 2px 0 0 22px"><li v-for="(a, j) in r.answers" :key="j">{{ a.label }}：{{ a.value }}</li></ul>
            </div>
            <p v-if="(t.payload.sent || []).length" class="small muted">{{ $t('todos.sentUsedOld', { n: t.payload.sent.length, titles: sentTitles(t) }, t.payload.sent.length) }}</p>
            <div class="row" style="margin-top: 6px">
              <button class="primary" :disabled="!factsPicked(t).length" @click="factsDecide(t, 'redo')"><Icon name="refresh" />{{ $t('todos.prepareTheTickedOnes') }}</button>
              <button :disabled="!factsPicked(t).length" @click="factsDecide(t, 'keep')">{{ $t('todos.sendTheTickedOnes') }}</button>
            </div>
          </div>
        </template>
        <template v-else-if="t.kind === 'mail_out'">
          <router-link :to="'/mail/' + t.payload.outgoing_id" class="btn primary"><Icon name="mail" />{{ $t('todos.lookAtItAnd') }}</router-link>
          <router-link v-if="t.payload.application_id" :to="'/applications/' + t.payload.application_id" class="btn">{{ $t('todos.openThisApplication') }}</router-link>
        </template>
        <template v-else-if="t.kind === 'gone'">
          <button class="primary" @click="dismiss(t)"><Icon name="check" />{{ $t('todos.gotIt') }}</button>
          <a v-if="t.job && t.job.url" :href="t.job.url" target="_blank" rel="noopener noreferrer" class="btn"><Icon name="external" />{{ $t('todos.openThePostingsPage') }}</a>
          <button v-if="t.job" @click="tryAgain(t)"><Icon name="refresh" />{{ $t('todos.itIsStillThere') }}</button>
          <router-link v-if="t.application" :to="'/applications/' + t.application.id" class="btn">{{ $t('todos.openThisApplication') }}</router-link>
        </template>
        <template v-else-if="t.kind === 'blocked'">
          <a v-if="t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />{{ $t('todos.openThePostingAnd') }}</a>
          <button @click="appliedMyself(t)"><Icon name="check" />{{ $t('todos.iveSubmittedIt') }}</button>
          <button @click="done(t)"><Icon name="refresh" />{{ $t('todos.letTheAppTry') }}</button>
          <button class="ghost" @click="skipJob(t)">{{ $t('todos.skipThisOne') }}</button>
        </template>
        <template v-else-if="t.kind === 'answer'">
          <router-link v-if="t.payload && t.payload.draft_id" :to="'/drafts/' + t.payload.draft_id" class="btn primary"><Icon name="edit" /><span v-if="t.payload.review">{{ $t('todos.viewTheApplicationsMaterials') }}</span><span v-else>{{ $t('todos.answer') }}</span></router-link>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.close') }}</button>
        </template>
        <template v-else-if="t.kind === 'followup' || t.kind === 'note'">
          <a v-if="t.payload && t.payload.link" :href="t.payload.link" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />{{ $t('calendar.open') }}</a>
          <router-link v-if="t.payload && t.payload.outgoing_id" :to="'/mail/' + t.payload.outgoing_id" class="btn primary"><Icon name="mail" />{{ $t('todos.lookAtTheReply') }}</router-link>
          <button v-else-if="t.payload && t.payload.category === 'info_request' && t.payload.message_id" @click="writeReply(t)"><Icon name="edit" />{{ $t('todos.writeAReply') }}</button>
          <button :class="{ primary: !(t.payload && t.payload.outgoing_id) }" @click="done(t)"><Icon name="check" />{{ $t('todos.done') }}</button>
          <button @click="openDue(t)"><Icon name="edit" />{{ t.due_at ? $t('calendar.move') : $t('todos.addDate') }}</button>
          <router-link v-if="t.payload && t.payload.application_id" :to="'/applications/' + t.payload.application_id" class="btn">{{ $t('todos.openThisApplicationAnd') }}</router-link>
          <router-link v-else-if="t.payload && t.payload.contact_id" to="/contacts" class="btn">{{ $t('todos.openContacts') }}</router-link>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.leaveItClose') }}</button>
        </template>
        <template v-else-if="['failed', 'submit'].includes(t.kind) && t.application && t.job">
          <template v-if="unknown(t)">
            <button class="primary" @click="checkMail(t)"><Icon name="mail" />{{ $t('todos.lookForTheConfirmation') }}</button>
            <button @click="markSubmitted(t)"><Icon name="check" />{{ $t('todos.iveSubmittedIt') }}</button>
            <button class="ghost" @click="againNotSubmitted(t)">{{ $t('todos.itWasNotSubmitted') }}</button>
          </template>
          <button v-else-if="t.kind === 'submit'" class="primary" @click="markSubmitted(t)"><Icon name="check" />{{ $t('todos.iveSubmittedIt') }}</button>
          <button v-else-if="t.payload.budget" class="primary" @click="moreBudget(t)"><Icon name="refresh" />{{ $t('todos.giveItAnotherBudget') }}</button>
          <button v-else class="primary" @click="tryAgain(t)"><Icon name="refresh" />{{ $t('todos.haveTheAgentTry') }}</button>
          <button v-if="t.can_retry_nodriver" @click="act(() => tryAgainFor(t, 'nodriver'), $t('todos.restarted'))">{{ $t('todos.tryAgainWithNodriver') }}</button>
          <router-link :to="'/applications/' + t.application.id" class="btn">{{ $t('todos.openThisApplication') }}</router-link>
          <router-link v-if="t.payload.draft_id" :to="'/drafts/' + t.payload.draft_id" class="btn">{{ $t('todos.viewDraft') }}</router-link>
          <button v-if="!unknown(t)" class="ghost" @click="notApplying(t)">{{ $t('todos.dontApplyClose') }}</button>
        </template>
        <template v-else-if="t.kind === 'captcha'">
          <a v-if="t.payload && t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />{{ $t('todos.openPage') }}</a>
          <button @click="done(t)">{{ $t('todos.imDoneContinue') }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.close') }}</button>
        </template>
        <template v-else-if="t.kind === 'mail_unmatched'">
          <AaSelect v-model="picked[t.id]" :placeholder="$t('todos.whichApplicationIsThis')" style="max-width: 460px">
            <option v-for="c in t.candidates || []" :key="c.id" :value="c.id">{{ c.label }}{{ c.site_status ? $t('todos.onTheSite', { status: c.site_status }) : '' }}</option>
          </AaSelect>
          <button class="primary" :disabled="!picked[t.id]" @click="linkMail(t)"><Icon name="check" />{{ $t('todos.linkToThisApplication') }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.notAboutAnApplication') }}</button>
        </template>
        <template v-else-if="t.kind === 'config' && FIX[t.ref]">
          <router-link :to="FIX[t.ref][0]" class="btn primary"><Icon name="settings" />{{ FIX[t.ref][1] }}</router-link>
          <button @click="done(t)">{{ $t('todos.itIsTakenCare') }}</button>
        </template>
        <template v-else>
          <a v-if="t.payload && t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn"><Icon name="external" />{{ $t('todos.openPage') }}</a>
          <router-link v-if="t.payload && t.payload.draft_id" :to="'/drafts/' + t.payload.draft_id" class="btn">{{ $t('todos.viewDraft') }}</router-link>
          <button @click="done(t)">{{ $t('todos.doneContinue') }}</button>
          <button class="ghost" @click="dismiss(t)">{{ $t('todos.close') }}</button>
        </template>
      </div>
      <div v-if="dueEdit.id === t.id" class="row" style="margin-top: 8px; flex-wrap: wrap">
        <label :for="'due-' + t.id" class="small muted">{{ $t('todos.whenThisIsFor') }}</label>
        <input :id="'due-' + t.id" v-model="dueEdit.value" type="datetime-local" style="width: 220px" />
        <button class="sm primary" @click="saveDue(t)">{{ $t('todos.save') }}</button>
        <button v-if="t.due_at" class="sm ghost" @click="dueEdit.value = ''; saveDue(t)">{{ $t('todos.removeTheDate') }}</button>
        <button class="sm ghost" @click="dueEdit = { id: 0, value: '' }">{{ $t('todos.cancel') }}</button>
      </div>
      <!-- "not now": out of the way until a day of the applicant's choosing, then shown and said again -->
      <div class="row" style="margin-top: 8px; flex-wrap: wrap">
        <button v-if="menu !== t.id" class="sm ghost" @click="menu = t.id; day = ''"><Icon name="clock" />{{ $t('todos.remindMeLater') }}</button>
        <template v-else>
          <span class="small muted">{{ $t('todos.remindMeAgain') }}</span>
          <button class="sm" @click="snooze(t, inDays(1))">{{ $t('todos.tomorrow') }}</button>
          <button class="sm" @click="snooze(t, inDays(3))">{{ $t('todos.inDays') }}</button>
          <button class="sm" @click="snooze(t, nextMonday())">{{ $t('todos.nextMonday') }}</button>
          <input v-model="day" type="date" :aria-label="$t('todos.chooseADay')" style="width: 150px" />
          <button class="sm" :disabled="!day" @click="snoozeDay(t)">{{ $t('todos.onThisDay') }}</button>
          <button class="sm ghost" @click="menu = 0">{{ $t('todos.cancel') }}</button>
        </template>
      </div>
      <TechDetails :text="t.explained.detail" />
    </div>
  </div>
  </template>

  <div v-if="later.length" class="card">
    <button class="ghost" @click="showLater = !showLater">{{ $t('todos.later', { n: later.length }) }} {{ showLater ? $t('todos.hide') : $t('todos.show') }}</button>
    <div v-if="showLater" class="list" style="margin-top: 8px">
      <div v-for="t in later" :key="t.id" class="item">
        <span class="badge" style="min-width: 96px; justify-content: center">{{ dayText(t.snoozed_until) }}</span>
        <div><div class="main">{{ view(t).title(t) }}</div><div v-if="t.due_at" class="sub">{{ $t('todos.when', { when: dueText(t) }) }}</div></div>
        <div class="right"><button class="sm" @click="snooze(t, null)">{{ $t('todos.showItNow') }}</button></div>
      </div>
    </div>
  </div>
  <div v-if="active.length && !shown.length" class="card"><EmptyState icon="search" :title="$t('todos.noMatchingToDos')" :text="$t('todos.tryAnotherCategoryOr')" /></div>

  <div v-if="!active.length" class="card"><EmptyState icon="check" :title="$t('todos.nothingNeedsYouRight')" :text="$t('todos.requestsToSignIn')" /></div>
  </template>
</template>

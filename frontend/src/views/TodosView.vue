<script setup>
import { t as T } from '../i18n/catalog'
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import HelpPop from '../components/HelpPop.vue'
import Icon from '../components/Icon.vue'
import IconButton from '../components/IconButton.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import Tabs from '../components/Tabs.vue'
import Popover from '../components/Popover.vue'
import Trunc from '../components/Trunc.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run as runAction, toast } from '../ui'
import { t } from '../i18n/catalog'
import { dateOf, dateTimeOf, dayText, listed } from '../i18n/format'

const router = useRouter()
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
  mail_unmatched: { icon: 'mail', tone: 'info', title: () => T('todos.anEmailDidntMatch'), what: (t) => (t.body ? T('todos.what.mail', { subject: t.title, body: t.body }) : T('todos.what.mailOnly', { subject: t.title })) },
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
// (only what is late or about to be stands out: the rest is a plain date)
const dueTone = (t) => (t.days_left == null ? '' : t.days_left < 0 ? 'bad' : t.days_left <= 1 ? 'warn' : '')
// "show me this again": tomorrow morning, in three days, next Monday - or a day of the applicant's choosing
const day = ref('')
function at9(d) { d.setHours(9, 0, 0, 0); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T09:00` }
function inDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return at9(d) }
function nextMonday() { const d = new Date(); d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); return at9(d) }
const snooze = (t, until) => act(() => api.post(`/todos/${t.id}/snooze`, { until }), until ? T('todos.snoozedTo', { day: dayText(until) }) : T('todos.backAmongTheTo'))
const snoozeDay = (t) => (day.value ? snooze(t, day.value + 'T09:00') : null)
const dueEdit = ref({ id: 0, value: '' })
const openDue = (t) => { dueEdit.value = { id: t.id, value: t.due_at ? t.due_at.slice(0, 16) : '' } }
const saveDue = (t) => { const due = dueEdit.value.value || null; return act(() => api.post(`/todos/${t.id}/due`, { due }), T('todos.theDateIsUpdated')) }
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
// a mail about an application made elsewhere: what it gives a date for, on the applicant's own calendar
// (the mail is dealt with then: its card closes, and the notice leads to the day on the calendar)
const calendarDay = (w) => `/calendar?view=day&date=${String(w.start).slice(0, 10)}`
const toCalendar = (t) => act(async () => {
  const r = await api.post(`/todos/${t.id}/to-calendar`)
  toast(T('todos.putOnYourCalendar'), '', { to: calendarDay(r.start ? r : t.mail_when), link: T('todos.openOnYourCalendar') })
}, '')
// An item of the applicant's own calendar: closing its card takes it off the calendar - said so, and undone in one click
const removeOwn = (t) => act(async () => {
  await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false })
  toast(T('todos.removedFromCalendar'), '', { act: () => act(() => api.post(`/todos/${t.id}/reopen`), T('todos.backOnYourCalendar')), link: T('todos.undo') })
}, '')
const mailWhen = (w) => (w.all_day ? dateOf(new Date(w.start.slice(0, 10) + 'T00:00')) : dateTimeOf(new Date(w.start.slice(0, 16))))
const ackAll = () => act(() => api.post('/todos/bulk', { ids: infoIds.value }), T('todos.closedNotes', { n: infoIds.value.length }, infoIds.value.length))
const moreBudget = (t) => act(() => api.post(`/applications/${t.application.id}/budget?request_id=todo-${t.id}`), T('todos.anotherBudgetIsGiven'))
const tryAgainFor = async (t, backend) => { await api.post(`/jobs/${t.job.id}/draft`, backend ? { browser_backend: backend } : {}); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }
const tryAgain = (t) => act(() => tryAgainFor(t), T('todos.theAgentHasStarted'))
const appliedMyself = (t) => act(() => api.post(`/jobs/${t.payload.job_id}/mark-submitted`), T('todos.markedAsAppliedWell'))
const skipJob = (t) => act(async () => { await api.patch(`/jobs/${t.payload.job_id}`, { status: 'skipped' }); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }) }, T('todos.markedAsNotApplying'))
const markSubmitted = (t) => act(() => api.post(`/applications/${(t.application && t.application.id) || t.payload.application_id}/mark-submitted`), T('todos.markedAsAppliedWell'))
// ── what a card offers: one main action, at most two beside it, the rest in its menu ("not now" among them). What
// that is follows from the kind of card and from where its application stands - worked out here once, so that every
// card is laid out the same way. An action is { label, icon, go | to | href, disabled?, danger? }.
const named = (t) => view(t).title(t).includes(t.job.company)      // the title already says which employer
const A = (label, icon, how) => ({ label, icon, ...how })
const follow = (a) => (a.to ? router.push(a.to) : a.href ? window.open(a.href, '_blank', 'noopener,noreferrer') : a.go())
function acts(t) {
  const p = t.payload || {}
  const appId = (t.application && t.application.id) || p.application_id
  const away = A(T('todos.dismiss'), 'x', { go: () => dismiss(t) })
  const openApp = (label) => (appId ? [A(label || T('todos.openThisApplication'), 'external', { to: '/applications/' + appId })] : [])
  const draft = p.draft_id ? [A(T('todos.viewDraft'), 'draft', { to: '/drafts/' + p.draft_id })] : []
  const page = p.url ? [A(T('todos.openPage'), 'external', { href: p.url })] : []
  const goOn = (go) => A(T('todos.doneContinue'), 'check', { go })
  let main = null, beside = [], menu = [], more = {}
  if (['takeover', 'login'].includes(t.kind) && p.tenant_key) {
    main = A(p.provider ? T('todos.signInTo', { provider: p.provider }) : T('todos.signIn'), 'login', { go: () => takeover(t) })
    menu = [away]
    // what is kept of a sign-in is said where the button is; how to have the app sign in by itself is help
    more = t.remembers ? { remember: true } : p.tenant_key.startsWith('idp:') ? { note: T('todos.onlyTheSignIn') } : { help: T('todos.inThisSignIn') }
  } else if (t.kind === 'code') {
    main = A(T('todos.giveItToThe'), 'check', { go: () => giveCode(t), disabled: !codes.value[t.id] })
    menu = [away]; more = { note: T('todos.theAgentIsWaiting') }
  } else if (t.kind === 'confirm') {
    main = goOn(() => confirmed(t)); menu = [away]
    more = { note: p.window ? T('todos.theBrowserWindowIs') : T('todos.onceYouHaveDone') }
  } else if (t.kind === 'resume') {
    const r = RESUME[p.need] || RESUME.confirm
    main = A(r[1], 'refresh', { go: () => resumeNow(t) }); menu = [away]; more = { help: r[2] }
  } else if (t.kind === 'facts_changed') {
    const none = !factsPicked(t).length
    main = A(T('todos.prepareTheTickedOnes'), 'refresh', { go: () => factsDecide(t, 'redo'), disabled: none })
    beside = [A(T('todos.sendTheTickedOnes'), '', { go: () => factsDecide(t, 'keep'), disabled: none })]
  } else if (t.kind === 'mail_out') {
    main = A(T('todos.lookAtItAnd'), 'mail', { to: '/mail/' + p.outgoing_id }); beside = openApp()
  } else if (t.kind === 'gone') {
    main = A(T('todos.gotIt'), 'check', { go: () => dismiss(t) })
    beside = t.job && t.job.url ? [A(T('todos.openThePostingsPage'), 'external', { href: t.job.url })] : []
    menu = [...(t.job ? [A(T('todos.itIsStillThere'), 'refresh', { go: () => tryAgain(t) })] : []), ...(t.application ? openApp() : [])]
  } else if (t.kind === 'blocked') {
    const mine = A(T('todos.iveSubmittedIt'), 'check', { go: () => appliedMyself(t) })
    main = p.url ? A(T('todos.openThePostingAnd'), 'external', { href: p.url }) : mine
    beside = p.url ? [mine] : []
    menu = [A(T('todos.letTheAppTry'), 'refresh', { go: () => done(t) }), A(T('todos.skipThisOne'), 'x', { go: () => skipJob(t) })]
  } else if (t.kind === 'answer') {
    main = p.draft_id ? A(p.review ? T('todos.viewTheApplicationsMaterials') : T('todos.answer'), 'edit', { to: '/drafts/' + p.draft_id }) : null
    menu = [away]
  } else if (t.kind === 'followup' || t.kind === 'note') {
    const finish = A(T('todos.done'), 'check', { go: () => done(t) })
    const open = p.link ? [A(T('calendar.open'), 'external', { href: p.link })] : []
    const reply = p.outgoing_id ? [A(T('todos.lookAtTheReply'), 'mail', { to: '/mail/' + p.outgoing_id })]
      : p.category === 'info_request' && p.message_id ? [A(T('todos.writeAReply'), 'edit', { go: () => writeReply(t) })] : []
    // (a reply that is written is what to look at; else the link the item came with; else there is only "done")
    const first = p.outgoing_id ? reply[0] : open[0] || finish
    const rest = [...open, ...reply, finish].filter((x) => x !== first)
    main = first; beside = rest.slice(0, 2)
    menu = [...rest.slice(2), ...(p.application_id ? [A(T('todos.openThisApplicationAnd'), 'external', { to: '/applications/' + p.application_id })] : p.contact_id ? [A(T('todos.openContacts'), 'user', { to: '/contacts' })] : []),
      A(T('todos.removeFromCalendar'), 'x', { go: () => removeOwn(t) })]
  } else if (['failed', 'submit'].includes(t.kind) && t.application && t.job) {
    const other = t.can_retry_nodriver ? [A(T('todos.tryAgainWithNodriver'), 'globe', { go: () => act(() => tryAgainFor(t, 'nodriver'), T('todos.restarted')) })] : []
    if (unknown(t)) {
      main = A(T('todos.lookForTheConfirmation'), 'mail', { go: () => checkMail(t) })
      beside = [A(T('todos.iveSubmittedIt'), 'check', { go: () => markSubmitted(t) })]
      menu = [A(T('todos.itWasNotSubmitted'), 'refresh', { go: () => againNotSubmitted(t) }), ...openApp(), ...other, ...draft]
    } else {
      main = t.kind === 'submit' ? A(T('todos.iveSubmittedIt'), 'check', { go: () => markSubmitted(t) })
        : p.budget ? A(T('todos.giveItAnotherBudget'), 'refresh', { go: () => moreBudget(t) }) : A(T('todos.haveTheAgentTry'), 'refresh', { go: () => tryAgain(t) })
      beside = openApp()
      menu = [...other, ...draft, A(T('todos.skipThisOne'), 'x', { go: () => notApplying(t) })]
    }
  } else if (t.kind === 'captcha') {
    main = page[0] || goOn(() => done(t)); beside = page.length ? [goOn(() => done(t))] : []; menu = [away]
  } else if (t.kind === 'mail_unmatched') {
    main = A(T('todos.linkToThisApplication'), 'check', { go: () => linkMail(t), disabled: !picked.value[t.id] })
    // (an application made elsewhere: the date it gives goes on the calendar; once there, the card leads to it)
    beside = t.mail_when ? [t.on_calendar ? A(T('todos.openOnYourCalendar'), 'calendar', { to: calendarDay(t.mail_when) })
      : A(T('todos.putOnMyCalendar'), 'calendar', { go: () => toCalendar(t) })] : []
    menu = [A(T('todos.notAboutAnApplication'), 'x', { go: () => dismiss(t) })]; more = { pick: true }
  } else if (t.kind === 'config' && FIX[t.ref]) {
    main = A(FIX[t.ref][1], 'settings', { to: FIX[t.ref][0] }); beside = [A(T('todos.itIsTakenCare'), 'check', { go: () => done(t) })]
  } else {
    main = goOn(() => done(t)); beside = page; menu = [...draft, away]
  }
  return { shown: [...(main ? [{ ...main, primary: true }] : []), ...beside], menu, ...more }
}
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(() => { loadRang(); return load() }, { every: 15000 })
// the reminders that went off in the last hours (the calendar's, alarms.py): what is about to happen, at the top
const rang = ref([])
const loadRang = () => api.get('/calendar/alarms/recent').then((r) => (rang.value = r)).catch(() => {})
onMounted(() => { load(); loadRang() })
</script>

<template>
  <PageHead :title="$t('todos.needsYou')" :help="$t('todos.thingsTheAppCant')" />
  <div v-if="rang.length" class="callout rang">
    <Icon name="clock" />
    <div class="grow">
      <div class="t-primary">{{ $t('calendar.rang.title') }}</div>
      <div class="rows tight">
        <div v-for="x in rang" :key="x.id" class="r">
          <Trunc class="grow" :text="x.subject ? x.subject + ' · ' + x.title : x.title" />
          <span class="end">
            <span class="t-meta atomic">{{ x.all_day ? dayText(x.start) : dateTimeOf(new Date(x.start)) }}</span>
            <router-link :to="{ path: '/calendar', query: { view: 'day', date: x.start.slice(0, 10) } }" class="btn sm ghost">{{ $t('calendar.rang.openDay') }}</router-link>
            <a v-if="x.link" :href="x.link" target="_blank" rel="noopener" class="btn sm primary"><Icon name="external" />{{ $t('calendar.open') }}</a>
          </span>
        </div>
      </div>
    </div>
  </div>
  <DataState :s="st" :what="$t('todos.toDo')" @retry="load" />
  <template v-if="st.at">

  <template v-if="todos.length">
    <!-- (a kind with nothing in it is left out: the row stays short enough for one line) -->
    <Tabs v-model="cat" class="page-tabs" :label="$t('todos.needsYou')" :items="CATS.filter(([x]) => x === 'all' || x === cat || count(x)).map(([id, label]) => ({ id, label, count: count(id) }))" />
    <div class="filters">
      <input v-model="q" type="search" :placeholder="$t('todos.searchCompaniesPostingsOr')" :aria-label="$t('todos.searchCompaniesPostingsOr')" />
      <AaSelect :model-value="sort" :aria-label="$t('todos.sortBy')" @update:model-value="setSort"><option v-for="(l, k) in SORTS" :key="k" :value="k">{{ l }}</option></AaSelect>
      <span class="grow"></span>
      <button v-if="infoIds.length > 1" class="sm" @click="ackAll"><Icon name="check" />{{ $t('todos.allRead', { n: infoIds.length }, infoIds.length) }}</button>
      <span class="t-meta atomic">{{ $t('todos.count', { n: shown.length }, shown.length) }}</span>
    </div>
  </template>

  <template v-for="sec in sections" :key="sec.label">
  <div v-if="sec.label" class="todo-sec" :class="'u' + sec.u">{{ sec.label }}<span>{{ sec.rows.length }}</span></div>
  <div v-for="t in sec.rows" :key="t.id" class="card todo" :class="'u' + t.urgency">
    <div class="ico" :class="view(t).tone"><Icon :name="view(t).icon" /></div>
    <div class="todo-body">
      <div class="head">
        <span class="title grow">{{ view(t).title(t) }}</span>
        <span class="todo-meta">
          <template v-if="t.due_at">
            <span v-tip="t.payload && t.payload.due_text ? $t('todos.inTheMail', { text: t.payload.due_text }) : ''" :class="dueTone(t) ? 'tag ' + dueTone(t) : 'meta'">{{ dueText(t) }}<template v-if="dueLeft(t)"> · {{ dueLeft(t) }}</template></span>
          </template>
          <!-- the date of an item that has one of its own can be set here -->
          <Popover v-if="t.kind === 'followup' || t.kind === 'note'" :label="$t('todos.whenThisIsFor')" :width="300" align="end" @open="openDue(t)">
            <template #trigger="{ toggle, attrs }">
              <IconButton v-if="t.due_at" icon="edit" size="sm" :label="$t('calendar.move')" v-bind="attrs" @click="toggle" />
              <button v-else class="ghost sm" v-bind="attrs" @click="toggle"><Icon name="calendar" />{{ $t('todos.addDate') }}</button>
            </template>
            <template #default="{ close }">
              <div class="field"><label :for="'due-' + t.id">{{ $t('todos.whenThisIsFor') }}</label><input :id="'due-' + t.id" v-model="dueEdit.value" class="w-full" type="datetime-local" /></div>
              <div class="actions pop-acts">
                <button v-if="t.due_at" class="sm ghost" @click="dueEdit.value = ''; saveDue(t); close()">{{ $t('todos.removeTheDate') }}</button>
                <span class="grow"></span>
                <button class="sm" @click="close()">{{ $t('todos.cancel') }}</button>
                <button class="sm primary" @click="saveDue(t); close()">{{ $t('todos.save') }}</button>
              </div>
            </template>
          </Popover>
          <span v-if="t.site && t.site.system" class="meta">{{ t.site.system }}</span>
          <span class="t-meta atomic">{{ fmtTime(t.created_at) }}</span>
        </span>
      </div>
      <!-- (the posting, when the title does not already name it) -->
      <router-link v-if="t.job && !named(t)" :to="{ path: '/jobs', query: { open: t.job.id } }" class="todo-job">
        <span v-if="t.job.score != null" class="score" :class="scoreCls(t.job.score)">{{ t.job.score.toFixed(1) }}</span>
        <Trunc :text="t.job.company + ' · ' + t.job.title" />
        <span v-if="left(t) && !t.due_at" class="meta small" :class="{ soon: t.days_left <= 3 }">{{ left(t) }}</span>
      </router-link>
      <p v-if="view(t).what(t)" class="what">{{ view(t).what(t) }}</p>
      <p v-if="t.kind === 'mail_unmatched' && t.payload && t.payload.site && t.payload.site.length" class="callout"><Icon name="info" /><span>{{ $t('todos.siteCouldNotTell', { shown: listed(t.payload.site) }) }}</span></p>
      <p v-else-if="t.kind === 'mail_unmatched' && t.candidates && !t.candidates_near" class="t-secondary">{{ $t('todos.theSendingEmployerWas') }}</p>
      <!-- (the date the mail gives, on the applicant's clock: what "Add to my calendar" puts there) -->
      <p v-if="t.kind === 'mail_unmatched' && t.mail_when" class="t-secondary todo-when"><Icon name="calendar" /><span class="t-primary">{{ $t('todos.theEmailGivesThisTime', { when: mailWhen(t.mail_when) }) }}</span>
        <span v-if="t.mail_when.said" class="meta">{{ $t('todos.asTheEmailWrote', { said: t.mail_when.said }) }}</span></p>
      <p v-if="t.payload && t.payload.trying" class="callout"><Icon name="clock" /><span>{{ $t('todos.theSignInWindow') }}</span></p>
      <div v-else-if="t.payload && t.payload.last_try" class="callout warn"><Icon name="alert" /><div><div>{{ $t('todos.lastTryDidNotWork') }}</div><TechDetails :text="t.payload.last_try" /></div></div>

      <!-- what a "profile changed" card asks about: the lines that changed, and the applications that still say the old thing -->
      <div v-if="t.kind === 'facts_changed'" class="facts-changed">
        <div v-for="(c, i) in t.payload.changes || []" :key="i" class="fc-line"><span class="meta">{{ c.key || $t('todos.thisLine') }}</span> <s class="muted">{{ c.old }}</s> → <span class="t-primary">{{ c.new || $t('todos.removed') }}</span></div>
        <div v-for="r in factsLeft(t)" :key="r.application_id" class="fc-app">
          <label><input type="checkbox" :checked="(factPick[t.id] || {})[r.application_id] !== false" @change="factTick(t, r.application_id, $event.target.checked)" />
            <router-link :to="'/applications/' + r.application_id">{{ r.title }}</router-link>
            <span v-if="r.told_while_working" class="meta small">{{ $t('todos.beingWorkedItHas') }}</span></label>
          <dl><template v-for="(a, j) in r.answers" :key="j"><dt>{{ a.label }}</dt><dd>{{ a.value }}</dd></template></dl>
        </div>
        <p v-if="(t.payload.sent || []).length" class="t-secondary">{{ $t('todos.sentUsedOld', { n: t.payload.sent.length, titles: sentTitles(t) }, t.payload.sent.length) }}</p>
      </div>

      <!-- one main action, at most two beside it; the rest is in the menu; "later" is the clock -->
      <div class="actions todo-acts">
        <input v-if="t.kind === 'code'" v-model="codes[t.id]" class="w-short" :placeholder="$t('todos.enterTheCodeHere')" :aria-label="$t('todos.enterTheCodeHere')" inputmode="numeric" autocomplete="one-time-code" @keyup.enter="codes[t.id] && giveCode(t)" />
        <AaSelect v-if="acts(t).pick" v-model="picked[t.id]" class="todo-pick" :placeholder="$t('todos.whichApplicationIsThis')" :aria-label="$t('todos.whichApplicationIsThis')">
          <option v-for="c in t.candidates || []" :key="c.id" :value="c.id">{{ c.label }}{{ c.site_status ? ' ' + $t('todos.onTheSite', { status: c.site_status }) : '' }}</option>
        </AaSelect>
        <template v-for="(a, i) in acts(t).shown" :key="i">
          <router-link v-if="a.to" :to="a.to" class="btn" :class="{ primary: a.primary }"><Icon v-if="a.icon" :name="a.icon" />{{ a.label }}</router-link>
          <a v-else-if="a.href" :href="a.href" target="_blank" rel="noopener noreferrer" class="btn" :class="{ primary: a.primary }"><Icon v-if="a.icon" :name="a.icon" />{{ a.label }}</a>
          <button v-else :class="{ primary: a.primary }" :disabled="a.disabled" @click="a.go()"><Icon v-if="a.icon" :name="a.icon" />{{ a.label }}</button>
        </template>
        <label v-if="acts(t).remember" class="meta todo-check"><input v-model="saveCred" type="checkbox" /> {{ $t('todos.rememberMyPasswordAnd') }}</label>
        <HelpPop v-if="acts(t).help" :label="view(t).title(t)" :text="acts(t).help" />
        <span class="grow"></span>
        <Popover :label="$t('todos.remindMeLater')" :width="300" align="end" @open="day = ''">
          <template #trigger="{ toggle, attrs }"><IconButton icon="clock" :label="$t('todos.remindMeLater')" v-bind="attrs" @click="toggle" /></template>
          <template #default="{ close }">
            <div class="snooze">
              <div class="t-meta">{{ $t('todos.remindMeLater') }}</div>
              <div class="actions">
                <button class="sm" @click="close(); snooze(t, inDays(1))">{{ $t('todos.tomorrow') }}</button>
                <button class="sm" @click="close(); snooze(t, inDays(3))">{{ $t('todos.inDays') }}</button>
                <button class="sm" @click="close(); snooze(t, nextMonday())">{{ $t('todos.nextMonday') }}</button>
              </div>
              <div class="actions">
                <input v-model="day" class="grow" type="date" :aria-label="$t('todos.chooseADay')" />
                <button class="sm" :disabled="!day" @click="close(); snoozeDay(t)">{{ $t('todos.onThisDay') }}</button>
              </div>
            </div>
          </template>
        </Popover>
        <Menu v-if="acts(t).menu.length" :label="$t('common.more')" :items="acts(t).menu.map((a, i) => ({ id: i, label: a.label, icon: a.icon, danger: a.danger }))" @pick="(i) => follow(acts(t).menu[i])" />
      </div>
      <p v-if="acts(t).note" class="t-meta todo-note">{{ acts(t).note }}</p>
      <TechDetails :text="t.explained.detail" />
    </div>
  </div>
  </template>

  <div v-if="later.length" class="card">
    <button class="ghost later-toggle" :aria-expanded="showLater" @click="showLater = !showLater"><Icon :name="showLater ? 'chevron_up' : 'chevron'" />{{ $t('todos.later', { n: later.length }) }}</button>
    <div v-if="showLater" class="rows">
      <div v-for="t in later" :key="t.id" class="r">
        <DateTimeCell class="lead" :primary="dayText(t.snoozed_until)" />
        <EntityCell :primary="view(t).title(t)" :secondary="t.due_at ? $t('todos.when', { when: dueText(t) }) : ''" />
        <span class="end"><button class="ghost sm" @click="snooze(t, null)">{{ $t('todos.showItNow') }}</button></span>
      </div>
    </div>
  </div>
  <div v-if="active.length && !shown.length" class="card"><EmptyState icon="search" :title="$t('todos.noMatchingToDos')" :text="$t('todos.tryAnotherCategoryOr')" /></div>

  <div v-if="!active.length" class="card"><EmptyState icon="check" :title="$t('todos.nothingNeedsYouRight')" :text="$t('todos.requestsToSignIn')" /></div>
  </template>
</template>

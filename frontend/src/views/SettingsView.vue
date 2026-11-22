<script setup>
import { t as T } from '../i18n/catalog'
// The settings, in six groups by what they are about. Every section has an address (/settings/<group>/<section>), so
// a card, a notice or another page can lead to the very thing that needs changing.
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import AiPanel from '../components/AiPanel.vue'
import MailboxPanel from '../components/MailboxPanel.vue'
import AccessPanel from '../components/AccessPanel.vue'
import CardHead from '../components/CardHead.vue'
import HelpPop from '../components/HelpPop.vue'
import Icon from '../components/Icon.vue'
import NetworkPanel from '../components/NetworkPanel.vue'
import BrowserPanel from '../components/BrowserPanel.vue'
import DoctorPanel from '../components/DoctorPanel.vue'
import PromptsPanel from '../components/PromptsPanel.vue'
import PageHead from '../components/PageHead.vue'
import Popover from '../components/Popover.vue'
import SetSection from '../components/SetSection.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import FormError from '../components/FormError.vue'
import { useRoute, useRouter } from 'vue-router'
import { ask, fmtTime, persona, run as runAction, toast } from '../ui'
import { absorb, changed, clone, unsaved, useUnsaved } from '../dirty'
import { t } from '../i18n/catalog'

const s = ref(null)
const info = ref({ secrets: {}, gmail: {} })
const blankSecrets = () => ({ anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '', discord_bot_token: '', discord_webhook: '' })
const sec = ref(blankSecrets())
const netPanel = ref(null)
const route = useRoute()
const router = useRouter()
const rerun = async () => { await api.post('/persona/restart'); persona.done = false; router.push('/welcome') }
const sys = ref({})
const exported = ref(null)
const docs = ref([])
api.get('/system').then((d) => (sys.value = d)).catch(() => {})
api.get('/documents').then((d) => (docs.value = d)).catch(() => {})
const exportData = async (sessions) => {
  try {
    exported.value = await api.post('/system/export', { sessions })
    sys.value = await api.get('/system')        // "last exported" is read from the exports themselves
  } catch (e) { toast(e.message, 'bad') }
}
const lastExport = computed(() => sys.value.last_export || null)
// (one sentence for each of the two cases: the parts are not put together from pieces)
const lastExportLine = computed(() => {
  const e = lastExport.value
  if (!e) return ''
  const when = fmtTime(e.created), mb = (e.size / 1e6).toFixed(1)
  return e.sessions ? T('settings.page.lastExportFilesMb', { p0: when, p1: e.files, p2: mb }) : T('settings.page.lastExportFilesMb2', { p0: when, p1: e.files, p2: mb })
})

// --- where everything is ---------------------------------------------------------------------------------------------
// [group, its name, [[section, its name], ...]]. The sections of a group are on one page, in this order.
const GROUPS = [
  ['overview', T('settings.page.overview'), []],
  ['goals', T('settings.page.searchGoalsAndMatching'), [['profile', T('settings.page.yourSearchProfile')], ['filters', T('settings.page.hardConditionsBeforeIntake')], ['search', T('settings.page.whatToSearchFor')], ['sources', T('settings.page.sourcesAndWatchedEmployers')]]],
  ['automation', T('settings.page.automationAndWorkPlan'), [['prepare', T('settings.page.startingApplicationsByItself')], ['submit', T('settings.page.howItIsSent')], ['limits', T('settings.page.howTheAgentWorks')], ['schedule', T('settings.page.plan')]]],
  ['materials', T('settings.page.files2'), [['resume', T('settings.page.rSum')], ['cover', T('settings.page.coverLetter')]]],
  ['accounts', T('settings.page.accountsAndConnections'), [['logins', T('settings.page.signInsToCareer')], ['mailbox', T('settings.page.mailbox')], ['ai', T('settings.page.aiService')]]],
  ['notify', T('settings.page.noticesAndReminders'), [['channel', T('settings.page.whereNoticesGo')], ['bots', T('settings.page.handleItFromYour')], ['events', T('settings.page.whatToNotifyAbout')], ['reminders', T('settings.page.calendarReminders')]]],
  ['system', T('settings.page.systemAndData'), [['network', T('settings.page.networkConnectionOutbound')], ['browser', T('settings.page.browserCompatibility')], ['remote', T('settings.page.remoteAccessInbound')], ['security', T('settings.page.accountSecurity')], ['retention', T('settings.page.dataRetention')], ['backup', T('settings.page.backupAndUpdates')], ['diagnose', T('settings.page.diagnostics')], ['expert', T('settings.page.expertTools')]]],
]
const group = computed(() => (GROUPS.some((g) => g[0] === route.params.group) ? route.params.group : 'overview'))
const sections = computed(() => GROUPS.find((g) => g[0] === group.value)[2])      // of the open group: a line of links under the tabs
// what the settings come to, as the server reads them (rules.py): asked for when the overview is opened, and again after a save
const rules = ref(null)
const loadRules = () => api.get('/rules').then((d) => (rules.value = d)).catch((e) => toast(e.message, 'bad'))
watch(group, (g) => { if (g === 'overview') loadRules() }, { immediate: true })
// (who does a step is a fact, not a success: no green here)
const WHO = { auto: [T('settings.page.theProgramDoesIt'), 'info'], you: [T('settings.page.waitingForYou'), 'warn'], mixed: [T('settings.page.itDepends'), ''], off: [T('settings.page.notDone'), ''] }
function settle() {
  // an address that names no group, or one that is not there (an old link): the first group
  if (route.params.group !== group.value) { router.replace('/settings/' + group.value); return }
  const sec = route.params.section
  if (sec) nextTick(() => { const el = document.getElementById('set-' + sec); if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' }) })
}
watch(() => [route.params.group, route.params.section, !!s.value], settle)
// The groups are one line of tabs that scrolls sideways where the window is too narrow for all of them: the open
// group is brought into view, and an edge fades where there is more beyond it.
const nav = ref(null)
const more = reactive({ left: false, right: false })
function edges() {
  const el = nav.value
  if (!el) return
  more.left = el.scrollLeft > 2
  more.right = el.scrollLeft + el.clientWidth < el.scrollWidth - 2
}
function showTab() {
  nextTick(() => {
    const on = nav.value && nav.value.querySelector('.on')
    if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    edges()
  })
}
watch(() => [group.value, !!s.value], showTab)
onMounted(() => window.addEventListener('resize', edges))
onUnmounted(() => window.removeEventListener('resize', edges))

const COUNTRIES = [['CA', T('settings.page.canada')], ['US', T('settings.page.unitedStates')]]
const examples = ref('Software Engineering Intern, Summer 2027 | Seattle, WA, US\nSenior Software Engineer | Toronto, ON, CA\nSoftware Developer Co-op | Vancouver, BC, Canada\nMBA Intern | New York, NY, US\nSoftware Engineering Intern | Singapore')
const tried = ref([])
// what separates the items of a list typed into one field: a comma, also the full-width one (written by its code)
const SEP = /[,\uFF0C]/
const csv = (key) => (s.value[key] || []).join(', ')
const setCsv = (key, v) => { s.value[key] = v.split(/[,\uFF0C\n]/).map((x) => x.trim()).filter(Boolean) }
function toggleCountry(c) { const cur = new Set(s.value['intake.countries'] || []); cur.has(c) ? cur.delete(c) : cur.add(c); s.value['intake.countries'] = [...cur] }
async function tryRules() {
  const rules = { title_any: s.value['intake.title_any'], title_role_any: s.value['intake.title_role_any'], title_none: s.value['intake.title_none'], countries: s.value['intake.countries'], max_age_days: s.value['intake.max_age_days'] }
  try { tried.value = (await api.post('/sources/try-rules', { rules, examples: examples.value.split('\n').filter((x) => x.trim()) })).results } catch (e) { toast(e.message, 'bad') }
}

// --- how what is on this page gets saved -------------------------------------------------------------------------------
// Three ways, and each section says which of them it uses: the button at the top right (most settings), a part's own
// button (a mailbox, an AI service, a prompt, the access settings), and at once. The button at the top saves what was
// changed and says how much that is; nothing reads the settings afresh over what is being edited.
// settings that belong to their own panels / endpoints / pages: the button at the top does not send them
const ELSEWHERE = ['employers', 'employers.migrated', 'mail.kind', 'mail.imap', 'llm.provider', 'llm.providers', 'persona', 'onboarding.done', 'sso.sites', 'sso.offered',
  'sources.greenhouse', 'sources.lever', 'sources.ashby', 'sources.workday', 'sources.bigtech', 'sources.pdportal', 'schedule.paused']
const saved = ref({})         // the settings as they were last read or saved
const saving = ref(false)
const dirtyKeys = computed(() => (s.value ? changed(saved.value, s.value).filter((k) => !ELSEWHERE.includes(k)) : []))
const typedSecrets = computed(() => Object.keys(sec.value).filter((k) => sec.value[k]))
const pending = computed(() => dirtyKeys.value.length + typedSecrets.value.length)
// in which group each change was made (a change is made in the group that is open): the groups with something unsaved are marked
const madeIn = reactive({})
watch(() => [...dirtyKeys.value, ...typedSecrets.value.map((k) => 'secret:' + k)], (now) => {
  for (const k of now) if (!madeIn[k]) madeIn[k] = group.value
  for (const k of Object.keys(madeIn)) if (!now.includes(k)) delete madeIn[k]
})
const marked = (g) => Object.values(madeIn).includes(g) || (g === group.value && unsaved.value.some((a) => a.id !== 'settings' && a.scope === '/settings/' + g))

async function load() {
  const d = await api.get('/settings')
  if (!s.value) { s.value = d.settings; saved.value = clone(d.settings) } else absorb(s.value, saved.value, d.settings)      // (dirty.absorb: what is being edited stays)
  info.value = d
}
async function save() {
  const keys = dirtyKeys.value
  const n = pending.value
  if (!n) { toast(T('settings.page.thereAreNoChanges')); return true }
  if (saving.value) return false
  saving.value = true
  try {
    // (ui.run: what the server refused stays on the page, next to the button, until it is saved again)
    const done = await runAction(async () => {
      const st = {}
      for (const k of keys) st[k] = s.value[k]       // what was changed, and only that: a setting another part saved meanwhile is not sent back as it was
      const secrets = {}
      for (const k in sec.value) if (sec.value[k]) secrets[k] = sec.value[k]
      await api.put('/settings', { settings: st, secrets })
      for (const k of keys) saved.value[k] = clone(s.value[k])
      sec.value = blankSecrets()
    }, T('settings.page.savedChangeS', { p0: n }, n), async () => {
      await load()
      if (group.value === 'overview') loadRules()
      if (netPanel.value) netPanel.value.load()
      loadDiscord()
    }, { form: 'settings' })
    return done !== false
  } finally { saving.value = false }
}
function discard() {
  for (const k of dirtyKeys.value) s.value[k] = clone(saved.value[k])
  sec.value = blankSecrets()
}
useUnsaved({ id: 'settings', label: T('settings.page.settings'), dirty: () => pending.value > 0, save, discard, scope: '/settings' })
// (after an action of this page - a test message, a part saved by its own button - the settings are read afresh;
// load takes what is new and leaves what is being edited)
const act = (fn, ok) => runAction(fn, ok, load)
const tgTest = () => act(() => api.post('/settings/telegram-test'), T('settings.page.testMessageSentCheck'))
// Discord: the bot behind the saved token, and the applicant it is bound to (a code they send it in a direct message)
const dc = ref(null)
let dcTimer = null
async function loadDiscord() {
  clearTimeout(dcTimer)
  try { dc.value = await api.get('/settings/discord') } catch { dc.value = null }
  if (dc.value && dc.value.code && !dc.value.bound) dcTimer = setTimeout(loadDiscord, 3000)      // waiting for the code to be sent: the page sees it arrive
}
const dcBind = () => runAction(() => api.post('/settings/discord/bind'), T('settings.page.linkingCodeCreatedSend'), loadDiscord)
const dcUnbind = async () => (await ask(T('settings.page.unlinkAsk'), { ok: T('settings.page.unlink'), danger: true })) && runAction(() => api.post('/settings/discord/unbind'), T('settings.page.unlinked'), loadDiscord)
const dcTest = () => act(() => api.post('/settings/discord-test'), T('settings.page.testMessageSentCheck2'))
onUnmounted(() => clearTimeout(dcTimer))
const dcState = computed(() => {
  if (!dc.value) return { cls: 'warn', text: T('settings.page.notSetUpYet2') }
  if (dc.value.error) return { cls: 'bad', text: T('settings.page.tokenDoesNotWork') }
  if (dc.value.token && dc.value.bound) return { cls: 'ok', text: T('settings.page.connected') }
  if (dc.value.token) return { cls: 'warn', text: T('settings.page.notLinkedYet') }
  if (dc.value.webhook) return { cls: 'ok', text: T('settings.page.notificationsOnlyWebhook') }
  return { cls: 'warn', text: T('settings.page.notSetUpYet2') }
})
const tgOn = computed(() => !!(info.value.secrets.telegram_bot_token && s.value && s.value['notify.telegram_chat_id']))
// the reminders each kind of calendar item gets by itself (alarms.py): minutes before, written as "1440, 30"
const REMINDER_KINDS = ['interview', 'assessment', 'offer', 'info_request', 'contact', 'own', 'deadline']
const minutesText = (k) => ((s.value['calendar.reminders'] || {})[k] || []).join(', ')
function setMinutes(k, text) {
  const v = String(text).split(/[,\uFF0C\s]+/).map((x) => parseInt(x, 10)).filter((n) => Number.isFinite(n) && n >= 0)
  s.value['calendar.reminders'] = { ...(s.value['calendar.reminders'] || {}), [k]: [...new Set(v)].sort((a, b) => b - a) }
}
const remindText = (k) => {
  const v = (s.value['calendar.reminders'] || {})[k] || []
  if (!v.length) return t('settings.reminders.none')
  return v.map((n) => (n % 1440 === 0 ? (n ? t('calendar.alarm.days', { n: n / 1440 }, n / 1440) : t('calendar.alarm.sameDay')) : n % 60 === 0 ? t('calendar.alarm.hours', { n: n / 60 }, n / 60) : t('calendar.alarm.minutes', { n }, n))).join(' · ')
}
// which notifications go to which channel (a channel not named takes every kind that is switched on)
const CATS = [['todo', T('settings.page.thingsThatNeedYou')], ['task_result', T('settings.page.outcomeSentFailed')], ['status_update', T('settings.page.applicationProgress')], ['task_started', T('settings.page.startDoingSomething')]]
const channelsOn = computed(() => [
  info.value.secrets.telegram_bot_token && s.value['notify.telegram_chat_id'] ? ['telegram', 'Telegram'] : null,
  dc.value && ((dc.value.token && dc.value.bound) || dc.value.webhook) ? ['discord', 'Discord'] : null,
].filter(Boolean))
const takes = (ch, cat) => { const c = (s.value['notify.channel_categories'] || {})[ch]; return !c || c.includes(cat) }
function setTakes(ch, cat, on) {
  const all = { ...(s.value['notify.channel_categories'] || {}) }
  const cur = all[ch] || CATS.map((c) => c[0])
  all[ch] = on ? [...new Set([...cur, cat])] : cur.filter((x) => x !== cat)
  s.value['notify.channel_categories'] = all
}
const hasWord = computed(() => docs.value.some((d) => d.kind === 'resume_docx' && d.active))
const template = computed(() => docs.value.find((d) => d.kind === 'cl_template' && d.active))
// the conventions of the applicant's own letter template, one per line
const pairs = (key, a, b) => (s.value[key] || []).map((x) => `${x[a]} | ${x[b]}`).join('\n')
const setPairs = (key, a, b, text) => { s.value[key] = text.split('\n').map((l) => l.split('|').map((x) => x.trim())).filter((p) => p.length >= 2 && p[0] && p[1]).map((p) => ({ [a]: p[0], [b]: p.slice(1).join('|').trim() })) }
onMounted(() => { load(); loadDiscord() })
</script>

<template>
  <div v-if="s">
    <PageHead :title="$t('settings.page.settings')">
      <Status v-if="pending" tone="warn" role="status" :label="$t('settings.page.changeSNotSaved', { p0: pending }, pending)" />
      <button v-if="pending" class="ghost" :disabled="saving" @click="discard">{{ $t('settings.page.discardChanges') }}</button>
      <button class="primary" :disabled="!pending || saving" @click="save"><Icon name="check" />{{ saving ? $t('settings.page.saving') : $t('settings.page.save') }}</button>
    </PageHead>
    <FormError name="settings" />
    <nav ref="nav" class="seg tabs set-nav" :class="{ 'more-left': more.left, 'more-right': more.right }" :aria-label="$t('settings.page.groupsOfSettings')" @scroll.passive="edges">
      <router-link v-for="[g, name] in GROUPS" :key="g" :to="'/settings/' + g" class="seg-link" :class="{ on: group === g }" :aria-current="group === g ? 'page' : undefined">{{ name }}<span v-if="marked(g)" v-tip="$t('settings.page.unsavedChanges')" class="unsaved-dot" role="img" :aria-label="$t('settings.page.unsavedChanges')"></span></router-link>
    </nav>
    <nav v-if="sections.length > 1" class="set-toc" :aria-label="$t('settings.page.sections')">
      <router-link v-for="[id, name] in sections" :key="id" :to="'/settings/' + group + '/' + id" :class="{ on: route.params.section === id }">{{ name }}</router-link>
    </nav>

    <!-- Overview: what the settings come to -->
    <template v-if="group === 'overview'">
      <p v-if="pending" class="callout warn"><Icon name="alert" /><span>{{ $t('settings.page.whatIsWrittenBelow', { p0: pending }, pending) }}</span></p>
      <div v-if="rules" class="set-cols">
        <div class="card">
          <CardHead :title="$t('settings.page.whatIApplyTo')" :help="$t('settings.page.fromTopToBottom')" />
          <ul class="rule-list">
            <li v-for="(r, i) in rules.apply" :key="i">
              <span class="meta">{{ r.label }}</span>
              <div class="grow"><router-link :to="r.where">{{ r.text }}</router-link><span v-if="r.note" class="t-meta">{{ r.note }}</span></div>
            </li>
          </ul>
        </div>
        <div class="card">
          <CardHead :title="$t('settings.page.whatTheProgramMay')" :help="$t('settings.page.everyStepOfAn')" />
          <p v-if="rules.paused" class="callout warn"><Icon name="pause" /><span><b>{{ $t('settings.page.automaticRunningIsPaused') }}</b>{{ $t('settings.page.everythingTheProgramBegins') }}</span></p>
          <ul class="rule-list">
            <li v-for="st in rules.allowed" :key="st.key">
              <Status :tone="WHO[st.who][1]" :label="WHO[st.who][0]" />
              <div class="grow"><div class="t-primary">{{ st.name }}</div><router-link :to="st.where">{{ st.text }}</router-link>
                <ul v-if="st.more.length"><li v-for="(m, i) in st.more" :key="i">{{ m }}</li></ul></div>
            </li>
          </ul>
          <p class="set-note">{{ $t('settings.page.forEachApplicationIts') }}</p>
        </div>
      </div>
    </template>

    <!-- Search goals and matching -->
    <template v-if="group === 'goals'">
      <SetSection id="profile" :title="$t('settings.page.yourSearchProfile')" how="">
        <div class="card">
          <CardHead :title="$t('settings.page.whatYouToldThe')" :help="$t('settings.page.yourProfileDecidesWhat')">
            <button class="sm" @click="rerun">{{ $t('settings.page.planAgainRunThe') }}</button>
          </CardHead>
          <p class="t-secondary">{{ persona.features.summary || $t('settings.page.notSetUpYet') }}</p>
          <div class="set-actions">
            <span class="t-meta">{{ $t('settings.page.seeAlso') }}</span>
            <router-link :to="{ path: '/profile', query: { tab: 'scoring' } }">{{ $t('settings.page.profileScoringRules') }}</router-link>
            <router-link to="/settings/automation/prepare">{{ $t('settings.page.startingApplicationsByItself') }}</router-link>
          </div>
        </div>
      </SetSection>

      <SetSection id="filters" :title="$t('settings.page.hardConditionsBeforeIntake')">
        <div class="card">
          <CardHead :title="$t('settings.page.whichPostingsGetAdded')" :help="$t('settings.page.thisIsAFilter')">
            <label class="set-check"><input v-model="s['intake.enabled']" type="checkbox" /> {{ $t('settings.page.enable') }}</label>
          </CardHead>
          <div class="field"><label for="f-title-any">{{ $t('settings.page.titleMustIncludeOne') }}<HelpPop :text="$t('settings.page.separateWithCommasMatches')" /></label>
            <input id="f-title-any" :value="csv('intake.title_any')" @change="setCsv('intake.title_any', $event.target.value)" /></div>
          <div class="field"><label for="f-role-any">{{ $t('settings.page.andMustHaveOne') }}</label>
            <textarea id="f-role-any" class="plain" rows="3" :value="csv('intake.title_role_any')" @change="setCsv('intake.title_role_any', $event.target.value)"></textarea></div>
          <div class="field"><label for="f-title-none">{{ $t('settings.page.titlesCantContainThese') }}</label>
            <input id="f-title-none" :value="csv('intake.title_none')" @change="setCsv('intake.title_none', $event.target.value)" /></div>
          <div class="field"><label for="f-programs">{{ $t('settings.page.yourProgrammeOfStudy') }}<HelpPop :text="$t('settings.page.someSourcesAUniversitys')" /></label>
            <input id="f-programs" :value="csv('intake.programs')" :placeholder="$t('settings.page.forExampleComputer')" @change="setCsv('intake.programs', $event.target.value)" /></div>
          <div class="kv">
            <label>{{ $t('settings.page.locatedIn') }}</label>
            <div class="set-val"><div class="set-opts"><label v-for="[c, name] in COUNTRIES" :key="c"><input type="checkbox" :checked="(s['intake.countries'] || []).includes(c)" @change="toggleCountry(c)" /> {{ name }}</label></div>
              <span class="hint">{{ $t('settings.page.leaveAllUncheckedFor') }}</span></div>
            <label for="f-age">{{ $t('settings.page.onlyPostingsFromThe') }}</label>
            <div class="set-val"><input id="f-age" v-model.number="s['intake.max_age_days']" class="w-num" type="number" /><span class="unit">{{ $t('settings.page.days') }}</span><span class="hint">{{ $t('settings.page.enterForNoLimit') }}</span></div>
          </div>
        </div>
        <div class="card">
          <CardHead :title="$t('settings.page.tryIt')" :help="$t('settings.page.oneTitlePerLine')" />
          <textarea v-model="examples" class="plain" rows="5" :aria-label="$t('settings.page.titlesToTryThe')"></textarea>
          <div class="set-actions"><button @click="tryRules">{{ $t('settings.page.tryIt') }}</button></div>
          <div v-if="tried.length" class="try-list">
            <div v-for="(x, i) in tried" :key="i">
              <Status :tone="x.kept ? 'ok' : ''" :label="x.kept ? $t('settings.page.keep') : $t('settings.page.discard')" />
              <EntityCell :primary="x.title" :secondary="x.location || ''" />
              <Trunc class="t-secondary" :text="x.why || ''" />
            </div>
          </div>
        </div>
      </SetSection>

      <SetSection id="search" :title="$t('settings.page.whatToSearchFor')">
        <div class="card">
          <div class="field last"><label for="f-terms">{{ $t('settings.page.searchTerms') }}<HelpPop :text="$t('settings.page.careerSitesLikeAmazons')" /></label>
            <input id="f-terms" :value="csv('sources.search_terms')" :placeholder="$t('settings.page.eGInternCo')" @change="setCsv('sources.search_terms', $event.target.value)" /></div>
        </div>
      </SetSection>

      <SetSection id="sources" :title="$t('settings.page.sourcesAndWatchedEmployers')" how="">
        <div class="card">
          <p class="t-secondary">{{ $t('settings.page.sourcesMoved') }}</p>
          <div class="set-actions">
            <router-link to="/jobs/sources" class="btn sm">{{ $t('settings.page.sourcesAndWatchedEmployers') }}</router-link>
            <router-link to="/settings/automation/schedule" class="btn sm ghost">{{ $t('settings.page.plan') }}</router-link>
          </div>
        </div>
      </SetSection>
    </template>

    <!-- Automation and work plan -->
    <template v-if="group === 'automation'">
      <SetSection id="prepare" :title="$t('settings.page.startingApplicationsByItself')">
        <template #actions><HelpPop :text="$t('settings.page.whenNewPostingsAre')" /></template>
        <div class="card">
          <div class="kv">
            <label for="f-min">{{ $t('settings.page.ordinaryPostingsFromWhich') }}</label>
            <div class="set-val"><input id="f-min" v-model.number="s['queue.min_score_for_draft']" class="w-num" type="number" step="0.5" /><span class="unit">{{ $t('settings.page.outOf') }}</span></div>
            <label for="f-pmin">{{ $t('settings.page.postingsOfPriorityEmployers') }}
              <HelpPop :label="$t('settings.page.postingsOfPriorityEmployers')"><p>{{ $t('settings.page.whichEmployersArePriority') }}<router-link to="/jobs/sources">{{ $t('settings.page.sourcesAndWatchedEmployers') }}</router-link>{{ $t('settings.page.text2') }}</p></HelpPop></label>
            <div class="set-val"><input id="f-pmin" v-model.number="s['employers.priority_min_score']" class="w-num" type="number" step="0.5" min="0" max="10" /><span class="unit">{{ $t('settings.page.outOf') }}</span></div>
            <label for="f-cap">{{ $t('settings.page.howManyApplicationsMay') }}<HelpPop :text="$t('settings.page.whenThisManyApplications')" /></label>
            <div class="set-val"><input id="f-cap" v-model.number="s['drafts.max_pending']" class="w-num" type="number" min="0" step="1" /></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="submit" :title="$t('settings.page.howItIsSent')">
        <div class="card">
          <CardHead :title="$t('settings.page.howApplicationsAreSent')">
            <template #help>
              <p>{{ $t('settings.page.theAgentWorksEach') }}</p>
              <p>{{ $t('settings.page.howFormsAreFilled') }} <router-link to="/profile">{{ $t('settings.page.openTheProfile') }}</router-link></p>
            </template>
          </CardHead>
          <div class="kv">
            <label for="f-submit-policy">{{ $t('settings.page.sending') }}</label>
            <div class="set-val">
              <AaSelect id="f-submit-policy" v-model="s['submit.policy']" class="w-line">
                <option value="auto">{{ $t('settings.page.sendWhenNothingIs') }}</option>
                <option value="approve">{{ $t('settings.page.showMeEachOne') }}</option>
                <option value="hand_over">{{ $t('settings.page.goToTheLast') }}</option>
              </AaSelect>
              <span class="hint">{{ s['submit.policy'] === 'auto' ? $t('settings.page.whenYourProfileAnswers') : s['submit.policy'] === 'approve' ? $t('settings.page.theAgentStopsBefore') : $t('settings.page.theAgentIsTold') }}</span>
            </div>
            <label for="f-manual">{{ $t('settings.page.forTheseCompaniesI') }}</label>
            <div class="set-val"><input id="f-manual" class="w-full" :value="(s['policy.manual_companies'] || []).join(', ')" :placeholder="$t('settings.page.eGGoogleApple')" @change="s['policy.manual_companies'] = $event.target.value.split(SEP).map((x) => x.trim()).filter(Boolean)" />
              <span class="hint">{{ $t('settings.page.whateverIsChosenAbove') }}</span></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="limits" :title="$t('settings.page.howTheAgentWorks')">
        <div class="card">
          <CardHead :title="$t('settings.page.theMostOneApplication')" :help="$t('settings.page.fromThePostingTo')" />
          <div class="kv">
            <label for="f-budget-steps">{{ $t('settings.page.stepsAtMost') }}</label>
            <div class="set-val"><input id="f-budget-steps" v-model.number="s['agent.budgets'].apply.steps" class="w-num" type="number" min="1" max="2000" /></div>
            <label for="f-budget-minutes">{{ $t('settings.page.minutesAtMost') }}</label>
            <div class="set-val"><input id="f-budget-minutes" v-model.number="s['agent.budgets'].apply.minutes" class="w-num" type="number" min="1" max="240" /></div>
          </div>
        </div>
        <div class="card">
          <CardHead :title="$t('settings.page.howManyAtOnce')" />
          <div class="kv">
            <label for="f-parallel">{{ $t('settings.page.applicationsWorkedAtThe') }}<HelpPop :text="$t('settings.page.eachApplicationHasIts')" /></label>
            <div class="set-val"><input id="f-parallel" v-model.number="s['agent.parallel']" class="w-num" type="number" min="1" max="6" /></div>
            <label for="f-keep">{{ $t('settings.page.whenARecordWaits') }}<HelpPop :text="$t('settings.page.whenARecordIs')" /></label>
            <div class="set-val"><input id="f-keep" v-model.number="s['agent.keep_window_minutes']" class="w-num" type="number" min="0" max="120" /><span class="unit">{{ $t('settings.page.minutesAtMost2') }}</span>
              <input v-model.number="s['agent.keep_window_most']" class="w-num" type="number" min="1" max="6" :aria-label="$t('settings.page.atMostHowMany')" /><span class="unit">{{ $t('settings.page.items') }}</span></div>
            <label for="f-mail-send">{{ $t('settings.page.eMailsTheProgram') }}<HelpPop :text="$t('settings.page.applicationsThatAreSent')" /></label>
            <div class="set-val">
              <AaSelect id="f-mail-send" v-model="s['mail.send']" class="w-line">
                <option value="review">{{ $t('settings.page.iLookAtIt') }}</option>
                <option value="auto">{{ $t('settings.page.sendByItselfWhen') }}</option>
              </AaSelect>
              <span class="hint">{{ $t('settings.page.mailCannotBeUndone') }}</span></div>
            <label for="f-show-window">{{ $t('settings.page.theBrowserWindowWhile') }}<HelpPop :text="$t('settings.page.whenOnTheBrowser')" /></label>
            <div class="set-val"><label><input id="f-show-window" v-model="s['agent.show_window']" type="checkbox" /> {{ $t('settings.page.showItOnScreen') }}</label></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="schedule" :title="$t('settings.page.plan')">
        <div class="card">
          <div class="kv">
            <label for="f-scan">{{ $t('settings.page.scanForNewJobs') }}</label>
            <div class="set-val"><span class="unit">{{ $t('settings.page.every') }}</span><input id="f-scan" v-model.number="s['schedule.discover_minutes']" class="w-num" type="number" min="0" /><span class="unit">{{ $t('settings.page.minutes') }}</span></div>
            <label for="f-mail-new">{{ $t('settings.page.lookForNewMail') }}<HelpPop :text="$t('settings.page.switchesItOffIt')" /></label>
            <div class="set-val"><span class="unit">{{ $t('settings.page.every') }}</span><input id="f-mail-new" v-model.number="s['schedule.mail_new_minutes']" class="w-num" type="number" min="0" /><span class="unit">{{ $t('settings.page.minutes') }}</span></div>
            <label for="f-mail">{{ $t('settings.page.readTheLastFew') }}<HelpPop :text="$t('settings.page.switchesItOffThe')" /></label>
            <div class="set-val"><span class="unit">{{ $t('settings.page.every') }}</span><input id="f-mail" v-model.number="s['schedule.mail_minutes']" class="w-num" type="number" min="0" /><span class="unit">{{ $t('settings.page.minutes') }}</span></div>
          </div>
          <p class="set-note">{{ $t('settings.page.enterToTurnOff') }}</p>
          <div class="set-actions">
            <span class="t-secondary">{{ $t('settings.page.pause') }}</span>
            <HelpPop :label="$t('settings.page.pause')"><p><b>{{ $t('settings.page.pause') }}</b>{{ $t('settings.page.isAtTheBottom') }}<router-link :to="{ path: '/runs', query: { tab: 'plan' } }">{{ $t('settings.page.activityWorkPlan') }}</router-link>{{ $t('settings.page.text') }}</p></HelpPop>
            <router-link :to="{ path: '/runs', query: { tab: 'plan' } }">{{ $t('settings.page.activityWorkPlan') }}</router-link>
          </div>
          <details class="tech"><summary>{{ $t('settings.page.usageAndPaceAdvanced') }}</summary>
            <div class="kv in-details">
              <label for="f-batch">{{ $t('settings.page.maxPostingsForAi') }}
                <HelpPop :label="$t('settings.page.maxPostingsForAi')"><p>{{ $t('settings.page.theRestWaitsFor') }}<router-link to="/settings/accounts/ai">{{ $t('settings.page.aiService') }}</router-link>{{ $t('settings.page.underAllowanceWarnings') }}</p></HelpPop></label>
              <div class="set-val"><input id="f-batch" v-model.number="s['scoring.max_per_run']" class="w-num" type="number" /><span class="unit">{{ $t('settings.page.items') }}</span></div>
            </div>
          </details>
        </div>
      </SetSection>
    </template>

    <!-- Files: résumé and cover letter -->
    <template v-if="group === 'materials'">
      <SetSection id="resume" :title="$t('settings.page.rSum')">
        <div class="card">
          <CardHead :title="$t('settings.page.tailorRSumTo')" :help="$t('settings.page.forEachPostingThe')" />
          <div v-if="s['tailor.mode'] !== 'off' && !hasWord" class="callout warn"><Icon name="alert" /><span>{{ $t('settings.page.thereIsNoWord') }}<router-link to="/files">{{ $t('settings.page.uploadOneInThe') }}</router-link>{{ $t('settings.page.withThePurposeR') }}</span></div>
          <div class="choice">
            <label :class="{ on: s['tailor.mode'] === 'off' }"><input v-model="s['tailor.mode']" type="radio" value="off" /><div><b>{{ $t('settings.page.noChanges') }}</b><span>{{ $t('settings.page.allPostingsUseThe') }}</span></div></label>
            <label :class="{ on: s['tailor.mode'] === 'select' }"><input v-model="s['tailor.mode']" type="radio" value="select" /><div><b>{{ $t('settings.page.reorderOnly') }}</b><span>{{ $t('settings.page.reordersBulletPointsProjects') }}</span></div></label>
            <label :class="{ on: s['tailor.mode'] === 'rephrase' }"><input v-model="s['tailor.mode']" type="radio" value="rephrase" /><div><b>{{ $t('settings.page.reorderAndAllowRewording') }}</b><span>{{ $t('settings.page.rewordsBulletPointsTo') }}</span></div></label>
          </div>
          <div v-if="s['tailor.mode'] !== 'off'" class="kv after-choice">
            <label>{{ $t('settings.page.whenToAdjust') }}</label>
            <AaSelect :model-value="s['tailor.auto'] ? 'auto' : 'ask'" @update:model-value="s['tailor.auto'] = $event === 'auto'"><option value="auto">{{ $t('settings.page.tailorAutomaticallyWhenDrafting') }}</option><option value="ask">{{ $t('settings.page.onlyWhenIClick') }}</option></AaSelect>
            <template v-if="s['tailor.auto']">
              <label for="f-tmin">{{ $t('settings.page.minimumScoreForTailoring') }}</label>
              <div class="set-val"><input id="f-tmin" v-model.number="s['tailor.min_score']" class="w-num" type="number" step="0.5" min="0" max="10" /><span class="hint">{{ $t('settings.page.postingsBelowThisScore') }}</span></div>
            </template>
            <label>{{ $t('settings.page.whichExperiencesCanBe') }}</label>
            <AaSelect v-model="s['tailor.reorder_entries']"><option value="projects">{{ $t('settings.page.reorderProjectsOnlyKeep') }}</option><option value="all">{{ $t('settings.page.everySectionCanBe') }}</option><option value="none">{{ $t('settings.page.changeNothingExceptThe') }}</option></AaSelect>
            <label for="f-tskills">{{ $t('settings.page.reorderSkills') }}<HelpPop :text="$t('settings.page.movesTheSkillsThe')" /></label>
            <div class="set-val"><input id="f-tskills" v-model="s['tailor.reorder_skills']" type="checkbox" /></div>
            <label for="f-tdrop">{{ $t('settings.page.irrelevantPointsCanBe') }}<HelpPop :text="$t('settings.page.goodForRSum')" /></label>
            <div class="set-val"><input id="f-tdrop" v-model="s['tailor.allow_drop']" type="checkbox" /></div>
            <label for="f-tbul">{{ $t('settings.page.minimumBulletPointsPer') }}</label>
            <div class="set-val"><input id="f-tbul" v-model.number="s['tailor.min_bullets']" class="w-num" type="number" min="1" max="10" /><span class="unit">{{ $t('settings.page.items2') }}</span></div>
            <label for="f-tpages">{{ $t('settings.page.pageLimit') }}<HelpPop :text="$t('settings.page.keepsYourRSum')" /></label>
            <div class="set-val"><input id="f-tpages" v-model.number="s['tailor.target_pages']" class="w-num" type="number" min="0" max="5" /><span class="unit">{{ $t('settings.page.page') }}</span></div>
            <label for="f-trev">{{ $t('settings.page.letMeReviewTailored') }}<HelpPop :text="$t('settings.page.whenTickedAnApplication')" /></label>
            <div class="set-val"><input id="f-trev" v-model="s['tailor.review']" type="checkbox" /></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="cover" :title="$t('settings.page.coverLetter')">
        <div class="card">
          <p class="t-secondary">{{ $t('settings.page.lettersAreWrittenFrom') }}</p>
          <div class="set-actions flush">
            <Status :tone="template ? 'ok' : 'warn'" :label="template ? $t('settings.page.templateInUse', { name: template.name }) : $t('settings.page.noTemplate')" />
            <router-link to="/files" class="btn sm">{{ $t('settings.page.files') }}</router-link>
          </div>
          <div class="field"><label for="f-bold">{{ $t('settings.page.namesSetInBold') }}</label>
            <input id="f-bold" :value="csv('cover_letter.bold_terms')" :placeholder="$t('settings.page.forExampleNamesOf')" @change="setCsv('cover_letter.bold_terms', $event.target.value)" /></div>
          <div class="field"><label for="f-links">{{ $t('settings.page.linksToKeepIn') }}</label>
            <textarea id="f-links" class="plain" rows="2" :value="pairs('cover_letter.links', 'text', 'url')" :placeholder="$t('settings.page.onePerLineThe')" @change="setPairs('cover_letter.links', 'text', 'url', $event.target.value)"></textarea></div>
          <div class="field last"><label for="f-repl">{{ $t('settings.page.fixedTextOfThe') }}</label>
            <textarea id="f-repl" class="plain" rows="2" :value="pairs('cover_letter.replace', 'find', 'with')" :placeholder="$t('settings.page.onePerLineThe2')" @change="setPairs('cover_letter.replace', 'find', 'with', $event.target.value)"></textarea></div>
        </div>
      </SetSection>
    </template>

    <!-- Accounts and connections -->
    <template v-if="group === 'accounts'">
      <SetSection id="logins" :title="$t('settings.page.signInsToCareer')">
        <div class="card">
          <div class="kv">
            <label for="f-email">{{ $t('settings.page.emailForSignUp') }}
              <HelpPop :label="$t('settings.page.signInsToCareer')"><p>{{ $t('settings.page.whenASiteNeeds') }}</p><p>{{ $t('settings.page.toHaveASite') }} <router-link to="/profile">{{ $t('settings.page.openTheProfile') }}</router-link></p></HelpPop></label>
            <input id="f-email" v-model="s['account.email']" />
          </div>
          <div class="set-actions"><router-link to="/accounts" class="btn sm">{{ $t('settings.page.seeWhereEachSites') }}</router-link></div>
        </div>
      </SetSection>

      <SetSection id="mailbox" :title="$t('settings.page.mailbox')" how="own">
        <MailboxPanel />
      </SetSection>

      <SetSection id="ai" :title="$t('settings.page.aiService')" how="own">
        <AiPanel :s="s" :sec="sec" :secrets="info.secrets" @changed="load" />
      </SetSection>
    </template>

    <!-- Notifications and reminders -->
    <template v-if="group === 'notify'">
      <SetSection id="channel" :title="$t('settings.page.whereNoticesGo')">
        <div class="card">
          <CardHead title="Telegram">
            <template #help><p>{{ $t('settings.page.progressThingsThatNeed') }}</p><p><router-link :to="{ path: '/runs', query: { tab: 'notes' } }">{{ $t('settings.page.activityNotificationsAndBots') }}</router-link></p></template>
            <template #after><Status :tone="tgOn ? 'ok' : 'warn'" :label="tgOn ? $t('settings.page.connected') : $t('settings.page.notSetUpYet2')" /></template>
          </CardHead>
          <div class="kv">
            <label for="f-tg">{{ $t('settings.page.botToken') }}</label><input id="f-tg" v-model="sec.telegram_bot_token" type="password" autocomplete="off" :placeholder="info.secrets.telegram_bot_token ? $t('settings.page.savedToChangeIt') : $t('settings.page.youGetThisAfter')" />
            <label for="f-chat">{{ $t('settings.page.chatId') }}</label><input id="f-chat" v-model="s['notify.telegram_chat_id']" :placeholder="$t('settings.page.sendTheBotA')" />
            <label for="f-base">{{ $t('settings.page.linksInNotificationsOpen') }}
              <HelpPop :label="$t('settings.page.linksInNotificationsOpen')"><p>{{ $t('settings.page.theAddressALink') }}</p><p><router-link to="/settings/system/remote">{{ $t('settings.page.remoteAccess') }}</router-link></p></HelpPop></label>
            <input id="f-base" v-model="s['app.base_url']" />
          </div>
          <div class="set-actions"><button @click="tgTest"><Icon name="send" />{{ $t('settings.page.sendATestMessage') }}</button><span class="hint">{{ $t('settings.page.saveFirstThenTest') }}</span></div>
        </div>
        <div class="card">
          <CardHead title="Discord" :help="$t('settings.page.likeTelegramNotificationsArrive')">
            <template #after><Status :tone="dcState.cls" :label="dcState.text" /></template>
          </CardHead>
          <div class="kv">
            <label for="f-dc">{{ $t('settings.page.botToken') }}<HelpPop :text="$t('settings.page.createAnApplicationIn')" /></label><input id="f-dc" v-model="sec.discord_bot_token" type="password" autocomplete="off" :placeholder="info.secrets.discord_bot_token ? $t('settings.page.savedToChangeIt') : ''" />
            <template v-if="dc && dc.token">
              <label>{{ $t('settings.page.bot') }}<HelpPop v-if="dc.bot && !dc.error" :text="$t('settings.page.aBotCanOnly')" /></label>
              <div class="set-val">
                <template v-if="dc.error"><span>{{ $t('settings.page.thisTokenCannotReach') }}</span><span class="hint">{{ dc.error }}</span></template>
                <template v-else-if="dc.bot"><span class="t-primary">{{ dc.bot.name }}</span><a :href="dc.bot.invite" target="_blank" rel="noopener">{{ $t('settings.page.addTheBotTo') }}</a></template>
              </div>
              <label>{{ $t('settings.page.yourAccount') }}</label>
              <div class="set-val">
                <template v-if="dc.bound"><Status tone="ok" :label="$t('settings.page.linked')" /><button class="ghost sm" @click="dcUnbind">{{ $t('settings.page.unlink') }}</button></template>
                <template v-else-if="dc.code">
                  <span>{{ $t('settings.page.inDiscordSendThe') }}</span><code class="set-code">{{ dc.code }}</code>
                  <span class="hint">{{ $t('settings.page.validForMinutesOnce') }}</span>
                </template>
                <button v-else :disabled="!!dc.error" @click="dcBind">{{ $t('settings.page.linkMyDiscordAccount') }}</button>
              </div>
            </template>
            <label for="f-dch">{{ $t('settings.page.webhookOptional') }}</label><input id="f-dch" v-model="sec.discord_webhook" type="password" autocomplete="off" :placeholder="info.secrets.discord_webhook ? $t('settings.page.savedToChangeIt') : $t('settings.page.channelSettingsIntegrationsWebhooks')" />
          </div>
          <div class="set-actions"><button @click="dcTest"><Icon name="send" />{{ $t('settings.page.sendATestMessage') }}</button><span class="hint">{{ $t('settings.page.saveFirstThenTest2') }}</span></div>
        </div>
      </SetSection>

      <SetSection id="bots" :title="$t('settings.page.handleItFromYour')">
        <div class="card">
          <div class="set-check"><label><input v-model="s['bot.listen']" type="checkbox" /> {{ $t('settings.page.theBotsTakeButton') }}</label>
            <HelpPop :label="$t('settings.page.handleItFromYour')"><p>{{ $t('settings.page.theButtonsDoWhat') }}</p><p>{{ $t('settings.page.commandsStatusWhatIs') }}</p></HelpPop></div>
          <div class="set-check"><label><input v-model="s['bot.chat']" type="checkbox" :disabled="!s['bot.listen']" /> {{ $t('settings.page.anythingElseYouSay') }}</label><HelpPop :text="$t('settings.page.askItHowThings')" /></div>
          <div v-if="s['bot.daily_summary']" class="set-check">
            <label><input v-model="s['bot.daily_summary'].on" type="checkbox" /> {{ $t('settings.summary.on') }}</label>
            <input v-model="s['bot.daily_summary'].at" class="w-time" type="time" :disabled="!s['bot.daily_summary'].on" :aria-label="$t('settings.summary.at')" />
            <HelpPop :text="$t('settings.summary.hint')" />
          </div>
        </div>
      </SetSection>

      <SetSection id="events" :title="$t('settings.page.whatToNotifyAbout')">
        <div class="card">
          <div class="kv">
            <label>{{ $t('settings.page.whichNotifications') }}</label>
            <div class="set-opts">
              <label><input v-model="s['notify.todo']" type="checkbox" /> {{ $t('settings.page.thingsThatNeedYou') }}</label>
              <label><input v-model="s['notify.task_result']" type="checkbox" /> {{ $t('settings.page.outcomeSentFailed') }}</label>
              <label><input v-model="s['notify.status_update']" type="checkbox" /> {{ $t('settings.page.applicationProgress') }}</label>
              <label><input v-model="s['notify.task_started']" type="checkbox" /> {{ $t('settings.page.startDoingSomething') }}</label>
            </div>
            <template v-if="channelsOn.length > 1">
              <label>{{ $t('settings.page.byChannel') }}</label>
              <table class="set-matrix">
                <thead><tr><th></th><th v-for="c in channelsOn" :key="c[0]">{{ c[1] }}</th></tr></thead>
                <tbody>
                  <tr v-for="[k, label] in CATS" :key="k">
                    <td>{{ label }}</td>
                    <td v-for="c in channelsOn" :key="c[0]"><input type="checkbox" :checked="takes(c[0], k)" :disabled="!s['notify.' + k]" :aria-label="$t('settings.page.channelKind', { channel: c[1], kind: label })" @change="setTakes(c[0], k, $event.target.checked)" /></td>
                  </tr>
                </tbody>
              </table>
            </template>
            <label for="quiet-on">{{ $t('settings.page.quietHours') }}<HelpPop :text="$t('settings.page.nothingFromTheseHours')" /></label>
            <div v-if="s['notify.quiet']" class="set-val">
              <label><input id="quiet-on" v-model="s['notify.quiet'].on" type="checkbox" /> {{ $t('settings.page.sendNothingToThe') }}</label>
              <span class="unit">{{ $t('settings.page.from') }}</span><input v-model="s['notify.quiet'].from" class="w-time" type="time" :disabled="!s['notify.quiet'].on" :aria-label="$t('settings.page.quietHoursStart')" />
              <span class="unit">{{ $t('settings.page.to') }}</span><input v-model="s['notify.quiet'].to" class="w-time" type="time" :disabled="!s['notify.quiet'].on" :aria-label="$t('settings.page.quietHoursEnd')" />
            </div>
          </div>
          <p class="set-note">{{ $t('settings.page.invitationsToInterviewsAnd') }}<router-link to="/todos">{{ $t('settings.page.needsYourAction') }}</router-link>{{ $t('settings.page.cardByCard') }}</p>
        </div>
      </SetSection>

      <SetSection id="reminders" :title="$t('settings.reminders.title')">
        <template #actions><HelpPop :text="$t('settings.reminders.intro')" :label="$t('settings.reminders.title')" /></template>
        <div class="card">
          <div v-if="s['calendar.reminders']" class="kv">
            <template v-for="k in REMINDER_KINDS" :key="k">
              <label :for="'rem-' + k">{{ $t('calendar.kind.' + k) }}</label>
              <div class="set-val"><input :id="'rem-' + k" class="w-short" :value="minutesText(k)" :placeholder="$t('settings.reminders.none')" @change="setMinutes(k, $event.target.value)" />
                <span class="unit">{{ remindText(k) }}</span></div>
            </template>
            <label for="rem-morning">{{ $t('settings.reminders.morning') }}</label><div class="set-val"><input id="rem-morning" v-model="s['calendar.allday_at']" class="w-time" type="time" /></div>
            <label for="rem-quiet">{{ $t('settings.reminders.quietLabel') }}<HelpPop :text="$t('settings.reminders.hint')" /></label>
            <div class="set-val"><label><input id="rem-quiet" v-model="s['calendar.reminders_quiet']" type="checkbox" /> {{ $t('settings.reminders.quiet') }}</label></div>
          </div>
        </div>
      </SetSection>
    </template>

    <!-- System and data -->
    <template v-if="group === 'system'">
      <SetSection id="network" :title="$t('settings.page.networkConnectionOutbound')">
        <template #actions><HelpPop :text="$t('settings.page.howTheProgramReaches')" /></template>
        <NetworkPanel ref="netPanel" :s="s" :sec="sec" :has-password="!!info.secrets.proxy_password" />
      </SetSection>
      <SetSection id="browser" :title="$t('settings.page.browserCompatibility')">
        <template #actions><HelpPop :text="$t('settings.page.byDefaultThePrograms')" /></template>
        <BrowserPanel :s="s" />
      </SetSection>
      <AccessPanel />
      <SetSection id="retention" :title="$t('settings.page.dataRetention')">
        <template #actions><HelpPop :text="$t('settings.page.theseThreeOnlyDecide')" /></template>
        <div class="card">
          <div class="kv">
            <label for="f-arch">{{ $t('settings.page.archivePostingsHowLong') }}<HelpPop :text="$t('settings.page.postingsThatWereTaken')" /></label>
            <div class="set-val"><input id="f-arch" v-model.number="s['archive.closed_after_days']" class="w-num" type="number" /><span class="unit">{{ $t('settings.page.days') }}</span></div>
            <label for="f-silent">{{ $t('settings.page.archiveAfterHowLong') }}<HelpPop :text="$t('settings.page.theApplicationStaysSubmitted')" /></label>
            <div class="set-val"><input id="f-silent" v-model.number="s['archive.silent_after_days']" class="w-num" type="number" /><span class="unit">{{ $t('settings.page.days') }}</span></div>
            <label for="f-dedupe">{{ $t('settings.page.timeBetweenHiringRounds') }}<HelpPop :text="$t('settings.page.postingsWithTheSame')" /></label>
            <div class="set-val"><input id="f-dedupe" v-model.number="s['dedupe.window_days']" class="w-num" type="number" /><span class="unit">{{ $t('settings.page.days') }}</span></div>
          </div>
        </div>
      </SetSection>
      <SetSection id="backup" :title="$t('settings.page.backupAndUpdates')" how="">
        <div class="card">
          <p class="t-secondary">{{ $t('settings.page.allYourDataStays') }} <code>{{ sys.data_dir }}</code> {{ $t('settings.page.and') }} <code>{{ sys.knowledge_dir }}</code>{{ $t('settings.page.updatesWontTouchThese') }}</p>
          <div class="set-actions flush">
            <button @click="exportData(false)"><Icon name="download" />{{ $t('settings.page.exportAllData') }}</button>
            <button @click="exportData(true)">{{ $t('settings.page.exportWithSignIn') }}</button>
            <Popover :label="$t('settings.page.whatAnExportHolds')" :width="420">
              <template #trigger="{ toggle, attrs }"><button class="ghost" v-bind="attrs" @click="toggle"><Icon name="info" />{{ $t('settings.page.whatAnExportHolds') }}</button></template>
              <div class="help-pop">
                <h4>{{ $t('settings.page.whatAnExportHolds') }}</h4>
                <ul>
                  <li>{{ $t('settings.page.everyRecordPostingsApplications') }}</li>
                  <li>{{ $t('settings.page.theFilesYouUploaded') }}</li>
                  <li>{{ $t('settings.page.yourProfileTheScoring') }}</li>
                  <li>{{ $t('settings.page.withExportWithSign') }}</li>
                </ul>
                <h4>{{ $t('settings.page.whatAnExportDoes') }}</h4>
                <ul>
                  <li v-if="sys.secrets === 'file'">{{ $t('settings.page.passwordsAndApiKeys') }}</li>
                  <li v-else>{{ $t('settings.page.passwordsAndApiKeys2') }}</li>
                  <li>{{ $t('settings.page.theScreenshotsAndPage') }}</li>
                  <li>{{ $t('settings.page.theOrdinaryBrowsersProfile') }}</li>
                  <li>{{ $t('settings.page.theSettingsForRemote') }}</li>
                </ul>
              </div>
            </Popover>
            <span class="grow"></span>
            <span class="meta small">{{ $t('settings.page.currentVersion', { p0: sys.version }) }}</span>
            <router-link to="/about" class="btn ghost"><Icon name="refresh" />{{ $t('settings.page.updatesOnAbout') }}</router-link>
          </div>
          <p v-if="exported" class="set-note">{{ $t('settings.page.exportedFilesMb', { p0: exported.files, p1: (exported.size / 1e6).toFixed(1) }) }} <a :href="'/api/system/export/' + exported.name">{{ $t('settings.page.download', { p0: exported.name }) }}</a>
            <span>{{ $t('settings.page.alsoSavedIn', { p0: exported.path }) }}</span></p>
          <p class="set-note">
            <template v-if="lastExport">{{ lastExportLine }} <a :href="'/api/system/export/' + lastExport.name">{{ $t('settings.page.downloadThisOne') }}</a></template>
            <template v-else>{{ $t('settings.page.nothingHasBeenExported') }}</template>
          </p>
          <details class="tech"><summary>{{ $t('settings.page.restoreAndMove') }}</summary>
            <div class="backup-notes">
              <div>
                <h4>{{ $t('settings.page.restoringOnThisComputer') }}</h4>
                <ul>
                  <li>{{ $t('settings.page.quitTheProgramFirst') }} <router-link :to="{ path: '/runs', query: { tab: 'plan' } }">{{ $t('settings.page.openTheWorkPlan') }}</router-link></li>
                  <li>{{ $t('settings.page.runTheCommandBelow') }}<div><code>{{ $t('settings.page.uvRunAutoapplyRestore') }}</code></div></li>
                  <li>{{ $t('settings.page.passwordsAndApiKeys3') }}</li>
                </ul>
              </div>
              <div>
                <h4>{{ $t('settings.page.movingToAnotherComputer') }}</h4>
                <ul>
                  <li>{{ $t('settings.page.installTheProgramOn') }}</li>
                  <li>{{ $t('settings.page.passwordsAndApiKeys4') }}</li>
                  <li>{{ $t('settings.page.signInsDoNot') }} <router-link to="/accounts">{{ $t('settings.page.openSiteAccounts') }}</router-link></li>
                </ul>
              </div>
            </div>
            <p class="set-note">{{ $t('settings.page.toUpdateTheProgram') }}</p>
          </details>
        </div>
      </SetSection>
      <SetSection id="diagnose" :title="$t('settings.page.diagnostics')" how="">
        <DoctorPanel />
      </SetSection>
      <SetSection id="expert" :title="$t('settings.page.expertTools')" how="own">
        <template #actions><HelpPop :label="$t('settings.page.expertTools')"><p>{{ $t('settings.page.notNeededDayTo') }}<router-link to="/profile">{{ $t('settings.page.profile') }}</router-link>{{ $t('settings.page.andTheScoringRules') }}</p></HelpPop></template>
        <PromptsPanel />
      </SetSection>
    </template>
  </div>
</template>

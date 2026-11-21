<script setup>
import { t as T } from '../i18n/catalog'
// The settings, in six groups by what they are about. Every section has an address (/settings/<group>/<section>), so
// a card, a notice or another page can lead to the very thing that needs changing.
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import AiPanel from '../components/AiPanel.vue'
import MailboxPanel from '../components/MailboxPanel.vue'
import AccessPanel from '../components/AccessPanel.vue'
import Icon from '../components/Icon.vue'
import NetworkPanel from '../components/NetworkPanel.vue'
import BrowserPanel from '../components/BrowserPanel.vue'
import DoctorPanel from '../components/DoctorPanel.vue'
import PromptsPanel from '../components/PromptsPanel.vue'
import PageHead from '../components/PageHead.vue'
import SetSection from '../components/SetSection.vue'
import FormError from '../components/FormError.vue'
import { useRoute, useRouter } from 'vue-router'
import { fmtTime, persona, run as runAction, toast } from '../ui'
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
// [group, its name, what it is for, [[section, its name], ...]]. The sections of a group are on one page, in this order.
const GROUPS = [
  ['overview', T('settings.page.overview'), T('settings.page.whatTheSettingsCome'), []],
  ['goals', T('settings.page.searchGoalsAndMatching'), T('settings.page.whatKindOfPostings'), [['profile', T('settings.page.yourSearchProfile')], ['filters', T('settings.page.hardConditionsBeforeIntake')], ['search', T('settings.page.whatToSearchFor')], ['sources', T('settings.page.sourcesAndWatchedEmployers')]]],
  ['automation', T('settings.page.automationAndWorkPlan'), T('settings.page.howFarTheProgram'), [['prepare', T('settings.page.startingApplicationsByItself')], ['submit', T('settings.page.howItIsSent')], ['limits', T('settings.page.howTheAgentWorks')], ['schedule', T('settings.page.plan')]]],
  ['materials', T('settings.page.files2'), T('settings.page.howTheRSum'), [['resume', T('settings.page.rSum')], ['cover', T('settings.page.coverLetter')]]],
  ['accounts', T('settings.page.accountsAndConnections'), T('settings.page.signInsToCareer2'), [['logins', T('settings.page.signInsToCareer')], ['mailbox', T('settings.page.mailbox')], ['ai', T('settings.page.aiService')]]],
  ['notify', T('settings.page.noticesAndReminders'), T('settings.page.whatYouAreTold'), [['channel', T('settings.page.whereNoticesGo')], ['bots', T('settings.page.handleItFromYour')], ['events', T('settings.page.whatToNotifyAbout')], ['reminders', T('settings.page.calendarReminders')]]],
  ['system', T('settings.page.systemAndData'), T('settings.page.networkBrowserRemoteAccess'), [['network', T('settings.page.networkConnectionOutbound')], ['browser', T('settings.page.browserCompatibility')], ['remote', T('settings.page.remoteAccessInbound')], ['security', T('settings.page.accountSecurity')], ['retention', T('settings.page.dataRetention')], ['backup', T('settings.page.backupAndUpdates')], ['diagnose', T('settings.page.diagnostics')], ['expert', T('settings.page.expertTools')]]],
]
const group = computed(() => (GROUPS.some((g) => g[0] === route.params.group) ? route.params.group : 'overview'))
// what the settings come to, as the server reads them (rules.py): asked for when the overview is opened, and again after a save
const rules = ref(null)
const loadRules = () => api.get('/rules').then((d) => (rules.value = d)).catch((e) => toast(e.message, 'bad'))
watch(group, (g) => { if (g === 'overview') loadRules() }, { immediate: true })
const WHO = { auto: [T('settings.page.theProgramDoesIt'), 'ok'], you: [T('settings.page.waitingForYou'), 'warn'], mixed: [T('settings.page.itDepends'), 'info'], off: [T('settings.page.notDone'), ''] }
const KIND_TONE = { fact: 'info', filter: 'warn', preference: '', threshold: 'ok', source: '' }
const here = computed(() => GROUPS.find((g) => g[0] === group.value))
function settle() {
  // an address that names no group, or one that is not there (an old link): the first group
  if (route.params.group !== group.value) { router.replace('/settings/' + group.value); return }
  const sec = route.params.section
  if (sec) nextTick(() => { const el = document.getElementById('set-' + sec); if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' }) })
}
watch(() => [route.params.group, route.params.section, !!s.value], settle)

const COUNTRIES = [['CA', T('settings.page.canada')], ['US', T('settings.page.unitedStates')]]
const examples = ref('Software Engineering Intern, Summer 2027 | Seattle, WA, US\nSenior Software Engineer | Toronto, ON, CA\nSoftware Developer Co-op | Vancouver, BC, Canada\nMBA Intern | New York, NY, US\nSoftware Engineering Intern | Singapore')
const tried = ref([])
const csv = (key) => (s.value[key] || []).join(', ')
const setCsv = (key, v) => { s.value[key] = v.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean) }
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
    }, T('settings.page.savedChangeS', { p0: n }), async () => {
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
const dcUnbind = () => runAction(() => api.post('/settings/discord/unbind'), T('settings.page.unlinked'), loadDiscord)
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
// the reminders each kind of calendar item gets by itself (alarms.py): minutes before, written as "1440, 30"
const REMINDER_KINDS = ['interview', 'assessment', 'offer', 'info_request', 'contact', 'own', 'deadline']
const minutesText = (k) => ((s.value['calendar.reminders'] || {})[k] || []).join(', ')
function setMinutes(k, text) {
  const v = String(text).split(/[,，\s]+/).map((x) => parseInt(x, 10)).filter((n) => Number.isFinite(n) && n >= 0)
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
      <span v-if="pending" class="badge warn" role="status">{{ $t('settings.page.changeSNotSaved', { p0: pending }) }}</span>
      <button v-if="pending" class="ghost" :disabled="saving" @click="discard">{{ $t('settings.page.discardChanges') }}</button>
      <button class="primary" :disabled="!pending || saving" @click="save"><Icon name="check" />{{ saving ? $t('settings.page.saving') : pending ? $t('settings.page.save') : $t('settings.page.saved') }}</button>
    </PageHead>
    <FormError name="settings" />
    <nav class="seg" style="margin-bottom: 8px" :aria-label="$t('settings.page.groupsOfSettings')">
      <router-link v-for="[g, name] in GROUPS" :key="g" :to="'/settings/' + g" class="seg-link" :class="{ on: group === g }">{{ name }}<span v-if="marked(g)" class="unsaved-dot" :title="$t('settings.page.unsavedChanges')" :aria-label="$t('settings.page.unsavedChanges')"></span></router-link>
    </nav>
    <p class="muted" style="margin: 0 0 6px">{{ here[2] }}</p>

    <!-- 总览：这些设置合起来是什么意思 -->
    <template v-if="group === 'overview'">
      <p v-if="pending" class="callout warn"><Icon name="alert" /><span>{{ $t('settings.page.whatIsWrittenBelow', { p0: pending }) }}</span></p>
      <div v-if="rules" class="cols">
        <div class="card">
          <div class="card-title">{{ $t('settings.page.whatIApplyTo') }}</div>
          <p class="muted">{{ $t('settings.page.fromTopToBottom') }}</p>
          <ul class="rule-list">
            <li v-for="(r, i) in rules.apply" :key="i">
              <span class="tag" :class="KIND_TONE[r.kind]">{{ r.label }}</span>
              <div class="grow"><router-link :to="r.where">{{ r.text }}</router-link><div v-if="r.note" class="small muted">{{ r.note }}</div></div>
            </li>
          </ul>
        </div>
        <div class="card">
          <div class="card-title">{{ $t('settings.page.whatTheProgramMay') }}</div>
          <p class="muted">{{ $t('settings.page.everyStepOfAn') }}<template v-if="rules.paused"><b>{{ $t('settings.page.automaticRunningIsPaused') }}</b>{{ $t('settings.page.everythingTheProgramBegins') }}</template></p>
          <ul class="rule-list">
            <li v-for="st in rules.allowed" :key="st.key">
              <span class="tag" :class="WHO[st.who][1]">{{ WHO[st.who][0] }}</span>
              <div class="grow"><b>{{ st.name }}</b>：<router-link :to="st.where">{{ st.text }}</router-link>
                <ul v-if="st.more.length" class="small muted" style="margin: 4px 0 0 18px"><li v-for="(m, i) in st.more" :key="i">{{ m }}</li></ul></div>
            </li>
          </ul>
          <p class="hint" style="margin-top: 10px">{{ $t('settings.page.forEachApplicationIts') }}</p>
        </div>
      </div>
    </template>

    <!-- 求职目标与匹配 -->
    <template v-if="group === 'goals'">
      <SetSection id="profile" :title="$t('settings.page.yourSearchProfile')" how="">
        <div class="card">
          <div class="row"><span class="card-title grow">{{ $t('settings.page.whatYouToldThe') }}</span><button class="sm" @click="rerun">{{ $t('settings.page.planAgainRunThe') }}</button></div>
          <p class="muted" style="margin: 4px 0 0">{{ persona.features.summary || $t('settings.page.notSetUpYet') }}</p>
          <p class="hint" style="margin-top: 6px">{{ $t('settings.page.yourProfileDecidesWhat') }}</p>
          <p class="small" style="margin: 10px 0 0">{{ $t('settings.page.howPostingsAreScored') }}<router-link :to="{ path: '/profile', query: { tab: 'scoring' } }">{{ $t('settings.page.profileScoringRules') }}</router-link>{{ $t('settings.page.theScoreFromWhich') }}<router-link to="/settings/automation/prepare">{{ $t('settings.page.prepareDraftsAutomatically') }}</router-link>{{ $t('settings.page.text') }}</p>
        </div>
      </SetSection>

      <SetSection id="filters" :title="$t('settings.page.hardConditionsBeforeIntake')">
        <div class="card">
          <div class="row"><span class="card-title grow">{{ $t('settings.page.whichPostingsGetAdded') }}</span><label><input v-model="s['intake.enabled']" type="checkbox" /> {{ $t('settings.page.enable') }}</label></div>
          <p class="muted">{{ $t('settings.page.thisIsAFilter') }}</p>
          <div class="field"><label for="f-title-any">{{ $t('settings.page.titleMustIncludeOne') }}</label>
            <input id="f-title-any" :value="csv('intake.title_any')" @change="setCsv('intake.title_any', $event.target.value)" />
            <span class="hint">{{ $t('settings.page.separateWithCommasMatches') }}</span></div>
          <div class="field"><label for="f-role-any">{{ $t('settings.page.andMustHaveOne') }}</label>
            <textarea id="f-role-any" rows="3" style="font-family: inherit" :value="csv('intake.title_role_any')" @change="setCsv('intake.title_role_any', $event.target.value)"></textarea></div>
          <div class="field"><label for="f-title-none">{{ $t('settings.page.titlesCantContainThese') }}</label>
            <input id="f-title-none" :value="csv('intake.title_none')" @change="setCsv('intake.title_none', $event.target.value)" /></div>
          <div class="field"><label for="f-programs">{{ $t('settings.page.yourProgrammeOfStudy') }}</label>
            <input id="f-programs" :value="csv('intake.programs')" :placeholder="$t('settings.page.forExampleComputer')" @change="setCsv('intake.programs', $event.target.value)" />
            <span class="hint">{{ $t('settings.page.someSourcesAUniversitys') }}</span></div>
          <div class="kv">
            <label>{{ $t('settings.page.locatedIn') }}</label>
            <div class="row"><label v-for="[c, name] in COUNTRIES" :key="c"><input type="checkbox" :checked="(s['intake.countries'] || []).includes(c)" @change="toggleCountry(c)" /> {{ name }}</label>
              <span class="hint">{{ $t('settings.page.leaveAllUncheckedFor') }}</span></div>
            <label for="f-age">{{ $t('settings.page.onlyPostingsFromThe') }}</label>
            <div><input id="f-age" v-model.number="s['intake.max_age_days']" type="number" style="width: 100px" /> {{ $t('settings.page.days') }} <span class="hint">{{ $t('settings.page.enterForNoLimit') }}</span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title">{{ $t('settings.page.tryIt') }}</div>
          <p class="muted">{{ $t('settings.page.oneTitlePerLine') }}</p>
          <textarea v-model="examples" rows="5" style="font-family: inherit" :aria-label="$t('settings.page.titlesToTryThe')"></textarea>
          <div class="row" style="margin-top: 8px"><button @click="tryRules">{{ $t('settings.page.tryIt') }}</button></div>
          <div v-if="tried.length" class="list" style="margin-top: 8px">
            <div v-for="(t, i) in tried" :key="i" class="item">
              <span class="badge" :class="t.kept ? 'ok' : ''" style="min-width: 56px; justify-content: center">{{ t.kept ? $t('settings.page.keep') : $t('settings.page.discard') }}</span>
              <div><div class="main">{{ t.title }}</div><div class="sub">{{ t.location }}</div></div>
              <span class="small muted">{{ t.why }}</span>
            </div>
          </div>
        </div>
      </SetSection>

      <SetSection id="search" :title="$t('settings.page.whatToSearchFor')">
        <div class="card">
          <div class="field" style="margin: 0"><label for="f-terms">{{ $t('settings.page.searchTerms') }}</label>
            <input id="f-terms" :value="csv('sources.search_terms')" :placeholder="$t('settings.page.eGInternCo')" @change="setCsv('sources.search_terms', $event.target.value)" />
            <span class="hint">{{ $t('settings.page.careerSitesLikeAmazons') }}</span></div>
        </div>
      </SetSection>

      <SetSection id="sources" :title="$t('settings.page.sourcesAndWatchedEmployers')" how="">
        <div class="card">
          <p class="muted" style="margin: 0">{{ $t('settings.page.whichEmployersAreWatched') }}<router-link to="/jobs/sources">{{ $t('settings.page.sourcesAndWatchedEmployers') }}</router-link>{{ $t('settings.page.thatIsSomethingTo') }}<router-link to="/settings/automation/schedule">{{ $t('settings.page.plan') }}</router-link>{{ $t('settings.page.text') }}</p>
        </div>
      </SetSection>
    </template>

    <!-- 自动化与工作计划 -->
    <template v-if="group === 'automation'">
      <SetSection id="prepare" :title="$t('settings.page.startingApplicationsByItself')">
        <div class="card">
          <p class="muted" style="margin-top: 0">{{ $t('settings.page.whenNewPostingsAre') }}</p>
          <div class="kv" style="margin-top: 12px">
            <label for="f-min">{{ $t('settings.page.ordinaryPostingsFromWhich') }}</label><div><input id="f-min" v-model.number="s['queue.min_score_for_draft']" type="number" step="0.5" style="width: 100px" /> <span class="hint">{{ $t('settings.page.outOf') }}</span></div>
            <label for="f-pmin">{{ $t('settings.page.postingsOfPriorityEmployers') }}</label><div><input id="f-pmin" v-model.number="s['employers.priority_min_score']" type="number" step="0.5" min="0" max="10" style="width: 100px" /> <span class="hint">{{ $t('settings.page.whichEmployersArePriority') }}<router-link to="/jobs/sources">{{ $t('settings.page.sourcesAndWatchedEmployers') }}</router-link>{{ $t('settings.page.text2') }}</span></div>
            <label for="f-cap">{{ $t('settings.page.howManyApplicationsMay') }}</label><div><input id="f-cap" v-model.number="s['drafts.max_pending']" type="number" min="0" step="1" style="width: 100px" /> <span class="hint">{{ $t('settings.page.whenThisManyApplications') }}</span></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="submit" :title="$t('settings.page.howItIsSent')">
        <div class="card">
          <div class="card-title">{{ $t('settings.page.howApplicationsAreSent') }}</div>
          <p class="muted">{{ $t('settings.page.theAgentWorksEach') }}</p>
          <div class="kv">
            <label for="f-submit-policy">{{ $t('settings.page.sending') }}</label>
            <AaSelect id="f-submit-policy" v-model="s['submit.policy']">
              <option value="auto">{{ $t('settings.page.sendWhenNothingIs') }}</option>
              <option value="approve">{{ $t('settings.page.showMeEachOne') }}</option>
              <option value="hand_over">{{ $t('settings.page.goToTheLast') }}</option>
            </AaSelect>
            <label for="f-manual">{{ $t('settings.page.forTheseCompaniesI') }}</label>
            <div><input id="f-manual" style="width: 100%" :value="(s['policy.manual_companies'] || []).join(', ')" :placeholder="$t('settings.page.eGGoogleApple')" @change="s['policy.manual_companies'] = $event.target.value.split(/[,，]/).map((x) => x.trim()).filter(Boolean)" />
              <div class="hint">{{ $t('settings.page.whateverIsChosenAbove') }}</div></div>
          </div>
          <p v-if="s['submit.policy'] === 'auto'" class="hint">{{ $t('settings.page.whenYourProfileAnswers') }}</p>
          <p v-else-if="s['submit.policy'] === 'approve'" class="hint">{{ $t('settings.page.theAgentStopsBefore') }}</p>
          <p v-else class="hint">{{ $t('settings.page.theAgentIsTold') }}</p>
          <p class="hint">{{ $t('settings.page.howFormsAreFilled') }} <router-link to="/profile">{{ $t('settings.page.openTheProfile') }}</router-link></p>
        </div>
      </SetSection>

      <SetSection id="limits" :title="$t('settings.page.howTheAgentWorks')">
        <div class="card">
          <div class="card-title">{{ $t('settings.page.theMostOneApplication') }}</div>
          <p class="muted">{{ $t('settings.page.fromThePostingTo') }}</p>
          <div class="kv">
            <label for="f-budget-steps">{{ $t('settings.page.stepsAtMost') }}</label>
            <div><input id="f-budget-steps" v-model.number="s['agent.budgets'].apply.steps" type="number" min="1" max="2000" style="width: 90px" /></div>
            <label for="f-budget-minutes">{{ $t('settings.page.minutesAtMost') }}</label>
            <div><input id="f-budget-minutes" v-model.number="s['agent.budgets'].apply.minutes" type="number" min="1" max="240" style="width: 90px" /></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title">{{ $t('settings.page.howManyAtOnce') }}</div>
          <div class="kv">
            <label for="f-parallel">{{ $t('settings.page.applicationsWorkedAtThe') }}</label>
            <div><input id="f-parallel" v-model.number="s['agent.parallel']" type="number" min="1" max="6" style="width: 90px" />
              <div class="hint">{{ $t('settings.page.eachApplicationHasIts') }}</div></div>
            <label for="f-keep">{{ $t('settings.page.whenARecordWaits') }}</label><div><input id="f-keep" v-model.number="s['agent.keep_window_minutes']" type="number" min="0" max="120" style="width: 90px" /> {{ $t('settings.page.minutesAtMost2') }} <input v-model.number="s['agent.keep_window_most']" type="number" min="1" max="6" style="width: 70px" :aria-label="$t('settings.page.atMostHowMany')" /> {{ $t('settings.page.items') }}
              <div class="hint">{{ $t('settings.page.whenARecordIs') }}</div></div>
            <label for="f-mail-send">{{ $t('settings.page.eMailsTheProgram') }}</label>
            <div><AaSelect id="f-mail-send" v-model="s['mail.send']" style="max-width: 320px">
                <option value="review">{{ $t('settings.page.iLookAtIt') }}</option>
                <option value="auto">{{ $t('settings.page.sendByItselfWhen') }}</option>
              </AaSelect>
              <div class="hint">{{ $t('settings.page.applicationsThatAreSent') }}</div></div>
            <label for="f-show-window">{{ $t('settings.page.theBrowserWindowWhile') }}</label>
            <div><label><input id="f-show-window" v-model="s['agent.show_window']" type="checkbox" /> {{ $t('settings.page.showItOnScreen') }}</label>
              <div class="hint">{{ $t('settings.page.whenOnTheBrowser') }}</div></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="schedule" :title="$t('settings.page.plan')">
        <div class="card">
          <div class="kv">
            <label for="f-scan">{{ $t('settings.page.scanForNewJobs') }}</label><div>{{ $t('settings.page.every') }} <input id="f-scan" v-model.number="s['schedule.discover_minutes']" type="number" style="width: 90px" /> {{ $t('settings.page.minutes') }} <span class="hint">{{ $t('settings.page.enterToTurnOff') }}</span></div>
            <label for="f-mail-new">{{ $t('settings.page.lookForNewMail') }}</label><div>{{ $t('settings.page.every') }} <input id="f-mail-new" v-model.number="s['schedule.mail_new_minutes']" type="number" min="0" style="width: 90px" /> {{ $t('settings.page.minutes') }} <span class="hint">{{ $t('settings.page.switchesItOffIt') }}</span></div>
            <label for="f-mail">{{ $t('settings.page.readTheLastFew') }}</label><div>{{ $t('settings.page.every') }} <input id="f-mail" v-model.number="s['schedule.mail_minutes']" type="number" min="0" style="width: 90px" /> {{ $t('settings.page.minutes') }} <span class="hint">{{ $t('settings.page.switchesItOffThe') }}</span></div>
          </div>
          <p class="hint" style="margin-top: 12px"><b>{{ $t('settings.page.pause') }}</b>{{ $t('settings.page.isAtTheBottom') }}<router-link :to="{ path: '/runs', query: { tab: 'plan' } }">{{ $t('settings.page.activityWorkPlan') }}</router-link>{{ $t('settings.page.text') }}</p>
          <details class="tech" style="margin-top: 10px"><summary>{{ $t('settings.page.usageAndPaceAdvanced') }}</summary>
            <div class="kv" style="margin-top: 10px">
              <label for="f-batch">{{ $t('settings.page.maxPostingsForAi') }}</label>
              <div><input id="f-batch" v-model.number="s['scoring.max_per_run']" type="number" style="width: 100px" /> {{ $t('settings.page.items') }} <span class="hint">{{ $t('settings.page.theRestWaitsFor') }}<router-link to="/settings/accounts/ai">{{ $t('settings.page.aiService') }}</router-link>{{ $t('settings.page.underAllowanceWarnings') }}</span></div>
            </div>
          </details>
        </div>
      </SetSection>
    </template>

    <!-- 材料与回答 -->
    <template v-if="group === 'materials'">
      <SetSection id="resume" :title="$t('settings.page.rSum')">
        <div class="card">
          <div class="card-title">{{ $t('settings.page.tailorRSumTo') }}</div>
          <p class="muted">{{ $t('settings.page.forEachPostingThe') }}</p>
          <div v-if="s['tailor.mode'] !== 'off' && !hasWord" class="callout warn"><Icon name="alert" /><span>{{ $t('settings.page.thereIsNoWord') }}<router-link to="/files">{{ $t('settings.page.uploadOneInThe') }}</router-link>{{ $t('settings.page.withThePurposeR') }}</span></div>
          <div class="choice">
            <label :class="{ on: s['tailor.mode'] === 'off' }"><input v-model="s['tailor.mode']" type="radio" value="off" /><div><b>{{ $t('settings.page.noChanges') }}</b><span>{{ $t('settings.page.allPostingsUseThe') }}</span></div></label>
            <label :class="{ on: s['tailor.mode'] === 'select' }"><input v-model="s['tailor.mode']" type="radio" value="select" /><div><b>{{ $t('settings.page.reorderOnly') }}</b><span>{{ $t('settings.page.reordersBulletPointsProjects') }}</span></div></label>
            <label :class="{ on: s['tailor.mode'] === 'rephrase' }"><input v-model="s['tailor.mode']" type="radio" value="rephrase" /><div><b>{{ $t('settings.page.reorderAndAllowRewording') }}</b><span>{{ $t('settings.page.rewordsBulletPointsTo') }}</span></div></label>
          </div>
          <div v-if="s['tailor.mode'] !== 'off'" class="kv" style="margin-top: 16px">
            <label>{{ $t('settings.page.whenToAdjust') }}</label>
            <AaSelect :model-value="s['tailor.auto'] ? 'auto' : 'ask'" @update:model-value="s['tailor.auto'] = $event === 'auto'"><option value="auto">{{ $t('settings.page.tailorAutomaticallyWhenDrafting') }}</option><option value="ask">{{ $t('settings.page.onlyWhenIClick') }}</option></AaSelect>
            <template v-if="s['tailor.auto']">
              <label for="f-tmin">{{ $t('settings.page.minimumScoreForTailoring') }}</label>
              <div><input id="f-tmin" v-model.number="s['tailor.min_score']" type="number" step="0.5" min="0" max="10" style="width: 100px" /> <span class="hint">{{ $t('settings.page.postingsBelowThisScore') }}</span></div>
            </template>
            <label>{{ $t('settings.page.whichExperiencesCanBe') }}</label>
            <AaSelect v-model="s['tailor.reorder_entries']"><option value="projects">{{ $t('settings.page.reorderProjectsOnlyKeep') }}</option><option value="all">{{ $t('settings.page.everySectionCanBe') }}</option><option value="none">{{ $t('settings.page.changeNothingExceptThe') }}</option></AaSelect>
            <label for="f-tskills">{{ $t('settings.page.reorderSkills') }}</label>
            <div><input id="f-tskills" v-model="s['tailor.reorder_skills']" type="checkbox" /> <span class="hint">{{ $t('settings.page.movesTheSkillsThe') }}</span></div>
            <label for="f-tdrop">{{ $t('settings.page.irrelevantPointsCanBe') }}</label>
            <div><input id="f-tdrop" v-model="s['tailor.allow_drop']" type="checkbox" /> <span class="hint">{{ $t('settings.page.goodForRSum') }}</span></div>
            <label for="f-tbul">{{ $t('settings.page.minimumBulletPointsPer') }}</label>
            <div><input id="f-tbul" v-model.number="s['tailor.min_bullets']" type="number" min="1" max="10" style="width: 100px" /> {{ $t('settings.page.items2') }}</div>
            <label for="f-tpages">{{ $t('settings.page.pageLimit') }}</label>
            <div><input id="f-tpages" v-model.number="s['tailor.target_pages']" type="number" min="0" max="5" style="width: 100px" /> {{ $t('settings.page.page') }} <span class="hint">{{ $t('settings.page.keepsYourRSum') }}</span></div>
            <label for="f-trev">{{ $t('settings.page.letMeReviewTailored') }}</label>
            <div><input id="f-trev" v-model="s['tailor.review']" type="checkbox" /> <span class="hint">{{ $t('settings.page.whenTickedAnApplication') }}</span></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="cover" :title="$t('settings.page.coverLetter')">
        <div class="card">
          <p class="muted" style="margin-top: 0">{{ $t('settings.page.lettersAreWrittenFrom') }}
            <template v-if="template">{{ $t('settings.page.theTemplateInUse', { p0: template.name }) }}</template><template v-else>{{ $t('settings.page.noTemplateHasBeen') }}</template>{{ $t('settings.page.inThe') }}<router-link to="/files">{{ $t('settings.page.files') }}</router-link>{{ $t('settings.page.youCanChangeIt') }}</p>
          <div class="field"><label for="f-bold">{{ $t('settings.page.namesSetInBold') }}</label>
            <input id="f-bold" :value="csv('cover_letter.bold_terms')" :placeholder="$t('settings.page.forExampleNamesOf')" @change="setCsv('cover_letter.bold_terms', $event.target.value)" /></div>
          <div class="field"><label for="f-links">{{ $t('settings.page.linksToKeepIn') }}</label>
            <textarea id="f-links" rows="2" style="font-family: inherit" :value="pairs('cover_letter.links', 'text', 'url')" :placeholder="$t('settings.page.onePerLineThe')" @change="setPairs('cover_letter.links', 'text', 'url', $event.target.value)"></textarea></div>
          <div class="field" style="margin-bottom: 0"><label for="f-repl">{{ $t('settings.page.fixedTextOfThe') }}</label>
            <textarea id="f-repl" rows="2" style="font-family: inherit" :value="pairs('cover_letter.replace', 'find', 'with')" :placeholder="$t('settings.page.onePerLineThe2')" @change="setPairs('cover_letter.replace', 'find', 'with', $event.target.value)"></textarea></div>
        </div>
      </SetSection>

    </template>

    <!-- 账号与连接 -->
    <template v-if="group === 'accounts'">
      <SetSection id="logins" :title="$t('settings.page.signInsToCareer')">
        <div class="card">
          <p class="muted" style="margin-top: 0">{{ $t('settings.page.whenASiteNeeds') }} <router-link to="/accounts">{{ $t('settings.page.seeWhereEachSites') }}</router-link></p>
          <div class="kv">
            <label for="f-email">{{ $t('settings.page.emailForSignUp') }}</label><input id="f-email" v-model="s['account.email']" />
          </div>
          <p class="hint" style="margin-top: 12px">{{ $t('settings.page.toHaveASite') }} <router-link to="/profile">{{ $t('settings.page.openTheProfile') }}</router-link></p>
        </div>
      </SetSection>

      <SetSection id="mailbox" :title="$t('settings.page.mailbox')" how="own">
        <MailboxPanel />
        <p class="hint" style="margin: -6px 0 16px">{{ $t('settings.page.howOftenTheMailbox') }}<router-link to="/settings/automation/schedule">{{ $t('settings.page.plan') }}</router-link>{{ $t('settings.page.text') }}</p>
      </SetSection>

      <SetSection id="ai" :title="$t('settings.page.aiService')" how="own">
        <p class="hint" style="margin: 0 0 10px">{{ $t('settings.page.afterTheServiceOr') }}</p>
        <AiPanel :s="s" :sec="sec" :secrets="info.secrets" @changed="load" />
      </SetSection>
    </template>

    <!-- 通知与提醒 -->
    <template v-if="group === 'notify'">
      <SetSection id="channel" :title="$t('settings.page.whereNoticesGo')">
        <div class="card">
          <div class="row"><span class="card-title grow">Telegram</span><span class="badge" :class="info.secrets.telegram_bot_token && s['notify.telegram_chat_id'] ? 'ok' : 'warn'">{{ info.secrets.telegram_bot_token && s['notify.telegram_chat_id'] ? $t('settings.page.connected') : $t('settings.page.notSetUpYet2') }}</span></div>
          <p class="muted">{{ $t('settings.page.progressThingsThatNeed') }}<router-link :to="{ path: '/runs', query: { tab: 'notes' } }">{{ $t('settings.page.activityNotificationsAndBots') }}</router-link>）。</p>
          <div class="kv">
            <label for="f-tg">{{ $t('settings.page.botToken') }}</label><input id="f-tg" v-model="sec.telegram_bot_token" type="password" autocomplete="off" :placeholder="info.secrets.telegram_bot_token ? $t('settings.page.savedToChangeIt') : $t('settings.page.youGetThisAfter')" />
            <label for="f-chat">{{ $t('settings.page.chatId') }}</label><input id="f-chat" v-model="s['notify.telegram_chat_id']" :placeholder="$t('settings.page.sendTheBotA')" />
            <label for="f-base">{{ $t('settings.page.linksInNotificationsOpen') }}</label><div><input id="f-base" v-model="s['app.base_url']" style="width: 100%" /><div class="hint">{{ $t('settings.page.theAddressALink') }}<router-link to="/settings/system/remote">{{ $t('settings.page.remoteAccess') }}</router-link>）。</div></div>
          </div>
          <div class="row" style="margin-top: 12px"><button @click="tgTest"><Icon name="send" />{{ $t('settings.page.sendATestMessage') }}</button><span class="hint">{{ $t('settings.page.saveFirstThenTest') }}</span></div>
        </div>
        <div class="card" style="margin-top: 12px">
          <div class="row"><span class="card-title grow">Discord</span><span class="badge" :class="dcState.cls">{{ dcState.text }}</span></div>
          <p class="muted">{{ $t('settings.page.likeTelegramNotificationsArrive') }}</p>
          <div class="kv">
            <label for="f-dc">{{ $t('settings.page.botToken') }}</label><input id="f-dc" v-model="sec.discord_bot_token" type="password" autocomplete="off" :placeholder="info.secrets.discord_bot_token ? $t('settings.page.savedToChangeIt') : $t('settings.page.createAnApplicationIn')" />
            <template v-if="dc && dc.token">
              <label>{{ $t('settings.page.bot') }}</label>
              <div>
                <template v-if="dc.error"><div>{{ $t('settings.page.thisTokenCannotReach') }}</div><div class="hint">{{ dc.error }}</div></template>
                <template v-else-if="dc.bot">
                  <div>{{ dc.bot.name }}　<a :href="dc.bot.invite" target="_blank" rel="noopener">{{ $t('settings.page.addTheBotTo') }}</a></div>
                  <div class="hint">{{ $t('settings.page.aBotCanOnly') }}</div>
                </template>
              </div>
              <label>{{ $t('settings.page.yourAccount') }}</label>
              <div>
                <div v-if="dc.bound" class="row">{{ $t('settings.page.linked') }}<button class="ghost" @click="dcUnbind">{{ $t('settings.page.unlink') }}</button></div>
                <div v-else-if="dc.code">
                  <div>{{ $t('settings.page.inDiscordSendThe') }}<code style="font-size: 1.2em; letter-spacing: 2px">{{ dc.code }}</code></div>
                  <div class="hint">{{ $t('settings.page.validForMinutesOnce') }}</div>
                </div>
                <button v-else :disabled="!!dc.error" @click="dcBind">{{ $t('settings.page.linkMyDiscordAccount') }}</button>
              </div>
            </template>
            <label for="f-dch">{{ $t('settings.page.webhookOptional') }}</label><input id="f-dch" v-model="sec.discord_webhook" type="password" autocomplete="off" :placeholder="info.secrets.discord_webhook ? $t('settings.page.savedToChangeIt') : $t('settings.page.channelSettingsIntegrationsWebhooks')" />
          </div>
          <div class="row" style="margin-top: 12px"><button @click="dcTest"><Icon name="send" />{{ $t('settings.page.sendATestMessage') }}</button><span class="hint">{{ $t('settings.page.saveFirstThenTest2') }}</span></div>
        </div>
      </SetSection>

      <SetSection id="bots" :title="$t('settings.page.handleItFromYour')">
        <div class="card">
          <label><input v-model="s['bot.listen']" type="checkbox" /> {{ $t('settings.page.theBotsTakeButton') }}</label>
          <p class="hint">{{ $t('settings.page.theButtonsDoWhat') }}</p>
          <p class="hint">{{ $t('settings.page.commandsStatusWhatIs') }}</p>
          <label style="display: block; margin-top: 8px"><input v-model="s['bot.chat']" type="checkbox" :disabled="!s['bot.listen']" /> {{ $t('settings.page.anythingElseYouSay') }}</label>
          <p class="hint">{{ $t('settings.page.askItHowThings') }}</p>
          <div v-if="s['bot.daily_summary']" class="row" style="margin-top: 8px; flex-wrap: wrap; gap: 8px">
            <label><input v-model="s['bot.daily_summary'].on" type="checkbox" /> {{ $t('settings.summary.on') }}</label>
            <input v-model="s['bot.daily_summary'].at" type="time" :disabled="!s['bot.daily_summary'].on" :aria-label="$t('settings.summary.at')" style="width: 120px" />
          </div>
          <p class="hint">{{ $t('settings.summary.hint') }}</p>
        </div>
      </SetSection>

      <SetSection id="events" :title="$t('settings.page.whatToNotifyAbout')">
        <div class="card">
          <div class="kv">
            <label>{{ $t('settings.page.whichNotifications') }}</label>
            <div class="row" style="flex-wrap: wrap">
              <label><input v-model="s['notify.todo']" type="checkbox" /> {{ $t('settings.page.thingsThatNeedYou') }}</label>
              <label><input v-model="s['notify.task_result']" type="checkbox" /> {{ $t('settings.page.outcomeSentFailed') }}</label>
              <label><input v-model="s['notify.status_update']" type="checkbox" /> {{ $t('settings.page.applicationProgress') }}</label>
              <label><input v-model="s['notify.task_started']" type="checkbox" /> {{ $t('settings.page.startDoingSomething') }}</label>
            </div>
            <template v-if="channelsOn.length > 1">
              <label>{{ $t('settings.page.byChannel') }}</label>
              <table style="width: auto">
                <thead><tr><th></th><th v-for="c in channelsOn" :key="c[0]">{{ c[1] }}</th></tr></thead>
                <tbody>
                  <tr v-for="[k, label] in CATS" :key="k">
                    <td>{{ label }}</td>
                    <td v-for="c in channelsOn" :key="c[0]"><input type="checkbox" :checked="takes(c[0], k)" :disabled="!s['notify.' + k]" :aria-label="`${c[1]}：${label}`" @change="setTakes(c[0], k, $event.target.checked)" /></td>
                  </tr>
                </tbody>
              </table>
            </template>
            <label for="quiet-on">{{ $t('settings.page.quietHours') }}</label>
            <div v-if="s['notify.quiet']">
              <div class="row" style="flex-wrap: wrap">
                <label><input id="quiet-on" v-model="s['notify.quiet'].on" type="checkbox" /> {{ $t('settings.page.sendNothingToThe') }}</label>
                <span>{{ $t('settings.page.from') }} <input v-model="s['notify.quiet'].from" type="time" :disabled="!s['notify.quiet'].on" :aria-label="$t('settings.page.quietHoursStart')" style="width: 110px" />
                  {{ $t('settings.page.to') }} <input v-model="s['notify.quiet'].to" type="time" :disabled="!s['notify.quiet'].on" :aria-label="$t('settings.page.quietHoursEnd')" style="width: 110px" /></span>
              </div>
              <p class="hint" style="margin: 6px 0 0">{{ $t('settings.page.nothingFromTheseHours') }}</p>
            </div>
          </div>
          <p class="hint" style="margin-top: 12px">{{ $t('settings.page.invitationsToInterviewsAnd') }}<router-link to="/todos">{{ $t('settings.page.needsYourAction') }}</router-link>{{ $t('settings.page.cardByCard') }}</p>
        </div>
      </SetSection>

      <SetSection id="reminders" :title="$t('settings.reminders.title')">
        <div class="card">
          <p class="muted" style="margin-top: 0">{{ $t('settings.reminders.intro') }}</p>
          <div v-if="s['calendar.reminders']" class="kv">
            <template v-for="k in REMINDER_KINDS" :key="k">
              <label :for="'rem-' + k">{{ $t('calendar.kind.' + k) }}</label>
              <div><input :id="'rem-' + k" :value="minutesText(k)" style="width: 220px" :placeholder="$t('settings.reminders.none')" @change="setMinutes(k, $event.target.value)" />
                <span class="hint" style="margin-left: 8px">{{ remindText(k) }}</span></div>
            </template>
            <label for="rem-morning">{{ $t('settings.reminders.morning') }}</label><input id="rem-morning" v-model="s['calendar.allday_at']" type="time" style="width: 120px" />
            <label for="rem-quiet">{{ $t('settings.reminders.quietLabel') }}</label>
            <label><input id="rem-quiet" v-model="s['calendar.reminders_quiet']" type="checkbox" /> {{ $t('settings.reminders.quiet') }}</label>
          </div>
          <p class="hint" style="margin: 10px 0 0">{{ $t('settings.reminders.hint') }}</p>
        </div>
      </SetSection>
    </template>

    <!-- 系统与数据 -->
    <template v-if="group === 'system'">
      <SetSection id="network" :title="$t('settings.page.networkConnectionOutbound')">
        <p class="hint" style="margin: 0 0 10px">{{ $t('settings.page.howTheProgramReaches') }}</p>
        <NetworkPanel ref="netPanel" :s="s" :sec="sec" :has-password="!!info.secrets.proxy_password" />
      </SetSection>
      <SetSection id="browser" :title="$t('settings.page.browserCompatibility')">
        <p class="hint" style="margin: 0 0 10px">{{ $t('settings.page.byDefaultThePrograms') }}</p>
        <BrowserPanel :s="s" />
      </SetSection>
      <AccessPanel />
      <SetSection id="retention" :title="$t('settings.page.dataRetention')">
        <div class="card">
          <p class="muted" style="margin-top: 0">{{ $t('settings.page.theseThreeOnlyDecide') }}</p>
          <div class="kv">
            <label for="f-arch">{{ $t('settings.page.archivePostingsHowLong') }}</label>
            <div><input id="f-arch" v-model.number="s['archive.closed_after_days']" type="number" style="width: 100px" /> {{ $t('settings.page.days') }} <span class="hint">{{ $t('settings.page.postingsThatWereTaken') }}</span></div>
            <label for="f-silent">{{ $t('settings.page.archiveAfterHowLong') }}</label>
            <div><input id="f-silent" v-model.number="s['archive.silent_after_days']" type="number" style="width: 100px" /> {{ $t('settings.page.days') }} <span class="hint">{{ $t('settings.page.theApplicationStaysSubmitted') }}</span></div>
            <label for="f-dedupe">{{ $t('settings.page.timeBetweenHiringRounds') }}</label>
            <div><input id="f-dedupe" v-model.number="s['dedupe.window_days']" type="number" style="width: 100px" /> {{ $t('settings.page.days') }} <span class="hint">{{ $t('settings.page.postingsWithTheSame') }}</span></div>
          </div>
        </div>
      </SetSection>
      <SetSection id="backup" :title="$t('settings.page.backupAndUpdates')" how="">
        <div class="card">
          <p class="muted" style="margin-top: 0">{{ $t('settings.page.allYourDataStays') }}<code>{{ sys.data_dir }}</code> {{ $t('settings.page.and') }} <code>{{ sys.knowledge_dir }}</code>{{ $t('settings.page.updatesWontTouchThese') }}</p>
          <div class="row" style="gap: 8px; flex-wrap: wrap; margin-top: 8px">
            <button @click="exportData(false)"><Icon name="download" />{{ $t('settings.page.exportAllData') }}</button>
            <button class="ghost" @click="exportData(true)">{{ $t('settings.page.exportWithSignIn') }}</button>
            <router-link to="/about" class="btn"><Icon name="refresh" />{{ $t('settings.page.updatesOnAbout') }}</router-link>
            <span class="muted small">{{ $t('settings.page.currentVersion', { p0: sys.version }) }}</span>
          </div>
          <p v-if="exported" class="small" style="margin-top: 8px">{{ $t('settings.page.exportedFilesMb', { p0: exported.files, p1: (exported.size / 1e6).toFixed(1) }) }}<a :href="'/api/system/export/' + exported.name">{{ $t('settings.page.download', { p0: exported.name }) }}</a>
            <span class="muted">{{ $t('settings.page.alsoSavedIn', { p0: exported.path }) }}</span></p>
          <p class="small" style="margin: 10px 0 0">
            <template v-if="lastExport">{{ lastExportLine }} <a :href="'/api/system/export/' + lastExport.name">{{ $t('settings.page.downloadThisOne') }}</a></template>
            <template v-else>{{ $t('settings.page.nothingHasBeenExported') }}</template>
          </p>
          <div class="backup-notes">
            <div>
              <h4>{{ $t('settings.page.whatAnExportHolds') }}</h4>
              <ul>
                <li>{{ $t('settings.page.everyRecordPostingsApplications') }}</li>
                <li>{{ $t('settings.page.theFilesYouUploaded') }}</li>
                <li>{{ $t('settings.page.yourProfileTheScoring') }}</li>
                <li>{{ $t('settings.page.withExportWithSign') }}</li>
              </ul>
            </div>
            <div>
              <h4>{{ $t('settings.page.whatAnExportDoes') }}</h4>
              <ul>
                <li v-if="sys.secrets === 'file'">{{ $t('settings.page.passwordsAndApiKeys') }}</li>
                <li v-else>{{ $t('settings.page.passwordsAndApiKeys2') }}</li>
                <li>{{ $t('settings.page.theScreenshotsAndPage') }}</li>
                <li>{{ $t('settings.page.theOrdinaryBrowsersProfile') }}</li>
                <li>{{ $t('settings.page.theSettingsForRemote') }}</li>
              </ul>
            </div>
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
          <p class="hint" style="margin: 10px 0 0">{{ $t('settings.page.toUpdateTheProgram') }}</p>
        </div>
      </SetSection>
      <SetSection id="diagnose" :title="$t('settings.page.diagnostics')" how="">
        <DoctorPanel />
      </SetSection>
      <SetSection id="expert" :title="$t('settings.page.expertTools')" how="own">
        <p class="hint" style="margin: 0 0 10px">{{ $t('settings.page.notNeededDayTo') }}<router-link to="/profile">{{ $t('settings.page.profile') }}</router-link>{{ $t('settings.page.andTheScoringRules') }}</p>
        <PromptsPanel />
      </SetSection>
    </template>
  </div>
</template>

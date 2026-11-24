<script setup>
// Site accounts: the accounts the program uses on job sites, and the provider sessions behind "Sign in with ...".
// Three things are kept apart everywhere on this page, because the server keeps them apart: whether a password is
// stored, whether a session is saved (and until when it can last at most), and what the program can do with them by
// itself. A saved session is never called "signed in": nothing here asks the site.
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { t as T } from '../i18n/catalog'
import { api, fmt, ROOT } from '../api'
import CredentialCell from '../components/cells/CredentialCell.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import DataState from '../components/DataState.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import FileButton from '../components/FileButton.vue'
import FormError from '../components/FormError.vue'
import Icon from '../components/Icon.vue'
import IconButton from '../components/IconButton.vue'
import InfoTip from '../components/InfoTip.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import Popover from '../components/Popover.vue'
import ProviderCard from '../components/ProviderCard.vue'
import SectionHead from '../components/SectionHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
import { dataState, useRefresh } from '../data'
import { asDate, dateOf } from '../i18n/format'
import { ask, fmtTime, persona, run as runAction, toast } from '../ui'

const accounts = ref([])
const idps = ref([])
const idpState = ref({})
const browserRules = ref([])
const nodriverOn = ref(true)
const store = ref('')            // where passwords are kept on the server: keyring | file (GET /system) - the security line says which
const enc = encodeURIComponent

// ── passwords that are being shown ───────────────────────────────────────────────────────────────────────────────────
// Read one at a time, when asked for, through the one request that gives a password out. Kept here and nowhere else
// (not in storage, not in a tooltip or a name), and forgotten again: after HIDE_AFTER, when its row goes, when the
// page is left, when the window is no longer looked at.
const HIDE_AFTER = 30000
const revealed = reactive(new Map())      // tenant_key -> password
const revealing = ref('')
const hiding = new Map()
function hide(key) { revealed.delete(key); clearTimeout(hiding.get(key)); hiding.delete(key) }
function hideAll() { for (const key of [...revealed.keys()]) hide(key) }
const shownOf = (a) => (revealed.has(a.tenant_key) ? revealed.get(a.tenant_key) : null)
async function reveal(a) {
  if (revealing.value) return
  if (!(await ask(T('accounts.showThePasswordFor', { p0: a.site.name })))) return
  revealing.value = a.tenant_key
  try {
    const r = await api.post(`/accounts/${enc(a.tenant_key)}/reveal`, { confirm: a.tenant_key })
    if (r.password === null || r.password === undefined) return toast(T('accounts.passwordMissing'), 'warn')
    revealed.set(a.tenant_key, r.password)
    hiding.set(a.tenant_key, setTimeout(() => hide(a.tenant_key), HIDE_AFTER))
  } catch (e) { toast(e.message || T('common.failed'), 'bad') } finally { revealing.value = '' }
}
async function copy(a) {
  const value = shownOf(a)
  if (value === null) return
  try { await navigator.clipboard.writeText(value); toast(T('accounts.passwordCopied')) } catch (e) { toast(T('accounts.copyFailed'), 'bad') }
}
const unseen = () => { if (document.hidden) hideAll() }

// ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────
async function loadIdps() {
  const [list, state] = await Promise.all([api.get('/identities'), api.get('/identities/state')])
  idps.value = list
  idpState.value = state
}
async function read() {
  const [rows, settings, system] = await Promise.all([api.get('/accounts'), api.get('/settings'), api.get('/system')])
  accounts.value = rows
  browserRules.value = settings.settings['browser.rules'] || []
  nodriverOn.value = !!settings.settings['browser.nodriver_enabled']
  store.value = system.secrets || ''
  for (const key of [...revealed.keys()]) if (!rows.some((r) => r.tenant_key === key && r.has_password)) hide(key)
  await loadIdps()
}
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
const run = (fn, ok, opts) => runAction(fn, ok, load, opts)
// While a sign-in window is open - a provider's, or one this page opened for a site within the last ten minutes (as
// long as the window waits) - the page reads again every few seconds: the session shows when the sign-in is done.
const watchUntil = ref(0)
const waiting = () => Object.values(idpState.value).includes('trying') || Date.now() < watchUntil.value
useRefresh(load, { every: 5000, when: waiting })
onMounted(() => {
  load(); loadCarry(); fitAct()
  document.addEventListener('visibilitychange', unseen)
  if (typeof ResizeObserver !== 'undefined' && probe.value) { probing = new ResizeObserver(fitAct); probing.observe(probe.value); if (autoProbe.value) probing.observe(autoProbe.value) }
})
onUnmounted(() => { hideAll(); probing?.disconnect(); document.removeEventListener('visibilitychange', unseen) })

// ── the browser a sign-in is made in (settings: browser.rules, one rule per site or provider) ─────────────────────────
const backendFor = (tenant) => browserRules.value.find((r) => r.tenant === tenant)?.backend || ''
const browserName = (b) => (b === 'playwright' ? T('accounts.browserOwn') : b === 'nodriver' ? T('accounts.browserOrdinary') : T('accounts.followSiteRules'))
function withRule(rules, tenant, backend) {
  const rest = (rules || []).filter((r) => r.tenant !== tenant)
  return backend ? [{ tenant, backend, operations: [] }, ...rest] : rest
}
const savedText = (backend) => (backend === 'nodriver' && !nodriverOn.value ? T('accounts.browserChoiceSavedNodriver') : T('accounts.saved'))
const bform = reactive({ backend: '' })
const pops = new Map()      // tenant_key -> the popover of that row (opened from its menu)
const setPop = (key, el) => { if (el) pops.set(key, el); else pops.delete(key) }
function saveBrowser(a, close) {
  const backend = bform.backend
  close()
  if (backend === backendFor(a.tenant_key)) return
  run(async () => {
    const rules = withRule((await api.get('/settings')).settings['browser.rules'], a.tenant_key, backend)
    await api.put('/settings', { settings: { 'browser.rules': rules } })
  }, savedText(backend))
}

// ── providers ────────────────────────────────────────────────────────────────────────────────────────────────────────
const MAIN = ['google', 'linkedin', 'microsoft', 'apple']
const showAll = ref(false)
const usual = computed(() => idps.value.filter((p) => MAIN.includes(p.key) || p.session || p.custom))
const providers = computed(() => (showAll.value ? idps.value : usual.value))
const idpLogin = (p) => run(() => api.post(`/identities/${p.key}/login`), T('accounts.aWindowHasOpened', { p0: p.name }))
const idpForget = async (p) => (await ask(T('accounts.deleteTheSavedSession', { p0: p.name, p1: p.name }), { danger: true, ok: T('accounts.deleteSignInSession') }))
  && run(() => api.del('/identities/' + p.key), T('accounts.sessionCleared'))
// (what the card's form holds: the browser and the e-mail of the account there; only what changed is written)
function saveProvider(p, v) {
  const tenant = 'idp:' + p.key
  const browser = (v.backend || '') !== backendFor(tenant)
  const email = v.email !== (p.email || '')
  if (!browser && !email) return
  run(async () => {
    const now = (await api.get('/settings')).settings
    const settings = {}
    if (browser) settings['browser.rules'] = withRule(now['browser.rules'], tenant, v.backend)
    if (email) settings['identity.emails'] = { ...(now['identity.emails'] || {}), [p.key]: v.email }
    await api.put('/settings', { settings })
  }, browser ? savedText(v.backend) : T('accounts.saved'))
}
const custom = reactive({ name: '', url: '', domains: '' })
function addCustom(close) {
  const row = { name: custom.name.trim(), url: custom.url.trim(), domains: custom.domains.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean) }
  if (!row.domains.length) { try { row.domains = [new URL(row.url).hostname.split('.').slice(-2).join('.')] } catch (e) { /* checked by the server */ } }
  run(async () => {
    const now = (await api.get('/settings')).settings
    await api.put('/settings', { settings: { 'identity.custom': [...(now['identity.custom'] || []), row] } })
    Object.assign(custom, { name: '', url: '', domains: '' })
    close()
  }, T('accounts.added', { p0: row.name }), { form: 'provider' })
}
const removeCustom = async (p) => (await ask(T('accounts.removeProviderAsk', { name: p.name }), { danger: true, ok: T('accounts.remove') })) && run(async () => {
  const now = (await api.get('/settings')).settings
  await api.del('/identities/' + p.key)
  await api.put('/settings', { settings: { 'identity.custom': (now['identity.custom'] || []).filter((c) => c.name !== p.name) } })
}, T('accounts.removed', { p0: p.name }))

// ── the accounts table ───────────────────────────────────────────────────────────────────────────────────────────────
// Two columns are as wide as their words, which depend on the language: the last one ("Sign in" and the menu) and the
// automation state (the longest of its labels - a state is read whole, not cut). Both widths are taken from copies
// nobody sees, whenever those change.
const probe = ref(null)
const autoProbe = ref(null)
const actWidth = ref(124)
const autoWidth = ref(160)
const PAD = 24      // a cell's padding, both sides (--dt-pad)
function fitAct() {
  if (probe.value && probe.value.offsetWidth) actWidth.value = probe.value.offsetWidth + 60      // + the gap, the menu and the padding
  if (autoProbe.value) {
    const widest = Math.max(0, ...[...autoProbe.value.children].map((e) => e.offsetWidth))
    if (widest) autoWidth.value = Math.ceil(widest) + PAD + 2      // (+2: a width measured in fractions is not cut by rounding)
  }
}
let probing = null
// The site is what a row is read by: it takes the room that is left. The password is dots and a button (fixed), the
// source a short word (bounded). On a narrow screen the source goes first, then the session, the account and the
// password - each of them is in the row's details.
const columns = computed(() => [
  { id: 'site', header: T('accounts.website'), min: 220, flex: 1 },
  { id: 'login', header: T('accounts.account'), min: 150, flex: 0.4, max: 220, priority: 2 },
  { id: 'cred', header: T('accounts.colCredential'), width: 136, priority: 1 },
  { id: 'auto', header: T('accounts.automation'), width: autoWidth.value, headerTip: T('accounts.automationHelp') },
  { id: 'session', header: T('accounts.colSession'), width: 168, priority: 3, headerTip: T('accounts.sessionHelp') },
  { id: 'source', header: T('accounts.howItGotHere'), min: 124, flex: 0.2, max: 140, priority: 4 },
  { id: 'act', header: '', width: actWidth.value, align: 'end' },
])
const sources = computed(() => ({ agent: T('accounts.registeredByTheApp'), takeover: T('accounts.savedWhenYouSign'), manual: T('accounts.sourceManual'), chrome_csv: T('accounts.importFromChrome') }))

// What the program can do on the site by itself (server: auth.readiness - told from the record, the site is not asked).
// A short state; why, in a sentence, behind the (i); the raw text only in the details.
const AUTO = computed(() => ({
  ready: ['ok', T('accounts.canSignInAutomatically')], manual: ['warn', T('accounts.youNeedToSign')], verify: ['info', T('accounts.waitingForItsE')],
  register_failed: ['bad', T('accounts.registrationFailed')], signin_failed: ['bad', T('accounts.signInFailed')], locked: ['bad', T('accounts.locked')],
  never: ['', T('accounts.neverSignedIn')], not_needed: ['', T('accounts.noSignInNeeded')], register: ['info', T('accounts.registerAgain')],
}))
const BY_STATUS = { ok: 'ready', pending: 'verify', needs_human: 'manual', locked: 'locked', not_needed: 'not_needed', register: 'register' }      // a server that does not say `automation`
function automation(a) {
  const kind = AUTO.value[a.automation] ? a.automation : BY_STATUS[a.status] || 'never'
  const [tone, label] = AUTO.value[kind]
  const said = (a.explained && a.explained.message) || ''
  let tip = said
  if (kind === 'ready') tip = a.last_login_ok ? T('accounts.readyTipSince', { time: fmtTime(a.last_login_ok) }) : T('accounts.readyTip')
  else if (kind === 'manual') tip = said || (a.status === 'ok' ? T('accounts.manualTipNothingLeft') : T('accounts.manualTip'))
  else if (kind === 'verify') tip = T('accounts.verifyTip')
  else if (kind === 'never') tip = a.has_password ? T('accounts.neverTipPassword') : T('accounts.neverTip')
  else if (kind === 'not_needed') tip = ''
  else if (!said) tip = T('accounts.failedTip')
  return { kind, tone, label, tip }
}
// The saved session in two short lines. "Expires by" is the date of the cookie that lasts longest: an upper bound.
const day = (iso) => dateOf(asDate(iso))
function sessionCell(s) {
  if (!s) return { primary: T('accounts.notSaved'), secondary: '', tone: 'muted', tip: '' }
  const saved = T('accounts.saved2', { p0: fmtTime(s.saved_at) })
  if (s.expired) return { primary: saved, secondary: T('accounts.sessionExpired'), tone: 'warn', tip: T('accounts.sessionExpiredTip') }
  if (s.valid_until) return { primary: saved, secondary: T('accounts.expiresByDate', { date: day(s.valid_until) }), tone: '', tip: T('accounts.expiresByTip') }
  return { primary: saved, secondary: T('accounts.noExpiryGiven'), tone: '', tip: T('accounts.noExpiryTip') }
}
const sessionState = (s) => (!s ? { tone: '', label: T('accounts.notSaved') } : s.expired ? { tone: 'warn', label: T('accounts.sessionExpired') } : { tone: 'ok', label: T('accounts.signedIn') })

const rowItems = (a) => [
  { id: 'detail', label: T('accounts.viewDetails'), icon: 'info' },
  { id: 'browser', label: T('accounts.signInBrowser'), icon: 'globe', hint: browserName(backendFor(a.tenant_key)) },
  { divider: true },
  { id: 'session', label: T('accounts.deleteSignInSession'), icon: 'x', disabled: !a.session },
  { id: 'password', label: T('accounts.removePassword'), icon: 'key', disabled: !a.has_password },
  { divider: true },
  { id: 'delete', label: T('accounts.deleteAccount'), icon: 'trash', danger: true },
]
function onRow(a, id) {
  if (id === 'detail') drawer.value = { kind: 'detail', key: a.tenant_key }
  else if (id === 'browser') { bform.backend = backendFor(a.tenant_key); pops.get(a.tenant_key)?.open() }
  else if (id === 'session') clearSession(a)
  else if (id === 'password') removePassword(a)
  else if (id === 'delete') remove(a)
}
const takeover = (a) => run(async () => {
  const r = await api.post('/accounts/takeover', { tenant_key: a.tenant_key, url: 'https://' + a.host, save_credentials: true })
  watchUntil.value = Date.now() + 600000
  return r
}, T('accounts.theSignInWindow'))
// Each of the three takes away exactly what it names, and says so before it does.
const clearSession = async (a) => (await ask(T('accounts.clearSessionAsk', { site: a.site.name }), { danger: true, ok: T('accounts.deleteSignInSession') }))
  && run(() => api.del(`/accounts/${enc(a.tenant_key)}/session`), T('accounts.sessionCleared'))
const removePassword = async (a) => (await ask(T('accounts.removePasswordAsk', { site: a.site.name }), { danger: true, ok: T('accounts.removePassword') }))
  && run(async () => { hide(a.tenant_key); await api.del(`/accounts/${enc(a.tenant_key)}/password`) }, T('accounts.passwordRemoved'))
const remove = async (a) => (await ask(T('accounts.deleteTheAccountRecord', { p0: a.site.name }), { danger: true, ok: T('accounts.deleteAccount') }))
  && run(async () => { hide(a.tenant_key); await api.del('/accounts/' + enc(a.tenant_key)); if (drawer.value?.key === a.tenant_key) drawer.value = null }, T('accounts.deleted'))

// ── what opens beside the page: an account's details, and the three forms that were the "advanced" block ──────────────
const drawer = ref(null)      // { kind: 'detail', key } | { kind: 'add' } | { kind: 'password', key } | { kind: 'chrome' } | { kind: 'move' }
const detail = computed(() => (drawer.value?.kind === 'detail' ? accounts.value.find((a) => a.tenant_key === drawer.value.key) || null : null))
const form = reactive({ tenant_key: '', login_email: '', password: '' })
const formFor = computed(() => (drawer.value?.kind === 'password' ? accounts.value.find((a) => a.tenant_key === drawer.value.key) || null : null))
function closeDrawer() { form.password = ''; carry.pass = ''; carry.inPass = ''; drawer.value = null }
function openAdd(a) {
  Object.assign(form, { tenant_key: a ? a.tenant_key : '', login_email: a ? a.login_email || '' : '', password: '' })
  drawer.value = a ? { kind: 'password', key: a.tenant_key } : { kind: 'add' }
}
const save = () => run(async () => {
  await api.put('/accounts/' + enc(form.tenant_key.trim()), { ...form, tenant_key: form.tenant_key.trim() })
  closeDrawer()
}, T('accounts.saved'), { form: 'account' })
const pageItems = computed(() => [
  { id: 'chrome', label: T('accounts.importSavedPasswordsFrom'), icon: 'download' },
  { id: 'move', label: T('accounts.carryASignIn'), icon: 'external' },
])
function onPage(id) { drawer.value = { kind: id }; if (id === 'move') loadCarry() }

function importCsv(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f)
  run(() => api.upload('/accounts/import-chrome-csv', fd), (r) => T('accounts.importedAccountsForJob', { p0: r.imported.length, p1: r.skipped }))
  ev.target.value = ''
}
// carrying a session to another computer (a server cannot do a passkey sign-in; your own computer can)
const carry = reactive({ sessions: [], tenant: '', pass: '', inPass: '' })
async function loadCarry() { try { carry.sessions = await api.get('/accounts/sessions') } catch (e) { /* nothing to carry */ } }
async function exportSession() {
  try {
    const r = await fetch(`${ROOT}/api/accounts/session/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_key: carry.tenant, passphrase: carry.pass }) })
    if (!r.ok) throw new Error((await r.json()).detail || T('accounts.nothingWasExported'))
    const a = document.createElement('a')
    a.href = URL.createObjectURL(await r.blob())
    a.download = (r.headers.get('Content-Disposition') || '').replace(/.*filename="([^"]+)".*/, '$1') || 'session.aasession'
    a.click()
    URL.revokeObjectURL(a.href)
    carry.pass = ''
    toast(T('accounts.exportedTakeTheFile'))
  } catch (e) { toast(e.message, 'bad') }
}
function importSession(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f); fd.append('passphrase', carry.inPass)
  run(() => api.upload('/accounts/session/import', fd), (r) => T('accounts.theSignInFor', { p0: r.name })).then(() => { carry.inPass = ''; loadCarry() })
  ev.target.value = ''
}
</script>

<template>
  <button ref="probe" type="button" class="sm acc-probe" tabindex="-1" aria-hidden="true"><Icon name="login" />{{ $t('accounts.signIn') }}</button>
  <div ref="autoProbe" class="acc-probe acc-probe-list" aria-hidden="true"><Status v-for="(v, k) in AUTO" :key="k" :tone="v[0]" :label="v[1]" tip="-" /></div>
  <PageHead :title="$t('accounts.siteAccounts')" :help="$t('accounts.pageHelp')">
    <Menu :label="$t('common.more')" :items="pageItems" @pick="onPage">
      <template #trigger="{ toggle, attrs }"><button type="button" v-bind="attrs" @click="toggle"><Icon name="more" />{{ $t('common.more') }}</button></template>
    </Menu>
    <button type="button" @click="openAdd()"><Icon name="plus" />{{ $t('accounts.addAccount') }}</button>
  </PageHead>

  <!-- The one security line: where the two things are kept. Everything it says is what secrets.py and browser.py do. -->
  <p class="acc-secure">
    <Icon name="shield" />
    <span>{{ store === 'file' ? $t('accounts.secureLineFile') : $t('accounts.secureLine') }}</span>
    <Popover :label="$t('accounts.secureTitle')" :width="400">
      <template #trigger="{ toggle, attrs }"><button type="button" class="ghost sm" v-bind="attrs" @click="toggle">{{ $t('accounts.learnMore') }}</button></template>
      <dl class="acc-secure-more">
        <dt>{{ $t('accounts.password') }}</dt>
        <dd>{{ store === 'file' ? $t('accounts.securePasswordFile') : $t('accounts.securePassword') }}</dd>
        <dt>{{ $t('accounts.signInStatus') }}</dt>
        <dd>{{ $t('accounts.secureSession') }}</dd>
        <dt>{{ $t('accounts.accountsUsedToSign') }}</dt>
        <dd>{{ $t('accounts.secureProviders') }}</dd>
        <dt>{{ $t('accounts.secureLeavesTitle') }}</dt>
        <dd>{{ $t('accounts.secureLeaves') }}</dd>
      </dl>
    </Popover>
  </p>

  <DataState :s="st" :what="$t('accounts.siteAccounts')" @retry="load" />
  <template v-if="st.at">
    <SectionHead :title="$t('accounts.accountsUsedToSign')" :help="$t('accounts.providersHelp')">
      <Popover :label="$t('accounts.notHereAddYour')" :width="340" align="end">
        <template #trigger="{ toggle, attrs }"><button type="button" class="sm acc-add-provider" :aria-label="$t('accounts.notHereAddYour')" v-bind="attrs" @click="toggle"><Icon name="plus" /><span>{{ $t('accounts.notHereAddYour') }}</span></button></template>
        <template #default="{ close }">
          <div class="field"><label for="acc-cp-name">{{ $t('accounts.providerName') }}</label><input id="acc-cp-name" v-model="custom.name" :placeholder="$t('accounts.nameEGUniversity')" /></div>
          <div class="field"><label for="acc-cp-url">{{ $t('accounts.itsSignInPage') }}</label><input id="acc-cp-url" v-model="custom.url" type="url" placeholder="https://login.example.edu/" /></div>
          <div class="field"><label for="acc-cp-dom">{{ $t('accounts.itsDomainOptional') }}</label><input id="acc-cp-dom" v-model="custom.domains" placeholder="example.edu" /></div>
          <p class="hint">{{ $t('accounts.afterAddingItClick') }}</p>
          <FormError name="provider" />
          <div class="actions acc-pop-acts">
            <button type="button" class="sm" @click="close()">{{ $t('common.cancel') }}</button>
            <button type="button" class="sm primary" :disabled="!custom.name.trim() || !custom.url.trim()" @click="addCustom(close)">{{ $t('accounts.add') }}</button>
          </div>
        </template>
      </Popover>
    </SectionHead>
    <div class="pgrid-box">
      <div class="pgrid">
        <ProviderCard v-for="p in providers" :key="p.key" :provider="p" :state="idpState[p.key] || ''" :backend="backendFor('idp:' + p.key)"
          @login="idpLogin(p)" @forget="idpForget(p)" @remove="removeCustom(p)" @save="saveProvider(p, $event)" />
      </div>
    </div>
    <div v-if="idps.length > usual.length" class="actions pgrid-more">
      <button type="button" class="ghost sm" :aria-expanded="showAll ? 'true' : 'false'" @click="showAll = !showAll">
        <Icon :name="showAll ? 'chevron_up' : 'chevron'" />{{ showAll ? $t('accounts.showCommonProviders') : $t('accounts.showAllProviders', { n: idps.length }) }}
      </button>
    </div>

    <SectionHead :title="$t('accounts.siteAccounts')" :count="accounts.length" />
    <DataTable :columns="columns" :rows="accounts" row-key="tenant_key" density="comfortable" :label="$t('accounts.siteAccounts')">
      <template #cell-site="{ row }">
        <EntityCell :primary="row.site.name" :secondary="row.host"><template v-if="row.site.system" #after><span class="meta small">{{ row.site.system }}</span></template></EntityCell>
      </template>
      <template #cell-login="{ row }"><Trunc v-if="row.login_email" :text="row.login_email" /><span v-else class="none">—</span></template>
      <template #cell-cred="{ row }">
        <CredentialCell :saved="row.has_password" :value="shownOf(row)" :loading="revealing === row.tenant_key" @reveal="reveal(row)" @hide="hide(row.tenant_key)" @copy="copy(row)" @add="openAdd(row)" />
      </template>
      <template #cell-auto="{ row }"><Status :tone="automation(row).tone" :label="automation(row).label" :tip="automation(row).tip" /></template>
      <template #cell-session="{ row }"><DateTimeCell v-bind="sessionCell(row.session)" /></template>
      <template #cell-source="{ row }"><Trunc v-if="sources[row.created_by]" class="meta" :text="sources[row.created_by]" /><span v-else class="none">—</span></template>
      <template #cell-act="{ row }">
        <button v-if="row.host" type="button" class="sm ghost" @click="takeover(row)"><Icon name="login" />{{ $t('accounts.signIn') }}</button>
        <Popover :ref="(el) => setPop(row.tenant_key, el)" :label="$t('accounts.signInBrowser')" :width="300" align="end">
          <template #trigger><Menu :label="$t('common.more')" :items="rowItems(row)" @pick="onRow(row, $event)" /></template>
          <template #default="{ close }">
            <div class="field">
              <label :for="'acc-b-' + row.tenant_key">{{ $t('accounts.signInBrowser') }} <InfoTip :text="$t('accounts.browserHelp')" /></label>
              <AaSelect :id="'acc-b-' + row.tenant_key" v-model="bform.backend">
                <option value="">{{ $t('accounts.followSiteRules') }}</option>
                <option value="playwright">{{ $t('accounts.browserOwn') }}</option>
                <option value="nodriver">{{ $t('accounts.browserOrdinary') }}</option>
              </AaSelect>
            </div>
            <div class="actions acc-pop-acts">
              <button type="button" class="sm" @click="close()">{{ $t('common.cancel') }}</button>
              <button type="button" class="sm primary" @click="saveBrowser(row, close)">{{ $t('common.save') }}</button>
            </div>
          </template>
        </Popover>
      </template>
      <template #empty><EmptyState icon="key" :title="$t('accounts.noSiteAccountsSaved')" :text="$t('accounts.theFirstTimeA')" /></template>
    </DataTable>
  </template>

  <!-- an account: everything on record about it, and the raw text of what went wrong last -->
  <SideDrawer v-if="detail" :title="detail.site.name" :sub="detail.host" :wide="false" @close="closeDrawer">
    <dl class="acc-facts">
      <div><dt>{{ $t('accounts.account') }}</dt><dd><Trunc v-if="detail.login_email" :text="detail.login_email" /><span v-else class="none">—</span></dd></div>
      <div><dt>{{ $t('accounts.colCredential') }}</dt><dd>
        <CredentialCell :saved="detail.has_password" :value="shownOf(detail)" :loading="revealing === detail.tenant_key" @reveal="reveal(detail)" @hide="hide(detail.tenant_key)" @copy="copy(detail)" @add="openAdd(detail)" />
      </dd></div>
      <div><dt>{{ $t('accounts.automation') }}</dt><dd>
        <Status :tone="automation(detail).tone" :label="automation(detail).label" />
        <p v-if="automation(detail).tip" class="t-secondary acc-why">{{ automation(detail).tip }}</p>
      </dd></div>
      <div><dt>{{ $t('accounts.lastSignInOk') }}</dt><dd><span v-if="detail.last_login_ok" class="num">{{ fmt(detail.last_login_ok) }}</span><span v-else class="none">—</span></dd></div>
      <div><dt>{{ $t('accounts.colSession') }}</dt><dd>
        <Status :tone="sessionState(detail.session).tone" :label="sessionState(detail.session).label" />
        <template v-if="detail.session">
          <p class="t-secondary acc-why num">{{ $t('accounts.saved2', { p0: fmt(detail.session.saved_at) }) }}</p>
          <p v-if="!detail.session.expired" class="t-secondary acc-why num">{{ detail.session.valid_until ? $t('accounts.expiresByDate', { date: day(detail.session.valid_until) }) : $t('accounts.noExpiryGiven') }}</p>
          <p class="t-meta acc-why">{{ detail.session.expired ? $t('accounts.sessionExpiredTip') : detail.session.valid_until ? $t('accounts.expiresByTip') : $t('accounts.noExpiryTip') }}</p>
        </template>
      </dd></div>
      <div><dt>{{ $t('accounts.signInBrowser') }}</dt><dd>{{ browserName(backendFor(detail.tenant_key)) }}</dd></div>
      <div><dt>{{ $t('accounts.howItGotHere') }}</dt><dd><template v-if="sources[detail.created_by]">{{ sources[detail.created_by] }}</template><span v-else class="none">—</span></dd></div>
      <div><dt>{{ $t('accounts.recruitingSystem') }}</dt><dd><template v-if="detail.site.system">{{ detail.site.system }}</template><span v-else class="none">—</span></dd></div>
      <div><dt>{{ $t('accounts.siteId') }}</dt><dd><code class="acc-id">{{ detail.tenant_key }}</code></dd></div>
    </dl>
    <h4 class="acc-h">{{ $t('common.techDetails') }}</h4>
    <pre v-if="detail.explained.detail || detail.last_error" class="acc-raw" tabindex="0">{{ detail.explained.detail || detail.last_error }}</pre>
    <p v-else class="t-secondary">{{ $t('accounts.noErrorRecorded') }}</p>
    <div class="actions acc-drawer-acts">
      <button v-if="detail.host" type="button" class="primary" @click="takeover(detail)"><Icon name="login" />{{ $t('accounts.signIn') }}</button>
    </div>
  </SideDrawer>

  <!-- add an account by hand, or the password of one that has none -->
  <SideDrawer v-else-if="drawer && (drawer.kind === 'add' || drawer.kind === 'password')" :title="formFor ? $t('accounts.addPasswordFor', { site: formFor.site.name }) : $t('accounts.addAccount')" :sub="formFor ? formFor.host : ''" :wide="false" @close="closeDrawer">
    <form class="acc-form" @submit.prevent="save">
      <div v-if="!formFor" class="field">
        <label for="acc-f-id">{{ $t('accounts.siteId') }}
          <Popover :label="$t('accounts.siteId')" :width="360">
            <template #trigger="{ toggle, attrs }"><IconButton icon="help" size="sm" :label="$t('accounts.siteIdHelp')" v-bind="attrs" @click="toggle" /></template>
            <p>{{ $t('accounts.aWorkdayIdIs') }}</p>
            <p v-if="persona.features.portal">{{ $t('accounts.theUniversitysCoOp') }}</p>
          </Popover>
        </label>
        <input id="acc-f-id" v-model="form.tenant_key" placeholder="workday:altera.wd1" autocomplete="off" spellcheck="false" />
      </div>
      <div class="field"><label for="acc-f-login">{{ $t('accounts.loginNameOrE') }}</label><input id="acc-f-login" v-model="form.login_email" autocomplete="off" spellcheck="false" /></div>
      <div class="field"><label for="acc-f-pw">{{ $t('accounts.password') }}</label><input id="acc-f-pw" v-model="form.password" type="password" autocomplete="new-password" /></div>
      <FormError name="account" />
      <div class="actions acc-drawer-acts">
        <button type="button" @click="closeDrawer">{{ $t('common.cancel') }}</button>
        <button type="submit" class="primary" :disabled="!form.tenant_key.trim() || (!!formFor && !form.password)">{{ $t('common.save') }}</button>
      </div>
    </form>
  </SideDrawer>

  <SideDrawer v-else-if="drawer && drawer.kind === 'chrome'" :title="$t('accounts.importSavedPasswordsFrom')" :wide="false" @close="closeDrawer">
    <p>{{ $t('accounts.inChromeGoTo') }}</p>
    <div class="callout warn"><Icon name="alert" /><div>{{ $t('accounts.deleteThatCsvFile') }}</div></div>
    <div class="actions acc-drawer-acts"><FileButton accept=".csv" class="primary" @change="importCsv"><Icon name="inbox" />{{ $t('accounts.chooseCsvFile') }}</FileButton></div>
  </SideDrawer>

  <SideDrawer v-else-if="drawer && drawer.kind === 'move'" :title="$t('accounts.carryASignIn')" :wide="false" @close="closeDrawer">
    <div class="callout warn"><Icon name="alert" /><div>{{ $t('accounts.someSignInsCannot') }}</div></div>
    <h4 class="acc-h">{{ $t('accounts.export') }}</h4>
    <div class="field">
      <label for="acc-m-site">{{ $t('accounts.website') }}</label>
      <AaSelect id="acc-m-site" v-model="carry.tenant" :placeholder="$t('accounts.chooseASiteYou')"><option v-for="s in carry.sessions" :key="s.tenant_key" :value="s.tenant_key">{{ s.name }}</option></AaSelect>
    </div>
    <div class="field"><label for="acc-m-pass">{{ $t('accounts.passphrase') }}</label><input id="acc-m-pass" v-model="carry.pass" type="password" autocomplete="new-password" :placeholder="$t('accounts.passphraseAtLeastCharacters')" /></div>
    <div class="actions"><button type="button" :disabled="!carry.tenant || carry.pass.length < 8" @click="exportSession"><Icon name="download" />{{ $t('accounts.exportTheFile') }}</button></div>
    <h4 class="acc-h">{{ $t('accounts.import') }}</h4>
    <div class="field"><label for="acc-m-in">{{ $t('accounts.passphrase') }}</label><input id="acc-m-in" v-model="carry.inPass" type="password" autocomplete="off" :placeholder="$t('accounts.thePassphraseChosenAt')" /></div>
    <div class="actions"><FileButton accept=".aasession" :disabled="carry.inPass.length < 8" @change="importSession"><Icon name="inbox" />{{ $t('accounts.chooseTheSignIn') }}</FileButton></div>
  </SideDrawer>
</template>

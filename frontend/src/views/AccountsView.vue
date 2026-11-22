<script setup>
import { t as T } from '../i18n/catalog'
import { onMounted, onUnmounted, ref } from 'vue'
import { api, fmt, ROOT } from '../api'
import EmptyState from '../components/EmptyState.vue'
import FileButton from '../components/FileButton.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { fmtTime, run as runAction, ask, toast } from '../ui'
import { dateOf } from '../i18n/format'

const accounts = ref([])
const form = ref({ tenant_key: '', login_email: '', password: '' })
const revealed = ref({})
const idps = ref([])
const idpState = ref({})
const browserRules = ref([])
const advanced = ref(false)      // which browser an account uses, importing, moving sign-ins: there when needed, out of the way otherwise
const backendFor = (tenant) => browserRules.value.find((r) => r.tenant === tenant)?.backend || ''
async function setBackend(tenant, backend) {
  await runAction(async () => {
    const d = await api.get('/settings')
    const rules = (d.settings['browser.rules'] || []).filter((r) => r.tenant !== tenant)
    if (backend) rules.unshift({ tenant, backend, operations: [] })
    await api.put('/settings', { settings: { 'browser.rules': rules } })
    browserRules.value = rules
  }, T('accounts.browserChoiceSavedNodriver'))
}
let timer
const custom = ref({ name: '', url: '', domains: '' })
const showAll = ref(false)
const MAIN = ['google', 'linkedin', 'microsoft', 'apple']
async function addCustom() {
  const d = await api.get('/settings')
  const cur = d.settings['identity.custom'] || []
  const row = { name: custom.value.name.trim(), url: custom.value.url.trim(), domains: custom.value.domains.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean) }
  if (!row.domains.length) { try { row.domains = [new URL(row.url).hostname.split('.').slice(-2).join('.')] } catch (e) { /* checked by the server */ } }
  await runAction(() => api.put('/settings', { settings: { 'identity.custom': [...cur, row] } }), T('accounts.added', { p0: row.name }), loadIdps)
  custom.value = { name: '', url: '', domains: '' }
}
async function setIdpEmail(p, v) {
  const d = await api.get('/settings')
  await runAction(() => api.put('/settings', { settings: { 'identity.emails': { ...(d.settings['identity.emails'] || {}), [p.key]: v.trim() } } }), T('accounts.saved'), loadIdps)
}
async function removeCustom(p) {
  const d = await api.get('/settings')
  await api.del('/identities/' + p.key)
  await runAction(() => api.put('/settings', { settings: { 'identity.custom': (d.settings['identity.custom'] || []).filter((c) => c.name !== p.name) } }), T('accounts.removed', { p0: p.name }), loadIdps)
}
const until = (x) => (x ? dateOf(new Date(x)) : '')
function sessionText(x) {
  if (!x) return T('accounts.notSaved')
  if (x.expired) return T('accounts.expiredSignInAgain')
  return T('accounts.saved2', { p0: fmtTime(x.saved_at) }) + (x.valid_until ? T('accounts.validUntilAtMost', { p0: until(x.valid_until) }) : T('accounts.mayStopWorkingOnce'))
}
async function loadIdps() { idps.value = await api.get('/identities'); idpState.value = await api.get('/identities/state') }
const idpLogin = (p) => runAction(() => api.post(`/identities/${p.key}/login`), T('accounts.aWindowHasOpened', { p0: p.name }), loadIdps)
const idpForget = async (p) => (await ask(T('accounts.deleteTheSavedSession', { p0: p.name, p1: p.name }), { danger: true })) && runAction(() => api.del('/identities/' + p.key), T('accounts.deleted'), loadIdps)

const STATUS = { ok: [T('accounts.canSignInAutomatically'), 'ok'], pending: [T('accounts.waitingForItsE'), 'warn'], locked: [T('accounts.locked'), 'bad'], needs_human: [T('accounts.youNeedToSign'), 'warn'], unknown: [T('accounts.neverSignedIn'), ''], not_needed: [T('accounts.noSignInNeeded'), ''] }
const BY = { agent: T('accounts.registeredByTheApp'), takeover: T('accounts.savedWhenYouSign'), manual: T('accounts.addManually'), chrome_csv: T('accounts.importFromChrome') }

async function read() { accounts.value = await api.get('/accounts'); browserRules.value = (await api.get('/settings')).settings['browser.rules'] || []; loadIdps() }
const run = (fn, ok) => runAction(fn, ok, load)
const save = () => run(async () => { await api.put('/accounts/' + encodeURIComponent(form.value.tenant_key), form.value); form.value = { tenant_key: '', login_email: '', password: '' } }, T('accounts.saved'))
const remove = async (a) => (await ask(T('accounts.deleteTheAccountRecord', { p0: a.site.name }), { danger: true })) && run(() => api.del('/accounts/' + encodeURIComponent(a.tenant_key)), T('accounts.deleted'))
async function reveal(a) {
  if (revealed.value[a.tenant_key]) { const r = { ...revealed.value }; delete r[a.tenant_key]; revealed.value = r; return }
  if (!(await ask(T('accounts.showThePasswordFor', { p0: a.site.name })))) return
  await runAction(async () => { revealed.value = { ...revealed.value, [a.tenant_key]: (await api.post(`/accounts/${encodeURIComponent(a.tenant_key)}/reveal`, { confirm: a.tenant_key })).password } }, '')
}
function importCsv(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f)
  run(() => api.upload('/accounts/import-chrome-csv', fd), (r) => T('accounts.importedAccountsForJob', { p0: r.imported.length, p1: r.skipped }))
  ev.target.value = ''
}
const takeover = (a) => run(() => api.post('/accounts/takeover', { tenant_key: a.tenant_key, url: 'https://' + a.host, save_credentials: true }), T('accounts.theSignInWindow'))
// carrying a sign-in to another computer (a server cannot do a passkey sign-in; your own computer can)
const carry = ref({ sessions: [], tenant: '', pass: '', inPass: '' })
const loadCarry = async () => { try { carry.value.sessions = await api.get('/accounts/sessions') } catch (e) { /* nothing to carry */ } }
async function exportSession() {
  const c = carry.value
  try {
    const r = await fetch(`${ROOT}/api/accounts/session/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_key: c.tenant, passphrase: c.pass }) })
    if (!r.ok) throw new Error((await r.json()).detail || T('accounts.nothingWasExported'))
    const a = document.createElement('a')
    a.href = URL.createObjectURL(await r.blob())
    a.download = (r.headers.get('Content-Disposition') || '').replace(/.*filename="([^"]+)".*/, '$1') || 'session.aasession'
    a.click()
    URL.revokeObjectURL(a.href)
    c.pass = ''
    toast(T('accounts.exportedTakeTheFile'))
  } catch (e) { toast(e.message, 'bad') }
}
function importSession(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f); fd.append('passphrase', carry.value.inPass)
  run(() => api.upload('/accounts/session/import', fd), (r) => T('accounts.theSignInFor', { p0: r.name })).then(() => { carry.value.inPass = ''; loadCarry() })
  ev.target.value = ''
}
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load)
onMounted(() => { load(); loadCarry(); timer = setInterval(loadIdps, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <PageHead :title="$t('accounts.siteAccounts')" :sub="$t('accounts.oneEntryPerJob')" />
  <DataState :s="st" :what="$t('accounts.siteAccounts')" @retry="load" />
  <template v-if="st.at">

  <div class="card">
    <div class="card-title">{{ $t('accounts.accountsUsedToSign') }}</div>
    <p class="muted">{{ $t('accounts.manyJobSitesLet') }}<b>{{ $t('accounts.passwordsForTheseAccounts') }}</b>。</p>
    <div class="idps">
      <div v-for="p in idps.filter((x) => showAll || MAIN.includes(x.key) || x.session || x.custom)" :key="p.key" class="idp">
        <div class="row"><b class="grow">{{ p.name }}<span v-if="p.region" class="muted small" style="font-weight: 400">　{{ p.region }}</span></b><span class="badge" :class="p.session && !p.session.expired ? 'ok' : ''">{{ p.session && !p.session.expired ? $t('accounts.signedIn') : $t('accounts.notSignedIn') }}</span></div>
        <div class="small muted" style="margin: 4px 0 10px; min-height: 36px">
          <template v-if="idpState[p.key] === 'trying'">{{ $t('accounts.signInWindowIs') }}</template>
          <template v-else-if="idpState[p.key]"><span style="color: var(--warn)">{{ $t('accounts.lastAttemptFailed', { p0: idpState[p.key] }) }}</span></template>
          <template v-else>{{ sessionText(p.session) }}</template>
        </div>
        <div class="row">
          <AaSelect :value="backendFor('idp:' + p.key)" small :aria-label="$t('accounts.signInBrowser')" @change="setBackend('idp:' + p.key, $event.target.value)"><option value="">{{ $t('accounts.followSiteRules') }}</option><option value="playwright">Playwright</option><option value="nodriver">nodriver</option></AaSelect>
          <button class="sm" :class="{ primary: !p.session }" :disabled="idpState[p.key] === 'trying'" @click="idpLogin(p)"><Icon name="login" />{{ p.session ? $t('accounts.signInAgain') : $t('accounts.signIn') }}</button>
          <button v-if="p.session" class="sm ghost danger" @click="idpForget(p)">{{ $t('accounts.deleteSignInSession') }}</button>
          <button v-if="p.custom" class="sm ghost danger" @click="removeCustom(p)">{{ $t('accounts.remove') }}</button>
        </div>
        <input v-if="p.session" :value="p.email" class="idp-mail" :placeholder="$t('accounts.emailForThisAccount')" @change="setIdpEmail(p, $event.target.value)" />
        <div v-if="p.note" class="hint" style="margin-top: 8px">{{ p.note }}</div>
        <div v-else-if="p.custom" class="hint" style="margin-top: 8px">{{ $t('accounts.addedByYouJust') }}</div>
      </div>
    </div>
    <div class="row" style="margin-top: 12px">
      <button class="sm ghost" @click="showAll = !showAll">{{ showAll ? $t('accounts.collapse') : $t('accounts.moreFacebookIndeedGithub') }}</button>
    </div>
    <details class="tech"><summary>{{ $t('accounts.notHereAddYour') }}</summary>
      <div class="emp-add" style="margin-top: 8px">
        <input v-model="custom.name" style="width: 160px" :placeholder="$t('accounts.nameEGUniversity')" />
        <input v-model="custom.url" class="grow" :placeholder="$t('accounts.itsSignInPage')" />
        <input v-model="custom.domains" style="width: 220px" :placeholder="$t('accounts.itsDomainOptional')" />
        <button :disabled="!custom.name.trim() || !custom.url.trim()" @click="addCustom">{{ $t('accounts.add') }}</button>
      </div>
      <p class="hint" style="margin-top: 6px">{{ $t('accounts.afterAddingItClick') }}</p>
    </details>
  </div>

  <div class="table-wrap" style="max-height: none">
    <table>
      <thead><tr><th>{{ $t('accounts.website') }}</th><th>{{ $t('accounts.loginNameOrE') }}</th><th>{{ $t('accounts.password') }}</th><th>{{ $t('accounts.status') }}</th><th>{{ $t('accounts.signInStatus') }}</th><th>{{ $t('accounts.howItGotHere') }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="a in accounts" :key="a.tenant_key">
          <td><b>{{ a.site.name }}</b> <span v-if="a.site.system" class="badge">{{ a.site.system }}</span><div class="muted small">{{ a.host }}</div></td>
          <td>{{ a.login_email || '—' }}</td>
          <td>
            <template v-if="a.has_password">
              <code v-if="revealed[a.tenant_key]">{{ revealed[a.tenant_key] }}</code><span v-else class="muted">{{ $t('accounts.saved') }}</span>
              <button class="sm ghost" @click="reveal(a)">{{ revealed[a.tenant_key] ? $t('accounts.hide') : $t('accounts.show') }}</button>
            </template>
            <template v-else><span class="muted">{{ $t('accounts.notSaved') }}</span> <button class="sm ghost" @click="form.tenant_key = a.tenant_key; form.login_email = a.login_email || ''; advanced = true">{{ $t('accounts.enter') }}</button></template>
          </td>
          <td>
            <span class="badge" :class="(STATUS[a.status] || [])[1]">{{ (STATUS[a.status] || [a.status])[0] }}</span>
            <div v-if="a.explained.message && a.status !== 'ok'" class="small muted" style="margin-top: 4px; max-width: 320px">{{ a.explained.message }}</div>
            <TechDetails v-if="a.status !== 'ok'" :text="a.explained.detail" />
          </td>
          <td class="small" style="max-width: 240px">{{ sessionText(a.session) }}<AaSelect v-if="advanced" :value="backendFor(a.tenant_key)" small :aria-label="$t('accounts.accountBrowser')" @change="setBackend(a.tenant_key, $event.target.value)"><option value="">{{ $t('accounts.followSiteRules') }}</option><option value="playwright">Playwright</option><option value="nodriver">nodriver</option></AaSelect></td>
          <td class="small">{{ BY[a.created_by] || '—' }}</td>
          <td><div class="row" style="flex-wrap: nowrap"><button v-if="a.host" class="sm" @click="takeover(a)"><Icon name="login" />{{ $t('accounts.signIn') }}</button><button class="sm ghost danger" @click="remove(a)">{{ $t('accounts.delete') }}</button></div></td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!accounts.length" icon="key" :title="$t('accounts.noSiteAccountsSaved')" :text="$t('accounts.theFirstTimeA')" />
  </div>

  <details class="card" style="margin-top: 16px" :open="advanced" @toggle="advanced = $event.target.open">
    <summary><b>{{ $t('accounts.advanced') }}</b> <span class="muted small">{{ $t('accounts.whichBrowserAnAccount') }}</span></summary>
    <p class="hint" style="margin: 10px 0 0">{{ $t('accounts.onceThisIsOpen') }}<router-link to="/settings/system/browser">{{ $t('accounts.settingsBrowserCompatibility') }}</router-link>{{ $t('accounts.thereIsUsuallyNothing') }}</p>
  <div class="cols" style="margin-top: 16px">
    <div class="card">
      <div class="card-title">{{ $t('accounts.importSavedPasswordsFrom') }}</div>
      <p class="muted">{{ $t('accounts.inChromeGoTo') }}</p>
      <FileButton accept=".csv" @change="importCsv"><Icon name="inbox" />{{ $t('accounts.chooseCsvFile') }}</FileButton>
      <p class="hint" style="margin-top: 8px">{{ $t('accounts.deleteThatCsvFile') }}</p>
    </div>
    <div class="card">
      <div class="card-title">{{ $t('accounts.carryASignIn') }}</div>
      <p class="muted">{{ $t('accounts.someSignInsCannot') }}</p>
      <div class="kv" style="margin-top: 12px">
        <label>{{ $t('accounts.export') }}</label>
        <div class="row">
          <AaSelect v-model="carry.tenant" :aria-label="$t('accounts.website')"><option value="">{{ $t('accounts.chooseASiteYou') }}</option><option v-for="s in carry.sessions" :key="s.tenant_key" :value="s.tenant_key">{{ s.name }}</option></AaSelect>
          <input v-model="carry.pass" type="password" autocomplete="new-password" :placeholder="$t('accounts.passphraseAtLeastCharacters')" style="width: 200px" />
          <button :disabled="!carry.tenant || carry.pass.length < 8" @click="exportSession"><Icon name="external" />{{ $t('accounts.exportTheFile') }}</button>
        </div>
        <label>{{ $t('accounts.import') }}</label>
        <div class="row">
          <input v-model="carry.inPass" type="password" autocomplete="off" :placeholder="$t('accounts.thePassphraseChosenAt')" style="width: 200px" />
          <FileButton accept=".aasession" :disabled="carry.inPass.length < 8" @change="importSession"><Icon name="inbox" />{{ $t('accounts.chooseTheSignIn') }}</FileButton>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">{{ $t('accounts.addManually') }}</div>
      <div class="kv" style="margin-top: 12px">
        <label>{{ $t('accounts.siteId') }}</label><input v-model="form.tenant_key" placeholder="workday:altera.wd1" />
        <label>{{ $t('accounts.loginNameOrE') }}</label><input v-model="form.login_email" />
        <label>{{ $t('accounts.password') }}</label><input v-model="form.password" type="password" autocomplete="new-password" />
      </div>
      <p class="hint" style="margin-top: 8px">{{ $t('accounts.aWorkdayIdIs') }}</p>
      <p class="hint" style="margin-top: 8px">{{ $t('accounts.theUniversitysCoOp') }}</p>
      <button class="primary" :disabled="!form.tenant_key" @click="save">{{ $t('accounts.save') }}</button>
    </div>
  </div>
  </details>
  </template>
</template>

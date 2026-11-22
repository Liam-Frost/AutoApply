<script setup>
import { t as T } from '../i18n/catalog'
// Settings -> System and data: two sections that share what the server keeps as "access" - how other devices reach the
// program (where it listens, the proxy in front of it), and the account (how long a login lasts, the password, the
// open logins). Each has its own button and saves its own part: the address of the server is not sent along with a
// change of how long a login lasts.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import CardHead from './CardHead.vue'
import HelpPop from './HelpPop.vue'
import Icon from './Icon.vue'
import SetSection from './SetSection.vue'
import Status from './Status.vue'
import { ask, run, session, toast } from '../ui'
import { clone, same, useUnsaved } from '../dirty'

const info = ref(null)
const c = ref(null)
const where = ref('local')     // local | all | one
const pw = ref({ current: '', password: '', again: '', user: '' })
const proxies = ref('')
const hosts = ref('')

async function load() {
  info.value = await api.get('/access')
  c.value = { ...info.value.settings }
  place()
  proxies.value = c.value.trusted_proxies.join(', ')
  hosts.value = c.value.allowed_hosts.join(', ')
  pw.value.user = info.value.user
  base.value = clone(shown())
}
// what this panel saves with its own button, as it was last read or saved
const base = ref(null)
const shown = () => ({ c: c.value, proxies: proxies.value, hosts: hosts.value })
const reach = (x) => ({ ...x.c, session_days: 0, proxies: x.proxies, hosts: x.hosts })       // the part "remote access" saves
const dirty = computed(() => !!base.value && !same(reach(shown()), reach(base.value)))
const daysDirty = computed(() => !!base.value && !same(c.value.session_days, base.value.c.session_days))
const place = () => { where.value = c.value.host === '127.0.0.1' || c.value.host === 'localhost' ? 'local' : c.value.host === '0.0.0.0' ? 'all' : 'one' }
function discard() { c.value = { ...clone(base.value.c), session_days: c.value.session_days }; proxies.value = base.value.proxies; hosts.value = base.value.hosts; place() }
const typedPw = computed(() => !!(pw.value.password || pw.value.again))      // (not the current one: a browser fills that in by itself)
const list = (t) => t.split(/[\s,;]+/).filter(Boolean)
const exposed = computed(() => where.value !== 'local')
const unencrypted = computed(() => exposed.value && !c.value.https_by_proxy)
function pickWhere(v) { where.value = v; c.value.host = v === 'local' ? '127.0.0.1' : v === 'all' ? '0.0.0.0' : (info.value.addresses.find((a) => /^\d/.test(a)) || '') }
// each button sends its own part, with the other part as it was last saved; what is being edited in the other stays
const save = () => run(async () => {
  const days = c.value.session_days
  await api.put('/access', { settings: { ...c.value, session_days: base.value.c.session_days, trusted_proxies: list(proxies.value), allowed_hosts: list(hosts.value) } })
  await load()
  c.value.session_days = days
}, T('settings.access.savedTheAddressPort'))
const saveDays = () => run(async () => {
  const days = c.value.session_days
  await api.put('/access', { settings: { ...base.value.c, session_days: days } })
  info.value = await api.get('/access')
  base.value.c.session_days = info.value.settings.session_days
  c.value.session_days = info.value.settings.session_days
}, T('settings.access.savedItCountsFrom'))
const changePassword = () => {
  if (pw.value.password !== pw.value.again) { toast(T('settings.access.theTwoNewPasswords'), 'bad'); return false }
  return run(async () => {
    await api.post('/auth/password', { current: pw.value.current, password: pw.value.password, user: pw.value.user })
    pw.value = { current: '', password: '', again: '', user: pw.value.user }
    session.user = pw.value.user
    await load()
  }, T('settings.access.passwordChangedOtherDevices'))
}
useUnsaved({ id: 'access', label: T('settings.access.remoteAccess'), dirty: () => dirty.value, save: () => save(), discard })
useUnsaved({ id: 'access-days', label: T('settings.access.howLongALogin2'), dirty: () => daysDirty.value, save: () => saveDays(), discard: () => { c.value.session_days = base.value.c.session_days } })
useUnsaved({ id: 'access-pw', label: T('settings.access.newPassword'), dirty: () => typedPw.value, save: () => changePassword(), discard: () => { pw.value = { current: '', password: '', again: '', user: info.value.user } } })
const signOutAll = async () => (await ask(T('settings.access.signOutOnEvery2'), { ok: T('settings.access.signOutOnEvery'), danger: true })) && run(async () => { await api.post('/auth/logout', { everywhere: true }); session.in = false }, T('settings.access.signedOutEverywhere'))
onMounted(load)
</script>

<template>
  <template v-if="c">
    <SetSection id="remote" :title="$t('settings.access.remoteAccessInbound')" how="own">
      <div class="card">
        <CardHead :title="$t('settings.access.whereAutoapplyCanBe')" :help="$t('settings.access.byDefaultOnlyThis')" />
        <p v-if="info.restart_needed" class="callout"><Icon name="info" /><span>{{ $t('settings.access.theRunningServerListens', { p0: info.running.host, p1: info.running.port }) }}</span></p>
        <div class="kv">
          <label>{{ $t('settings.access.listenOn') }}</label>
          <div class="set-val">
            <AaSelect :model-value="where" class="w-line" @update:model-value="pickWhere">
              <option value="local">{{ $t('settings.access.thisComputerOnly') }}</option>
              <option value="all">{{ $t('settings.access.everyNetworkThisComputer') }}</option>
              <option value="one">{{ $t('settings.access.oneAddress') }}</option>
            </AaSelect>
            <input v-if="where === 'one'" v-model.trim="c.host" class="w-short" placeholder="192.168.1.20" :aria-label="$t('settings.access.ipAddressToListen')" />
            <span v-if="where !== 'local' && info.addresses.length" class="hint">{{ $t('settings.access.thisComputersAddresses', { p0: info.addresses.join(', ') }) }}</span>
          </div>
          <label>{{ $t('settings.access.port') }}</label><div class="set-val"><input v-model.number="c.port" class="w-num" type="number" /></div>
          <label>{{ $t('settings.access.pathPrefix') }}</label><div class="set-val"><input v-model.trim="c.root_path" class="w-short" :placeholder="$t('settings.access.leaveEmpty')" /><span class="hint">{{ $t('settings.access.onlyWhenAReverse') }}</span></div>
        </div>
        <p class="set-note">{{ $t('settings.access.takesEffectAfterA') }}</p>
        <p v-if="unencrypted" class="callout warn after-form"><Icon name="alert" /><span>{{ $t('settings.access.whenAnotherDeviceOpens') }}</span></p>
      </div>

      <div class="card">
        <CardHead :title="$t('settings.access.reverseProxy')" :help="$t('settings.access.autoapplyDoesNotDo')" />
        <div class="kv">
          <label for="f-https">{{ $t('settings.access.aReverseProxyDoes') }}<HelpPop :text="$t('settings.access.whenOnTheLogin')" /></label><div class="set-val"><input id="f-https" v-model="c.https_by_proxy" type="checkbox" /></div>
          <label>{{ $t('settings.access.proxyAddresses') }}<HelpPop :text="$t('settings.access.whenTheProxyRuns')" /></label><input v-model="proxies" :placeholder="$t('settings.access.leaveEmpty')" />
          <label>{{ $t('settings.access.hostNames') }}<HelpPop :text="$t('settings.access.fillInWhenYou')" /></label><input v-model="hosts" placeholder="jobs.example.com" />
        </div>
        <div class="set-actions">
          <button class="primary" :disabled="!dirty" @click="save"><Icon name="check" />{{ $t('settings.access.saveAccessSettings') }}</button>
          <Status v-if="dirty" tone="warn" :label="$t('settings.access.unsavedChanges')" /><span v-else class="hint">{{ $t('settings.access.thisButtonSavesBoth') }}</span>
        </div>
      </div>
    </SetSection>

    <SetSection id="security" :title="$t('settings.access.accountSecurity')" how="own">
      <div class="card">
        <CardHead :title="$t('settings.access.howLongALogin')" />
        <div class="kv">
          <label for="f-days">{{ $t('settings.access.staySignedIn') }}</label><div class="set-val"><input id="f-days" v-model.number="c.session_days" class="w-num" type="number" /><span class="unit">{{ $t('settings.access.days') }}</span><span class="hint">{{ $t('settings.access.afterThatYouSign') }}</span></div>
        </div>
        <div class="set-actions"><button class="primary" :disabled="!daysDirty" @click="saveDays"><Icon name="check" />{{ $t('settings.access.save') }}</button><Status v-if="daysDirty" tone="warn" :label="$t('settings.access.unsavedChanges')" /></div>
      </div>

      <div class="card">
        <CardHead :title="$t('settings.access.administratorAccount')" :help="$t('settings.access.theOnlyAccountOnly')" />
        <div class="kv">
          <label>{{ $t('settings.access.username') }}</label><div class="set-val"><input v-model.trim="pw.user" class="w-line" autocomplete="username" /></div>
          <label>{{ $t('settings.access.currentPassword') }}</label><div class="set-val"><input v-model="pw.current" class="w-line" type="password" autocomplete="current-password" /></div>
          <label>{{ $t('settings.access.newPassword') }}</label><div class="set-val"><input v-model="pw.password" class="w-line" type="password" autocomplete="new-password" /><span class="hint">{{ $t('settings.access.atLeastCharacters') }}</span></div>
          <label>{{ $t('settings.access.newPasswordAgain') }}</label><div class="set-val"><input v-model="pw.again" class="w-line" type="password" autocomplete="new-password" /></div>
        </div>
        <div class="set-actions">
          <button :disabled="!pw.current || !pw.password" @click="changePassword"><Icon name="key" />{{ $t('settings.access.changePassword') }}</button>
          <span class="grow"></span>
          <button class="ghost" @click="signOutAll">{{ $t('settings.access.signOutOnEvery') }}</button>
        </div>
      </div>
    </SetSection>
  </template>
</template>

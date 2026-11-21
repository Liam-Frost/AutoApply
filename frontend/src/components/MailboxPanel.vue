<script setup>
import { t as T } from '../i18n/catalog'
// Which mailbox the program reads (read-only): verification codes and links, confirmations, interview invitations, rejections.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { run, toast } from '../ui'
import { clone, same, useUnsaved } from '../dirty'
import FileButton from './FileButton.vue'
import Icon from './Icon.vue'

const d = ref(null)
const pick = ref('gmail_api')   // gmail_api | <imap preset>
const form = ref({ host: '', port: 993, user: '', password: '' })
const busy = ref(false)
const result = ref(null)
const clientId = ref('')
let olTimer

const preset = computed(() => d.value && d.value.presets.find((p) => p.key === pick.value))
const inUse = computed(() => d.value && (pick.value === 'gmail_api' ? d.value.kind === 'gmail_api' : d.value.kind === 'imap' && d.value.imap.preset === pick.value))
async function load() {
  d.value = await api.get('/mailbox')
  pick.value = d.value.kind === 'imap' ? d.value.imap.preset || 'custom' : 'gmail_api'
  fill()
  base.value = clone(shown())
}
// which mailbox and how it is reached, as it was last read or saved
const base = ref(null)
const shown = () => ({ pick: pick.value, form: form.value })
const dirty = computed(() => !!base.value && !same(shown(), base.value))
function discard() { pick.value = base.value.pick; form.value = clone(base.value.form); result.value = null }
function fill() {
  const i = d.value.imap
  const mine = d.value.kind === 'imap' && i.preset === pick.value
  form.value = { host: mine ? i.host : (preset.value ? preset.value.host : ''), port: mine ? i.port : (preset.value ? preset.value.port : 993), user: i.user || '', password: '' }
  result.value = null
}
const isOutlook = computed(() => pick.value === 'outlook')
async function outlookAuth() {
  busy.value = true
  try {
    await api.put('/settings', { settings: { 'mail.kind': 'imap', 'mail.imap': imapBody() } })
    await api.post('/mailbox/outlook/authorize', clientId.value.trim() ? { client_id: clientId.value.trim() } : {})
    d.value = await api.get('/mailbox')
    clearInterval(olTimer)
    olTimer = setInterval(async () => {
      d.value = await api.get('/mailbox')
      if (d.value.outlook.flow.state !== 'waiting') { clearInterval(olTimer); if (d.value.outlook.flow.state === 'done') toast(T('settings.mailbox.outlookMailboxAuthorized')) }
    }, 4000)
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
}
const outlookForget = () => run(() => api.del('/mailbox/outlook'), T('settings.mailbox.outlookAuthorizationRemoved'), load)
const imapBody = () => ({ preset: pick.value, host: form.value.host, port: form.value.port, user: form.value.user })
async function test() {
  busy.value = true; result.value = null
  try {
    const r = await api.post('/mailbox/test', pick.value === 'gmail_api' ? {} : { imap: imapBody(), password: form.value.password })
    result.value = { ok: true, text: T('settings.mailbox.readableEmailsReceivedIn', { p0: r.recent }) }
  } catch (e) { result.value = { ok: false, text: e.message } }
  busy.value = false
}
async function save() {
  busy.value = true
  try {
    if (pick.value === 'gmail_api') await api.put('/settings', { settings: { 'mail.kind': 'gmail_api' } })
    else await api.put('/settings', { settings: { 'mail.kind': 'imap', 'mail.imap': imapBody() }, secrets: form.value.password ? { imap_password: form.value.password } : {} })
    toast(T('settings.mailbox.emailSettingsSaved'))
    await load()
    busy.value = false
    return true
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
  return false
}
useUnsaved({ id: 'mailbox', label: T('settings.mailbox.email'), dirty: () => dirty.value, save, discard })
function gmailClient(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f)
  run(() => api.upload('/settings/gmail-client', fd), T('settings.mailbox.fileSavedNowClick'), load)
}
const gmailAuth = () => run(() => api.post('/settings/gmail-authorize'), T('settings.mailbox.theBrowserIsOpen'), load)
onMounted(load)
</script>

<template>
  <div v-if="d" class="card">
    <div class="row"><span class="card-title grow">{{ $t('settings.mailbox.email') }}</span><span class="badge" :class="d.ready ? 'ok' : 'warn'">{{ d.ready ? $t('settings.mailbox.connected') : $t('settings.mailbox.notConnectedYet') }}</span></div>
    <p class="muted">{{ $t('settings.mailbox.readingCodesAndActivation') }}</p>
    <div class="kv">
      <label>{{ $t('settings.mailbox.emailType') }}</label>
      <AaSelect v-model="pick" @change="fill">
        <option value="gmail_api">{{ $t('settings.mailbox.gmailGoogleAuthorizationReads') }}</option>
        <option v-for="p in d.presets" :key="p.key" :value="p.key">{{ p.name }}</option>
      </AaSelect>
    </div>

    <template v-if="pick === 'gmail_api'">
      <p class="hint" style="margin: 12px 0">{{ $t('settings.mailbox.authorizingAsksForReading') }}</p>
      <div class="row">
        <FileButton accept=".json" @change="gmailClient"><Icon name="inbox" />{{ $t('settings.mailbox.chooseJsonFile') }}</FileButton>
        <button :disabled="!d.client" @click="gmailAuth">{{ $t('settings.mailbox.authorize') }}</button>
        <span class="badge" :class="d.authorized ? 'ok' : ''">{{ d.authorized ? $t('settings.mailbox.authorized') : d.reconnect ? $t('settings.mailbox.theAuthorizationIsNo') : d.client ? $t('settings.mailbox.fileUploadedNotYet') : $t('settings.mailbox.noFilesUploadedYet') }}</span>
        <span v-if="d.authorized" class="badge" :class="d.can_send ? 'ok' : 'warn'">{{ d.can_send ? $t('settings.mailbox.canSend') : $t('settings.mailbox.readingOnlyAuthorizeOnce') }}</span>
      </div>
      <details class="tech"><summary>{{ $t('settings.mailbox.howToGetThis') }}</summary><pre>{{ $t('settings.mailbox.inGoogleCloudCreate') }}</pre></details>
    </template>
    <template v-else>
      <p class="callout" style="margin-top: 12px"><Icon name="info" /><span>{{ preset.how }}</span></p>
      <div class="kv">
        <template v-if="pick === 'custom'">
          <label>{{ $t('settings.mailbox.imapServer') }}</label><div class="row" style="flex-wrap: nowrap"><input v-model="form.host" class="grow" placeholder="imap.example.com" /><input v-model.number="form.port" type="number" style="width: 90px" :aria-label="$t('settings.mailbox.port')" /></div>
        </template>
        <label>{{ $t('settings.mailbox.emailAddress') }}</label><input v-model="form.user" placeholder="you@example.com" autocomplete="off" />
        <template v-if="isOutlook">
          <label>{{ $t('settings.mailbox.applicationClientId') }}</label><input v-model="clientId" :placeholder="d.outlook.client_id ? $t('settings.mailbox.savedToChangeIt') : $t('settings.mailbox.formatXxxxxxxxXxxxXxxx')" autocomplete="off" />
          <label>{{ $t('settings.mailbox.authorize') }}</label>
          <div>
            <div class="row"><button :disabled="busy || !form.user || (!clientId.trim() && !d.outlook.client_id)" @click="outlookAuth"><Icon name="login" />{{ d.outlook.authorized ? $t('settings.mailbox.reauthorize') : $t('settings.mailbox.authorize') }}</button>
              <span class="badge" :class="d.outlook.authorized ? 'ok' : ''">{{ d.outlook.authorized ? $t('settings.mailbox.authorized') : $t('settings.mailbox.notAuthorizedYet') }}</span>
              <button v-if="d.outlook.authorized" class="sm ghost danger" @click="outlookForget">{{ $t('settings.mailbox.removeAccess') }}</button></div>
            <p v-if="d.outlook.flow.state === 'waiting'" class="callout" style="margin-top: 8px"><Icon name="info" /><span>{{ $t('settings.mailbox.open') }} <a :href="d.outlook.flow.url" target="_blank" rel="noopener">{{ d.outlook.flow.url }}</a>{{ $t('settings.mailbox.enterTheCode') }} <b style="font-size: 16px; letter-spacing: 1px">{{ d.outlook.flow.code }}</b>{{ $t('settings.mailbox.signInWithYour') }}</span></p>
            <p v-else-if="d.outlook.flow.state === 'failed'" class="small" style="color: var(--bad); margin-top: 6px">{{ $t('settings.mailbox.didntWork', { p0: d.outlook.flow.error }) }}</p>
          </div>
        </template>
        <template v-else>
          <label>{{ $t('settings.mailbox.authorizationCodeAppPassword') }}</label><input v-model="form.password" type="password" autocomplete="new-password" :placeholder="d.imap.has_password && inUse ? $t('settings.mailbox.savedLeaveBlankTo') : $t('settings.mailbox.notYourEmailLogin')" />
        </template>
      </div>
      <p class="hint" style="margin-top: 8px">{{ $t('settings.mailbox.authorizationCodesAndTokens') }}</p>
    </template>

    <div class="row" style="margin-top: 12px">
      <button :disabled="busy" @click="test"><Icon name="refresh" />{{ busy ? $t('settings.mailbox.pleaseWait') : $t('settings.mailbox.testIfItCan') }}</button>
      <button class="primary" :disabled="busy || (pick !== 'gmail_api' && !form.user)" @click="save"><Icon name="check" />{{ inUse ? $t('settings.mailbox.save') : $t('settings.mailbox.saveAndSwitchTo') }}</button>
      <span v-if="result" class="small" :style="result.ok ? 'color: var(--ok)' : 'color: var(--bad)'">{{ result.text }}</span>
    </div>
  </div>
</template>

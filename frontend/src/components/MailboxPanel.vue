<script setup>
import { t as T } from '../i18n/catalog'
// Which mailbox the program reads (read-only): verification codes and links, confirmations, interview invitations, rejections.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { ask, run, toast } from '../ui'
import { clone, same, useUnsaved } from '../dirty'
import CardHead from './CardHead.vue'
import FileButton from './FileButton.vue'
import HelpPop from './HelpPop.vue'
import Icon from './Icon.vue'
import Status from './Status.vue'

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
const outlookForget = async () => (await ask(T('settings.mailbox.removeAccessAsk'), { ok: T('settings.mailbox.removeAccess'), danger: true })) && run(() => api.del('/mailbox/outlook'), T('settings.mailbox.outlookAuthorizationRemoved'), load)
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
// Mail from before: read as history (on the applications, nothing announced) - from the first application still in
// play, or a span chosen here
const backFrom = ref('')
const backTo = ref('')
const readBack = (span) => run(() => api.post('/mailbox/read-back', span ? { since: backFrom.value, until: backTo.value || undefined } : {}),
  (r) => (r.until ? T('settings.mailbox.readingSpan', { from: r.since, to: r.until }) : T('settings.mailbox.readingFrom', { from: r.since })), load)
onMounted(load)
</script>

<template>
  <div v-if="d" class="card">
    <CardHead :title="$t('settings.mailbox.email')" :help="$t('settings.mailbox.readingCodesAndActivation')">
      <template #after><Status :tone="d.ready ? 'ok' : 'warn'" :label="d.ready ? $t('settings.mailbox.connected') : $t('settings.mailbox.notConnectedYet')" /></template>
    </CardHead>
    <div class="kv">
      <label>{{ $t('settings.mailbox.emailType') }}</label>
      <AaSelect v-model="pick" @change="fill">
        <option value="gmail_api">{{ $t('settings.mailbox.gmailGoogleAuthorizationReads') }}</option>
        <option v-for="p in d.presets" :key="p.key" :value="p.key">{{ p.name }}</option>
      </AaSelect>

      <template v-if="pick === 'gmail_api'">
        <label>{{ $t('settings.mailbox.authorize') }}<HelpPop :text="$t('settings.mailbox.authorizingAsksForReading')" :label="$t('settings.mailbox.authorize')" /></label>
        <div class="set-val">
          <FileButton accept=".json" @change="gmailClient"><Icon name="inbox" />{{ $t('settings.mailbox.chooseJsonFile') }}</FileButton>
          <button :disabled="!d.client" @click="gmailAuth">{{ $t('settings.mailbox.authorize') }}</button>
          <Status :tone="d.authorized ? 'ok' : d.reconnect ? 'warn' : ''" :label="d.authorized ? $t('settings.mailbox.authorized') : d.reconnect ? $t('settings.mailbox.theAuthorizationIsNo') : d.client ? $t('settings.mailbox.fileUploadedNotYet') : $t('settings.mailbox.noFilesUploadedYet')" />
          <Status v-if="d.authorized" :tone="d.can_send ? 'ok' : 'warn'" :label="d.can_send ? $t('settings.mailbox.canSend') : $t('settings.mailbox.readingOnlyAuthorizeOnce')" />
        </div>
      </template>
      <template v-else>
        <template v-if="pick === 'custom'">
          <label>{{ $t('settings.mailbox.imapServer') }}</label>
          <div class="set-val"><input v-model="form.host" class="w-short" placeholder="imap.example.com" :aria-label="$t('settings.mailbox.imapServer')" /><input v-model.number="form.port" class="w-num" type="number" :aria-label="$t('settings.mailbox.port')" /></div>
        </template>
        <label>{{ $t('settings.mailbox.emailAddress') }}</label><input v-model="form.user" placeholder="you@example.com" autocomplete="off" />
        <template v-if="isOutlook">
          <label>{{ $t('settings.mailbox.applicationClientId') }}</label><input v-model="clientId" :placeholder="d.outlook.client_id ? $t('settings.mailbox.savedToChangeIt') : $t('settings.mailbox.formatXxxxxxxxXxxxXxxx')" autocomplete="off" />
          <label>{{ $t('settings.mailbox.authorize') }}</label>
          <div class="set-val">
            <button :disabled="busy || !form.user || (!clientId.trim() && !d.outlook.client_id)" @click="outlookAuth"><Icon name="login" />{{ d.outlook.authorized ? $t('settings.mailbox.reauthorize') : $t('settings.mailbox.authorize') }}</button>
            <Status :tone="d.outlook.authorized ? 'ok' : ''" :label="d.outlook.authorized ? $t('settings.mailbox.authorized') : $t('settings.mailbox.notAuthorizedYet')" />
            <button v-if="d.outlook.authorized" class="sm ghost" @click="outlookForget">{{ $t('settings.mailbox.removeAccess') }}</button>
            <span v-if="d.outlook.flow.state === 'failed'" class="form-note bad">{{ $t('settings.mailbox.didntWork', { p0: d.outlook.flow.error }) }}</span>
          </div>
        </template>
        <template v-else>
          <label>{{ $t('settings.mailbox.authorizationCodeAppPassword') }}<HelpPop :text="$t('settings.mailbox.authorizationCodesAndTokens')" /></label><input v-model="form.password" type="password" autocomplete="new-password" :placeholder="d.imap.has_password && inUse ? $t('settings.mailbox.savedLeaveBlankTo') : $t('settings.mailbox.notYourEmailLogin')" />
        </template>
      </template>
    </div>

    <details v-if="pick === 'gmail_api'" class="tech"><summary>{{ $t('settings.mailbox.howToGetThis') }}</summary><pre>{{ $t('settings.mailbox.inGoogleCloudCreate') }}</pre></details>
    <template v-else>
      <p v-if="isOutlook && d.outlook.flow.state === 'waiting'" class="callout after-form"><Icon name="info" /><span>{{ $t('settings.mailbox.open') }} <a :href="d.outlook.flow.url" target="_blank" rel="noopener">{{ d.outlook.flow.url }}</a>{{ $t('settings.mailbox.enterTheCode') }} <b class="set-code">{{ d.outlook.flow.code }}</b>{{ $t('settings.mailbox.signInWithYour') }}</span></p>
      <p v-if="preset && preset.how" class="callout after-form"><Icon name="info" /><span>{{ preset.how }}</span></p>
    </template>

    <div class="set-actions">
      <button :disabled="busy" @click="test"><Icon name="refresh" />{{ busy ? $t('settings.mailbox.pleaseWait') : $t('settings.mailbox.testIfItCan') }}</button>
      <button class="primary" :disabled="busy || (pick !== 'gmail_api' && !form.user)" @click="save"><Icon name="check" />{{ inUse ? $t('settings.mailbox.save') : $t('settings.mailbox.saveAndSwitchTo') }}</button>
      <Status v-if="dirty" tone="warn" :label="$t('settings.page.unsavedChanges')" />
      <span v-if="result" class="result" :class="result.ok ? 'ok' : 'bad'" role="status">{{ result.text }}</span>
    </div>
    <div v-if="d.ready" class="read-back">
      <div class="t-meta">{{ $t('settings.mailbox.mailFromBefore') }} <HelpPop :text="$t('settings.mailbox.mailFromBeforeHelp')" /></div>
      <p class="t-secondary small">{{ d.read_back.read_to ? $t('settings.mailbox.readBackTo', { day: d.read_back.read_to }) : $t('settings.mailbox.notReadBackYet') }}<template v-if="d.read_back.reading"> · {{ $t('settings.mailbox.readingNow') }}</template></p>
      <div class="actions">
        <button v-if="d.read_back.first_open" type="button" :disabled="d.read_back.reading" @click="readBack(false)"><Icon name="mail" />{{ $t('settings.mailbox.readFromFirstOpen', { day: d.read_back.first_open }) }}</button>
      </div>
      <div class="actions back-span">
        <input v-model="backFrom" type="date" :aria-label="$t('settings.mailbox.spanFrom')" />
        <span class="t-secondary">–</span>
        <input v-model="backTo" type="date" :aria-label="$t('settings.mailbox.spanTo')" />
        <button type="button" :disabled="!backFrom || d.read_back.reading || (backTo && backTo < backFrom)" @click="readBack(true)">{{ $t('settings.mailbox.readThisSpan') }}</button>
      </div>
    </div>
    <p class="set-note">{{ $t('settings.page.howOftenTheMailbox') }}<router-link to="/settings/automation/schedule">{{ $t('settings.page.plan') }}</router-link>{{ $t('settings.page.text') }}</p>
  </div>
</template>

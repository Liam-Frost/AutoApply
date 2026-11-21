<script setup>
import { t as T } from '../i18n/catalog'
// Which AI service does the work. Each service keeps its own settings; "用这个" switches to it.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { run, toast } from '../ui'
import { clockOf, shortDayOf } from '../i18n/format'
import { mayLeave, same, useUnsaved } from '../dirty'
import Icon from './Icon.vue'
import ModelPick from './ModelPick.vue'
import TechDetails from './TechDetails.vue'

const props = defineProps({ s: { type: Object, required: true }, sec: { type: Object, required: true }, secrets: { type: Object, default: () => ({}) } })
const emit = defineEmits(['changed'])
const d = ref(null)
const pick = ref('')
const form = ref({ base_url: '', model: '', small_model: '', effort: '', api_key: '' })
const models = ref([])
const claude = ref(null)
const busy = ref(false)
const loadingModels = ref(false)
const modelNote = ref('')

const cur = computed(() => d.value && d.value.providers.find((p) => p.key === pick.value))
const inUse = computed(() => d.value && d.value.current === pick.value)
const GROUPS = [[T('settings.ai.signInWithSubscription'), ['claude_subscription', 'chatgpt']], [T('settings.ai.useAnApiKey'), ['anthropic', 'openai', 'gemini', 'deepseek', 'qwen', 'openrouter']], [T('settings.ai.other'), ['custom']]]
const byKey = (k) => d.value.providers.find((p) => p.key === k)

function fill() {
  const p = cur.value
  form.value = { base_url: p.base_url || '', model: p.model || '', small_model: p.small_model || '', effort: p.effort || '', api_key: '' }
  models.value = []
}
async function load(keep) {
  d.value = await api.get('/llm/providers')
  pick.value = keep || pick.value || d.value.current
  fill()
  autoModels()
  api.get('/settings/claude-status').then((c) => (claude.value = c)).catch(() => {})
}
// (switching the service that is being set up is leaving what was typed for the other one)
async function choose(k) { if (k === pick.value || !(await mayLeave(['ai-provider']))) return; pick.value = k; fill(); autoModels() }
const formDirty = computed(() => {
  const p = cur.value
  return !!p && (!!form.value.api_key || form.value.base_url !== (p.base_url || '') || form.value.model !== (p.model || '') || form.value.small_model !== (p.small_model || '') || form.value.effort !== (p.effort || ''))
})
let keyTimer
function keyTyped() { clearTimeout(keyTimer); keyTimer = setTimeout(autoModels, 700) }
async function autoModels() {
  const p = cur.value
  if (!p) return
  const can = p.key === 'claude_subscription' || p.key === 'anthropic' || (p.kind === 'codex' ? p.installed && p.logged_in : p.has_key || form.value.api_key || p.key === 'custom')
  models.value = []; modelNote.value = ''
  if (!can || (p.key === 'custom' && !form.value.base_url)) return
  loadingModels.value = true
  const asked = p.key
  try {
    const r = await api.post(`/llm/providers/${p.key}/models`, { base_url: form.value.base_url, api_key: form.value.api_key })
    if (pick.value === asked) models.value = r.models
  } catch (e) { if (pick.value === asked) modelNote.value = e.message }
  loadingModels.value = false
}
async function save(use) {
  busy.value = true
  try {
    await api.put('/llm/providers/' + pick.value, { ...form.value, use })
    toast(use ? T('settings.ai.switchedTo', { p0: cur.value.name }) : T('settings.ai.saved'))
    await load(pick.value)
    emit('changed')
    busy.value = false
    return true
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
  return false
}
useUnsaved({ id: 'ai-provider', get label() { return cur.value ? T('settings.ai.aiService', { p0: cur.value.name.split('（')[0] }) : T('settings.ai.aiService2') }, dirty: () => formDirty.value, save: () => save(false), discard: fill })
async function listModels() {
  busy.value = true
  try {
    models.value = (await api.post(`/llm/providers/${pick.value}/models`, { base_url: form.value.base_url, api_key: form.value.api_key })).models
    toast(models.value.length ? T('settings.ai.foundModelsPickOne', { p0: models.value.length }) : T('settings.ai.thisServiceDidntReturn2'))
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
}
const chatgptLogin = () => run(() => api.post('/llm/chatgpt/login'), T('settings.ai.chatgptSignInPage'), poll)
const chatgptLogout = () => run(() => api.post('/llm/chatgpt/logout'), T('settings.ai.signedOutOfChatgpt'), () => load(pick.value))
let pollTimer
function poll() {
  clearInterval(pollTimer)
  let n = 0
  pollTimer = setInterval(async () => {
    d.value = await api.get('/llm/providers')
    const c = d.value.providers.find((p) => p.key === 'chatgpt')
    if (++n > 100 || !c || !c.login || c.login.state !== 'waiting') clearInterval(pollTimer)
  }, 3000)
}
const test = () => run(() => api.post('/settings/llm-test'), (r) => T('settings.ai.worksModelReplied', { p0: r.reply }))

// --- backups: tried in this order when the service in use runs out or cannot be reached ---
const fo = ref({ chain: [], saved: [] })
const backups = ref([])          // editable copy of the saved list
const foModels = ref({})         // provider -> model names, read once per provider
const foTest = ref({})           // row index -> result of the test button
const foBusy = ref(false)
const usable = (p) => p.key === 'claude_subscription' || (p.kind === 'codex' ? p.installed && p.logged_in : p.kind === 'anthropic' ? p.has_key : (p.has_key || p.key === 'custom') && !!p.model)
const candidates = computed(() => (d.value ? d.value.providers : []))
const stateOf = (b) => fo.value.chain.find((c) => c.provider === b.provider && (c.set_model || '') === (b.model || ''))
async function loadFo() {
  fo.value = await api.get('/llm/failover')
  backups.value = fo.value.saved.map((e) => ({ ...e }))
  backups.value.forEach((b) => modelsFor(b.provider))
}
async function modelsFor(k) {
  if (!k || foModels.value[k]) return
  foModels.value = { ...foModels.value, [k]: [] }
  try { foModels.value = { ...foModels.value, [k]: (await api.post(`/llm/providers/${k}/models`, {})).models } } catch (e) { /* the list stays empty: the name can be typed */ }
}
function addBackup() {
  const used = new Set([d.value.current, ...backups.value.map((b) => b.provider)])
  const first = candidates.value.find((p) => usable(p) && !used.has(p.key)) || candidates.value.find((p) => !used.has(p.key)) || candidates.value[0]
  backups.value.push({ provider: first.key, model: '', small_model: '' })
  modelsFor(first.key)
}
const moveBackup = (i, by) => { const a = backups.value; const j = i + by; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; foTest.value = {} }
async function saveFo() {
  foBusy.value = true
  let ok = true
  try { fo.value = await api.put('/llm/failover', { entries: backups.value }); backups.value = fo.value.saved.map((e) => ({ ...e })); toast(T('settings.ai.backupOrderSaved')); loadQuota(false) } catch (e) { toast(e.message, 'bad'); ok = false }
  foBusy.value = false
  return ok
}
const foDirty = computed(() => !same(backups.value, fo.value.saved))
useUnsaved({ id: 'ai-backups', label: T('settings.ai.backupServices'), dirty: () => foDirty.value, save: saveFo, discard: () => { backups.value = fo.value.saved.map((e) => ({ ...e })); foTest.value = {} } })
async function testBackup(i) {
  foTest.value = { ...foTest.value, [i]: { busy: true } }
  try { foTest.value = { ...foTest.value, [i]: await api.post('/llm/failover/test', backups.value[i]) } } catch (e) { foTest.value = { ...foTest.value, [i]: { error: e.message } } }
}
const resetFo = () => run(() => api.post('/llm/failover/reset'), T('settings.ai.clearedTheNextCall'), loadFo)
const hhmm = (iso) => (iso ? clockOf(new Date(iso)) : '')      // (a local time without a zone)

// --- allowance of each service in the chain, where the service reports one ---
const quota = ref({ services: [], warn_percent: 80, warn_balance: 1, notify: true })
const quotaBusy = ref(false)
const quotaOf = (provider) => quota.value.services.find((x) => x.provider === provider)
async function loadQuota(refresh) {
  quotaBusy.value = true
  try { quota.value = await api.get('/llm/quota' + (refresh ? '?refresh=true' : '')) } catch (e) { if (refresh) toast(e.message, 'bad') }
  quotaBusy.value = false
}
const saveQuota = () => run(() => api.put('/llm/quota', { warn_percent: quota.value.warn_percent, warn_balance: quota.value.warn_balance, notify: quota.value.notify }), T('settings.ai.saved'), (r) => (quota.value = r))
const winTone = (w) => (w.blocked || w.used >= 100 ? 'out' : w.used >= quota.value.warn_percent ? 'low' : '')
const resetAt = (ts) => {      // "01:36" today, "11/18 22:36" on another day: figures only, the words around them are in the template
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toDateString() === new Date().toDateString() ? clockOf(d) : `${shortDayOf(d)} ${clockOf(d)}`
}
onMounted(async () => { await load(); await loadFo(); loadQuota(false) })
</script>

<template>
  <div v-if="d" class="pr">
    <div class="card pr-nav">
      <template v-for="[g, keys] in GROUPS" :key="g">
        <div class="pr-group">{{ g }}</div>
        <button v-for="k in keys" :key="k" :class="{ on: pick === k }" @click="choose(k)">
          <span class="ell">{{ byKey(k).name.split('（')[0] }}</span>
          <span v-if="d.current === k" class="badge ok">{{ $t('settings.ai.inUse') }}</span>
        </button>
      </template>
    </div>

    <div class="card">
      <div class="row">
        <span class="card-title grow">{{ cur.name }}</span>
        <span v-if="formDirty" class="badge warn">{{ $t('settings.ai.unsavedChanges') }}</span>
        <span v-if="inUse" class="badge ok">{{ $t('settings.ai.inUse2') }}</span>
      </div>

      <!-- Claude subscription -->
      <template v-if="cur.key === 'claude_subscription'">
        <p class="muted">{{ $t('settings.ai.usesYourOwnClaude') }}</p>
        <div v-if="claude" class="callout" :class="claude.logged_in ? '' : 'warn'"><Icon :name="claude.logged_in ? 'check' : 'alert'" />
          <div v-if="claude.logged_in">{{ $t('settings.ai.signedInTo', { p0: claude.plan ? '（' + claude.plan + '）' : '' }) }}
            <div v-if="claude.plan" class="small muted">{{ $t('settings.ai.thePlanNameIs') }} <code>uv run autoapply claude-login</code> {{ $t('settings.ai.toSignInAgain') }}</div></div>
          <div v-else>{{ $t('settings.ai.notSignedInIn') }} <code>uv run autoapply claude-login</code>{{ $t('settings.ai.signInInThe') }}</div></div>
        <div class="kv" style="margin-top: 14px">
          <label>{{ $t('settings.ai.mainModel') }}</label><div><ModelPick v-model="props.s['llm.model']" :models="models" :loading="loadingModels" /><div class="hint">{{ $t('settings.ai.theAgentThatWorks') }}</div></div>
          <label>{{ $t('settings.ai.modelForSimpleTasks') }}</label><div><ModelPick v-model="props.s['llm.small_model']" :models="models" :loading="loadingModels" /><div class="hint">{{ $t('settings.ai.forSmallTasksLike') }}</div></div>
          <label>{{ $t('settings.ai.thinkingDepth') }}</label><AaSelect v-model="props.s['llm.effort']"><option value="low">{{ $t('settings.ai.lowFast') }}</option><option value="medium">{{ $t('settings.ai.medium') }}</option><option value="high">{{ $t('settings.ai.high') }}</option><option value="xhigh">{{ $t('settings.ai.highestSlow') }}</option></AaSelect>
          <label>{{ $t('settings.ai.longLivedTokenOptional') }}</label><div><input v-model="props.sec.claude_oauth_token" type="password" autocomplete="off" style="width: 100%" :placeholder="props.secrets.claude_oauth_token ? $t('settings.ai.savedToChangeIt') : $t('settings.ai.signInsExpireFor')" /></div>
        </div>
        <p class="hint" style="margin-top: 10px">{{ $t('settings.ai.afterChangingTheModel') }}</p>
      </template>

      <!-- Anthropic API -->
      <template v-else-if="cur.key === 'anthropic'">
        <p class="muted">{{ $t('settings.ai.usesAnAnthropicApi') }}<a :href="cur.keys" target="_blank" rel="noopener">{{ $t('settings.ai.getAKeyHere') }}</a></p>
        <div class="kv" style="margin-top: 14px">
          <label>API key</label><input v-model="form.api_key" type="password" autocomplete="off" :placeholder="cur.has_key ? $t('settings.ai.savedToChangeIt') : $t('settings.ai.notSavedYet')" @input="keyTyped" />
          <label>{{ $t('settings.ai.mainModel') }}</label><div><ModelPick v-model="props.s['llm.model']" :models="models" :loading="loadingModels" /><div class="hint">{{ $t('settings.ai.theAgentThatWorks') }}</div></div>
          <label>{{ $t('settings.ai.modelForSimpleTasks') }}</label><ModelPick v-model="props.s['llm.small_model']" :models="models" :loading="loadingModels" />
          <label>{{ $t('settings.ai.thinkingDepth') }}</label><AaSelect v-model="props.s['llm.effort']"><option value="low">{{ $t('settings.ai.lowFast') }}</option><option value="medium">{{ $t('settings.ai.medium') }}</option><option value="high">{{ $t('settings.ai.high') }}</option><option value="xhigh">{{ $t('settings.ai.highestSlow') }}</option></AaSelect>
        </div>
        <p class="hint" style="margin-top: 10px">{{ $t('settings.ai.afterChangingTheModel2') }}</p>
      </template>

      <!-- ChatGPT subscription through the official Codex SDK -->
      <template v-else-if="cur.kind === 'codex'">
        <p class="muted">{{ $t('settings.ai.usesYourChatgptSubscription') }}</p>
        <div class="callout" :class="cur.installed && cur.logged_in ? '' : 'warn'" style="margin-top: 10px"><Icon :name="cur.installed && cur.logged_in ? 'check' : 'info'" />
          <div v-if="!cur.installed">{{ $t('settings.ai.theConnectorIsntInstalled') }} <code>uv sync --extra chatgpt</code>{{ $t('settings.ai.downloadsAboutMbThen') }}</div>
          <div v-else-if="cur.login && cur.login.state === 'waiting'">{{ $t('settings.ai.theChatgptSignIn') }}<a :href="cur.login.url" target="_blank" rel="noopener">{{ $t('settings.ai.clickHereToOpen') }}</a></div>
          <div v-else-if="!cur.logged_in">{{ $t('settings.ai.componentInstalledNotSigned') }}<template v-if="cur.login && cur.login.error">{{ $t('settings.ai.lastAttemptFailed', { p0: cur.login.error }) }}</template></div>
          <div v-else>{{ $t('settings.ai.signedInTo2', { p0: cur.plan ? '（' + cur.plan + '）' : '' }) }}</div></div>
        <div v-if="cur.installed" class="row" style="margin-top: 10px">
          <button v-if="!cur.logged_in" class="primary" @click="chatgptLogin"><Icon name="login" />{{ $t('settings.ai.signInWithChatgpt') }}</button>
          <button v-else class="ghost danger" @click="chatgptLogout">{{ $t('settings.ai.signOut') }}</button>
        </div>
        <div class="kv" style="margin-top: 14px">
          <label>{{ $t('settings.ai.mainModel') }}</label><ModelPick v-model="form.model" :models="models" :loading="loadingModels" :allow-empty="$t('settings.ai.useTheAccountsDefault')" />
          <label>{{ $t('settings.ai.modelForSimpleTasks') }}</label><ModelPick v-model="form.small_model" :models="models" :loading="loadingModels" :allow-empty="$t('settings.ai.sameAsMainModel')" />
          <label>{{ $t('settings.ai.thinkingDepth') }}</label><div><AaSelect v-model="form.effort"><option value="">{{ $t('settings.ai.theAccountsDefault') }}</option><option value="low">{{ $t('settings.ai.lowFastLightOn') }}</option><option value="medium">{{ $t('settings.ai.medium') }}</option><option value="high">{{ $t('settings.ai.high') }}</option><option value="xhigh">{{ $t('settings.ai.highestSlowHeavyOn') }}</option></AaSelect>
            <div class="hint">{{ $t('settings.ai.forTheMainModel') }}</div></div>
        </div>
      </template>

      <!-- OpenAI-compatible -->
      <template v-else>
        <p class="muted">{{ $t('settings.ai.usesThisProvidersApi') }}<a v-if="cur.keys" :href="cur.keys" target="_blank" rel="noopener">{{ $t('settings.ai.getAKeyHere') }}</a>
          <template v-if="cur.key === 'custom'">{{ $t('settings.ai.enterTheUrlOf') }} <code>http://localhost:11434/v1</code>{{ $t('settings.ai.noKeyNeeded') }}</template></p>
        <div class="kv" style="margin-top: 14px">
          <label>{{ $t('settings.ai.endpointUrl') }}</label><input v-model="form.base_url" :placeholder="cur.default_base_url || 'https://…/v1'" />
          <label>API key</label><input v-model="form.api_key" type="password" autocomplete="off" :placeholder="cur.has_key ? $t('settings.ai.savedToChangeIt') : cur.key === 'custom' ? $t('settings.ai.leaveBlankIfNot') : $t('settings.ai.notSavedYet')" @input="keyTyped" />
          <label>{{ $t('settings.ai.mainModel') }}</label>
          <div><ModelPick v-model="form.model" :models="models" :loading="loadingModels" />
            <div v-if="!models.length && !loadingModels" class="hint">{{ modelNote || (cur.has_key || form.api_key || cur.key === 'custom' ? $t('settings.ai.thisServiceDidntReturn') : $t('settings.ai.onceYouEnterAn')) }}</div>
            <div class="hint">{{ $t('settings.ai.theAgentThatWorks2') }}</div></div>
          <label>{{ $t('settings.ai.modelForSimpleTasks') }}</label>
          <div><ModelPick v-model="form.small_model" :models="models" :loading="loadingModels" :allow-empty="$t('settings.ai.sameAsMainModel')" />
            <div class="hint">{{ $t('settings.ai.usedForSmallTasks') }}</div></div>
          <label>{{ $t('settings.ai.thinkingDepth') }}</label><div><AaSelect v-model="form.effort"><option value="">{{ $t('settings.ai.notSetTheServices') }}</option><option value="low">{{ $t('settings.ai.lowFastCheap') }}</option><option value="medium">{{ $t('settings.ai.medium') }}</option><option value="high">{{ $t('settings.ai.high') }}</option><option value="xhigh">{{ $t('settings.ai.highestSlowCostly') }}</option></AaSelect>
            <div class="hint">{{ $t('settings.ai.forTheMainModel2') }}</div></div>
        </div>
      </template>

      <div class="row" style="margin-top: 16px">
        <button v-if="!inUse" class="primary" :disabled="busy" @click="save(true)"><Icon name="check" />{{ $t('settings.ai.saveAndUseThis') }}</button>
        <button v-if="cur.key !== 'claude_subscription'" :class="{ primary: inUse }" :disabled="busy" @click="save(false)">{{ $t('settings.ai.save', { p0: inUse ? '' : $t('settings.ai.dontSwitchYet') }) }}</button>
        <button v-if="inUse" @click="test">{{ $t('settings.ai.testIt') }}</button>
      </div>
    </div>

    <div class="card" style="grid-column: 1 / -1">
      <div class="row"><span class="card-title grow">{{ $t('settings.ai.backupServicesUsedAutomatically') }}</span>
        <button class="sm ghost" :disabled="quotaBusy" @click="loadQuota(true)"><Icon name="refresh" />{{ quotaBusy ? $t('settings.ai.checking') : $t('settings.ai.refreshUsage') }}</button>
        <button v-if="fo.chain.some((c) => c.state === 'cooling')" class="sm ghost" @click="resetFo">{{ $t('settings.ai.retryAll') }}</button></div>
      <p class="muted">{{ $t('settings.ai.whenAServiceRuns') }}</p>
      <div class="list" style="margin-top: 10px">
        <div v-if="fo.chain.length" class="item">
          <span class="badge info">{{ $t('settings.ai.primary') }}</span>
          <div class="grow"><b>{{ fo.chain[0].name }}</b> <span class="muted small">{{ fo.chain[0].model }}{{ fo.chain[0].small_model && fo.chain[0].small_model !== fo.chain[0].model ? $t('settings.ai.simpleTasksModel', { model: fo.chain[0].small_model }) : '' }}</span>
            <div v-if="fo.chain[0].state === 'cooling'" class="small" style="color: var(--warn)">{{ $t('settings.ai.pausedForNowWill', { p0: hhmm(fo.chain[0].until) }) }}</div>
            <div v-if="quotaOf(fo.chain[0].provider)" class="quota">
              <template v-for="q in [quotaOf(fo.chain[0].provider)]" :key="q.provider">
                <div v-if="!q.supported" class="muted small">{{ q.note }}</div>
                <div v-else-if="q.error" class="muted small">{{ $t('settings.ai.couldntCheckUsageThis') }}</div>
                <div v-else-if="q.pending" class="muted small">{{ q.note }}</div>
                <div v-for="w in q.windows || []" :key="w.key" class="qrow"><span class="lab">{{ w.label }}</span><span class="track"><span class="fill" :class="winTone(w)" :style="{ width: Math.min(100, w.used || 0) + '%' }"></span></span>
                  <span class="val"><template v-if="w.blocked || w.used >= 100">{{ $t('settings.ai.usedUp') }}</template><template v-else>{{ $t('settings.ai.used', { p0: w.used }) }}</template><span v-if="w.resets_at" class="muted">{{ $t('settings.ai.resets', { p0: resetAt(w.resets_at) }) }}</span></span></div>
                <div v-for="b in q.balances || []" :key="b.currency" class="small">{{ $t('settings.ai.balance') }} <b>{{ b.amount.toFixed(2) }} {{ b.currency }}</b></div>
              </template>
            </div></div>
          <span class="badge" :class="fo.chain[0].state === 'cooling' ? 'warn' : 'ok'">{{ fo.chain[0].state === 'cooling' ? $t('settings.ai.paused') : $t('settings.ai.available') }}</span>
        </div>
        <div v-for="(b, i) in backups" :key="i" class="item" style="align-items: flex-start">
          <span class="badge">{{ $t('settings.ai.backup', { p0: i + 1 }) }}</span>
          <div class="grow">
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <AaSelect v-model="b.provider" @change="b.model = ''; b.small_model = ''; modelsFor(b.provider)">
                <option v-for="p in candidates" :key="p.key" :value="p.key">{{ p.name.split('（')[0] }}{{ usable(p) ? '' : $t('settings.ai.notSetUpYet') }}</option>
              </AaSelect>
              <ModelPick v-model="b.model" :models="foModels[b.provider] || []" :allow-empty="$t('settings.ai.mainModelUseThis')" />
              <ModelPick v-model="b.small_model" :models="foModels[b.provider] || []" :allow-empty="$t('settings.ai.simpleTasksUseThis')" />
            </div>
            <div v-if="!usable(candidates.find((p) => p.key === b.provider) || {})" class="small" style="color: var(--warn); margin-top: 4px">{{ $t('settings.ai.thisProviderIsntSet') }}</div>
            <div v-else-if="stateOf(b) && stateOf(b).state === 'cooling'" class="small" style="color: var(--warn); margin-top: 4px">{{ $t('settings.ai.pausedForNowWill', { p0: hhmm(stateOf(b).until) }) }}</div>
            <div v-if="quotaOf(b.provider)" class="quota">
              <template v-for="q in [quotaOf(b.provider)]" :key="q.provider">
                <div v-if="!q.supported" class="muted small">{{ q.note }}</div>
                <div v-else-if="q.error" class="muted small">{{ $t('settings.ai.couldntCheckUsageThis') }}</div>
                <div v-else-if="q.pending" class="muted small">{{ q.note }}</div>
                <div v-for="w in q.windows || []" :key="w.key" class="qrow"><span class="lab">{{ w.label }}</span><span class="track"><span class="fill" :class="winTone(w)" :style="{ width: Math.min(100, w.used || 0) + '%' }"></span></span>
                  <span class="val"><template v-if="w.blocked || w.used >= 100">{{ $t('settings.ai.usedUp') }}</template><template v-else>{{ $t('settings.ai.used', { p0: w.used }) }}</template><span v-if="w.resets_at" class="muted">{{ $t('settings.ai.resets', { p0: resetAt(w.resets_at) }) }}</span></span></div>
                <div v-for="bal in q.balances || []" :key="bal.currency" class="small">{{ $t('settings.ai.balance') }} <b>{{ bal.amount.toFixed(2) }} {{ bal.currency }}</b></div>
              </template>
            </div>
            <template v-if="foTest[i]">
              <div v-if="foTest[i].busy" class="callout" style="margin-top: 8px"><Icon name="clock" /><div>{{ $t('settings.ai.sendingEachServiceA') }}</div></div>
              <div v-else-if="foTest[i].error" class="callout bad" style="margin-top: 8px"><Icon name="alert" /><div>{{ foTest[i].error }}</div></div>
              <template v-else>
                <div v-for="[k, lab] in [['main', $t('settings.ai.mainModel')], ['small', $t('settings.ai.modelForSimpleTasks')]]" :key="k" class="callout" :class="foTest[i][k].ok ? 'ok' : 'warn'" style="margin-top: 8px">
                  <Icon :name="foTest[i][k].ok ? 'check' : 'alert'" />
                  <div class="grow">
                    <div><b>{{ lab }}</b><span class="muted">{{ foTest[i][k].model ? '（' + foTest[i][k].model + '）' : '' }}</span>：{{ foTest[i][k].ok ? $t('settings.ai.workingItCanTake') : foTest[i][k].message }}</div>
                    <div v-if="!foTest[i][k].ok && foTest[i].quota && foTest[i].quota.lines.length" class="small muted" style="margin-top: 2px">{{ foTest[i].quota.lines.map((l) => l[0] + '：' + l[1]).join('；') }}</div>
                    <TechDetails v-if="!foTest[i][k].ok" :text="foTest[i][k].detail" />
                  </div>
                </div>
              </template>
            </template>
          </div>
          <div class="row" style="gap: 4px">
            <button class="sm ghost" :disabled="i === 0" :title="$t('settings.ai.moveUp')" @click="moveBackup(i, -1)">↑</button>
            <button class="sm ghost" :disabled="i === backups.length - 1" :title="$t('settings.ai.moveDown')" @click="moveBackup(i, 1)">↓</button>
            <button class="sm" @click="testBackup(i)">{{ $t('settings.ai.test') }}</button>
            <button class="sm ghost danger" @click="backups.splice(i, 1); foTest = {}">{{ $t('settings.ai.delete') }}</button>
          </div>
        </div>
      </div>
      <div class="row small" style="gap: 14px; flex-wrap: wrap; margin-top: 12px; align-items: center">
        <span class="muted">{{ $t('settings.ai.allowanceWarningsAppliedAs') }}</span>
        <label>{{ $t('settings.ai.whenUsageReaches') }} <input v-model.number="quota.warn_percent" type="number" min="1" max="100" style="width: 70px" @change="saveQuota" /> {{ $t('settings.ai.text') }}</label>
        <label>{{ $t('settings.ai.whenBalanceFallsBelow') }} <input v-model.number="quota.warn_balance" type="number" min="0" step="0.5" style="width: 80px" @change="saveQuota" /> {{ $t('settings.ai.text2') }}</label>
        <label><input v-model="quota.notify" type="checkbox" @change="saveQuota" /> {{ $t('settings.ai.notifyMe') }}</label>
        <span class="muted">{{ $t('settings.ai.checkedEveryMinutesUsage', { p0: quota.check_minutes || 30 }) }}</span>
      </div>
      <p v-if="!backups.length" class="muted" style="margin-top: 10px">{{ $t('settings.ai.noBackupServicesYet') }}</p>
      <div class="row" style="margin-top: 12px">
        <button @click="addBackup"><Icon name="plus" />{{ $t('settings.ai.addBackupService') }}</button>
        <button class="primary" :disabled="foBusy || !foDirty" @click="saveFo"><Icon name="check" />{{ $t('settings.ai.saveBackupOrder') }}</button>
        <span v-if="foDirty" class="badge warn">{{ $t('settings.ai.unsavedChanges') }}</span>
      </div>
    </div>
  </div>
</template>

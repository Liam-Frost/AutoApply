<script setup>
import { t as T } from '../i18n/catalog'
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import CardHead from './CardHead.vue'
import Icon from './Icon.vue'
import IconButton from './IconButton.vue'
import Trunc from './Trunc.vue'

const props = defineProps({ s: { type: Object, required: true } })
const status = ref(null)
const busy = ref(false)
const load = async () => { try { status.value = await api.get('/browser/status') } catch (e) { toast(e.message, 'bad') } }
const add = () => { props.s['browser.rules'].push({ domain: '', backend: 'nodriver', operations: [] }) }
// a rule is for an account (the whole of a site's work) or for a domain (pages passed on the way, by kind of work)
const OPS = { login: T('settings.browser.signIn'), scan: T('settings.browser.scan'), read: T('settings.browser.read'), apply: T('settings.browser.apply') }
function setKind(rule, kind) {
  const v = rule.tenant || rule.domain || ''
  delete rule[kind === 'tenant' ? 'domain' : 'tenant']
  rule[kind] = v
}
async function test() {
  busy.value = true
  try { await api.post('/browser/test'); toast(T('settings.browser.nodriverStartedTheBrowser')) } catch (e) { toast(e.message, 'bad') }
  finally { busy.value = false; await load() }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <CardHead :title="$t('settings.browser.browserBackend')" :help="$t('settings.browser.playwrightIsUsedBy')">
      <template #after><span v-if="status" class="meta small">{{ status.installed ? $t('settings.browser.nodriverIsInstalled') : $t('settings.browser.installWithUvSync') }}</span></template>
    </CardHead>
    <div class="kv">
      <label for="f-nodriver">{{ $t('settings.browser.enableNodriver') }}</label><div class="set-val"><input id="f-nodriver" v-model="props.s['browser.nodriver_enabled']" type="checkbox" /></div>
      <label>{{ $t('settings.browser.chromeEdgePath') }}</label>
      <div class="set-val"><input v-model="props.s['browser.executable']" class="w-full" :placeholder="$t('settings.browser.leaveEmptyToDetect')" />
        <Trunc v-if="status" class="hint" data-notr :text="status.executable || $t('settings.browser.chromeEdgeNotFound')" /></div>
    </div>
    <div class="set-actions"><button :disabled="busy || !status?.installed" @click="test">{{ busy ? $t('settings.browser.testing') : $t('settings.browser.testTheBrowserWith') }}</button></div>
  </div>
  <div class="card">
    <CardHead :title="$t('settings.browser.siteRules')" :help="$t('settings.browser.anAccountRuleSays')" :note="props.s['browser.rules'].length || ''">
      <button class="sm" @click="add"><Icon name="plus" />{{ $t('settings.browser.addRule') }}</button>
    </CardHead>
    <div v-if="props.s['browser.rules'].length" class="rule-rows">
      <div class="rule-row head" aria-hidden="true"><span>{{ $t('settings.browser.ruleFor') }}</span><span>{{ $t('settings.browser.siteId') }} / {{ $t('settings.browser.domain') }}</span><span>{{ $t('settings.browser.whichBrowserToUse') }}</span><span>{{ $t('settings.browser.usedFor') }}</span><span></span></div>
      <div v-for="(rule, i) in props.s['browser.rules']" :key="i" class="rule-row">
        <AaSelect :model-value="rule.tenant !== undefined ? 'tenant' : 'domain'" :aria-label="$t('settings.browser.whetherTheRuleIs')" @update:model-value="setKind(rule, $event)">
          <option value="tenant">{{ $t('settings.browser.accountTenant') }}</option><option value="domain">{{ $t('settings.browser.domain') }}</option>
        </AaSelect>
        <input v-if="rule.tenant !== undefined" v-model="rule.tenant" placeholder="pdportal:ubc" :aria-label="$t('settings.browser.siteId')" />
        <input v-else v-model="rule.domain" placeholder="accounts.google.com" :aria-label="$t('settings.browser.domain')" />
        <AaSelect v-model="rule.backend" :aria-label="$t('settings.browser.whichBrowserToUse')"><option value="playwright">{{ $t('settings.browser.engineOwn') }}</option><option value="nodriver">{{ $t('settings.browser.engineOrdinary') }}</option></AaSelect>
        <div v-if="rule.tenant === undefined" class="set-opts"><label v-for="(label, key) in OPS" :key="key"><input v-model="rule.operations" type="checkbox" :value="key" /> {{ label }}</label></div>
        <span v-else class="meta small">{{ $t('settings.browser.allWork') }}</span>
        <IconButton icon="trash" :label="$t('settings.browser.delete')" @click="props.s['browser.rules'].splice(i, 1)" />
      </div>
    </div>
  </div>
</template>

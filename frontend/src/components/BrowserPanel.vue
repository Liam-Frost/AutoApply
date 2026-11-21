<script setup>
import { t as T } from '../i18n/catalog'
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'

const props = defineProps({ s: { type: Object, required: true } })
const status = ref(null)
const busy = ref(false)
const load = async () => { try { status.value = await api.get('/browser/status') } catch (e) { toast(e.message, 'bad') } }
const add = () => { props.s['browser.rules'].push({ domain: '', backend: 'nodriver', operations: [] }) }
async function test() {
  busy.value = true
  try { await api.post('/browser/test'); toast(T('settings.browser.nodriverStartedTheBrowser')) } catch (e) { toast(e.message, 'bad') }
  finally { busy.value = false; await load() }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-title">{{ $t('settings.browser.browserBackend') }}</div>
    <p class="muted">{{ $t('settings.browser.playwrightIsUsedBy') }}</p>
    <label><input v-model="props.s['browser.nodriver_enabled']" type="checkbox" />{{ $t('settings.browser.enableNodriver') }}</label>
    <div class="kv" style="margin-top: 16px">
      <label>{{ $t('settings.browser.chromeEdgePath') }}</label><input v-model="props.s['browser.executable']" :placeholder="$t('settings.browser.leaveEmptyToDetect')" />
    </div>
    <p v-if="status" class="hint">{{ status.installed ? $t('settings.browser.nodriverIsInstalled') : $t('settings.browser.installWithUvSync') }} · {{ status.executable || $t('settings.browser.chromeEdgeNotFound') }}</p>
    <button :disabled="busy || !status?.installed" @click="test">{{ busy ? $t('settings.browser.testing') : $t('settings.browser.testTheBrowserWith') }}</button>
  </div>
  <div class="card">
    <div class="row"><span class="card-title grow">{{ $t('settings.browser.siteRules') }}</span><button @click="add">{{ $t('settings.browser.addRule') }}</button></div>
    <p class="hint">{{ $t('settings.browser.anAccountRuleSays') }}</p>
    <div v-for="(rule, i) in props.s['browser.rules']" :key="i" class="row" style="margin-top: 10px; flex-wrap: wrap">
      <AaSelect :value="rule.tenant !== undefined ? 'tenant' : 'domain'" :aria-label="$t('settings.browser.whetherTheRuleIs')" @change="rule[$event.target.value] = rule.tenant || rule.domain || ''; delete rule[$event.target.value === 'tenant' ? 'domain' : 'tenant']">
        <option value="tenant">{{ $t('settings.browser.accountTenant') }}</option><option value="domain">{{ $t('settings.browser.domain') }}</option>
      </AaSelect>
      <input v-if="rule.tenant !== undefined" v-model="rule.tenant" placeholder="pdportal:ubc" :aria-label="$t('settings.browser.siteId')" />
      <input v-else v-model="rule.domain" placeholder="accounts.google.com" :aria-label="$t('settings.browser.domain')" />
      <AaSelect v-model="rule.backend" :aria-label="$t('settings.browser.whichBrowserToUse')"><option value="playwright">Playwright</option><option value="nodriver">nodriver</option></AaSelect>
      <template v-if="rule.tenant === undefined"><label v-for="(label, key) in { login: $t('settings.browser.signIn'), scan: $t('settings.browser.scan'), read: $t('settings.browser.read'), apply: $t('settings.browser.apply') }" :key="key"><input v-model="rule.operations" type="checkbox" :value="key" />{{ label }}</label></template>
      <button @click="props.s['browser.rules'].splice(i, 1)">{{ $t('settings.browser.delete') }}</button>
    </div>
  </div>
</template>

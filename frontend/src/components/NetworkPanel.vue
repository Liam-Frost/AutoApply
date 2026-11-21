<script setup>
// How the program connects to the internet. Edits the settings object it is given; the page's own "保存" stores them.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import Icon from './Icon.vue'

const props = defineProps({ s: { type: Object, required: true }, sec: { type: Object, required: true }, hasPassword: Boolean })
const state = ref(null)
const results = ref(null)
const testing = ref(false)

async function load() { state.value = await api.get('/proxy') }
async function test() {
  testing.value = true; results.value = null
  try { const r = await api.post('/proxy/test'); state.value = r; results.value = r.results } catch (e) { toast(e.message, 'bad') }
  testing.value = false
}
onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="card">
    <div class="card-title">{{ $t('settings.network.networkConnection') }}</div>
    <p class="muted">{{ $t('settings.network.theAppGoesOnline') }}</p>
    <div class="choice">
      <label :class="{ on: props.s['proxy.mode'] === 'system' }"><input v-model="props.s['proxy.mode']" type="radio" value="system" /><div><b>{{ $t('settings.network.matchSystem') }}</b>
        <span>{{ $t('settings.network.useThisComputersSystem') }}<template v-if="state">{{ $t('settings.network.currentSystemProxy', { p0: state.system || $t('settings.network.notSetDirectConnection') }) }}</template></span></div></label>
      <label :class="{ on: props.s['proxy.mode'] === 'none' }"><input v-model="props.s['proxy.mode']" type="radio" value="none" /><div><b>{{ $t('settings.network.noProxy') }}</b><span>{{ $t('settings.network.connectDirectlyForEverything') }}</span></div></label>
      <label :class="{ on: props.s['proxy.mode'] === 'custom' }"><input v-model="props.s['proxy.mode']" type="radio" value="custom" /><div><b>{{ $t('settings.network.useASpecificProxy') }}</b><span>{{ $t('settings.network.onlyThisAppUses') }}</span></div></label>
    </div>
    <div v-if="props.s['proxy.mode'] === 'custom'" class="kv" style="margin-top: 16px">
      <label>{{ $t('settings.network.proxyAddress') }}</label>
      <div><input v-model="props.s['proxy.url']" style="width: 100%" :placeholder="$t('settings.network.httpOrSocks')" />
        <div class="hint">{{ $t('settings.network.withoutAProtocolHttp') }}</div></div>
      <label>{{ $t('settings.network.username') }}</label><input v-model="props.s['proxy.username']" :placeholder="$t('settings.network.leaveBlankIfNo')" autocomplete="off" />
      <label>{{ $t('settings.network.password') }}</label><input v-model="props.sec.proxy_password" type="password" :placeholder="hasPassword ? $t('settings.network.savedLeaveBlankTo') : $t('settings.network.leaveBlankIfNo')" autocomplete="new-password" />
    </div>
    <div v-if="props.s['proxy.mode'] !== 'none'" class="kv" style="margin-top: 16px">
      <label>{{ $t('settings.network.theseSitesSkipThe') }}</label>
      <div><input v-model="props.s['proxy.bypass']" style="width: 100%" :placeholder="$t('settings.network.eGPdportalApsc')" />
        <div class="hint">{{ $t('settings.network.onlyAppliesWhenUsing') }}</div></div>
    </div>
  </div>

  <div class="card">
    <div class="row"><span class="card-title grow">{{ $t('settings.network.testConnection') }}</span><button :disabled="testing" @click="test"><Icon name="refresh" />{{ testing ? $t('settings.network.testing') : $t('settings.network.testWithSavedSettings') }}</button></div>
    <p class="muted" style="margin-top: 4px">{{ $t('settings.network.afterChangingTheSettings') }}<template v-if="state">{{ $t('settings.network.currentlyInEffect') }}<b>{{ state.in_effect || $t('settings.network.connectDirectly') }}</b></template></p>
    <table v-if="results">
      <thead><tr><th>{{ $t('settings.network.connectTo') }}</th><th>{{ $t('settings.network.result') }}</th><th>{{ $t('settings.network.timeTaken') }}</th></tr></thead>
      <tbody>
        <tr v-for="r in results" :key="r.name">
          <td>{{ r.name }}</td>
          <td><span class="badge" :class="r.ok ? 'ok' : 'bad'">{{ r.ok ? $t('settings.network.connected') : $t('settings.network.cantConnect') }}</span> <span class="muted small">{{ r.ok ? '' : r.detail }}</span></td>
          <td class="small">{{ $t('settings.network.s', { p0: (r.ms / 1000).toFixed(1) }) }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="results" class="hint" style="margin-top: 10px">{{ $t('settings.network.sitesSlowerThanSeconds') }}</p>
  </div>
</template>

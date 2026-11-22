<script setup>
// How the program connects to the internet. Edits the settings object it is given; the page's own "Save" stores them.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import CardHead from './CardHead.vue'
import HelpPop from './HelpPop.vue'
import Icon from './Icon.vue'
import Status from './Status.vue'
import Trunc from './Trunc.vue'

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
    <CardHead :title="$t('settings.network.networkConnection')" :help="$t('settings.network.theAppGoesOnline')" />
    <div class="choice">
      <label :class="{ on: props.s['proxy.mode'] === 'system' }"><input v-model="props.s['proxy.mode']" type="radio" value="system" /><div><b>{{ $t('settings.network.matchSystem') }}</b>
        <span>{{ $t('settings.network.useThisComputersSystem') }}<template v-if="state">{{ ' ' + $t('settings.network.currentSystemProxy', { p0: state.system || $t('settings.network.notSetDirectConnection') }) }}</template></span></div></label>
      <label :class="{ on: props.s['proxy.mode'] === 'none' }"><input v-model="props.s['proxy.mode']" type="radio" value="none" /><div><b>{{ $t('settings.network.noProxy') }}</b><span>{{ $t('settings.network.connectDirectlyForEverything') }}</span></div></label>
      <label :class="{ on: props.s['proxy.mode'] === 'custom' }"><input v-model="props.s['proxy.mode']" type="radio" value="custom" /><div><b>{{ $t('settings.network.useASpecificProxy') }}</b><span>{{ $t('settings.network.onlyThisAppUses') }}</span></div></label>
    </div>
    <div v-if="props.s['proxy.mode'] !== 'none'" class="kv after-choice">
      <template v-if="props.s['proxy.mode'] === 'custom'">
        <label>{{ $t('settings.network.proxyAddress') }}<HelpPop :text="$t('settings.network.withoutAProtocolHttp')" /></label>
        <input v-model="props.s['proxy.url']" :placeholder="$t('settings.network.httpOrSocks')" />
        <label>{{ $t('settings.network.username') }}</label><input v-model="props.s['proxy.username']" :placeholder="$t('settings.network.leaveBlankIfNo')" autocomplete="off" />
        <label>{{ $t('settings.network.password') }}</label><input v-model="props.sec.proxy_password" type="password" :placeholder="hasPassword ? $t('settings.network.savedLeaveBlankTo') : $t('settings.network.leaveBlankIfNo')" autocomplete="new-password" />
      </template>
      <label>{{ $t('settings.network.theseSitesSkipThe') }}<HelpPop :text="$t('settings.network.onlyAppliesWhenUsing')" /></label>
      <input v-model="props.s['proxy.bypass']" :placeholder="$t('settings.network.eGPdportalApsc')" />
    </div>
  </div>

  <div class="card">
    <CardHead :title="$t('settings.network.testConnection')" :help="$t('settings.network.afterChangingTheSettings')">
      <button :disabled="testing" @click="test"><Icon name="refresh" />{{ testing ? $t('settings.network.testing') : $t('settings.network.testWithSavedSettings') }}</button>
    </CardHead>
    <p v-if="state" class="t-secondary">{{ $t('settings.network.currentlyInEffect') }} <span class="t-primary" data-notr>{{ state.in_effect || $t('settings.network.connectDirectly') }}</span></p>
    <template v-if="results">
      <div class="an-scroll">
        <table class="an-table">
          <colgroup><col /><col class="w-state" /><col class="w-n" /></colgroup>
          <thead><tr><th>{{ $t('settings.network.connectTo') }}</th><th>{{ $t('settings.network.result') }}</th><th class="num">{{ $t('settings.network.timeTaken') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in results" :key="r.name">
              <td><Trunc :text="r.name" /></td>
              <td><Status :tone="r.ok ? 'ok' : 'bad'" :label="r.ok ? $t('settings.network.connected') : $t('settings.network.cantConnect')" :tip="r.ok ? '' : r.detail || ''" /></td>
              <td class="num">{{ $t('settings.network.s', { p0: (r.ms / 1000).toFixed(1) }) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="set-note">{{ $t('settings.network.sitesSlowerThanSeconds') }}</p>
    </template>
  </div>
</template>

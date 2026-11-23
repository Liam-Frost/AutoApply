<script setup>
// Lab: one setting as a row - the name (with an (i), with a line under it) on the left, the control on the right, on
// one baseline whatever the control is (a select, a list of radios, two times, a switch); the same rows in a box of
// 480px, where they stack. The update modes are the program's own words; the rest is made up.
import { computed, ref } from 'vue'
import { t as T } from '../../../i18n/catalog'
import RadioList from '../../../components/RadioList.vue'
import SettingRow from '../../../components/SettingRow.vue'
import ToggleSwitch from '../../../components/ToggleSwitch.vue'

const mode = ref('auto')
const MODES = computed(() => ['off', 'notify', 'download', 'auto'].map((value) => ({ value, label: T('about.mode.' + value), hint: T('about.mode.' + value + 'How') })))
const channel = ref('stable')
const from = ref('03:00')
const to = ref('05:00')
const on = ref(true)
const name = ref('Made-up name')
</script>

<template>
  <p class="lab-note">Wide: the name's column and the control's. Values: <b data-t="sr-values">{{ mode }} · {{ channel }} · {{ from }}–{{ to }} · {{ on ? 'on' : 'off' }} · {{ name }}</b></p>
  <div v-for="w in ['wide', 'narrow']" :key="w" class="lab-box" :data-sr="w" :style="w === 'narrow' ? 'width: 480px; max-width: 100%; margin-top: 12px' : 'max-width: 900px'">
    <p v-if="w === 'narrow'" class="lab-note">A box of 480px: the name above its control</p>
    <div style="display: grid; row-gap: 16px">
      <SettingRow v-slot="{ labelId, descId }" :label="$t('about.byItself')" :description="$t('about.privacyShort')">
        <RadioList v-model="mode" :name="'lab-sr-mode-' + w" :label="$t('about.byItself')" hide-label :aria-labelledby="labelId" :aria-describedby="descId" :options="MODES" />
      </SettingRow>
      <SettingRow :label="$t('about.channel')" :for="'lab-sr-channel-' + w" help="A made-up sentence of help behind the (i).">
        <AaSelect :id="'lab-sr-channel-' + w" v-model="channel"><option value="stable">{{ $t('about.stable') }}</option><option value="beta">{{ $t('about.beta') }}</option></AaSelect>
      </SettingRow>
      <SettingRow v-slot="{ labelId }" :label="$t('about.window')" :description="$t('about.windowHint')">
        <div role="group" :aria-labelledby="labelId" style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
          <input v-model="from" type="time" :aria-label="$t('about.windowFrom')" /><span aria-hidden="true">–</span><input v-model="to" type="time" :aria-label="$t('about.windowTo')" />
        </div>
      </SettingRow>
      <SettingRow :label="'A switch'" description="A made-up line under the name.">
        <ToggleSwitch v-model="on" aria-label="Lab: a switch named by the row" />
      </SettingRow>
      <SettingRow :label="'A field'" :for="'lab-sr-text-' + w">
        <input :id="'lab-sr-text-' + w" v-model="name" class="w-mid" />
      </SettingRow>
    </div>
  </div>
</template>

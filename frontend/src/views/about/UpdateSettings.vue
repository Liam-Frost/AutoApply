<script setup>
// The update settings of the about page's "Software update", one SettingRow each: whether the program looks for,
// fetches and switches to a new version by itself (update.mode), the channel (update.channel) and, for the automatic
// switch only, the hours it may happen in (update.window). The privacy line stays beside the choice it is about.
// It saves nothing itself: each change is said (`save`, key and value) and the page saves it at once.
import { computed, ref, watch } from 'vue'
import { t as T } from '../../i18n/catalog'
import RadioList from '../../components/RadioList.vue'
import SettingRow from '../../components/SettingRow.vue'

const props = defineProps({ policy: { type: Object, required: true } })      // updateState(...).policy
const emit = defineEmits(['save'])

const mode = ref(props.policy.mode)
const channel = ref(props.policy.channel)
const win = ref({ ...props.policy.window })
watch(() => props.policy, (p) => { mode.value = p.mode; channel.value = p.channel; win.value = { ...p.window } })

const options = computed(() => {
  const words = { off: [T('about.mode.off'), T('about.mode.offHow')], notify: [T('about.mode.notify'), T('about.mode.notifyHow')],
    download: [T('about.mode.download'), T('about.mode.downloadHow')], auto: [T('about.mode.auto'), T('about.mode.autoHow')] }
  return props.policy.modes.map((o) => ({ value: o.value, label: words[o.value][0], hint: words[o.value][1], disabled: o.disabled }))
})
const limited = computed(() => props.policy.modes.some((o) => o.disabled))

function saveWindow() {
  if (!win.value.from || !win.value.to) return      // (a time field being cleared: saved when it holds a time again)
  emit('save', 'update.window', { from: win.value.from, to: win.value.to })
}
</script>

<template>
  <div class="up-settings">
    <SettingRow v-slot="{ labelId, descId }" :label="$t('about.byItself')" :description="$t('about.privacyShort')">
      <RadioList v-model="mode" name="update-mode" :label="$t('about.byItself')" hide-label :aria-labelledby="labelId" :aria-describedby="descId" :options="options"
        @change="emit('save', 'update.mode', $event)" />
      <p v-if="limited" class="hint up-limited">{{ $t('about.modesNotHere') }}</p>
    </SettingRow>
    <SettingRow :label="$t('about.channel')" for="u-channel">
      <AaSelect id="u-channel" :model-value="channel" @update:model-value="channel = $event; emit('save', 'update.channel', $event)">
        <option value="stable">{{ $t('about.stable') }}</option><option value="beta">{{ $t('about.beta') }}</option>
      </AaSelect>
    </SettingRow>
    <SettingRow v-if="mode === 'auto'" v-slot="{ labelId, descId }" :label="$t('about.window')" :description="$t('about.windowHint')">
      <div class="up-window" role="group" :aria-labelledby="labelId">
        <input v-model="win.from" type="time" :aria-label="$t('about.windowFrom')" :aria-describedby="descId" @change="saveWindow" />
        <span aria-hidden="true">–</span>
        <input v-model="win.to" type="time" :aria-label="$t('about.windowTo')" :aria-describedby="descId" @change="saveWindow" />
      </div>
    </SettingRow>
  </div>
</template>

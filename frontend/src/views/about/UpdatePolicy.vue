<script setup>
// The about page's update policy: whether the program looks for, fetches and switches to a new version by itself
// (update.mode), the channel (update.channel) and, for the automatic switch only, the hours it may happen in
// (update.window). Each change is saved at once (PUT /settings) and said; what is sent where and how a switch works
// are one line here and the whole of it under "How updates work".
import { computed, ref, watch } from 'vue'
import { t as T } from '../../i18n/catalog'
import { api } from '../../api'
import { run } from '../../ui'
import CardHead from '../../components/CardHead.vue'
import RadioList from '../../components/RadioList.vue'

const props = defineProps({ policy: { type: Object, required: true } })      // updateState(...).policy
const emit = defineEmits(['saved'])

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

const save = (key, value) => run(() => api.put('/settings', { settings: { [key]: value } }), T('about.saved'), () => emit('saved'))
function saveWindow() {
  if (!win.value.from || !win.value.to) return      // (a time field being cleared: saved when it holds a time again)
  save('update.window', { from: win.value.from, to: win.value.to })
}
</script>

<template>
  <section class="card up-policy">
    <CardHead :title="$t('about.policy')" />
    <RadioList v-model="mode" name="update-mode" :label="$t('about.byItself')" :options="options" @change="save('update.mode', $event)" />
    <p v-if="limited" class="hint up-limited">{{ $t('about.modesNotHere') }}</p>
    <div class="fields up-fields">
      <div class="f">
        <span id="u-channel-l">{{ $t('about.channel') }}</span>
        <AaSelect id="u-channel" aria-labelledby="u-channel-l" :model-value="channel" @update:model-value="channel = $event; save('update.channel', $event)">
          <option value="stable">{{ $t('about.stable') }}</option><option value="beta">{{ $t('about.beta') }}</option>
        </AaSelect>
      </div>
      <div v-if="mode === 'auto'" class="f span2 up-window">
        <span>{{ $t('about.window') }}</span>
        <div class="actions">
          <input v-model="win.from" type="time" :aria-label="$t('about.windowFrom')" @change="saveWindow" />
          <span aria-hidden="true">–</span>
          <input v-model="win.to" type="time" :aria-label="$t('about.windowTo')" @change="saveWindow" />
          <span class="t-meta">{{ $t('about.windowHint') }}</span>
        </div>
      </div>
    </div>
    <p class="hint up-privacy">{{ $t('about.privacyShort') }}</p>
    <details class="up-more">
      <summary>{{ $t('about.howItWorks') }}</summary>
      <p>{{ $t('about.privacy') }}</p>
      <p>{{ $t('about.howSwitch') }}</p>
      <p>{{ $t('about.idleHow') }}</p>
    </details>
  </section>
</template>

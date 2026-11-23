<script setup>
// The update settings of the about page's "Software update". Read: one row each in SettingRow's two columns - the update
// policy (update.mode) with "Change" at its end, the channel (update.channel) and, for the automatic switch only, its
// hours (update.window). "Change" puts a compact editor in their place: the modes as a RadioList - those this copy
// cannot use disabled, with the reason -, what an automatic download or switch does to this computer, said as soon as
// such a mode is chosen, the channel, and the switch window for "Update automatically" only. Nothing is saved before
// Save, which sends what changed (`save`, the page's PUT /api/settings) and closes the editor when it was saved; Cancel
// or Escape close it unchanged. The focus goes into it, and back to "Change" after.
import { computed, nextTick, ref } from 'vue'
import { t as T } from '../../i18n/catalog'
import Icon from '../../components/Icon.vue'
import RadioList from '../../components/RadioList.vue'
import SettingRow from '../../components/SettingRow.vue'

const props = defineProps({
  policy: { type: Object, required: true },      // updateState(...).policy
  kind: { type: String, default: '' },           // how this copy runs: an automatic switch needs the tray app ("managed")
  save: { type: Function, required: true },      // (changes) => truthy once saved; changes: { 'update.mode'?, 'update.channel'?, 'update.window'? }
})

const MODE = computed(() => ({
  off: [T('about.mode.off'), T('about.mode.offHow')], notify: [T('about.mode.notify'), T('about.mode.notifyHow')],
  download: [T('about.mode.download'), T('about.mode.downloadHow')], auto: [T('about.mode.auto'), T('about.mode.autoHow')],
}))
const REASON = computed(() => ({ install: T('about.mode.needsInstall') }))
const options = computed(() => props.policy.modes.map((o) => ({ value: o.value, label: MODE.value[o.value][0], hint: MODE.value[o.value][1], disabled: o.disabled,
  reason: o.reason ? REASON.value[o.reason] : '' })))
const CHANNEL = computed(() => ({ stable: T('about.stable'), beta: T('about.beta') }))
const modeName = computed(() => (MODE.value[props.policy.mode] || [props.policy.mode])[0])
const windowText = computed(() => T('time.range', { from: props.policy.window.from, to: props.policy.window.to }))

const editing = ref(false)
const draft = ref(null)
const changeBtn = ref(null)
const form = ref(null)
function edit() {
  const p = props.policy
  draft.value = { mode: p.mode, channel: p.channel, from: p.window.from, to: p.window.to }
  editing.value = true
  nextTick(() => {
    const f = form.value
    const first = f && (f.querySelector('input[type=radio]:checked:not(:disabled)') || f.querySelector('input:not(:disabled)'))
    if (first) first.focus()
  })
}
function close() {
  editing.value = false
  nextTick(() => { if (changeBtn.value) changeBtn.value.focus() })
}
function onEsc(e) {
  if (e.defaultPrevented) return      // (a select in it closed its own list on this key)
  e.preventDefault()
  close()
}

// what the chosen mode does to this computer by itself, while it is one this copy can use ("Update automatically"
// downloads too; its switch needs the tray app - updates.tick)
const risk = computed(() => {
  const d = draft.value
  const opt = d && props.policy.modes.find((o) => o.value === d.mode)
  if (!opt || opt.disabled || (d.mode !== 'download' && d.mode !== 'auto')) return []
  const said = [T('about.risk.download')]
  if (d.mode === 'auto') said.push(T('about.risk.auto'))
  if (d.mode === 'auto' && props.kind !== 'managed') said.push(T('about.error.notManaged'))
  return said
})
// only what changed is sent; the window only with the automatic switch, and only whole
const changes = computed(() => {
  const d = draft.value, p = props.policy, out = {}
  if (!d) return out
  if (d.mode !== p.mode) out['update.mode'] = d.mode
  if (d.channel !== p.channel) out['update.channel'] = d.channel
  if (d.mode === 'auto' && (d.from !== p.window.from || d.to !== p.window.to)) out['update.window'] = { from: d.from, to: d.to }
  return out
})
const incomplete = computed(() => !!draft.value && draft.value.mode === 'auto' && (!draft.value.from || !draft.value.to))
const saving = ref(false)
async function submit() {
  if (incomplete.value || saving.value) return
  if (!Object.keys(changes.value).length) return close()
  saving.value = true
  try { if (await props.save(changes.value)) close() } finally { saving.value = false }
}
</script>

<template>
  <div class="up-policy">
    <dl v-if="!editing" class="up-sum">
      <div data-sum="mode">
        <dt>{{ $t('about.policy') }}</dt>
        <dd><span>{{ modeName }}</span><button ref="changeBtn" type="button" class="sm up-change" :aria-label="$t('about.changePolicy')" @click="edit">{{ $t('about.change') }}</button></dd>
      </div>
      <div data-sum="channel"><dt>{{ $t('about.channel') }}</dt><dd>{{ CHANNEL[policy.channel] || policy.channel }}</dd></div>
      <div v-if="policy.windowApplies" data-sum="window"><dt>{{ $t('about.window') }}</dt><dd class="num">{{ windowText }}</dd></div>
    </dl>

    <form v-else ref="form" class="up-edit" :aria-label="$t('about.policy')" @submit.prevent="submit" @keydown.esc="onEsc">
      <SettingRow v-slot="{ labelId, descId }" :label="$t('about.policy')" :description="$t('about.privacyShort')">
        <RadioList v-model="draft.mode" name="update-mode" :label="$t('about.policy')" hide-label :aria-labelledby="labelId" :aria-describedby="descId" :options="options" />
        <div v-if="risk.length" class="callout warn up-risk" data-risk><Icon name="alert" /><div><p v-for="r in risk" :key="r">{{ r }}</p></div></div>
      </SettingRow>
      <SettingRow :label="$t('about.channel')" for="u-channel">
        <AaSelect id="u-channel" v-model="draft.channel">
          <option value="stable">{{ $t('about.stable') }}</option><option value="beta">{{ $t('about.beta') }}</option>
        </AaSelect>
      </SettingRow>
      <SettingRow v-if="draft.mode === 'auto'" v-slot="{ labelId, descId }" :label="$t('about.window')" :description="$t('about.windowHint')">
        <div class="up-window" role="group" :aria-labelledby="labelId">
          <input v-model="draft.from" type="time" required :aria-label="$t('about.windowFrom')" :aria-describedby="descId" />
          <span aria-hidden="true">–</span>
          <input v-model="draft.to" type="time" required :aria-label="$t('about.windowTo')" :aria-describedby="descId" />
        </div>
      </SettingRow>
      <div class="actions form-acts up-edit-acts">
        <button type="button" @click="close">{{ $t('common.cancel') }}</button>
        <button type="submit" class="primary" :disabled="saving || incomplete">{{ $t('common.save') }}</button>
      </div>
    </form>
  </div>
</template>

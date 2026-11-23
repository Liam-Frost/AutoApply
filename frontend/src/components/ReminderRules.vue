<script>
let counter = 0      // ids for the fields of the "+": unique on the page, nothing more
</script>

<script setup>
// The reminders a kind of calendar item gets by itself (docs/component-guidelines.md, ReminderRules): chips that say
// them in words, a × on each, and a "+" with the usual choices and an amount of one's own. The value stays what the
// backend keeps - minutes before the item, [1440, 30] - and every change gives the list as reminders.js keeps it
// (whole minutes, each once, the largest first). The words of a reminder are reminders.js's (formatReminder).
import { computed, nextTick, ref } from 'vue'
import { t as T } from '../i18n/catalog'
import { UNITS, formatReminder, has, normalize, parseAmount, presetsFor, toggled, withAdded, without, MOST, DAY } from '../reminders'
import Icon from './Icon.vue'
import IconButton from './IconButton.vue'
import Popover from './Popover.vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  label: { type: String, default: '' },        // what the reminders are of ("Interview"): the group's name and the "+"'s
  allDay: Boolean,                             // the item lasts a whole day: reminded in the morning, whole days apart
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'change'])
const uid = 'rr' + ++counter
const root = ref(null)

const list = computed(() => {
  const v = normalize(props.modelValue)
  // (for a whole day, "2 hours before" and "1 day before" are the same morning: one chip, as the backend gives one reminder)
  return props.allDay ? v.filter((m, i) => v.findIndex((x) => Math.ceil(x / DAY) === Math.ceil(m / DAY)) === i) : v
})
const say = (m) => formatReminder(m, { allDay: props.allDay })
const addLabel = computed(() => (props.label ? T('controls.reminders.addTo', { kind: props.label }) : T('controls.reminders.add')))
function set(v) { emit('update:modelValue', v); emit('change', v) }

// A × takes its reminder away; the keyboard stays where it was - on the next ×, or on the "+".
function drop(m, i) {
  set(without(props.modelValue, m))
  nextTick(() => {
    const all = root.value ? root.value.querySelectorAll('.icon-btn') : []
    const to = all[Math.min(i, all.length - 1)]
    if (to) to.focus()
  })
}

const presets = computed(() => presetsFor(props.allDay))
const on = (m) => (props.allDay ? list.value.some((x) => Math.ceil(x / DAY) === Math.ceil(m / DAY)) : has(props.modelValue, m))
// a choice already made is shown pressed; pressing it again takes it away (it is not disabled: the focus stays on it)
function flip(m) {
  if (props.allDay && on(m)) { set(normalize(props.modelValue).filter((x) => Math.ceil(x / DAY) !== Math.ceil(m / DAY))); return }
  set(toggled(props.modelValue, m))
}

const amount = ref('')
const unit = ref('minutes')
const UNIT_WORDS = { minutes: 'controls.reminders.unit_minutes', hours: 'controls.reminders.unit_hours', days: 'controls.reminders.unit_days' }
const units = computed(() => (props.allDay ? ['days'] : Object.keys(UNITS)))
const typed = computed(() => parseAmount(amount.value, props.allDay ? 'days' : unit.value, props.allDay ? list.value.map((m) => Math.ceil(m / DAY) * DAY) : props.modelValue))
const error = computed(() => (typed.value.error ? T('controls.reminders.' + typed.value.error, { days: MOST / DAY }) : ''))
function addTyped() {
  if (typed.value.minutes == null || typed.value.error) return
  set(withAdded(props.modelValue, typed.value.minutes))
  amount.value = ''
}
function reset() { amount.value = '' }
</script>

<template>
  <div ref="root" class="rr" role="group" :aria-label="label || undefined">
    <span v-for="(m, i) in list" :key="m" class="fchip lg rr-chip"><span class="rr-text">{{ say(m) }}</span>
      <IconButton icon="x" size="sm" :label="$t('controls.reminders.remove', { when: say(m) })" :disabled="disabled" @click="drop(m, i)" /></span>
    <span v-if="!list.length" class="rr-none">{{ $t('controls.reminders.none') }}</span>
    <Popover :label="addLabel" :width="320" @close="reset">
      <template #trigger="{ toggle, attrs }"><IconButton v-bind="attrs" icon="plus" :label="addLabel" :disabled="disabled" @click="toggle" /></template>
      <div class="rr-pop">
        <p class="pop-title">{{ addLabel }}</p>
        <div class="rr-presets" role="group" :aria-label="$t('controls.reminders.presets')">
          <button v-for="m in presets" :key="m" type="button" class="sm chip rr-preset" :class="{ on: on(m) }" :aria-pressed="on(m) ? 'true' : 'false'" @click="flip(m)">
            <Icon v-if="on(m)" name="check" />{{ say(m) }}</button>
        </div>
        <div class="rr-own">
          <label class="rr-own-label" :for="uid + '-n'">{{ $t('controls.reminders.custom') }}</label>
          <div class="rr-own-row">
            <input :id="uid + '-n'" v-model="amount" class="sm w-num" type="text" inputmode="numeric" autocomplete="off" :aria-invalid="error ? 'true' : undefined"
              :aria-describedby="error ? uid + '-e' : undefined" @keydown.enter.prevent="addTyped" />
            <AaSelect v-if="units.length > 1" v-model="unit" small :aria-label="$t('controls.reminders.unit')">
              <option v-for="u in units" :key="u" :value="u">{{ $t(UNIT_WORDS[u]) }}</option>
            </AaSelect>
            <span v-else class="rr-unit">{{ $t('controls.reminders.unit_days') }}</span>
            <button type="button" class="sm" :disabled="typed.minutes == null || !!typed.error" @click="addTyped">{{ $t('controls.reminders.addOne') }}</button>
          </div>
          <p v-if="error" :id="uid + '-e'" class="rr-error" role="alert">{{ error }}</p>
        </div>
      </div>
    </Popover>
  </div>
</template>

<script>
let counter = 0      // ids for the switch / label pairing: unique on the page, nothing more
</script>

<script setup>
// A setting that is on or off as a whole (quiet hours, a kind of reminder waiting for them): a switch, said to a screen
// reader as one (role="switch", aria-checked). Space and Enter flip it, as they press any button; the words beside it,
// when given, are its name and flip it too. (docs/component-guidelines.md, ToggleSwitch)
//
//   <ToggleSwitch v-model="on" :label="$t('…')" />        without a label: give it an aria-label
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: Boolean, label: { type: String, default: '' }, disabled: Boolean })
const emit = defineEmits(['update:modelValue', 'change'])
const uid = 'tsw' + ++counter
function flip() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
  emit('change', !props.modelValue)
}
</script>

<template>
  <span class="tsw" :class="{ on: modelValue, disabled }">
    <button v-bind="$attrs" type="button" role="switch" class="tsw-btn" :aria-checked="modelValue ? 'true' : 'false'"
      :aria-labelledby="label && !$attrs['aria-label'] ? uid : $attrs['aria-labelledby']" :disabled="disabled" @click="flip"><span class="tsw-knob" aria-hidden="true"></span></button>
    <span v-if="label" :id="uid" class="tsw-label" @click="flip">{{ label }}</span>
  </span>
</template>

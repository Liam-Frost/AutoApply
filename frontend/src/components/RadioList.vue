<script>
let counter = 0      // a name for the radios when the page gives none: unique on the page, nothing more
</script>

<script setup>
// A choice of one among a few, as a compact list of native radios (docs/component-guidelines.md, "RadioList"): a
// fieldset named by its legend, one row per option - the option's words, and its hint muted beside them while there is
// room, under them otherwise. Not cards: a row is --row-compact high and has no box of its own. The arrow keys move
// and choose as in any group of native radios (they share a name: the browser does it). An option that cannot be
// chosen says why (`reason`) where its hint would be, and is described by it.
//
//   <RadioList v-model="mode" name="update-mode" :label="$t('…')" :options="[{ value, label, hint?, disabled?, reason? }]" />
const props = defineProps({
  modelValue: { type: [String, Number, Boolean], default: null },
  options: { type: Array, required: true },        // { value, label, hint?, disabled?, reason? }
  label: { type: String, required: true },         // what is chosen: the legend, and the group's accessible name
  name: { type: String, default: '' },             // the radios' name; made up when not given
  disabled: { type: Boolean, default: false },     // the whole list
  hideLabel: { type: Boolean, default: false },    // the legend for a screen reader only (a title right above already says it)
})
const emit = defineEmits(['update:modelValue', 'change'])

const group = props.name || 'radios' + ++counter
const idOf = (i, part) => `${group}-${i}-${part}`
// what is said under an option's words: why it cannot be chosen, when it cannot and that is said; else its hint
const noteOf = (o) => (o.disabled && o.reason ? o.reason : o.hint)
function pick(o) {
  if (o.value === props.modelValue) return
  emit('update:modelValue', o.value)
  emit('change', o.value)
}
</script>

<template>
  <fieldset class="radio-list" :disabled="disabled">
    <legend :class="hideLabel ? 'rl-legend-hidden' : 'rl-legend'">{{ label }}</legend>
    <label v-for="(o, i) in options" :key="String(o.value)" class="rl-row" :class="{ on: o.value === modelValue, off: o.disabled || disabled }">
      <input type="radio" :name="group" :value="String(o.value)" :checked="o.value === modelValue" :disabled="o.disabled"
        :aria-labelledby="idOf(i, 'l')" :aria-describedby="noteOf(o) ? idOf(i, 'h') : undefined" @change="pick(o)" />
      <span class="rl-text"><span :id="idOf(i, 'l')" class="rl-label">{{ o.label }}</span><span v-if="noteOf(o)" :id="idOf(i, 'h')" class="rl-hint" :class="{ 'rl-reason': o.disabled && o.reason }">{{ noteOf(o) }}</span></span>
    </label>
  </fieldset>
</template>

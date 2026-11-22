<script setup>
// One figure of the analysis page: the number, what it is and - behind an (i) beside its name - how it is counted.
// The lines under it (the change, "n of m") come in the slot; slot `help` is for help with a link in it. The tile never
// grows to explain itself.
import HelpPop from '../../components/HelpPop.vue'

defineProps({
  value: { type: [String, Number], required: true },
  label: { type: String, required: true },
  help: { type: String, default: '' },
  tone: { type: String, default: '' },      // '' | ok | na (a figure that cannot be told)
})
</script>

<template>
  <div class="kpi">
    <div class="n" :class="tone">{{ value }}</div>
    <div class="l"><span>{{ label }}</span><HelpPop v-if="$slots.help" :label="label"><slot name="help" /></HelpPop><HelpPop v-else-if="help" :text="help" :label="label" /></div>
    <slot />
  </div>
</template>

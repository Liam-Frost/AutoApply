<script setup>
// The head of a card: its title, what the card shows behind an (i), a short note (a count, a state) and the card's own
// controls at the right. The title is cut when it does not fit and is never squeezed: when the controls leave it too
// little room they go under it as a group (.card-head in styles/analysis-settings.css) - by rule, not by where the
// words happen to break.
import HelpPop from './HelpPop.vue'
import Trunc from './Trunc.vue'

defineProps({
  title: { type: String, required: true },
  help: { type: String, default: '' },           // a sentence is a tooltip, more opens in a popover (HelpPop)
  note: { type: [String, Number], default: '' },      // a plain figure or fact after the title
})
</script>

<template>
  <div class="card-head">
    <div class="card-head-main">
      <Trunc class="card-title" :text="title" />
      <HelpPop v-if="$slots.help" :label="title"><slot name="help" /></HelpPop>
      <HelpPop v-else-if="help" :text="help" :label="title" />
      <slot name="after"><span v-if="note !== ''" class="meta small">{{ note }}</span></slot>
    </div>
    <div v-if="$slots.default" class="card-tools"><slot /></div>
  </div>
</template>

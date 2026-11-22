<script setup>
// The head of a section of a page: its title, how many there are of what it lists, and the section's own actions at
// the right. `help` is a sentence behind an (i).
import InfoTip from './InfoTip.vue'

defineProps({ title: { type: String, required: true }, help: { type: String, default: '' }, count: { type: [Number, String], default: null } })
</script>

<template>
  <div class="section-head">
    <h3>{{ title }}</h3>
    <span v-if="count !== null && count !== ''" class="count">{{ count }}</span>
    <InfoTip v-if="help" :text="help" />
    <div v-if="$slots.default" class="actions"><slot /></div>
  </div>
</template>

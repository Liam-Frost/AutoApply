<script setup>
// STUB (lead): to be written by the foundations work - see docs/component-guidelines.md for the contract.
defineProps({ title: { type: String, required: true }, help: { type: String, default: '' }, count: { type: [Number, String], default: null } })
</script>

<template>
  <div class="section-head"><h3>{{ title }}</h3><slot /></div>
</template>

<script setup>
// STUB (lead): to be written by the foundations work - see docs/component-guidelines.md for the contract.
defineProps({ tone: { type: String, default: '' }, label: { type: String, required: true }, tip: { type: String, default: '' } })
</script>

<template>
  <span class="status" :class="tone">{{ label }}</span>
</template>

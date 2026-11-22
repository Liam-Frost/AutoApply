<script setup>
// STUB (lead): to be written by the foundations work - see docs/component-guidelines.md for the contract.
defineProps({ count: { type: Number, required: true } })
defineEmits(['clear'])
</script>

<template>
  <div v-if="count" class="bulkbar"><slot /></div>
</template>

<script setup>
// STUB (lead): to be written by the overlay work - see docs/component-guidelines.md for the contract.
defineProps({ items: { type: Array, required: true }, label: { type: String, required: true }, icon: { type: String, default: 'more' }, align: { type: String, default: 'end' } })
defineEmits(['pick'])
</script>

<template>
  <span class="menu"></span>
</template>

<script setup>
// STUB (lead): to be written by the overlay work - see docs/component-guidelines.md for the contract.
defineProps({ label: { type: String, default: '' }, placement: { type: String, default: 'bottom' }, width: { type: Number, default: 320 } })
</script>

<template>
  <span class="popover"><slot name="trigger" :open="false" :toggle="() => {}" /></span>
</template>

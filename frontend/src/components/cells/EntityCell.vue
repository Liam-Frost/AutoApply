<script setup>
// STUB (lead): to be written by the table work - see docs/component-guidelines.md for the contract.
defineProps({ primary: { type: String, default: '' }, secondary: { type: String, default: '' }, to: { type: [String, Object], default: null } })
</script>

<template>
  <div class="entity">{{ primary }}</div>
</template>

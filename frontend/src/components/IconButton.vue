<script setup>
// STUB (lead): to be written by the foundations work - see docs/component-guidelines.md for the contract.
import Icon from './Icon.vue'
defineProps({ icon: { type: String, required: true }, label: { type: String, required: true }, size: { type: String, default: 'md' }, tone: { type: String, default: '' }, pressed: { type: Boolean, default: undefined }, loading: Boolean, disabled: Boolean })
</script>

<template>
  <button type="button" class="icon-btn ghost sm" :aria-label="label" :disabled="disabled"><Icon :name="icon" /></button>
</template>

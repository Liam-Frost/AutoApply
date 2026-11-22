<script setup>
// STUB (lead): to be written by the foundations work - see docs/component-guidelines.md for the contract.
defineProps({ text: { type: String, default: '' }, lines: { type: Number, default: 1 }, as: { type: String, default: 'span' } })
</script>

<template>
  <component :is="as" class="cut"><slot>{{ text }}</slot></component>
</template>

<script setup>
// STUB (lead): to be written by the table work - see docs/component-guidelines.md for the contract.
defineProps({ columns: { type: Array, required: true }, rows: { type: Array, required: true }, rowKey: { type: String, default: 'id' }, density: { type: String, default: 'standard' }, selectable: Boolean, selected: { type: Object, default: () => new Set() }, sort: { type: Object, default: null }, clickable: Boolean, label: { type: String, default: '' }, expandedKey: { default: null } })
defineEmits(['update:selected', 'update:sort', 'row'])
</script>

<template>
  <div class="dt"><slot name="empty" /></div>
</template>

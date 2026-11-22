<script setup>
import Icon from './Icon.vue'
defineProps({ icon: { type: String, default: 'inbox' }, title: { type: String, required: true }, text: { type: String, default: '' } })
</script>

<template>
  <div class="empty">
    <Icon :name="icon" />
    <div class="t">{{ title }}</div>
    <div v-if="text">{{ text }}</div>
    <div v-if="$slots.default" class="row empty-acts"><slot /></div>
  </div>
</template>

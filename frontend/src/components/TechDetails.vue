<script setup>
import { t as T } from '../i18n/catalog'
// Raw engine output (exception text, step logs). Always collapsed; never the first thing a user reads.
defineProps({ text: { type: String, default: '' }, label: { type: String, default: () => T('common.techDetails') } })
</script>

<template>
  <details v-if="text" class="tech">
    <summary>{{ label }}</summary>
    <pre>{{ text }}</pre>
  </details>
</template>

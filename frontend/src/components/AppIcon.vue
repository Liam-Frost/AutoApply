<script setup>
const props = defineProps({
  name: {
    type: String,
    required: true,
  },
})

const icons = {
  plus: '<path d="M12 5v14" /><path d="M5 12h14" />',
  trash:
    '<path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="M7 7l1 12h8l1-12" /><path d="M10 11v5" /><path d="M14 11v5" />',
  "chevron-right": '<path d="m9 6 6 6-6 6" />',
  "chevron-down": '<path d="m6 9 6 6 6-6" />',
}
</script>

<template>
  <svg
    class="app-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.9"
    stroke-linecap="round"
    stroke-linejoin="round"
    v-html="icons[props.name]"
  />
</template>

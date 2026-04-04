<script setup>
const props = defineProps({
  name: {
    type: String,
    required: true,
  },
})

const icons = {
  dashboard:
    '<path d="M4 4h7v7H4z" /><path d="M13 4h7v4h-7z" /><path d="M13 10h7v10h-7z" /><path d="M4 13h7v7H4z" />',
  jobs:
    '<path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M4 8h16v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /><path d="M9 12h6" />',
  applications:
    '<path d="M9 3h6l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M9 3v5h5" /><path d="M8 13h8" /><path d="M8 17h5" />',
  profile:
    '<path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Z" /><path d="M5 20a7 7 0 0 1 14 0" />',
  settings:
    '<path d="M12 3v3" /><path d="M12 18v3" /><path d="M3 12h3" /><path d="M18 12h3" /><path d="m5.64 5.64 2.12 2.12" /><path d="m16.24 16.24 2.12 2.12" /><path d="m5.64 18.36 2.12-2.12" /><path d="m16.24 7.76 2.12-2.12" /><circle cx="12" cy="12" r="3.5" />',
}
</script>

<template>
  <svg
    class="dock-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    v-html="icons[props.name]"
  />
</template>

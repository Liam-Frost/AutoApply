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
    '<circle cx="12" cy="12" r="3.2" /><path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 0 1-4 0v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 0 1 0-4h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 0 1 4 0v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a2 2 0 0 1 0 4h-.2a1 1 0 0 0-.9.6Z" />',
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

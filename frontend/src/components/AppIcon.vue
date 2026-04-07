<script setup>
const props = defineProps({
  name: {
    type: String,
    required: true,
  },
})

const icons = {
  plus: '<path d="M12 5v14" /><path d="M5 12h14" />',
  close: '<path d="M6 6l12 12" /><path d="M18 6 6 18" />',
  trash:
    '<path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="M7 7l1 12h8l1-12" /><path d="M10 11v5" /><path d="M14 11v5" />',
  "chevron-left": '<path d="m15 6-6 6 6 6" />',
  "chevron-right": '<path d="m9 6 6 6-6 6" />',
  "chevrons-left": '<path d="m13 6-6 6 6 6" /><path d="m19 6-6 6 6 6" />',
  "chevrons-right": '<path d="m5 6 6 6-6 6" /><path d="m11 6 6 6-6 6" />',
  "chevron-down": '<path d="m6 9 6 6 6-6" />',
  edit:
    '<path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />',
  rename:
    '<path d="M4 20h7" /><path d="M14.5 4.5a2.1 2.1 0 0 1 3 3L8 17l-4 1 1-4Z" /><path d="M12 7h8" />',
  check: '<path d="M5 12l4 4L19 6" />',
  back: '<path d="M19 12H5" /><path d="m12 19-7-7 7-7" />',
  filter:
    '<path d="M4 6h16" /><path d="M7 12h10" /><path d="M10 18h4" />',
  search: '<circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />',
  refresh:
    '<path d="M3 12a9 9 0 0 1 15.4-6.4L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15.4 6.4L3 16" /><path d="M3 21v-5h5" />',
  external: '<path d="M14 5h5v5" /><path d="M10 14 19 5" /><path d="M19 14v5H5V5h5" />',
  save:
    '<path d="M5 4h11l3 3v13H5z" /><path d="M9 4v5h6V4" /><path d="M9 20v-6h6v6" />',
  upload: '<path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M4 20h16" />',
  sun:
    '<circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" />',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" />',
  system:
    '<rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8" /><path d="M12 16v4" />',
  apply: '<path d="M5 12h11" /><path d="m12 5 7 7-7 7" />',
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

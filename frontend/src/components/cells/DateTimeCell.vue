<script setup>
// A date or a time in a row: the value (already formatted by the page) and, under it, what it is or how far away.
// It never wraps. `tone` colours the second line (warn, bad) or lets the whole cell step back (muted); `tip` says
// the whole thing - the full date, the time zone - in a tooltip.
defineProps({
  primary: { type: String, default: '' },
  secondary: { type: String, default: '' },
  tone: { type: String, default: '' },      // '' | warn | bad | muted
  tip: { type: String, default: '' },
})
</script>

<template>
  <div v-tip="tip" class="dtc" :class="tone">
    <span v-if="primary" class="dtc-1 num">{{ primary }}</span>
    <span v-else class="dtc-1 none">—</span>
    <span v-if="secondary" class="dtc-2">{{ secondary }}</span>
  </div>
</template>

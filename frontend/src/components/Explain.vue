<script setup>
// What a figure counts, behind a button: said to whoever asks, by mouse, keyboard or touch. (It was a `title` - there
// for a mouse that rests on the tile, and for nobody else.)
defineProps({ label: { type: String, default: '怎么算的' } })
</script>

<template>
  <details class="explain">
    <summary>{{ label }}</summary>
    <div class="explain-body"><slot /></div>
  </details>
</template>

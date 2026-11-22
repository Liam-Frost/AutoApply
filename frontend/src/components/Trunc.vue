<script setup>
// Text that may be longer than its place: one line cut with an ellipsis (or two lines, `lines="2"`), and the whole of
// it in a tooltip - only when it is actually cut (v-tip.overflow looks at the element, and again when its box changes).
// The words are never shortened, only shown shorter. With a slot, `text` is what the tooltip says.
defineProps({ text: { type: String, default: '' }, lines: { type: Number, default: 1 }, as: { type: String, default: 'span' } })
</script>

<template>
  <component :is="as" v-tip.overflow="text || undefined" :class="lines >= 2 ? 'cut2' : 'cut'"><slot>{{ text }}</slot></component>
</template>

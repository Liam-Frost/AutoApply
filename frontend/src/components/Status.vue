<script setup>
// An ordinary state in a dense place: a dot of the tone and the words - "Session saved", "Auto sign-in ready". The
// second of three weights (docs/component-guidelines.md): a filled .tag is for the few states that must be seen, .meta
// for a plain attribute. The colour is never alone: the words say it. `tip` is a short reason behind a small (i).
import Icon from './Icon.vue'

defineProps({ tone: { type: String, default: '' }, label: { type: String, required: true }, tip: { type: String, default: '' } })
const TONES = ['ok', 'warn', 'bad', 'info']
</script>

<template>
  <span class="status" :class="TONES.includes(tone) ? tone : ''">
    <span v-tip.overflow class="status-label">{{ label }}</span>
    <span v-if="tip" v-tip.press="tip" class="status-tip" tabindex="0" role="img" :aria-label="tip"><Icon name="info" /></span>
  </span>
</template>

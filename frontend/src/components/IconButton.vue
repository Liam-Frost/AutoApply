<script setup>
// A button that is an icon alone. Its name (`label`) is said twice on purpose: to a screen reader (aria-label) and to
// the eye (the tooltip) - an icon without words is a guess. Always square; `loading` puts the spinner where the glyph
// was, so the button keeps its size and its place.
import Icon from './Icon.vue'

const props = defineProps({
  icon: { type: String, required: true },      // a name in Icon.vue
  label: { type: String, required: true },
  size: { type: String, default: 'md' },       // md 28px | sm 24px
  tone: { type: String, default: '' },         // '' | danger
  pressed: { type: Boolean, default: undefined },      // a toggle: given at all, it is said as aria-pressed
  loading: Boolean,
  disabled: Boolean,
})
// While it is under way the button stays where the keyboard is, and a second press does nothing.
function guard(e) { if (props.loading) { e.preventDefault(); e.stopImmediatePropagation() } }
</script>

<template>
  <button v-tip="label" type="button" class="icon-btn" :class="[size === 'sm' ? 'sm' : '', tone === 'danger' ? 'danger' : '', { busy: loading }]" :aria-label="label"
    :aria-pressed="pressed === undefined ? undefined : pressed ? 'true' : 'false'" :aria-busy="loading ? 'true' : undefined" :disabled="disabled" @click="guard">
    <Icon :name="icon" />
  </button>
</template>

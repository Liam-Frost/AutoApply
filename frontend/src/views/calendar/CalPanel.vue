<script setup>
// Where the calendar shows one item or a list: beside the calendar when there is room for both, over it from the
// right when there is not - then it holds the keyboard like a drawer (focus.js) and Escape closes it. Beside the
// calendar, the page closes it on Escape.
import { onBeforeUnmount, ref, watch } from 'vue'
import { hold, onTop } from '../../focus'

const props = defineProps({ floating: Boolean, label: { type: String, default: '' } })
const emit = defineEmits(['close'])
const box = ref(null)
let release = null
watch([box, () => props.floating], ([el, floating]) => {
  if (release) { release(); release = null }
  if (el && floating) release = hold(el)
}, { flush: 'post', immediate: true })
onBeforeUnmount(() => { if (release) release() })
const onKey = (e) => { if (e.key === 'Escape' && props.floating && box.value && onTop(box.value)) { e.stopPropagation(); emit('close') } }
</script>

<template>
  <Teleport to="body" :disabled="!floating">
    <div v-if="floating" class="overlay" @click="emit('close')"></div>
    <aside ref="box" class="cal-panel" :class="{ floating }" :role="floating ? 'dialog' : 'complementary'" :aria-modal="floating ? 'true' : undefined" :aria-label="label" @keydown="onKey">
      <slot />
    </aside>
  </Teleport>
</template>

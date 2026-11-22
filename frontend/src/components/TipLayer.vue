<script setup>
// The one element that shows a tooltip's words (src/tip.js decides when and for what). It is on <body>, so no table,
// card or drawer can cut it, and it is always there - hidden - so that it can be measured before it is seen and so
// that `aria-describedby` has something to point at.
import { ref, watch } from 'vue'
import { place, windowSize } from '../float'
import { TIP_ID, shown } from '../tip'

const box = ref(null)
const at = ref({ left: 0, top: 0, placement: 'top' })
// Measured with the words it has now, then put beside its element: after the words were drawn, before they are painted.
function put() {
  const el = shown.el, b = box.value
  if (!el || !b) return
  at.value = place(el.getBoundingClientRect(), { width: b.offsetWidth, height: b.offsetHeight }, windowSize(), { placement: shown.placement, offset: 6 })
}
watch(() => [shown.el, shown.seq], put, { flush: 'post' })
</script>

<template>
  <Teleport to="body">
    <div :id="TIP_ID" ref="box" class="tip-box" :class="{ on: shown.el }" role="tooltip" :data-side="at.placement"
      :style="{ left: at.left + 'px', top: at.top + 'px', maxWidth: 'min(' + shown.max + 'px, calc(100vw - 16px))', zIndex: shown.z || undefined }">{{ shown.text }}</div>
  </Teleport>
</template>

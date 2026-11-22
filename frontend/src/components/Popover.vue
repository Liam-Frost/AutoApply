<script>
let counter = 0      // ids for the button / box pairing: unique on the page, nothing more
</script>

<script setup>
// A box beside what opened it: help that is more than a sentence, or a light form (docs/component-guidelines.md).
// It is on <body> (no table or card cuts it), placed by float.js, and holds the keyboard while it is open (focus.js):
// the focus goes into it, Escape or a press outside closes it, and the focus goes back to where it was.
//
//   <Popover :label="$t('…')" :width="300">
//     <template #trigger="{ open, toggle, attrs }"><button v-bind="attrs" @click="toggle">…</button></template>
//     <template #default="{ close }">…</template>
//   </Popover>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { place, windowSize, zOver } from '../float'
import { focusable, hold, onTop } from '../focus'

const props = defineProps({
  label: { type: String, default: '' },             // the box's name, for whoever does not see it
  placement: { type: String, default: 'bottom' },   // top | bottom | left | right
  align: { type: String, default: 'start' },        // start | center | end
  width: { type: Number, default: 320 },
})
const emit = defineEmits(['open', 'close'])

const uid = 'pop' + ++counter
const root = ref(null)
const box = ref(null)
const open = ref(false)
const at = ref({})
const attrs = computed(() => ({ 'aria-haspopup': 'dialog', 'aria-expanded': open.value ? 'true' : 'false', 'aria-controls': open.value ? uid : undefined }))
let release = null
let sized = null
let frame = 0

function put() {
  frame = 0
  const b = box.value
  if (!b || !root.value) return
  const p = place(root.value.getBoundingClientRect(), { width: b.offsetWidth, height: b.offsetHeight }, windowSize(), { placement: props.placement, align: props.align, offset: 6 })
  at.value = { left: p.left + 'px', top: p.top + 'px', zIndex: zOver(root.value, '--z-pop') || undefined }
}
// It stays beside its button while the page scrolls, the window changes, or what is in it grows.
const again = () => { if (!frame) frame = requestAnimationFrame(put) }
// A press outside closes it - but not one in something that belongs to it and lies elsewhere on <body>: the list of
// a select in it, a tooltip, or a menu or question opened from it (then it is not the one on top).
function outside(e) {
  const t = e.target
  if (!onTop(box.value) || box.value.contains(t) || root.value.contains(t)) return
  if (t.closest && t.closest('.sel-pop, .tip-box')) return
  close()
}

// Where the focus goes: what the content marks (`data-first`), else the first thing in it that can be used - an (i)
// is a note beside a label, not what the box is for - else the box itself (a text is read from its start).
function first() {
  const all = focusable(box.value)
  return box.value.querySelector('[data-first]') || all.find((x) => !x.classList.contains('info-tip')) || all[0]
}

async function show() {
  if (open.value) return
  open.value = true
  // Unseen and not pressable until it has been measured and placed: never a frame in the window's corner. (Opacity, not
  // visibility: that is inherited, and under reduced motion every child would "fade" into view a frame late - and
  // could not take the focus until then.)
  at.value = { left: '0px', top: '0px', opacity: 0, pointerEvents: 'none' }
  await nextTick()
  if (!open.value || !box.value) return
  put()
  release = hold(box.value, { first })
  document.addEventListener('pointerdown', outside, true)
  window.addEventListener('scroll', again, true)
  window.addEventListener('resize', again)
  if (typeof ResizeObserver !== 'undefined') { sized = new ResizeObserver(again); sized.observe(box.value) }
  emit('open')
}
function close() {
  if (!open.value) return
  open.value = false
  document.removeEventListener('pointerdown', outside, true)
  window.removeEventListener('scroll', again, true)
  window.removeEventListener('resize', again)
  if (sized) { sized.disconnect(); sized = null }
  if (frame) { cancelAnimationFrame(frame); frame = 0 }
  if (release) { release(); release = null }
  // (focus.js gives the focus back to where it was - the button, unless the browser did not focus it on the click)
  if (root.value && !root.value.contains(document.activeElement)) { const b = focusable(root.value)[0]; if (b) b.focus({ preventScroll: true }) }
  emit('close')
}
const toggle = () => (open.value ? close() : show())
// Escape closes what is innermost: a select in the box that closed its list on this key says so (preventDefault).
function onEsc(e) {
  if (e.defaultPrevented) return
  e.preventDefault()
  e.stopPropagation()      // this Escape is the popover's, not the drawer's under it
  close()
}

onBeforeUnmount(close)
defineExpose({ open: show, close, toggle })
</script>

<template>
  <!-- Nothing pressed here reaches what is around it: a popover in a row that opens on a click does not open the row. -->
  <span ref="root" class="popover" @click.stop @keydown.enter.stop @keydown.space.stop>
    <slot name="trigger" :open="open" :toggle="toggle" :attrs="attrs" />
    <Teleport to="body">
      <div v-if="open" :id="uid" ref="box" class="pop" role="dialog" :aria-label="label || undefined" :style="{ width: 'min(' + width + 'px, calc(100vw - 16px))', ...at }" @keydown.esc="onEsc">
        <slot :close="close" />
      </div>
    </Teleport>
  </span>
</template>

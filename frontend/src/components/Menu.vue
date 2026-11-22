<script>
let counter = 0      // ids for the button / menu pairing: unique on the page, nothing more
</script>

<script setup>
// A button that opens a list of actions: where the actions go that are not used often enough to stand in a row
// (docs/component-guidelines.md). The list is on <body> (no table or card cuts it), placed by float.js, and holds the
// keyboard while it is open (focus.js) - so Escape closes it and not the drawer it was opened in, and the focus goes
// back to the button afterwards.
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { place, windowSize, zOver } from '../float'
import { focusable, hold, step } from '../focus'
import Icon from './Icon.vue'
import IconButton from './IconButton.vue'

const props = defineProps({
  items: { type: Array, required: true },       // { id, label, icon?, danger?, disabled?, hint? } | { divider: true }
  label: { type: String, required: true },      // the button's name (and tooltip), and the menu's
  icon: { type: String, default: 'more' },
  align: { type: String, default: 'end' },      // which edges of button and menu are in line: end | start
  placement: { type: String, default: 'bottom' },
  size: { type: String, default: 'md' },        // of the default button
  disabled: Boolean,
})
const emit = defineEmits(['pick', 'open', 'close'])

const uid = 'menu' + ++counter
const root = ref(null)
const list = ref(null)
const open = ref(false)
const at = ref({})
const icons = computed(() => props.items.some((it) => it.icon))      // then every label starts at the same place
// What a button given through the `trigger` slot needs to say about itself.
const attrs = computed(() => ({ 'aria-haspopup': 'menu', 'aria-expanded': open.value ? 'true' : 'false', 'aria-controls': open.value ? uid : undefined }))
let release = null
let anchor = null      // where the button was when the list was placed
let typed = '', typedAt = 0

const rows = () => (list.value ? [...list.value.querySelectorAll('[role="menuitem"]:not([aria-disabled="true"])')] : [])
function put() {
  const b = list.value
  if (!b || !root.value) return
  const r = root.value.getBoundingClientRect()
  anchor = { left: r.left, top: r.top }
  const p = place(r, { width: b.offsetWidth, height: b.offsetHeight }, windowSize(), { placement: props.placement, align: props.align, offset: 4 })
  at.value = { left: p.left + 'px', top: p.top + 'px', zIndex: zOver(root.value, '--z-pop') || undefined }
}
const outside = (e) => { if (!(list.value && list.value.contains(e.target)) && !root.value.contains(e.target)) close() }
// (the page moved under it: what it belongs to is somewhere else now. A list that scrolls elsewhere is not our business.
// Only a scroll that really moved the button counts: the browser sends a scroll event a frame late, so a scroll that
// ended just before the click - a wheel or a smooth scroll, the page bringing the button into view - closed the menu
// as soon as it had opened.)
const moved = () => { const r = root.value.getBoundingClientRect(); return !anchor || Math.abs(r.left - anchor.left) > 1 || Math.abs(r.top - anchor.top) > 1 }
const scrolled = (e) => { if ((e.target === document || (e.target.contains && e.target.contains(root.value))) && moved()) close() }

async function show() {
  if (open.value || props.disabled) return
  open.value = true
  at.value = { left: '0px', top: '0px' }
  await nextTick()
  if (!open.value || !list.value) return
  put()
  release = hold(list.value, { first: () => rows()[0] })
  document.addEventListener('pointerdown', outside, true)
  window.addEventListener('scroll', scrolled, true)
  window.addEventListener('resize', close)
  emit('open')
}
function close() {
  if (!open.value) return
  open.value = false
  document.removeEventListener('pointerdown', outside, true)
  window.removeEventListener('scroll', scrolled, true)
  window.removeEventListener('resize', close)
  if (release) { release(); release = null }
  // (focus.js gives the focus back to where it was - the button, unless the browser did not focus it on the click)
  if (root.value && !root.value.contains(document.activeElement)) { const b = focusable(root.value)[0]; if (b) b.focus({ preventScroll: true }) }
  emit('close')
}
const toggle = () => (open.value ? close() : show())
function pick(it) {
  if (it.disabled) return
  close()
  emit('pick', it.id)
}
function go(to) {
  const all = rows()
  if (all[to]) all[to].focus()
}
function onKey(e) {
  const all = rows()
  const i = all.indexOf(document.activeElement)
  const k = e.key
  if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); close() }      // (stopped: this Escape is the menu's, not the drawer's under it)
  else if (k === 'Tab') close()                                                 // and the focus goes on from the button
  else if (k === 'ArrowDown') { e.preventDefault(); go(step(i, all.length, false)) }
  else if (k === 'ArrowUp') { e.preventDefault(); go(step(i, all.length, true)) }
  else if (k === 'Home' || k === 'PageUp') { e.preventDefault(); go(0) }
  else if (k === 'End' || k === 'PageDown') { e.preventDefault(); go(all.length - 1) }
  else if (k.length === 1 && k !== ' ' && !e.ctrlKey && !e.metaKey && !e.altKey) {      // type to jump
    const t = Date.now()
    typed = t - typedAt > 700 ? k : typed + k
    typedAt = t
    const want = typed.toLowerCase()
    const from = typed.length === 1 ? i + 1 : Math.max(i, 0)      // the same letter again goes to the next one that starts with it
    for (let n = 0; n < all.length; n++) {
      const el = all[(from + n) % all.length]
      if ((el.dataset.label || '').toLowerCase().startsWith(want)) { el.focus(); break }
    }
  }
}
// The pointer and the keyboard move the same mark: what is under the pointer has the focus.
const onMove = (e, it) => { if (!it.disabled && document.activeElement !== e.currentTarget) e.currentTarget.focus({ preventScroll: true }) }

onBeforeUnmount(close)
defineExpose({ open: show, close, toggle })
</script>

<template>
  <!-- Nothing pressed here reaches what is around it: a menu in a row that opens on a click does not open the row. -->
  <span ref="root" class="menu" @click.stop @keydown.enter.stop @keydown.space.stop @keydown.down.prevent.stop="show">
    <slot name="trigger" :open="open" :toggle="toggle" :attrs="attrs">
      <IconButton :icon="icon" :label="label" :size="size" :disabled="disabled" v-bind="attrs" @click="toggle" />
    </slot>
    <Teleport to="body">
      <div v-if="open" :id="uid" ref="list" class="menu-pop" :class="{ icons }" role="menu" :aria-label="label" :style="at" @keydown="onKey">
        <template v-for="(it, i) in items" :key="it.divider ? 'divider-' + i : it.id">
          <div v-if="it.divider" class="menu-sep" role="separator"></div>
          <button v-else type="button" class="menu-item" :class="{ danger: it.danger }" role="menuitem" tabindex="-1" :data-label="it.label"
            :aria-disabled="it.disabled ? 'true' : undefined" @click="pick(it)" @pointermove="onMove($event, it)">
            <Icon v-if="it.icon" :name="it.icon" />
            <span class="menu-text"><span class="menu-label">{{ it.label }}</span><span v-if="it.hint" class="menu-hint">{{ it.hint }}</span></span>
          </button>
        </template>
      </div>
    </Teleport>
  </span>
</template>

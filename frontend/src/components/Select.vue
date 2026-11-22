<script>
let counter = 0   // ids for the label / listbox pairing: unique on the page, nothing more
</script>

<script setup>
// Drop-down that replaces the browser's own <select>. Used exactly like one - <AaSelect v-model="x"><option value="a">A</option></AaSelect> -
// so the options stay readable in the template; they are read from the slot and drawn in the product's own style.
import { Fragment, Static, computed, nextTick, onBeforeUnmount, ref, useAttrs, useSlots } from 'vue'
import { t as T } from '../i18n/catalog'

// (attributes go to the button by hand: a `title` given to it is said in the program's tooltip - never the browser's -
// and is the button's name when it has no aria-label)
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: { default: undefined }, value: { default: undefined }, placeholder: { type: String, default: () => T('common.select.placeholder') }, disabled: Boolean, small: Boolean })
const emit = defineEmits(['update:modelValue', 'change'])
const slots = useSlots()
const attrs = useAttrs()

function textOf(c) {
  if (c == null || typeof c === 'boolean') return ''
  if (typeof c === 'string' || typeof c === 'number') return String(c)
  if (Array.isArray(c)) return c.map(textOf).join('')
  return textOf(c.children)
}
function collect(nodes, out) {
  for (const n of nodes || []) {
    if (!n || typeof n !== 'object') continue
    if (n.type === Fragment) collect(n.children, out)
    else if (n.type === Static) { // several plain <option>s in a row are compiled into one HTML string
      const box = document.createElement('select')
      box.innerHTML = n.children
      for (const o of box.options) out.push({ value: o.hasAttribute('value') ? o.getAttribute('value') : o.textContent.trim(), label: o.textContent.trim(), disabled: o.disabled })
    } else if (n.type === 'option') {
      const label = textOf(n.children).trim()
      const p = n.props || {}
      out.push({ value: 'value' in p ? p.value : label, label, disabled: p.disabled === '' || p.disabled === true })
    }
  }
  return out
}
const options = computed(() => collect(slots.default ? slots.default() : [], []))
const current = computed(() => (props.modelValue !== undefined ? props.modelValue : props.value))
const same = (a, b) => a === b || (a != null && b != null && String(a) === String(b))
const selected = computed(() => options.value.find((o) => same(o.value, current.value)))

const open = ref(false)
const active = ref(-1)
const btn = ref(null)
const pop = ref(null)
const place = ref({})
let typed = '', typedAt = 0

function position() {
  const r = btn.value.getBoundingClientRect()
  const below = window.innerHeight - r.bottom
  const h = Math.min(320, options.value.length * 34 + 10)
  const up = below < h + 12 && r.top > below
  place.value = { left: Math.max(8, Math.min(r.left, window.innerWidth - 8 - Math.max(r.width, 160))) + 'px', minWidth: r.width + 'px', maxHeight: Math.max(120, Math.min(320, (up ? r.top : below) - 12)) + 'px',
    ...(up ? { bottom: window.innerHeight - r.top + 4 + 'px' } : { top: r.bottom + 4 + 'px' }) }
}
function outside(e) { if (!btn.value.contains(e.target) && !(pop.value && pop.value.contains(e.target))) close() }
function scrolled(e) { if (!(pop.value && pop.value.contains(e.target))) close() }
async function show() {
  if (props.disabled || open.value) return
  open.value = true
  active.value = Math.max(0, options.value.findIndex((o) => same(o.value, current.value)))
  position()
  document.addEventListener('mousedown', outside, true)
  window.addEventListener('scroll', scrolled, true)
  window.addEventListener('resize', close)
  await nextTick()
  reveal()
}
function close() {
  if (!open.value) return
  open.value = false
  document.removeEventListener('mousedown', outside, true)
  window.removeEventListener('scroll', scrolled, true)
  window.removeEventListener('resize', close)
}
function reveal() { const el = pop.value && pop.value.children[active.value]; if (el) el.scrollIntoView({ block: 'nearest' }) }
function pick(o) {
  if (o.disabled) return
  close()
  if (!same(o.value, current.value)) { emit('update:modelValue', o.value); emit('change', { target: { value: o.value } }) }
  btn.value.focus()
}
function move(d) {
  const n = options.value.length
  if (!n) return
  let i = active.value
  for (let k = 0; k < n; k++) { i = (i + d + n) % n; if (!options.value[i].disabled) break }
  active.value = i
  nextTick(reveal)
}
function onKey(e) {
  const k = e.key
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(k)) { e.preventDefault(); show() }
    return
  }
  if (k === 'Escape' || k === 'Tab') { close(); if (k === 'Escape') e.preventDefault() }
  else if (k === 'ArrowDown') { e.preventDefault(); move(1) }
  else if (k === 'ArrowUp') { e.preventDefault(); move(-1) }
  else if (k === 'Home') { e.preventDefault(); active.value = -1; move(1) }
  else if (k === 'End') { e.preventDefault(); active.value = 0; move(-1) }
  else if (k === 'Enter' || k === ' ') { e.preventDefault(); if (options.value[active.value]) pick(options.value[active.value]) }
  else if (k.length === 1) { // type to jump
    const now = Date.now()
    typed = now - typedAt > 700 ? k : typed + k
    typedAt = now
    const i = options.value.findIndex((o) => o.label.toLowerCase().startsWith(typed.toLowerCase()))
    if (i >= 0) { active.value = i; nextTick(reveal) }
  }
}
onBeforeUnmount(close)
const uid = 'sel' + ++counter
</script>

<template>
  <button :id="attrs.id" ref="btn" type="button" class="sel" :class="[attrs.class, { open, sm: small, empty: !selected }]" v-tip="attrs.title" :style="attrs.style" :disabled="disabled"
    role="combobox" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="uid" :aria-label="attrs['aria-label'] || attrs.title"
    :aria-labelledby="attrs['aria-labelledby']" :aria-describedby="attrs['aria-describedby']"
    :aria-activedescendant="open && active >= 0 ? uid + '-' + active : undefined" @click="open ? close() : show()" @keydown="onKey">
    <span class="sel-val">{{ selected ? selected.label : placeholder }}</span>
    <svg class="sel-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
  </button>
  <Teleport to="body">
    <div v-if="open" :id="uid" ref="pop" class="sel-pop" role="listbox" :style="place">
      <div v-for="(o, i) in options" :id="uid + '-' + i" :key="i" class="sel-opt" :class="{ active: i === active, on: same(o.value, current), disabled: o.disabled }"
        role="option" :aria-selected="same(o.value, current)" :aria-disabled="o.disabled ? 'true' : undefined" @mouseenter="active = i" @mousedown.prevent @click="pick(o)">
        <span>{{ o.label }}</span>
        <svg v-if="same(o.value, current)" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5L20 6" /></svg>
      </div>
      <div v-if="!options.length" class="sel-opt disabled">{{ $t('common.select.none') }}</div>
    </div>
  </Teleport>
</template>

<script>
let counter = 0      // ids for the trigger / list / option pairing: unique on the page, nothing more
</script>

<script setup>
// A select you can search (docs/component-guidelines.md, Combobox): the trigger looks and sizes like AaSelect; pressing
// it - or ArrowDown, Enter, a letter - opens a list on <body> with a search field at its top that has the focus. The
// search itself is src/combobox.js (tested); this draws it, places it, and keeps the keyboard.
//
//   <Combobox v-model="v" :options="[{ value, label, hint?, group?, keywords?, disabled? }]" :groups="[{ id, label }]" :label="…" />
import { computed, nextTick, onBeforeUnmount, ref, useAttrs, watch } from 'vue'
import { t as T } from '../i18n/catalog'
import { indexOf, prepare, same, search, step } from '../combobox'

// (attributes go to the trigger by hand, as on AaSelect: its id is what a <label for> names)
defineOptions({ inheritAttrs: false })
const props = defineProps({
  modelValue: { default: undefined },
  options: { type: Array, default: () => [] },
  groups: { type: Array, default: () => [] },
  label: { type: String, required: true },                   // the accessible name of the trigger, the search and the list
  placeholder: { type: String, default: () => T('common.select.placeholder') },
  invalid: Boolean,
  disabled: Boolean,
  emptyText: { type: String, default: '' },                  // no option matches the search
  searchPlaceholder: { type: String, default: '' },          // what can be typed (an example), in the search field
  width: { type: Number, default: 0 },                       // the list's; default the trigger's, at least 320
})
const emit = defineEmits(['update:modelValue', 'change', 'open', 'close'])
const attrs = useAttrs()
const uid = 'cb' + ++counter

// what the trigger says: the chosen option - or a value that is not among them, as it is (never dropped)
const chosen = computed(() => props.options.find((o) => same(o.value, props.modelValue)) || null)
const shown = computed(() => (chosen.value ? chosen.value.label : props.modelValue != null && props.modelValue !== '' ? String(props.modelValue) : ''))
const whole = computed(() => [shown.value || props.placeholder, chosen.value && chosen.value.hint].filter(Boolean).join(' · '))

const prepared = computed(() => prepare(props.options))       // folded once per list of options, not per key
const query = ref('')
const found = computed(() => search(prepared.value, props.groups, query.value))
const count = computed(() => found.value.items.length)

const open = ref(false)
const active = ref(-1)
const btn = ref(null)
const box = ref(null)
const list = ref(null)
const input = ref(null)
const at = ref({})
let up = null        // the side chosen when it opened: kept while it is open, so the search field does not jump
let frame = 0

function put() {
  frame = 0
  if (!open.value || !btn.value) return
  const r = btn.value.getBoundingClientRect()
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight
  if (r.bottom < 0 || r.top > vh) { close(false); return }      // its field went out of sight
  const w = Math.min(Math.max(props.width || r.width, 320), vw - 16)
  if (up === null) { const below = vh - r.bottom; up = below < 320 && r.top > below }
  const room = (up ? r.top : vh - r.bottom) - 12
  at.value = { left: Math.max(8, Math.min(r.left, vw - 8 - w)) + 'px', width: w + 'px', maxHeight: Math.max(180, Math.min(440, room)) + 'px',
    ...(up ? { bottom: vh - r.top + 4 + 'px' } : { top: r.bottom + 4 + 'px' }) }
}
const again = (e) => { if (e && e.type === 'scroll' && box.value && box.value.contains(e.target)) return; if (!frame) frame = requestAnimationFrame(put) }
function outside(e) { if (!(btn.value && btn.value.contains(e.target)) && !(box.value && box.value.contains(e.target))) close(false) }

async function show(typed = '') {
  if (props.disabled || open.value) return
  query.value = typed
  open.value = true
  up = null
  const items = found.value.items
  const i = typed ? -1 : indexOf(items, props.modelValue)
  active.value = i >= 0 && !items[i].disabled ? i : step(items, -1, 'Home')
  put()
  document.addEventListener('pointerdown', outside, true)
  window.addEventListener('scroll', again, true)
  window.addEventListener('resize', again)
  emit('open')
  await nextTick()
  if (!open.value) return
  if (input.value) { input.value.focus({ preventScroll: true }); input.value.setSelectionRange(typed.length, typed.length) }
  reveal(true)
}
function close(refocus = true) {
  if (!open.value) return
  open.value = false
  document.removeEventListener('pointerdown', outside, true)
  window.removeEventListener('scroll', again, true)
  window.removeEventListener('resize', again)
  if (frame) { cancelAnimationFrame(frame); frame = 0 }
  if (refocus && btn.value) btn.value.focus({ preventScroll: true })
  emit('close')
}
function pick(o) {
  if (!o || o.disabled) return
  close(true)
  if (!same(o.value, props.modelValue)) { emit('update:modelValue', o.value); emit('change', o.value) }
}

// The mark is kept in sight: brought to the middle when the list opens, else just inside its edge (below the heading
// of its group, which stays at the top while its options scroll).
function reveal(middle = false) {
  const l = list.value
  const el = l && active.value >= 0 ? l.querySelector('#' + uid + '-o' + active.value) : null
  if (!el) { if (l && middle) l.scrollTop = 0; return }
  const head = el.parentElement && el.parentElement.querySelector('.cb-group')
  const top = el.offsetTop - (head ? head.offsetHeight : 0), bottom = el.offsetTop + el.offsetHeight
  if (middle) l.scrollTop = Math.max(0, el.offsetTop - l.clientHeight / 2 + el.offsetHeight / 2)
  else if (top < l.scrollTop) l.scrollTop = top
  else if (bottom > l.scrollTop + l.clientHeight) l.scrollTop = bottom - l.clientHeight
}
// (while a word is being typed, the first option that matches it is marked; with nothing typed, the chosen one)
watch(query, () => {
  if (!open.value) return
  const items = found.value.items
  const i = query.value ? -1 : indexOf(items, props.modelValue)
  active.value = i >= 0 && !items[i].disabled ? i : step(items, -1, 'Home')
  nextTick(() => reveal(!query.value))
})
// the mark follows the pointer only when the pointer moves (a list scrolled by the keyboard under a still pointer
// does not take the mark away)
const hover = (i, o) => { if (!o.disabled && active.value !== i) active.value = i }
const pageSize = () => { const l = list.value, o = l && l.querySelector('.cb-opt'); return o ? Math.max(1, Math.floor(l.clientHeight / o.offsetHeight) - 1) : 8 }

function onKey(e) {
  if (e.isComposing || e.keyCode === 229) return            // an input method is putting a word together
  const k = e.key
  if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'].includes(k)) {
    e.preventDefault()
    active.value = step(found.value.items, active.value, k, pageSize())
    nextTick(() => reveal())
  } else if (k === 'Enter') {
    e.preventDefault()
    pick(found.value.items[active.value])
  } else if (k === 'Escape') {
    e.preventDefault()
    e.stopPropagation()       // this Escape is the list's, not that of a drawer or popover it was opened from
    close(true)
  } else if (k === 'Tab') {
    close(true)               // the focus is on the trigger again, and the Tab moves on from there
  }
}
function onTriggerKey(e) {
  if (open.value) return
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); show() }
  else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); show(e.key) }      // typing starts a search
}
onBeforeUnmount(() => close(false))
defineExpose({ open: show, close })
</script>

<template>
  <button :id="attrs.id" ref="btn" type="button" class="sel cb" :class="[attrs.class, { open, blank: !shown, invalid }]" :style="attrs.style" :disabled="disabled"
    aria-haspopup="listbox" :aria-expanded="open ? 'true' : 'false'" :aria-controls="open ? uid + '-list' : undefined"
    :aria-labelledby="uid + '-name ' + uid + '-val'" :aria-describedby="attrs['aria-describedby']" :aria-invalid="invalid ? 'true' : undefined"
    @click="open ? close(true) : show()" @keydown="onTriggerKey">
    <span :id="uid + '-name'" class="cb-sr">{{ label }}</span>
    <span :id="uid + '-val'" v-tip.overflow="whole" class="sel-val cb-val"><span class="cb-main">{{ shown || placeholder }}</span><span v-if="chosen && chosen.hint" class="cb-hint">{{ chosen.hint }}</span></span>
    <svg class="sel-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
  </button>
  <Teleport to="body">
    <!-- (a press anywhere in it but the search field leaves the focus in the search field: typing goes on there) -->
    <div v-if="open" ref="box" class="sel-pop cb-pop" :style="at" @mousedown="(e) => { if (e.target !== input) e.preventDefault() }">
      <div class="cb-search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        <input ref="input" v-model="query" type="text" role="combobox" aria-autocomplete="list" aria-expanded="true" :aria-controls="uid + '-list'"
          :aria-activedescendant="active >= 0 ? uid + '-o' + active : undefined" :aria-label="label" :placeholder="searchPlaceholder || $t('controls.combobox.search')"
          autocomplete="off" autocapitalize="off" spellcheck="false" @keydown="onKey" />
      </div>
      <div :id="uid + '-list'" ref="list" class="cb-list" role="listbox" :aria-label="label">
        <div v-for="sec in found.sections" :key="sec.group ? sec.group.id : ''" class="cb-sec" :role="sec.group ? 'group' : undefined" :aria-label="sec.group ? sec.group.label : undefined">
          <div v-if="sec.group" class="cb-group" aria-hidden="true">{{ sec.group.label }}</div>
          <div v-for="r in sec.rows" :id="uid + '-o' + r.at" :key="r.at" class="sel-opt cb-opt" role="option"
            :class="{ active: r.at === active, on: same(r.option.value, modelValue), disabled: r.option.disabled }"
            :aria-selected="same(r.option.value, modelValue) ? 'true' : 'false'" :aria-disabled="r.option.disabled ? 'true' : undefined"
            @mousemove="hover(r.at, r.option)" @mousedown.prevent @click="pick(r.option)">
            <span class="cb-opt-label">{{ r.option.label }}</span>
            <span v-if="r.option.hint" class="cb-opt-hint">{{ r.option.hint }}</span>
            <svg v-if="same(r.option.value, modelValue)" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5L20 6" /></svg>
          </div>
        </div>
      </div>
      <div v-if="!count" class="cb-empty">{{ emptyText || $t('controls.combobox.none') }}</div>
      <div class="cb-sr" role="status" aria-live="polite">{{ query ? $t('controls.combobox.count', { n: count }, count) : '' }}</div>
    </div>
  </Teleport>
</template>

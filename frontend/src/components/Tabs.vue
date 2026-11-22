<script>
let counter = 0      // ids for the tabs, when the page gives none: unique on the page, nothing more
</script>

<script setup>
// A row of tabs: which part of a page is shown (docs/component-guidelines.md, "Tabs"). One line that scrolls sideways
// inside itself when it is longer than its place - never a second line. The keyboard is on one tab at a time (roving
// tabindex): the arrows, Home and End move it and select what they land on, a disabled tab is passed over. The page
// shows the part itself; its panel can name its tab with `aria-labelledby="<id>-<item id>"`.
//
//   <Tabs v-model="tab" :label="$t('…')" :items="[{ id: 'all', label: $t('…'), count: 12 }, { id: 'x', label: …, disabled: true }]" />
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  items: { type: Array, required: true },      // { id, label, count?, disabled? }
  modelValue: { type: [String, Number], default: null },
  label: { type: String, required: true },      // what the row chooses between: its accessible name
  id: { type: String, default: '' },            // the tabs' ids are `<id>-<item id>`
  controls: { type: String, default: '' },      // the id of the panel the tabs show, when there is one
})
const emit = defineEmits(['update:modelValue'])

const base = props.id || 'tabs' + ++counter
const row = ref(null)
const usable = computed(() => props.items.filter((it) => !it.disabled))
// The tab the keyboard comes to: the selected one, or the first that can be used when none is.
const stop = computed(() => (usable.value.some((it) => it.id === props.modelValue) ? props.modelValue : usable.value[0]?.id))
const hasCount = (it) => it.count !== undefined && it.count !== null && it.count !== ''

const tabOf = (id) => (row.value ? [...row.value.children].find((el) => el.dataset.tab === String(id)) : null)
// The row is scrolled so that the tab is in it - the row alone: the page does not move (scrollIntoView would).
function reveal(id) {
  const r = row.value, el = tabOf(id)
  if (!r || !el || r.scrollWidth <= r.clientWidth) return
  const pad = 8
  const a = el.offsetLeft, b = a + el.offsetWidth      // (from the row: it is positioned, .aa-tabs)
  if (a - pad < r.scrollLeft) r.scrollLeft = a - pad
  else if (b + pad > r.scrollLeft + r.clientWidth) r.scrollLeft = b + pad - r.clientWidth
}
function select(it, focus) {
  if (!it || it.disabled) return
  if (it.id !== props.modelValue) emit('update:modelValue', it.id)
  if (focus) { const el = tabOf(it.id); if (el) el.focus({ preventScroll: true }) }
}
// Which edges have more tabs past them (they fade out: the row has no scroll bar to say so).
const more = ref({ left: false, right: false })
function edges() {
  const r = row.value
  if (!r) return
  more.value = { left: r.scrollLeft > 1, right: r.scrollLeft + r.clientWidth < r.scrollWidth - 1 }
}
// The selected tab is in view when the row is drawn and whenever it changes, however it was chosen.
let sized = null
onMounted(() => {
  reveal(props.modelValue)
  edges()
  if (typeof ResizeObserver !== 'undefined') { sized = new ResizeObserver(edges); sized.observe(row.value) }
})
onBeforeUnmount(() => sized && sized.disconnect())
watch(() => props.modelValue, (id) => nextTick(() => { reveal(id); edges() }))
watch(() => props.items, () => nextTick(edges))
function onKey(e) {
  const all = usable.value
  if (!all.length) return
  const i = all.findIndex((it) => it.id === stop.value)
  const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1 }[e.key]
  if (to === undefined) return
  e.preventDefault()
  // (in a right-to-left page the arrows would turn round; the program has none)
  select(all[(to + all.length) % all.length], true)
}
// A wheel turned over a row that scrolls sideways moves it sideways (it has no visible scroll bar).
function onWheel(e) {
  const el = row.value
  if (!el || el.scrollWidth <= el.clientWidth || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return
  const left = el.scrollLeft
  el.scrollLeft += e.deltaY
  if (el.scrollLeft !== left) e.preventDefault()
}
</script>

<template>
  <div ref="row" class="seg tabs aa-tabs" :class="{ 'more-left': more.left, 'more-right': more.right }" role="tablist" :aria-label="label" @keydown="onKey" @wheel="onWheel" @scroll.passive="edges">
    <button v-for="it in items" :id="base + '-' + it.id" :key="it.id" type="button" role="tab" :data-tab="it.id" :class="{ on: it.id === modelValue }"
      :aria-selected="it.id === modelValue ? 'true' : 'false'" :aria-controls="controls && it.id === modelValue ? controls : undefined"
      :tabindex="it.id === stop ? 0 : -1" :disabled="it.disabled" @click="select(it, false)">{{ it.label }}<span v-if="hasCount(it)" class="n">{{ it.count }}</span></button>
  </div>
</template>

<script setup>
// The table every list of records uses (docs/component-guidelines.md, "DataTable"). The widths of its columns come
// from their definitions and the width of the box (tablelayout.js) and are written into a <colgroup> of a fixed-layout
// table: nothing a cell holds can widen a column or make a row taller. A column that is optional (`priority`) goes
// when the box is too narrow; if what must stay still does not fit, the table scrolls inside its own box.
// Sorting and filtering are the page's: this only says which header was pressed.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { layoutColumns } from '../tablelayout'
import Icon from './Icon.vue'
import InfoTip from './InfoTip.vue'
import Trunc from './Trunc.vue'

const props = defineProps({
  columns: { type: Array, required: true },      // { id, header, width?, min?, max?, flex?, align?, priority?, sortable?, headerTip?, class? }
  rows: { type: Array, required: true },
  rowKey: { type: [String, Function], default: 'id' },
  density: { type: String, default: 'standard' },      // compact | standard | comfortable
  selectable: Boolean,
  selected: { type: Object, default: () => new Set() },      // v-model:selected - a Set of row keys
  selectLabel: { type: Function, default: null },      // (row) => the name of that row's checkbox
  selectAllLabel: { type: String, default: '' },
  sort: { type: Object, default: null },      // v-model:sort - { by, dir: 'asc' | 'desc' }
  clickable: Boolean,
  label: { type: String, default: '' },
  expandedKey: { default: null },
  maxHeight: { type: [Number, String], default: null },      // the body scrolls under the header past this (px, or any CSS length); also --dt-max-h
  rowClass: { type: Function, default: null },      // (row) => class(es) of that row
})
const emit = defineEmits(['update:selected', 'update:sort', 'row'])

// The box's inner width: read when mounted and whenever it changes (the window, a panel beside it opening, a scrollbar).
const box = ref(null)
const width = ref(0)
let watcher = null
function measure() { if (box.value) width.value = box.value.clientWidth }
onMounted(() => {
  measure()
  if (typeof ResizeObserver === 'undefined') return window.addEventListener('resize', measure)
  watcher = new ResizeObserver(measure)
  watcher.observe(box.value)
})
onBeforeUnmount(() => { watcher?.disconnect(); window.removeEventListener('resize', measure) })

const layout = computed(() => layoutColumns(props.columns, width.value, { selectable: props.selectable }))
const shown = computed(() => layout.value.visible.map((id) => props.columns.find((c) => c.id === id)))
const span = computed(() => shown.value.length + (props.selectable ? 1 : 0))
const tone = computed(() => (['compact', 'comfortable'].includes(props.density) ? props.density : 'standard'))
const limit = computed(() => (props.maxHeight === null || props.maxHeight === '' ? null : typeof props.maxHeight === 'number' ? props.maxHeight + 'px' : props.maxHeight))

const keyOf = (row) => (typeof props.rowKey === 'function' ? props.rowKey(row) : row[props.rowKey])
const empty = (v) => v === null || v === undefined || v === ''
const side = (c) => (c.align === 'end' || c.align === 'center' ? 'a-' + c.align : null)

// ── sorting: the first press sorts upwards, the next turns it round
const sortOf = (c) => (props.sort && props.sort.by === c.id ? (props.sort.dir === 'desc' ? 'descending' : 'ascending') : 'none')
function sortBy(c) { emit('update:sort', { by: c.id, dir: sortOf(c) === 'ascending' ? 'desc' : 'asc' }) }

// ── selection
const has = (row) => !!props.selected && props.selected.has(keyOf(row))
const picked = computed(() => props.rows.filter(has).length)
const all = computed(() => props.rows.length > 0 && picked.value === props.rows.length)
let anchor = null      // the row ticked last: Shift and a press tick everything from there to here
function pick(row, index, e) {
  const next = new Set(props.selected)
  const on = !next.has(keyOf(row))
  const from = e.shiftKey && anchor !== null && anchor < props.rows.length ? anchor : index
  for (let i = Math.min(from, index); i <= Math.max(from, index); i++) on ? next.add(keyOf(props.rows[i])) : next.delete(keyOf(props.rows[i]))
  anchor = index
  emit('update:selected', next)
}
// The header's box ticks or clears the rows that are shown; what was ticked on another page or under another filter stays.
function pickAll() {
  const next = new Set(props.selected)
  const on = !all.value
  for (const row of props.rows) on ? next.add(keyOf(row)) : next.delete(keyOf(row))
  anchor = null
  emit('update:selected', next)
}

// ── a row as a target: a press anywhere in it, except on something in it that does a thing of its own, and except
// at the end of selecting its text
const OWN = 'a, button, input, select, textarea, label, summary, [role="button"], [role="link"], [role="menuitem"], [tabindex]:not(tr), [data-row-stop]'
function press(row, e) {
  if (!props.clickable || e.defaultPrevented) return
  const own = e.target.closest ? e.target.closest(OWN) : null
  if (own && e.currentTarget.contains(own)) return
  if (typeof window.getSelection === 'function' && String(window.getSelection())) return
  emit('row', row, e)
}

defineExpose({ layout })
</script>

<template>
  <div class="dt" :class="[tone, { 'has-scroll': layout.scroll }]" :style="{ '--dt-box': width + 'px', '--dt-max-h': limit }">
    <div ref="box" class="dt-scroll" :class="{ x: layout.scroll }" :tabindex="layout.scroll ? 0 : null">
      <table class="dt-table" :style="{ width: layout.total + 'px' }" :aria-label="label || null">
        <colgroup>
          <col v-if="selectable" :style="{ width: layout.select + 'px' }">
          <col v-for="c in shown" :key="c.id" :style="{ width: layout.widths[c.id] + 'px' }">
        </colgroup>
        <thead>
          <tr>
            <th v-if="selectable" scope="col" class="dt-th dt-select">
              <label class="dt-check"><input type="checkbox" :checked="all" :indeterminate.prop="picked > 0 && !all" :disabled="!rows.length" :aria-label="selectAllLabel || $t('common.table.selectAll')" @change="pickAll"></label>
            </th>
            <th v-for="c in shown" :key="c.id" scope="col" class="dt-th" :class="[c.class, side(c)]" :aria-sort="c.sortable ? sortOf(c) : null">
              <div class="dt-head">
                <button v-if="c.sortable" type="button" class="dt-sort" :class="{ on: sortOf(c) !== 'none' }" @click="sortBy(c)">
                  <slot :name="'head-' + c.id" :column="c"><Trunc :text="c.header" /></slot>
                  <Icon :name="sortOf(c) === 'descending' ? 'sort_down' : 'sort_up'" />
                </button>
                <slot v-else :name="'head-' + c.id" :column="c"><Trunc :text="c.header" /></slot>
                <InfoTip v-if="c.headerTip" :text="c.headerTip" />
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(row, i) in rows" :key="keyOf(row)">
            <tr class="dt-row" :class="[{ clickable, open: expandedKey !== null && expandedKey === keyOf(row) }, rowClass ? rowClass(row) : null]" :tabindex="clickable ? 0 : null"
                :aria-selected="selectable ? has(row) : null" @click="press(row, $event)" @keydown.enter.self="clickable && emit('row', row, $event)">
              <td v-if="selectable" class="dt-td dt-select" @click.stop>
                <label class="dt-check"><input type="checkbox" :checked="has(row)" :aria-label="selectLabel ? selectLabel(row) : $t('common.table.selectRow', { n: i + 1 })" @click="pick(row, i, $event)"></label>
              </td>
              <td v-for="c in shown" :key="c.id" class="dt-td" :class="[c.class, side(c)]">
                <div class="dt-cell">
                  <slot :name="'cell-' + c.id" :row="row" :index="i" :column="c">
                    <span v-if="empty(row[c.id])" class="none">—</span>
                    <Trunc v-else :text="String(row[c.id])" />
                  </slot>
                </div>
              </td>
            </tr>
            <tr v-if="$slots.expanded && expandedKey !== null && expandedKey === keyOf(row)" class="dt-expanded">
              <td class="dt-xtd" :colspan="span"><div class="dt-x"><slot name="expanded" :row="row" :index="i" /></div></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div v-if="!rows.length && $slots.empty" class="dt-empty"><slot name="empty" /></div>
  </div>
</template>

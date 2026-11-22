<script setup>
// The month - planning: what is coming and on which days it bunches. Each day shows what matters most on lines of its
// own (an interview, an assessment, an offer to answer, then what is to be done, then a deadline worth it), the day's
// other deadlines as one count, and how many more; how many lines a day has room for is measured, so a busy day never
// grows the grid (calendar.js plan). A day is chosen by a click; its whole list opens beside the calendar from the
// count, and the day view from a double click or the list.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '../../components/Icon.vue'
import EventChip from './EventChip.vue'
import { dayKey, FAMILY, iso, plan } from '../../calendar'
import { tag } from '../../i18n/catalog'
import { longDate } from './look'

const props = defineProps({ days: { type: Array, required: true }, month: { type: Number, required: true }, selected: { type: Date, required: true },
  items: { type: Array, required: true }, now: { type: Date, required: true }, openId: { type: String, default: '' } })
const emit = defineEmits(['select', 'open', 'list', 'create', 'day'])

const weekdays = computed(() => props.days.slice(0, 7).map((d) => new Intl.DateTimeFormat(tag(), { weekday: 'short' }).format(d)))
const weeks = computed(() => Math.ceil(props.days.length / 7))
const byDay = computed(() => {
  const m = new Map()
  for (const x of props.items) { const k = dayKey(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x) }
  return m
})

// how many lines a day has room for, and whether a day is too narrow for words (then points of colour)
const grid = ref(null)
const lines = ref(3)
const narrow = ref(false)
let watcher = null
const LINE = 20        // a line (18px) and the gap under it
function measure() {
  const cell = grid.value && grid.value.querySelector('.cal-cell')
  if (!cell) return
  lines.value = Math.max(1, Math.floor((cell.clientHeight - 9 - 24) / LINE))
  narrow.value = cell.clientWidth < 84
}
onMounted(() => { measure(); watcher = new ResizeObserver(measure); watcher.observe(grid.value) })
onBeforeUnmount(() => { if (watcher) watcher.disconnect() })

const plans = computed(() => {
  const out = {}
  for (const d of props.days) out[iso(d)] = plan(byDay.value.get(iso(d)) || [], lines.value, props.now)
  return out
})
const dots = (d) => (byDay.value.get(iso(d)) || []).slice(0, 5)
const count = (d) => (byDay.value.get(iso(d)) || []).length
const isToday = (d) => iso(d) === iso(props.now)
const weekend = (d) => d.getDay() === 0 || d.getDay() === 6
</script>

<template>
  <div ref="grid" class="cal-month" :style="{ gridTemplateRows: `34px repeat(${weeks}, minmax(var(--cell-min, 100px), 1fr))` }" role="grid" :aria-rowcount="weeks + 1">
    <div v-for="(w, i) in weekdays" :key="i" class="cal-wd" role="columnheader">{{ w }}</div>
    <div v-for="(d, i) in days" :key="iso(d)" class="cal-cell" role="gridcell" :aria-selected="iso(d) === iso(selected)"
         :class="{ out: d.getMonth() !== month, today: isToday(d), sel: iso(d) === iso(selected), weekend: weekend(d), last: i >= days.length - 7 }"
         @click="emit('select', d)" @dblclick="emit('day', d)">
      <div class="cal-cell-head">
        <button type="button" class="cal-num" :aria-label="longDate(d)" :aria-current="isToday(d) ? 'date' : undefined" @click.stop="emit('select', d)" @dblclick.stop="emit('day', d)">{{ d.getDate() }}</button>
        <button type="button" class="cal-add" :aria-label="$t('calendar.addOn', { day: longDate(d) })" v-tip="$t('calendar.addOn', { day: longDate(d) })" @click.stop="emit('create', d)"><Icon name="plus" /></button>
      </div>
      <div v-if="narrow" class="cal-dots" @click.stop="count(d) && emit('list', d, '')">
        <i v-for="x in dots(d)" :key="x.id" :class="'ev-' + FAMILY[x.kind]"></i>
        <b v-if="count(d) > 5">+{{ count(d) - 5 }}</b>
      </div>
      <div v-else class="cal-cell-body">
        <EventChip v-for="x in plans[iso(d)].top" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
        <button v-if="plans[iso(d)].deadlines.length" type="button" class="ev-agg" @click.stop="emit('list', d, 'deadline')">
          <Icon name="clock" /><span>{{ $t('calendar.deadlines', { n: plans[iso(d)].deadlines.length }, plans[iso(d)].deadlines.length) }}</span>
        </button>
        <EventChip v-for="x in plans[iso(d)].rest" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
        <button v-if="plans[iso(d)].more" type="button" class="ev-more" @click.stop="emit('list', d, '')">
          <span>{{ $t('calendar.more', { n: plans[iso(d)].more }, plans[iso(d)].more) }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

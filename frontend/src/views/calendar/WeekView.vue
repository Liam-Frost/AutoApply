<script setup>
// The week - scheduling: which hours are taken. Three bands in one scroll, so the seven columns stay lined up: the
// days, the whole-day strip (whole-day items, and the deadlines - a deadline is a point a day ends with, not time
// taken, so the many 23:59s are counted there and never stack up at the bottom of the hours), and the hours, where
// what has a time sits from its start, side by side with what it meets (calendar.js lanes). A click on an empty hour
// starts a new item at that time.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'
import EventChip from './EventChip.vue'
import { dayKey, iso, lanes, minuteOf, plan, timed } from '../../calendar'
import { tag } from '../../i18n/catalog'
import { clockOf } from '../../i18n/format'
import { longDate } from './look'

const props = defineProps({ days: { type: Array, required: true }, selected: { type: Date, required: true }, items: { type: Array, required: true },
  now: { type: Date, required: true }, openId: { type: String, default: '' } })
const emit = defineEmits(['open', 'list', 'create', 'day'])

const H = 48                // the height of an hour (style.css --hour)
const LEAST = 60            // how tall an item with no end is drawn, in minutes
const byDay = computed(() => {
  const m = new Map()
  for (const x of props.items) { const k = dayKey(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x) }
  return m
})
const of = (d) => byDay.value.get(iso(d)) || []
const strips = computed(() => props.days.map((d) => plan(of(d).filter((x) => !timed(x)), 3, props.now)))
const blocks = computed(() => props.days.map((d) => lanes(of(d).filter(timed), LEAST)))
const hours = Array.from({ length: 23 }, (_, i) => i + 1)
const at = (h) => clockOf(new Date(2000, 0, 1, h))
const isToday = (d) => iso(d) === iso(props.now)
const weekend = (d) => d.getDay() === 0 || d.getDay() === 6
const nowTop = computed(() => (props.now.getHours() * 60 + props.now.getMinutes()) * H / 60)
// a lane too narrow for words (three things at once on a small screen): its time only; the rest is in its tooltip
const colWidth = ref(160)
const tiny = (b) => colWidth.value / b.cols < 64
const box = (b) => ({ top: `${b.top * H / 60}px`, height: `${b.height * H / 60 - 2}px`, left: `calc(${(b.col / b.cols) * 100}% + 2px)`, width: `calc(${100 / b.cols}% - 4px)` })
const head = (d) => new Intl.DateTimeFormat(tag(), { weekday: 'short' }).format(d)

// Where the hours open: 08:00, or earlier when something is earlier; on this week, so that now is in view.
const scroller = ref(null)
const top = ref(null)
function place() {
  const el = scroller.value
  if (!el) return
  const minutes = props.days.flatMap((d) => of(d).filter(timed).map(minuteOf))
  const seen = Math.max(4, (el.clientHeight - (top.value ? top.value.offsetHeight : 0)) / H)
  let start = Math.min(8, minutes.length ? Math.floor(Math.min(...minutes) / 60) : 8)
  if (props.days.some(isToday)) { const h = props.now.getHours(); if (h + 1 > start + seen) start = Math.max(0, h + 2 - seen) }
  el.scrollTop = Math.max(0, start * H - 10)       // (the hour's label in view under the days)
}
let sizes = null
onMounted(() => {
  nextTick(place)
  sizes = new ResizeObserver(() => { if (scroller.value) colWidth.value = (scroller.value.clientWidth - 56) / 7 })
  sizes.observe(scroller.value)
})
onBeforeUnmount(() => { if (sizes) sizes.disconnect() })
watch(() => iso(props.days[0]), () => nextTick(place))

// an empty hour: where the pointer is, a new item on the half hour
const hover = ref(null)
const slot = (e) => { const r = e.currentTarget.getBoundingClientRect(); return Math.max(0, Math.min(1410, Math.floor(((e.clientY - r.top) / H) * 2) * 30)) }
const onMove = (d, e) => { if (e.target === e.currentTarget) hover.value = { day: iso(d), minute: slot(e) }; else hover.value = null }
const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`     // (the form's value)
const shown = (m) => clockOf(new Date(2000, 0, 1, Math.floor(m / 60), m % 60))
const onPick = (d, e) => { if (e.target === e.currentTarget) emit('create', d, hhmm(slot(e))) }
</script>

<template>
  <div ref="scroller" class="cal-week">
    <div class="cal-week-in">
      <div ref="top" class="cal-week-top">
        <div class="cal-wrow">
          <div class="cal-gut"></div>
          <button v-for="d in days" :key="iso(d)" type="button" class="cal-wh" :class="{ today: isToday(d), sel: iso(d) === iso(selected) }" :aria-label="longDate(d)" v-tip="$t('calendar.openDay')" @click="emit('day', d)">
            <span class="wd">{{ head(d) }}</span><span class="num">{{ d.getDate() }}</span>
          </button>
        </div>
        <div class="cal-wrow">
          <div class="cal-gut cal-strip-gut">{{ $t('calendar.allDay') }}</div>
          <div v-for="(d, i) in days" :key="iso(d)" class="cal-strip">
            <EventChip v-for="x in strips[i].top" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
            <button v-if="strips[i].deadlines.length" type="button" class="ev-agg" @click="emit('list', d, 'deadline')">
              <Icon name="clock" /><span>{{ $t('calendar.deadlines', { n: strips[i].deadlines.length }, strips[i].deadlines.length) }}</span>
            </button>
            <EventChip v-for="x in strips[i].rest" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
            <button v-if="strips[i].more" type="button" class="ev-more" @click="emit('list', d, '')"><span>{{ $t('calendar.more', { n: strips[i].more }, strips[i].more) }}</span></button>
          </div>
        </div>
      </div>
      <div class="cal-tgrid">
        <div class="cal-gut cal-hours" aria-hidden="true"><span v-for="h in hours" :key="h" :style="{ top: `${h * H}px` }">{{ at(h) }}</span></div>
        <div v-for="(d, i) in days" :key="iso(d)" class="cal-col" :class="{ today: isToday(d), weekend: weekend(d) }"
             :aria-label="longDate(d)" @click="onPick(d, $event)" @mousemove="onMove(d, $event)" @mouseleave="hover = null">
          <div v-if="hover && hover.day === iso(d)" class="cal-ghost" :style="{ top: `${hover.minute * H / 60 + 1}px`, height: `${H / 2 - 2}px` }">+ {{ shown(hover.minute) }}</div>
          <EventChip v-for="b in blocks[i]" :key="b.item.id" :item="b.item" :now="now" variant="block" :short="b.height * H / 60 < 40" :tiny="tiny(b)" :selected="b.item.id === openId"
                     :style="box(b)" @open="emit('open', $event)" />
          <div v-if="isToday(d)" class="cal-now" :style="{ top: `${nowTop}px` }" v-tip="clockOf(now)"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Stacked columns over time. buckets: [{ key, label, values: { seriesKey: number } }], series: [{ key, label, color }].
// One axis, one unit. A legend that also filters (click a series to leave it out), a tooltip with every part and the
// total, a value only on the tallest column. The chart has its own height and never grows: the numbers behind it are
// shown by the page in a detail panel (SeriesTable), not appended here.
import { computed, ref } from 'vue'

const props = defineProps({
  buckets: { type: Array, required: true },
  series: { type: Array, required: true },
  format: { type: Function, default: (v) => String(v) },
  height: { type: Number, default: 170 },
})
const off = ref(new Set())
const tip = ref(null)
const shown = computed(() => props.series.filter((s) => !off.value.has(s.key)))
const sum = (b) => shown.value.reduce((a, s) => a + (b.values[s.key] || 0), 0)
const max = computed(() => Math.max(0, ...props.buckets.map(sum)))
// a round number at or above the tallest column: 1, 2 or 5 times a power of ten
const top = computed(() => {
  const m = max.value
  if (m <= 0) return 1
  const p = Math.pow(10, Math.floor(Math.log10(m)))
  return [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((k) => k * p).find((v) => v >= m * 0.999)
})
const iMax = computed(() => props.buckets.reduce((b, d, i) => (sum(d) > sum(props.buckets[b]) ? i : b), 0))
const every = computed(() => Math.ceil(props.buckets.length / 8))
function toggle(k) {
  const s = new Set(off.value)
  if (s.has(k)) s.delete(k)
  else if (s.size < props.series.length - 1) s.add(k)      // the last one stays: an empty chart says nothing
  off.value = s
}
const tipSide = (i) => (i < props.buckets.length / 2 ? { left: '0', transform: 'none' } : { right: '0', left: 'auto', transform: 'none' })
</script>

<template>
  <div class="chart stack">
    <div class="plot" :style="{ height: height + 'px' }">
      <div v-for="t in [top, top / 2]" :key="t" class="gridline" :style="{ bottom: (t / top) * 100 + '%' }"><span>{{ format(t) }}</span></div>
      <div v-for="(b, i) in buckets" :key="b.key" class="col" @mouseenter="tip = i" @mouseleave="tip = null">
        <span v-if="i === iMax && sum(b) > 0" class="val">{{ format(sum(b)) }}</span>
        <div class="stackcol" :style="{ height: (sum(b) / top) * 100 + '%' }">
          <i v-for="s in shown.filter((x) => b.values[x.key] > 0)" :key="s.key" :style="{ flex: b.values[s.key] + ' 0 0', background: s.color }"></i>
        </div>
        <div v-if="tip === i" class="tip multi" :style="{ bottom: 'calc(' + (sum(b) / top) * 100 + '% + 10px)', top: 'auto', ...tipSide(i) }">
          <div class="h">{{ b.tip || b.label }}</div>
          <div v-for="s in shown.filter((x) => b.values[x.key] > 0)" :key="s.key" class="r"><span><i :style="{ background: s.color }"></i>{{ s.label }}</span><span>{{ format(b.values[s.key]) }}</span></div>
          <div v-if="shown.length > 1" class="r" style="margin-top: 2px; font-weight: 650"><span>{{ $t('common.chart.total') }}</span><span>{{ format(sum(b)) }}</span></div>
          <div v-if="b.note" style="opacity: 0.8">{{ b.note }}</div>
        </div>
      </div>
    </div>
    <div class="xaxis"><span v-for="(b, i) in buckets" :key="b.key">{{ i % every === 0 || (i === buckets.length - 1 && i % every >= every / 2) ? b.label : '' }}</span></div>
    <div v-if="series.length > 1" class="legend">
      <button v-for="s in series" :key="s.key" type="button" :class="{ off: off.has(s.key) }" :title="$t('common.chart.toggle')" @click="toggle(s.key)"><i :style="{ background: s.color }"></i>{{ s.label }}</button>
    </div>
  </div>
</template>

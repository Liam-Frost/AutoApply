<script setup>
import { t as T } from '../i18n/catalog'
// Single-series column chart. data: [{ label, value, tip }]. One hue, baseline-anchored columns (max 24px),
// hairline grid, a value only on the tallest and the last column, tooltip on hover, table view underneath.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  data: { type: Array, required: true },
  height: { type: Number, default: 150 },
  unit: { type: String, default: '' },
  tableLabel: { type: String, default: () => T('common.chart.item') },
  table: { type: Boolean, default: true },     // the "as a table" fold-out underneath; off where the page offers its own table view
})
const max = computed(() => Math.max(1, ...props.data.map((d) => d.value)))
const top = computed(() => { const m = max.value; const step = m <= 5 ? 1 : m <= 10 ? 2 : m <= 30 ? 5 : m <= 60 ? 10 : 20; return Math.ceil(m / step) * step })
const ticks = computed(() => [top.value, top.value / 2].filter((t) => Number.isInteger(t)))
const iMax = computed(() => props.data.reduce((b, d, i) => (d.value > props.data[b].value ? i : b), 0))
const labelled = (i) => props.data[i].value > 0 && (i === iMax.value || i === props.data.length - 1)
const tip = ref(null)
// The axis names as many steps as there is room for - all of them when they fit, else every second, third ... - by the
// width the chart really has (it was "six labels, whatever the width": a month of days in a wide card named six).
const plot = ref(null)
const width = ref(0)
let seen = null
onMounted(() => {
  if (!plot.value) return
  width.value = plot.value.clientWidth
  if (typeof ResizeObserver !== 'undefined') { seen = new ResizeObserver(() => { width.value = plot.value ? plot.value.clientWidth : 0 }); seen.observe(plot.value) }
})
onBeforeUnmount(() => { if (seen) seen.disconnect() })
const every = computed(() => {
  const n = props.data.length
  if (!n) return 1
  const widest = Math.max(...props.data.map((d) => String(d.label || '').length))
  const need = widest * 6.4 + 12                      // (px for one label at the axis' size, with air between two)
  const room = (width.value || 600) / n               // what one step has
  return Math.max(1, Math.ceil(need / room))
})
</script>

<template>
  <div class="chart">
    <div ref="plot" class="plot" :style="{ height: height + 'px' }">
      <div v-for="t in ticks" :key="t" class="gridline" :style="{ bottom: (t / top) * 100 + '%' }"><span>{{ t }}</span></div>
      <div v-for="(d, i) in data" :key="i" class="col" @mouseenter="tip = i" @mouseleave="tip = null">
        <span v-if="labelled(i)" class="val">{{ d.value }}</span>
        <div class="bar" :style="{ height: (d.value / top) * 100 + '%' }"></div>
        <div v-if="tip === i" class="tip" :style="{ left: '50%', bottom: 'calc(' + (d.value / top) * 100 + '% + 22px)', top: 'auto', transform: 'translateX(-50%)' }">{{ $t('common.chart.pair', { label: d.tip || d.label, value: unit ? d.value + ' ' + unit : d.value }) }}</div>
      </div>
    </div>
    <div class="xaxis"><span v-for="(d, i) in data" :key="i">{{ i % every === 0 ? d.label : '' }}</span></div>
    <details v-if="table" class="tech">
      <summary>{{ $t('common.chart.asTable') }}</summary>
      <table class="an-table"><colgroup><col /><col class="w-wide" /></colgroup><thead><tr><th v-tip.overflow>{{ tableLabel }}</th><th v-tip.overflow class="num">{{ $t('common.chart.count') }}</th></tr></thead>
        <tbody><tr v-for="(d, i) in data" :key="i"><td class="atomic">{{ d.tip || d.label }}</td><td class="num">{{ unit ? d.value + ' ' + unit : d.value }}</td></tr></tbody></table>
    </details>
  </div>
</template>

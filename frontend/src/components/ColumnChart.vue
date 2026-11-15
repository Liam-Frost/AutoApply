<script setup>
// Single-series column chart. data: [{ label, value, tip }]. One hue, baseline-anchored columns (max 24px),
// hairline grid, a value only on the tallest and the last column, tooltip on hover, table view underneath.
import { computed, ref } from 'vue'

const props = defineProps({
  data: { type: Array, required: true },
  height: { type: Number, default: 150 },
  unit: { type: String, default: '' },
  tableLabel: { type: String, default: '项目' },
  table: { type: Boolean, default: true },     // the "as a table" fold-out underneath; off where the page offers its own table view
})
const max = computed(() => Math.max(1, ...props.data.map((d) => d.value)))
const top = computed(() => { const m = max.value; const step = m <= 5 ? 1 : m <= 10 ? 2 : m <= 30 ? 5 : m <= 60 ? 10 : 20; return Math.ceil(m / step) * step })
const ticks = computed(() => [top.value, top.value / 2].filter((t) => Number.isInteger(t)))
const iMax = computed(() => props.data.reduce((b, d, i) => (d.value > props.data[b].value ? i : b), 0))
const labelled = (i) => props.data[i].value > 0 && (i === iMax.value || i === props.data.length - 1)
const tip = ref(null)
const every = computed(() => Math.ceil(props.data.length / 6))
</script>

<template>
  <div class="chart">
    <div class="plot" :style="{ height: height + 'px' }">
      <div v-for="t in ticks" :key="t" class="gridline" :style="{ bottom: (t / top) * 100 + '%' }"><span>{{ t }}</span></div>
      <div v-for="(d, i) in data" :key="i" class="col" @mouseenter="tip = i" @mouseleave="tip = null">
        <span v-if="labelled(i)" class="val">{{ d.value }}</span>
        <div class="bar" :style="{ height: (d.value / top) * 100 + '%' }"></div>
        <div v-if="tip === i" class="tip" :style="{ left: '50%', bottom: 'calc(' + (d.value / top) * 100 + '% + 22px)', top: 'auto', transform: 'translateX(-50%)' }">{{ d.tip || d.label }}：{{ d.value }}{{ unit }}</div>
      </div>
    </div>
    <div class="xaxis"><span v-for="(d, i) in data" :key="i">{{ i % every === 0 || i === data.length - 1 ? d.label : '' }}</span></div>
    <details v-if="table" class="tech">
      <summary>用表格看</summary>
      <table style="margin-top: 6px"><thead><tr><th>{{ tableLabel }}</th><th>数量</th></tr></thead>
        <tbody><tr v-for="(d, i) in data" :key="i"><td>{{ d.tip || d.label }}</td><td>{{ d.value }}{{ unit }}</td></tr></tbody></table>
    </details>
  </div>
</template>

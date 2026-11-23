<script setup>
// One bar divided into parts that add up to a whole, with its legend. parts: [{ key, label, value, color }].
// The legend is always there (identity is never colour alone) and carries the figures; zero parts are listed, not drawn.
import { computed } from 'vue'

const props = defineProps({
  parts: { type: Array, required: true },
  format: { type: Function, default: (v) => String(v) },
  legend: { type: Boolean, default: true },
  rows: { type: Boolean, default: false },      // legend as a grid of rows instead of a wrapped line
  single: { type: Boolean, default: false },    // ... in one column (a narrow card, or long names)
  share: { type: Boolean, default: true },      // show each part's share of the whole in the legend
})
const total = computed(() => props.parts.reduce((a, p) => a + (p.value || 0), 0))
const drawn = computed(() => props.parts.filter((p) => p.value > 0))
const pc = (v) => (total.value ? Math.round((v / total.value) * 100) : 0)
</script>

<template>
  <div>
    <div class="splitbar" :class="{ none: !total }">
      <i v-for="p in drawn" :key="p.key" v-tip="$t('common.chart.part', { label: p.label, value: format(p.value), pc: pc(p.value) })" :style="{ flex: p.value + ' 0 0', background: p.color }"></i>
    </div>
    <div v-if="legend" class="legend" :class="{ rows: rows || single, single }">
      <span v-for="p in parts" :key="p.key"><i :style="{ background: p.color }"></i><span v-tip.overflow class="cut">{{ p.label }}</span> <b>{{ format(p.value) }}</b><template v-if="share && total && p.value"> · {{ pc(p.value) }}%</template></span>
    </div>
  </div>
</template>

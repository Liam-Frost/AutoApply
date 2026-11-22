<script setup>
import { t as T } from '../i18n/catalog'
// The numbers behind a chart over time, a page at a time, newest first. Same props as the chart (buckets, series,
// format), so the table always shows what the chart shows - same range, same grouping, same filters.
// A compact figure table: the date column is fixed, the series share the rest in equal columns, and a long series
// name is cut in its header (the whole name on hover) - it cannot move a figure.
import { computed, ref, watch } from 'vue'
import Pager from './Pager.vue'
import Trunc from './Trunc.vue'

const props = defineProps({
  buckets: { type: Array, required: true },
  series: { type: Array, required: true },
  format: { type: Function, default: (v) => String(v) },
  tableLabel: { type: String, default: () => T('common.chart.date') },
  size: { type: Number, default: 12 },
})
const page = ref(0)
const rows = computed(() => [...props.buckets].reverse())
watch(() => [props.buckets, props.series], () => { page.value = 0 })      // other data: back to the first page
const shown = computed(() => rows.value.slice(page.value * props.size, (page.value + 1) * props.size))
const sum = (b) => props.series.reduce((a, s) => a + (b.values[s.key] || 0), 0)
// what the table needs before it scrolls in its own box: the date and 88px a figure
const min = computed(() => 132 + 88 * (props.series.length + (props.series.length > 1 ? 1 : 0)) + 'px')
</script>

<template>
  <div>
    <div class="an-scroll">
      <table class="an-table series" :style="{ '--min': min }">
        <colgroup><col class="w-date" /><col v-for="s in series" :key="s.key" /><col v-if="series.length > 1" /></colgroup>
        <thead><tr><th v-tip.overflow>{{ tableLabel }}</th><th v-for="s in series" :key="s.key" class="num"><Trunc :text="s.label" /></th><th v-if="series.length > 1" class="num">{{ $t('common.chart.total') }}</th></tr></thead>
        <tbody>
          <tr v-for="b in shown" :key="b.key">
            <td class="atomic">{{ b.tip || b.label }}</td>
            <td v-for="s in series" :key="s.key" class="num">{{ format(b.values[s.key] || 0) }}</td>
            <td v-if="series.length > 1" class="num sum">{{ format(sum(b)) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pager v-model:page="page" :size="size" :total="rows.length" />
  </div>
</template>

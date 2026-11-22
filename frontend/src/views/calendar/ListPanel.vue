<script setup>
// A list beside the calendar: a day's items (from its count on the grid), or what a number above the calendar counts.
// It lists exactly what was counted. A day's list leads to the day view; an item opens in its place, with a way back.
import { computed } from 'vue'
import Icon from '../../components/Icon.vue'
import AgendaRow from './AgendaRow.vue'
import { at, byRank, dayGroups, dayKey } from '../../calendar'
import { longDay } from './look'

const props = defineProps({ title: { type: String, required: true }, sub: { type: String, default: '' }, items: { type: Array, required: true }, now: { type: Date, required: true },
  day: { type: Date, default: null }, all: { type: Number, default: 0 }, openId: { type: String, default: '' } })
const emit = defineEmits(['open', 'close', 'day', 'all'])

// one day: by what it is (as the day view groups it); several days: by day
const groups = computed(() => {
  if (props.day) {
    const g = dayGroups(props.items, props.now)
    return [['calendar.timeline', g.timed], ['calendar.group.deadlines', g.deadlines], ['calendar.group.other', g.other], ['calendar.group.past', g.past]]
      .filter(([, l]) => l.length).map(([k, l]) => ({ key: k, label: k, items: l }))
  }
  const m = new Map()
  for (const x of props.items) { const k = dayKey(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x) }
  return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([k, l]) => ({ key: k, day: longDay(at(l[0])), items: l.slice().sort(byRank(props.now)) }))
})
</script>

<template>
  <div class="cal-pane">
    <div class="cal-pane-head">
      <div class="grow">
        <h3>{{ title }}</h3>
        <div v-if="sub" class="sub">{{ sub }}</div>
      </div>
      <button type="button" class="ghost close" :aria-label="$t('common.close')" @click="emit('close')"><Icon name="x" /></button>
    </div>
    <div v-if="day" class="cal-acts">
      <button type="button" class="sm" @click="emit('day', day)"><Icon name="calendar" />{{ $t('calendar.openDay') }}</button>
      <button v-if="all > items.length" type="button" class="sm ghost" @click="emit('all')">{{ $t('calendar.showAllDay', { n: all }) }}</button>
    </div>
    <div v-if="!items.length" class="cal-none">{{ $t('calendar.nothing') }}</div>
    <section v-for="g in groups" :key="g.key" class="cal-group">
      <h4>{{ g.day || $t(g.label) }} <span class="n">{{ g.items.length }}</span></h4>
      <AgendaRow v-for="x in g.items" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
    </section>
  </div>
</template>

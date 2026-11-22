<script setup>
// The day - doing: what to handle, by what it is. On today, first what is late from the days before; then what has a
// time; the deadlines, the ones to act on first; the other things to do; and, folded, what is done, past or a record.
// One list (the item opens beside it): no second list of the same things by the hour.
import { computed } from 'vue'
import Icon from '../../components/Icon.vue'
import AgendaRow from './AgendaRow.vue'
import { active, dayGroups, iso, RECORDS } from '../../calendar'
import { t } from '../../i18n/catalog'

const props = defineProps({ day: { type: Date, required: true }, items: { type: Array, required: true }, now: { type: Date, required: true },
  overdue: { type: Array, default: () => [] }, openId: { type: String, default: '' } })
const emit = defineEmits(['open', 'create'])

const g = computed(() => dayGroups(props.items, props.now))
const isToday = computed(() => iso(props.day) === iso(props.now))
const late = computed(() => (isToday.value ? props.overdue.filter((x) => x.start.slice(0, 10) < iso(props.day)) : []))
// "12 application deadlines · 1 interview": what the day holds, counted as the groups below count it
const counts = computed(() => {
  const n = (f) => props.items.filter(f).length
  const parts = [['deadline', n((x) => x.kind === 'deadline')], ['interview', n((x) => x.kind === 'interview')], ['assessment', n((x) => x.kind === 'assessment')],
    ['todo', n((x) => !['deadline', 'interview', 'assessment', ...RECORDS].includes(x.kind) && active(x, props.now))]]      // (to do: not what is done)
  return parts.filter(([, c]) => c).map(([k, c]) => (k === 'deadline' ? t('calendar.deadlines', { n: c }, c) : t('calendar.count.' + k, { n: c }, c))).join(t('calendar.sep'))
})
</script>

<template>
  <div class="cal-day">
    <div class="cal-day-sum">{{ counts || $t('calendar.nothing') }}</div>

    <section v-if="late.length" class="cal-group late">
      <h4>{{ $t('calendar.group.overdue') }} <span class="n">{{ late.length }}</span></h4>
      <AgendaRow v-for="x in late" :key="x.id" :item="x" :now="now" with-day :selected="x.id === openId" @open="emit('open', $event)" />
    </section>

    <section v-if="items.length || late.length" class="cal-group">
      <h4>{{ $t('calendar.timeline') }} <span v-if="g.timed.length" class="n">{{ g.timed.length }}</span></h4>
      <AgendaRow v-for="x in g.timed" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
      <div v-if="!g.timed.length" class="cal-none">{{ $t('calendar.nothingTimed') }}</div>
    </section>

    <section v-if="g.deadlines.length" class="cal-group">
      <h4>{{ $t('calendar.group.deadlines') }} <span class="n">{{ g.deadlines.length }}</span></h4>
      <AgendaRow v-for="x in g.deadlines" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
    </section>

    <section v-if="g.other.length" class="cal-group">
      <h4>{{ $t('calendar.group.other') }} <span class="n">{{ g.other.length }}</span></h4>
      <AgendaRow v-for="x in g.other" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
    </section>

    <details v-if="g.past.length" class="cal-group">
      <summary>{{ $t('calendar.group.past') }} <span class="n">{{ g.past.length }}</span></summary>
      <AgendaRow v-for="x in g.past" :key="x.id" :item="x" :now="now" :selected="x.id === openId" @open="emit('open', $event)" />
    </details>

    <div v-if="!items.length && !late.length" class="cal-group">
      <button type="button" class="sm" @click="emit('create', day)"><Icon name="plus" />{{ $t('calendar.add') }}</button>
    </div>
  </div>
</template>

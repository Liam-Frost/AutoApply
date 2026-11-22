<script setup>
// One item in a list (the day's agenda, a list in the panel): the name, the company or the kind under it, what says
// where it stands, and its time. The whole row opens it - no button of its own on every row.
import { computed } from 'vue'
import Icon from '../../components/Icon.vue'
import { at, status } from '../../calendar'
import { t } from '../../i18n/catalog'
import { dayOf } from '../../i18n/format'
import { companyOf, family, fullName, GLYPH, kindName, scoreOf, statusName, statusTone, timeOf, titleOf } from './look'

const props = defineProps({ item: { type: Object, required: true }, now: { type: Date, required: true }, selected: Boolean, withDay: Boolean })
const emit = defineEmits(['open'])
const st = computed(() => status(props.item, props.now))
const x = computed(() => props.item)
// what says where it stands, when it is not simply open: late, done, applied, closed (an interview to come says nothing)
const badge = computed(() => (['overdue', 'done', 'applied', 'closed'].includes(st.value) ? statusName(x.value, props.now) : ''))
const when = computed(() => (props.withDay ? t('time.dayAt', { day: dayOf(at(x.value)), time: timeOf(x.value) }) : timeOf(x.value)))
</script>

<template>
  <button type="button" class="ev-row" :class="[family(x), 'st-' + st, { sel: selected }]" :aria-pressed="selected" :title="fullName(x)" @click="emit('open', x)">
    <span class="ev-mark" aria-hidden="true"></span>
    <span class="ev-row-main">
      <span class="ev-row-title">{{ titleOf(x) }}</span>
      <span class="ev-row-sub">
        <Icon :name="GLYPH[x.kind] || 'info'" />
        <span v-if="x.kind !== 'deadline'" class="kind">{{ kindName(x) }}</span>
        <span v-if="companyOf(x)">{{ companyOf(x) }}</span>
      </span>
    </span>
    <span class="ev-row-meta">
      <Icon v-if="x.priority" name="star" class="star" :aria-label="$t('calendar.priorityEmployer')" />
      <span v-if="x.kind === 'deadline' && scoreOf(x)" class="score">{{ scoreOf(x) }}</span>
      <span v-if="badge" class="tag" :class="statusTone(st)">{{ badge }}</span>
      <span class="ev-row-time">{{ when }}</span>
    </span>
  </button>
</template>

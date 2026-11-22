<script setup>
// One item where room is short: a line on the month grid and in the week's whole-day strip ("line"), a block on the
// week's time grid ("block", placed by the week). Its kind is its colour and its glyph; where it stands is said by a
// line through, weaker text and, when it is late, a red point; the whole of it is in its tooltip and in the panel.
import { computed } from 'vue'
import Icon from '../../components/Icon.vue'
import { at, ownTime, status } from '../../calendar'
import { clockOf } from '../../i18n/format'
import { family, fullName, GLYPH, shortName, titleOf } from './look'

const props = defineProps({ item: { type: Object, required: true }, now: { type: Date, required: true }, variant: { type: String, default: 'line' },
  selected: Boolean, short: Boolean, tiny: Boolean, hideTime: Boolean })
const emit = defineEmits(['open'])
const st = computed(() => status(props.item, props.now))
// (a deadline's time is said when it is not the end of the day: the 23:59 most sources give says nothing)
const time = computed(() => (props.item.all_day || props.hideTime || (props.item.kind === 'deadline' && !ownTime(props.item)) ? '' : clockOf(at(props.item))))
</script>

<template>
  <button type="button" class="ev" :class="[family(item), 'st-' + st, { timed: variant === 'block', short, sel: selected }]" :title="fullName(item)"
          :aria-label="fullName(item)" :aria-pressed="selected" @click.stop="emit('open', item)">
    <template v-if="variant === 'block'">
      <span class="ev-time">{{ time }}</span>
      <template v-if="!tiny">
        <span class="ev-text">{{ shortName(item) }}</span>
        <span v-if="item.company && item.title !== item.company" class="ev-sub">{{ titleOf(item) }}</span>
      </template>
    </template>
    <template v-else>
      <Icon :name="GLYPH[item.kind] || 'info'" class="ev-ic" />
      <span v-if="st === 'overdue'" class="ev-late"></span>
      <span v-if="time" class="ev-time">{{ time }}</span>
      <span class="ev-text">{{ shortName(item) }}</span>
    </template>
  </button>
</template>

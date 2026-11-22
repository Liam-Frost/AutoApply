<script setup>
// Help behind a small (i), whatever its length. A sentence is the program's tooltip (InfoTip); what a tooltip does not
// hold - several sentences, or content given in the slot (a list, a link) - opens in a popover from the same (i). The
// page only says what the help is; which of the two it becomes is decided here, by one rule.
import { computed, useSlots } from 'vue'
import Icon from './Icon.vue'
import InfoTip from './InfoTip.vue'
import Popover from './Popover.vue'

const props = defineProps({
  text: { type: String, default: '' },
  label: { type: String, default: '' },      // what the help is about: the popover's name
  width: { type: Number, default: 340 },
  placement: { type: String, default: 'bottom' },
})
const slots = useSlots()
// What a tooltip holds: about three lines of its box. A full-width character takes the room of two.
const LIMIT = 160
const weight = (s) => { let n = 0; for (const ch of s) n += ch.codePointAt(0) > 0x2e7f ? 2 : 1; return n }
const long = computed(() => !!slots.default || weight(props.text) > LIMIT)
</script>

<template>
  <Popover v-if="long" :label="label || $t('common.moreInfo')" :width="width" :placement="placement">
    <template #trigger="{ toggle, attrs }">
      <button type="button" class="info-tip" v-bind="attrs" :aria-label="$t('common.moreInfo')" @click.stop="toggle"><Icon name="info" /></button>
    </template>
    <div class="help-pop"><slot><p>{{ text }}</p></slot></div>
  </Popover>
  <InfoTip v-else-if="text" :text="text" />
</template>

<script>
let counter = 0      // ids for the label / description pairing: unique on the page, nothing more
</script>

<script setup>
// One setting as a row (docs/component-guidelines.md, "SettingRow"): what it is on the left - its name, an (i) when it
// needs one, and a muted line on what it does under the name - and the control on the right. The two stand on one
// baseline (the name beside the first line of the control, a select or the first radio alike); in a box under 640px
// they stack, the name above the control. The row draws nothing of its own: no box, no border.
//
//   <SettingRow :label="$t('…')" for="u-channel"><AaSelect id="u-channel" … /></SettingRow>
//   <SettingRow :label="$t('…')" :description="$t('…')" v-slot="{ labelId, descId }">
//     <RadioList hide-label :aria-labelledby="labelId" :aria-describedby="descId" … />      (a group names itself by the label's id)
//   </SettingRow>
import { computed, useSlots } from 'vue'
import HelpPop from './HelpPop.vue'

const props = defineProps({
  label: { type: String, required: true },          // the setting's name
  for: { type: String, default: '' },               // the id of the control it names: the name is then its <label>
  help: { type: String, default: '' },              // behind an (i) beside the name (HelpPop: a sentence, or a popover)
  description: { type: String, default: '' },       // one muted line under the name (or the slot "description")
})
const slots = useSlots()
const uid = 'sr' + ++counter
const labelId = uid + '-l'
const descId = computed(() => (props.description || slots.description ? uid + '-d' : undefined))
</script>

<template>
  <div class="setting-row">
    <div class="sr-in">
      <div class="sr-label">
        <span class="sr-head">
          <label v-if="$props.for" :id="labelId" :for="$props.for" class="sr-name">{{ label }}</label>
          <span v-else :id="labelId" class="sr-name">{{ label }}</span>
          <HelpPop v-if="help" :text="help" :label="label" />
        </span>
        <p v-if="descId" :id="descId" class="sr-desc"><slot name="description">{{ description }}</slot></p>
      </div>
      <div class="sr-control"><slot :label-id="labelId" :desc-id="descId" /></div>
    </div>
  </div>
</template>

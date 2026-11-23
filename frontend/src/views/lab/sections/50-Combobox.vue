<script setup>
// Lab: the searchable select - groups, hints and keywords, a value that is not among the options, invalid, disabled,
// six hundred options, and one inside a popover. Every value is made up.
import { ref } from 'vue'
import Combobox from '../../../components/Combobox.vue'
import Popover from '../../../components/Popover.vue'

const GROUPS = [{ id: 'fruit', label: 'Fruit' }, { id: 'veg', label: 'Vegetables' }]
const FOOD = [
  { value: '', label: 'Anything', hint: 'no preference' },
  { value: 'apple', label: 'Apple', hint: 'Malus domestica', group: 'fruit', keywords: ['pomme'] },
  { value: 'apricot', label: 'Apricot', group: 'fruit' },
  { value: 'cherry', label: 'Cherry', hint: 'out of season', group: 'fruit', disabled: true },
  { value: 'creme', label: 'Crème de marrons', hint: 'chestnut spread', group: 'fruit' },
  { value: 'pineapple', label: 'Pineapple', group: 'fruit' },
  { value: 'carrot', label: 'Carrot', group: 'veg' },
  { value: 'celeriac', label: 'Celeriac', hint: 'celery root', group: 'veg', keywords: ['celery'] },
  { value: 'apple', label: 'Apple', hint: 'Malus domestica', group: 'veg' },
]
const food = ref('apple')
const odd = ref('durian')           // not among the options: shown as itself
const bad = ref('kale')
const none = ref('')
const MANY = Array.from({ length: 600 }, (_, i) => ({ value: 'r' + i, label: 'Row ' + (i + 1), hint: 'group ' + ((i % 6) + 1), group: 'g' + (i % 6) }))
const MANY_GROUPS = Array.from({ length: 6 }, (_, i) => ({ id: 'g' + i, label: 'Group ' + (i + 1) }))
const many = ref('r321')
const inPop = ref('carrot')
</script>

<template>
  <p class="lab-note">Press it, or ArrowDown / Enter / a letter on it: the search field has the focus. Arrows, Home / End, Page keys move the mark; Enter picks; Escape closes without a change; Tab closes and moves on. Chosen: <b data-t="cb-food">{{ food === '' ? '(empty)' : food }}</b></p>
  <div class="lab-row" data-t="cb-row">
    <div style="width: 300px"><Combobox id="lab-cb-food" v-model="food" :options="FOOD" :groups="GROUPS" label="Lab: food" style="width: 100%" data-t="cb-food-trigger" /></div>
    <div style="width: 220px"><Combobox v-model="odd" :options="FOOD" :groups="GROUPS" label="Lab: a value not among the options" style="width: 100%" /></div>
    <div style="width: 220px"><Combobox v-model="bad" :options="FOOD" :groups="GROUPS" label="Lab: invalid" invalid style="width: 100%" /></div>
    <div style="width: 220px"><Combobox v-model="none" :options="FOOD.slice(1)" :groups="GROUPS" label="Lab: nothing chosen" placeholder="Choose a food" style="width: 100%" /></div>
    <div style="width: 180px"><Combobox v-model="food" :options="FOOD" :groups="GROUPS" label="Lab: disabled" disabled style="width: 100%" /></div>
  </div>

  <p class="lab-note">Six hundred options in six groups (the list is drawn when it opens; the search narrows it as you type). Chosen: <b data-t="cb-many">{{ many }}</b></p>
  <div class="lab-row"><div style="width: 260px"><Combobox id="lab-cb-many" v-model="many" :options="MANY" :groups="MANY_GROUPS" label="Lab: six hundred rows" :width="360" style="width: 100%" /></div></div>

  <p class="lab-note">Inside a popover: its list lies over the popover, and a press in it does not close the popover.</p>
  <div class="lab-row">
    <Popover label="Lab: a form with a combobox" :width="320">
      <template #trigger="{ toggle, attrs }"><button class="sm" v-bind="attrs" data-t="cb-pop-btn" @click="toggle">Open a form</button></template>
      <div class="field"><label for="lab-cb-pop">Vegetable</label><Combobox id="lab-cb-pop" v-model="inPop" :options="FOOD" :groups="GROUPS" label="Vegetable" style="width: 100%" /></div>
      <p class="t-meta">Chosen: {{ inPop }}</p>
    </Popover>
  </div>
</template>

<script setup>
// Lab: the compact list of radios - hints beside the words while there is room and under them in a narrow box, an
// option that cannot be chosen, a whole list disabled, a legend for a screen reader only. The update modes are the
// program's own words; the rest is made up.
import { computed, ref } from 'vue'
import { t as T } from '../../../i18n/catalog'
import RadioList from '../../../components/RadioList.vue'

const mode = ref('notify')
const MODES = computed(() => ['off', 'notify', 'download', 'auto'].map((value) => ({ value, label: T('about.mode.' + value), hint: T('about.mode.' + value + 'How') })))
const size = ref('m')
const SIZES = [{ value: 's', label: 'Small' }, { value: 'm', label: 'Medium', hint: 'The usual one' }, { value: 'l', label: 'Large', hint: 'Not for this box', disabled: true }]
const plain = ref(2)
const PLAIN = [{ value: 1, label: 'One' }, { value: 2, label: 'Two' }, { value: 3, label: 'Three' }]
</script>

<template>
  <p class="lab-note">Native radios: Tab comes to the chosen one, the arrows move and choose. Chosen: <b data-t="rl-mode">{{ mode }}</b></p>
  <div class="lab-box" data-rl="wide" style="max-width: 760px; margin-bottom: 12px"><RadioList v-model="mode" name="lab-rl-mode" :label="$t('about.byItself')" :options="MODES" /></div>

  <p class="lab-note">The same in a box of 320px: a hint that does not fit beside its words goes under them</p>
  <div class="lab-box" data-rl="narrow" style="width: 320px; max-width: 100%; margin-bottom: 12px"><RadioList v-model="mode" name="lab-rl-narrow" :label="$t('about.byItself')" :options="MODES" /></div>

  <p class="lab-note">An option that cannot be chosen ("Large"); numbers as values; a whole list disabled; a legend for a screen reader only. Chosen: <b data-t="rl-size">{{ size }}</b> · <b>{{ plain }}</b></p>
  <div class="lab-row" style="align-items: flex-start">
    <div class="lab-box" data-rl="disabled-option" style="width: 260px"><RadioList v-model="size" name="lab-rl-size" label="Size" :options="SIZES" /></div>
    <div class="lab-box" data-rl="numbers" style="width: 200px"><RadioList v-model="plain" label="Count" :options="PLAIN" /></div>
    <div class="lab-box" data-rl="disabled" style="width: 200px"><RadioList v-model="plain" label="Count (disabled)" :options="PLAIN" disabled /></div>
    <div class="lab-box" data-rl="hidden-legend" style="width: 200px"><RadioList v-model="plain" label="Count, legend hidden" :options="PLAIN" hide-label /></div>
  </div>
</template>

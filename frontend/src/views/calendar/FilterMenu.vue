<script setup>
// The full filter, behind one button: every kind one by one (the same kinds the quick filters set in groups), what
// the application is, and what is shown. The button counts the conditions set beyond the quick filters. The
// filters are the page's (in its address): the three views share them.
import { onBeforeUnmount, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'
import { FAMILY, KINDS, RECORDS } from '../../calendar'

const props = defineProps({ kinds: { type: Array, required: true }, f: { type: Object, required: true }, summary: Boolean, count: { type: Number, default: 0 }, dirty: Boolean })
const emit = defineEmits(['kinds', 'set', 'reset', 'summary'])
const STATES = ['unapplied', 'in_progress', 'sent', 'progressed']
const MAIN = KINDS.filter((k) => !RECORDS.includes(k))

const open = ref(false)
const wrap = ref(null)
const company = ref(props.f.company)
const min = ref(props.f.min || '')
watch(() => props.f, (v) => { company.value = v.company; min.value = v.min || '' })
const toggle = (k) => emit('kinds', props.kinds.includes(k) ? props.kinds.filter((x) => x !== k) : [...props.kinds, k])
// (a drop-down's list is put over the page, outside this box: choosing in it is not a click outside)
const outside = (e) => { if (open.value && wrap.value && !wrap.value.contains(e.target) && !(e.target.closest && e.target.closest('.sel-pop'))) open.value = false }
const onKey = (e) => { if (open.value && e.key === 'Escape') { e.stopPropagation(); open.value = false; wrap.value?.querySelector('.cal-tool')?.focus() } }
watch(open, (v) => { if (v) document.addEventListener('mousedown', outside); else document.removeEventListener('mousedown', outside) })
onBeforeUnmount(() => document.removeEventListener('mousedown', outside))
</script>

<template>
  <div ref="wrap" class="cal-fwrap" @keydown="onKey">
    <button type="button" class="cal-tool" :class="{ on: open }" :aria-expanded="open" aria-haspopup="dialog" @click="open = !open">
      <Icon name="filter" />{{ $t('calendar.filter.button') }}<span v-if="count" class="n">{{ count }}</span>
    </button>
    <div v-if="open" class="cal-pop" role="dialog" :aria-label="$t('calendar.filter.button')">
      <fieldset>
        <legend>{{ $t('calendar.filter.types') }}</legend>
        <div class="checks">
          <label v-for="k in MAIN" :key="k" :class="'ev-' + FAMILY[k]"><input type="checkbox" :checked="kinds.includes(k)" @change="toggle(k)" /><span class="dot"></span>{{ $t('calendar.kind.' + k) }}</label>
        </div>
        <div class="sub-legend">{{ $t('calendar.filter.records') }}</div>
        <div class="checks">
          <label v-for="k in RECORDS" :key="k" :class="'ev-' + FAMILY[k]"><input type="checkbox" :checked="kinds.includes(k)" @change="toggle(k)" /><span class="dot"></span>{{ $t('calendar.kind.' + k) }}</label>
        </div>
      </fieldset>
      <fieldset>
        <legend>{{ $t('calendar.filter.app') }}</legend>
        <div class="kv2">
          <label for="cf-state">{{ $t('calendar.state.label') }}</label>
          <AaSelect id="cf-state" :model-value="f.state" @update:model-value="emit('set', { state: $event })">
            <option value="">{{ $t('calendar.state.any') }}</option>
            <option v-for="s in STATES" :key="s" :value="s">{{ $t('calendar.state.' + s) }}</option>
          </AaSelect>
          <label for="cf-company">{{ $t('calendar.company') }}</label>
          <input id="cf-company" v-model="company" @change="emit('set', { company: company.trim() })" />
          <label for="cf-min">{{ $t('calendar.minScore') }}</label>
          <input id="cf-min" v-model.number="min" type="number" min="0" max="10" step="0.5" @change="emit('set', { min: Number(min) || 0 })" />
        </div>
        <label style="margin-top: 6px"><input type="checkbox" :checked="f.prio" @change="emit('set', { prio: !f.prio })" />{{ $t('calendar.priority') }}</label>
      </fieldset>
      <fieldset>
        <legend>{{ $t('calendar.filter.display') }}</legend>
        <label v-tip="$t('calendar.allDeadlinesHint')"><input type="checkbox" :checked="f.all" @change="emit('set', { all: !f.all })" />{{ $t('calendar.allDeadlines') }}</label>
        <div class="hint" style="margin: 0 0 4px 24px">{{ $t('calendar.allDeadlinesHint') }}</div>
        <label><input type="checkbox" :checked="!f.hideDone" @change="emit('set', { hideDone: !f.hideDone })" />{{ $t('calendar.filter.showDone') }}</label>
        <label><input type="checkbox" :checked="summary" @change="emit('summary', !summary)" />{{ $t('calendar.filter.summary') }}</label>
      </fieldset>
      <div class="cal-pop-foot">
        <span class="hint">{{ $t('calendar.kbd') }}</span>
        <button type="button" class="sm ghost" :disabled="!dirty" @click="emit('reset')">{{ $t('calendar.filter.reset') }}</button>
      </div>
    </div>
  </div>
</template>

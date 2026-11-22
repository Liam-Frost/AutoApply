<script setup>
// What a page says about what it shows while that is not simply "here it is": still being read, could not be read,
// or read earlier and possibly out of date (data.js). It shows nothing when the data is there and current - the page
// shows its content (and its own "nothing here" picture) under `v-if="st.at"`.
import { clock } from '../data'
import Icon from './Icon.vue'

defineProps({ s: { type: Object, required: true }, what: { type: String, default: '' } })
defineEmits(['retry'])
</script>

<template>
  <div v-if="s.phase === 'loading'" class="card data-wait" role="status" aria-live="polite"><span class="spin" aria-hidden="true"></span>{{ $t('common.loading') }}</div>
  <div v-else-if="s.phase === 'error'" class="callout bad" role="alert"><Icon name="alert" />
    <div><b>{{ $t('common.notRead', { what: what || $t('common.thisPage') }) }}</b><div class="small">{{ s.error }}</div>
      <button class="sm data-retry" :disabled="s.busy" @click="$emit('retry')"><Icon name="refresh" />{{ s.busy ? $t('common.retrying') : $t('common.retry') }}</button></div></div>
  <div v-else-if="s.phase === 'stale'" class="callout warn data-stale" role="status"><Icon name="alert" />
    <span class="grow">{{ $t('common.stale', { time: clock(s.at) }) }}</span>
    <button class="sm" :disabled="s.busy" @click="$emit('retry')"><Icon name="refresh" />{{ s.busy ? $t('common.retrying') : $t('common.retry') }}</button></div>
</template>

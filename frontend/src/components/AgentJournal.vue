<script setup>
import { t as T } from '../i18n/catalog'
// What the agent wrote down while it worked an application - and, while a run is on it, the applicant's side of it:
// a word to the agent (it hears it with its next action) and "stop".
import { onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime, run } from '../ui'

const props = defineProps({
  journal: { type: Array, default: () => [] },
  spent: { type: Object, default: null },
  runningTask: { type: Number, default: 0 },       // the task of the run that is on this application now (0: none)
  expected: { type: Boolean, default: false },     // a run waits in the queue: it may begin any moment
  applicationId: { type: Number, required: true },
  note: { type: String, default: '' },
})
const emit = defineEmits(['refresh'])
const word = ref('')
let timer = null

// While a run is working, the page keeps up with what it writes down; while one waits in the queue, it looks for it
// to begin (a page opened before the worker took the task would otherwise never show the run).
watch(() => [props.runningTask, props.expected], ([on, soon]) => {
  clearInterval(timer)
  timer = on || soon ? setInterval(() => emit('refresh'), on ? 4000 : 6000) : null
}, { immediate: true })
onUnmounted(() => clearInterval(timer))

async function say() {
  const text = word.value.trim()
  if (!text) return
  if (await run(() => api.post(`/applications/${props.applicationId}/say`, { text }), T('journal.told'), () => emit('refresh'), { name: 'say' })) word.value = ''
}
const stop = () => run(() => api.post(`/tasks/${props.runningTask}/stop`), T('journal.stopped'), () => emit('refresh'), { name: 'stop' })
</script>

<template>
  <div v-if="journal.length || runningTask" class="panel" style="margin-bottom: 16px">
    <div class="row"><h3 class="grow" style="margin: 0">{{ $t('journal.title') }}</h3>
      <span v-if="runningTask" class="badge warn">{{ $t('journal.working') }}</span>
      <span v-if="spent && spent.runs" class="muted small">{{ $t('journal.spent', { steps: spent.steps, of: spent.of_steps, minutes: spent.minutes, runs: spent.runs }) }}</span></div>
    <div v-if="note" class="muted small">{{ note }}</div>
    <ul v-if="journal.length" class="journal">
      <li v-for="(e, i) in journal" :key="i" :class="'j-' + e.kind">
        <span class="muted small nowrap">{{ fmtTime(e.at) }}</span>
        <span v-if="e.kind === 'run'" class="badge">{{ $t('journal.run') }}</span>
        <span v-else-if="e.kind === 'ask'" class="j-strong">{{ $t('journal.asked', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'said'" class="j-strong">{{ $t('journal.said', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'said_waiting'" class="j-strong">{{ $t('journal.said', { text: e.text }) }}<span class="muted" style="font-weight: 400">{{ $t('journal.hearsNext') }}</span></span>
        <span v-else-if="e.kind === 'waits'" class="j-strong">{{ $t('journal.waits', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'sending'" class="j-strong">{{ $t('journal.sending', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'report'">{{ $t('journal.ended', { n: e.calls, text: e.text }, e.calls) }}</span>
        <span v-else-if="e.kind === 'ended'" class="j-strong">{{ $t('journal.broke', { n: e.calls, text: e.text }, e.calls) }}</span>
        <span v-else-if="e.kind === 'note'" class="muted">{{ $t('journal.learned', { text: e.text }) }}</span>
        <span v-else>{{ e.text }}</span>
      </li>
    </ul>
    <template v-if="runningTask">
      <div class="row" style="margin-top: 10px">
        <input v-model="word" class="grow" maxlength="2000" :aria-label="$t('journal.sayLabel')" :placeholder="$t('journal.sayPlaceholder')" @keyup.enter="say" />
        <button :disabled="!word.trim()" @click="say">{{ $t('journal.tell') }}</button>
        <button class="ghost danger" @click="stop">{{ $t('journal.stop') }}</button>
      </div>
      <div class="muted small" style="margin-top: 6px">{{ $t('journal.howItHears') }}</div>
    </template>
  </div>
</template>

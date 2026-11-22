<script setup>
import { t as T } from '../i18n/catalog'
// What the agent wrote down while it worked an application - and, while a run is on it, the applicant's side of it:
// a word to the agent (it hears it with its next action) and "stop".
import { onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import InfoTip from './InfoTip.vue'
import SectionHead from './SectionHead.vue'
import Status from './Status.vue'
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
  <div v-if="journal.length || runningTask" class="panel journal-panel">
    <SectionHead :title="$t('journal.title')" :help="note">
      <Status v-if="runningTask" tone="info" :label="$t('journal.working')" />
      <span v-if="spent && spent.runs" class="meta small">{{ $t('journal.spent', { steps: spent.steps, of: spent.of_steps, minutes: spent.minutes, runs: spent.runs }) }}</span>
    </SectionHead>
    <ul v-if="journal.length" class="journal">
      <li v-for="(e, i) in journal" :key="i" :class="'j-' + e.kind">
        <span class="t-meta num atomic">{{ fmtTime(e.at) }}</span>
        <span v-if="e.kind === 'run'" class="meta small">{{ $t('journal.run') }}</span>
        <span v-else-if="e.kind === 'ask'" class="j-strong">{{ $t('journal.asked', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'said'" class="j-strong">{{ $t('journal.said', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'said_waiting'" class="j-strong">{{ $t('journal.said', { text: e.text }) }}<span class="t-meta">{{ $t('journal.hearsNext') }}</span></span>
        <span v-else-if="e.kind === 'waits'" class="j-strong">{{ $t('journal.waits', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'sending'" class="j-strong">{{ $t('journal.sending', { text: e.text }) }}</span>
        <span v-else-if="e.kind === 'report'">{{ $t('journal.ended', { n: e.calls, text: e.text }, e.calls) }}</span>
        <span v-else-if="e.kind === 'ended'" class="j-strong">{{ $t('journal.broke', { n: e.calls, text: e.text }, e.calls) }}</span>
        <span v-else-if="e.kind === 'note'" class="muted">{{ $t('journal.learned', { text: e.text }) }}</span>
        <span v-else>{{ e.text }}</span>
      </li>
    </ul>
    <template v-if="runningTask">
      <!-- a word to the agent, and - last, apart - the way to stop it; how both are heard is behind the (i) -->
      <div class="journal-say">
        <input v-model="word" class="grow" maxlength="2000" :aria-label="$t('journal.sayLabel')" :placeholder="$t('journal.sayPlaceholder')" @keyup.enter="say" />
        <InfoTip :text="$t('journal.howItHears')" />
        <button :disabled="!word.trim()" @click="say">{{ $t('journal.tell') }}</button>
        <button class="ghost danger" @click="stop">{{ $t('journal.stop') }}</button>
      </div>
    </template>
  </div>
</template>

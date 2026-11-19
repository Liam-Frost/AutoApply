<script setup>
// What the agent wrote down while it worked an application - and, while a run is on it, the applicant's side of it:
// a word to the agent (it hears it with its next action) and "stop".
import { onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime, run } from '../ui'

const props = defineProps({
  journal: { type: Array, default: () => [] },
  spent: { type: Object, default: null },
  runningTask: { type: Number, default: 0 },       // the task of the run that is on this application now (0: none)
  applicationId: { type: Number, required: true },
  note: { type: String, default: '' },
})
const emit = defineEmits(['refresh'])
const word = ref('')
let timer = null

// while a run is working, the page keeps up with what it writes down
watch(() => props.runningTask, (on) => {
  clearInterval(timer)
  timer = on ? setInterval(() => emit('refresh'), 4000) : null
}, { immediate: true })
onUnmounted(() => clearInterval(timer))

async function say() {
  const text = word.value.trim()
  if (!text) return
  if (await run(() => api.post(`/applications/${props.applicationId}/say`, { text }), '已告诉它，它会在下一步操作时看到', () => emit('refresh'), { name: 'say' })) word.value = ''
}
const stop = () => run(() => api.post(`/tasks/${props.runningTask}/stop`), '已叫停，Agent 会在下一步操作之前停下', () => emit('refresh'), { name: 'stop' })
</script>

<template>
  <div v-if="journal.length || runningTask" class="panel" style="margin-bottom: 16px">
    <div class="row"><h3 class="grow" style="margin: 0">Agent 做了什么</h3>
      <span v-if="runningTask" class="badge warn">正在处理这份申请</span>
      <span v-if="spent && spent.runs" class="muted small">已用 {{ spent.steps }} / {{ spent.of_steps }} 步，约 {{ spent.minutes }} 分钟，{{ spent.runs }} 次运行</span></div>
    <div v-if="note" class="muted small">{{ note }}</div>
    <ul v-if="journal.length" class="journal">
      <li v-for="(e, i) in journal" :key="i" :class="'j-' + e.kind">
        <span class="muted small nowrap">{{ fmtTime(e.at) }}</span>
        <span v-if="e.kind === 'run'" class="badge">开始一次运行</span>
        <span v-else-if="e.kind === 'ask'" class="j-strong">问你：{{ e.text }}</span>
        <span v-else-if="e.kind === 'said'" class="j-strong">你说：{{ e.text }}</span>
        <span v-else-if="e.kind === 'said_waiting'" class="j-strong">你说：{{ e.text }}<span class="muted" style="font-weight: 400">（它下一步操作时会看到）</span></span>
        <span v-else-if="e.kind === 'waits'" class="j-strong">等你处理：{{ e.text }}</span>
        <span v-else-if="e.kind === 'sending'" class="j-strong">即将点提交：{{ e.text }}</span>
        <span v-else-if="e.kind === 'report'">这次运行结束（{{ e.calls }} 次操作）：{{ e.text }}</span>
        <span v-else-if="e.kind === 'ended'" class="j-strong">这次运行中断（{{ e.calls }} 次操作）：{{ e.text }}</span>
        <span v-else-if="e.kind === 'note'" class="muted">记下了这个网站的一条经验：{{ e.text }}</span>
        <span v-else>{{ e.text }}</span>
      </li>
    </ul>
    <template v-if="runningTask">
      <div class="row" style="margin-top: 10px">
        <input v-model="word" class="grow" maxlength="2000" aria-label="对 Agent 说的话" placeholder="有话直接对它说，例如：地址用温哥华的那个" @keyup.enter="say" />
        <button :disabled="!word.trim()" @click="say">告诉它</button>
        <button class="ghost danger" @click="stop">叫停</button>
      </div>
      <div class="muted small" style="margin-top: 6px">你说的话它会在下一步操作时看到，并且留在这份申请的记录里。叫停之后它在下一步操作之前停下，网站上已经保存的内容还在。</div>
    </template>
  </div>
</template>

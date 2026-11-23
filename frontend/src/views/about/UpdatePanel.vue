<script setup>
// The about page's updates card: the state the update is in (src/updatestate.js), the facts that go with it, and the
// actions valid in that state - nothing else is offered. It does nothing itself: it says which action was pressed
// (`act`), the page does it. (The UI lab feeds it made-up states: views/lab/sections/56-UpdateStates.vue.)
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText, num, when } from '../../i18n/format'
import { at } from '../../calendar'
import { renderMarkdown } from '../../md'
import { actionTarget, releaseText } from '../../updatestate'
import CardHead from '../../components/CardHead.vue'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import InfoTip from '../../components/InfoTip.vue'

const props = defineProps({ model: { type: Object, required: true } })
const emit = defineEmits(['act'])

const rel = (r) => releaseText(r, T, dayText)
// (when the last check was: the server's own wall clock, without a zone - updates.check - so read as calendar times are)
const checkedAt = (s) => when(at({ start: s }))
const m = computed(() => props.model)
const v = computed(() => rel(m.value.target))
const title = computed(() => {
  const s = m.value
  const p = { v: v.value }
  if (s.id === 'failed') return { check: T('about.state.checkFailed'), prepare: T('about.state.prepareFailed', p), switch: T('about.state.switchFailed', p) }[s.error.stage]
  const id = s.found || s.id      // (a copy that does not update itself: what the look found; `how` says the rest)
  return {
    unchecked: T('about.state.unchecked'), checking: T('about.state.checking'), current: T('about.state.current'), newer: T('about.state.newer', p),
    failed: T('about.state.checkFailed'), downloading: T('about.state.downloading', p), preparing: T('about.state.preparing', p),
    ready: s.how === 'unmanaged' ? T('about.state.prepared', p) : T('about.state.ready', p), switching: T('about.state.switching', p),
  }[id]
})
const FACT = computed(() => ({ running: T('about.fact.running'), latest: T('about.fact.latest'), staged: T('about.fact.staged'), switching: T('about.fact.switching'),
  pending: T('about.fact.pending'), whenIdle: T('about.fact.whenIdle'), previous: T('about.fact.previous'), checked: T('about.fact.checked') }))
const FACT_HELP = computed(() => ({ pending: T('about.fact.pendingHow'), whenIdle: T('about.fact.whenIdleHow') }))
const line = computed(() => {
  const s = m.value
  if (s.id === 'failed') return T(s.error.key, s.error.params)
  if (s.id === 'downloading') return num(s.progress / 100, { style: 'percent' })
  if (s.id === 'preparing') return T('about.preparingHow')
  if (s.id === 'switching') return T('about.switchingHow')
  return ''
})
const moving = computed(() => ['checking', 'downloading', 'preparing', 'switching'].includes(m.value.id))
const ICON = { check: 'refresh', retry: 'refresh', prepare: 'download', switch: 'play' }
function label(a) {
  const target = actionTarget(a, T, dayText)
  if (a.id === 'check') return T('about.check')
  if (a.id === 'retry') return T('common.retry')
  if (a.id === 'prepare') return T('about.prepare', { v: target })
  if (a.id === 'switch') return T('about.switchTo', { v: target })
  return T(a.direction === 'forward' ? 'about.forwardTo' : 'about.backTo', { v: target })
}
const switches = computed(() => m.value.actions.some((a) => a.does === 'switch' || a.does === 'rollback'))
</script>

<template>
  <section class="card up-card" :data-state="model.id">
    <CardHead :title="$t('about.updates')" />
    <div class="up-state" role="status">
      <span v-if="moving" class="spin" aria-hidden="true"></span><span v-else class="up-dot" :class="model.tone" aria-hidden="true"></span>
      <span class="up-title">{{ title }}</span>
    </div>
    <div v-if="model.id === 'downloading' || model.id === 'preparing'" class="up-bar" :class="{ moving: model.id === 'preparing' }" role="progressbar" :aria-label="title"
      aria-valuemin="0" aria-valuemax="100" :aria-valuenow="model.id === 'downloading' ? model.progress : undefined"><span :style="{ width: (model.id === 'downloading' ? model.progress : 100) + '%' }"></span></div>
    <p v-if="line" class="up-line" :class="{ 'up-bad': model.id === 'failed', num: model.id === 'downloading' }">{{ line }}</p>
    <p v-if="model.notice" class="up-line up-warn">{{ $t(model.notice.key, model.notice.params) }}</p>
    <p v-if="model.how === 'source'" class="up-how">{{ $t('about.howSource') }} <code>git pull</code> · <code>uv sync</code> · <code>npm run build</code></p>
    <p v-else-if="model.how === 'container'" class="up-how">{{ $t('about.howContainer') }} <code>docker compose pull &amp;&amp; docker compose up -d</code></p>
    <p v-else-if="model.how === 'unmanaged'" class="up-how">{{ $t('about.howUnmanaged') }}</p>

    <dl class="kv up-facts">
      <template v-for="f in model.facts" :key="f.id">
        <dt>{{ FACT[f.id] }}<InfoTip v-if="FACT_HELP[f.id]" :text="FACT_HELP[f.id]" /></dt>
        <dd v-if="f.id === 'running'"><span class="t-primary">{{ f.release ? rel(f.release) : f.version }}</span><span v-if="f.release" class="t-meta up-raw">{{ f.release.name }}</span></dd>
        <dd v-else-if="f.id === 'latest'">
          <template v-if="f.release"><span>{{ f.release.version }}</span><span v-if="f.release.date" class="t-meta">{{ dayText(f.release.date) }}</span><span v-if="f.release.prerelease" class="tag info">{{ $t('about.rel.prerelease') }}</span></template>
          <span v-else class="muted">{{ $t('about.fact.none') }}</span>
        </dd>
        <dd v-else-if="f.id === 'whenIdle'">{{ f.version }}</dd>
        <dd v-else-if="f.id === 'checked'" class="atomic">{{ checkedAt(f.at) }}</dd>
        <dd v-else><span>{{ rel(f.release) }}</span><span v-if="f.release.local" class="t-meta up-raw">{{ f.release.name }}</span></dd>
      </template>
    </dl>

    <div v-if="model.actions.length" class="actions up-acts">
      <button v-for="a in model.actions" :key="a.id" type="button" :class="{ primary: a.primary }" :data-act="a.id" @click="emit('act', a)">
        <Icon :name="ICON[a.id] || (a.direction === 'forward' ? 'forward' : 'back')" />{{ label(a) }}
      </button>
      <HelpPop v-if="switches" :text="$t('about.howSwitch')" :label="$t('about.switch')" />
    </div>

    <details v-if="model.notes" class="up-notes">
      <summary>{{ $t('about.whatsNew', { v: model.notes.version }) }}</summary>
      <p v-if="model.notes.url" class="up-notes-link"><a :href="model.notes.url" target="_blank" rel="noopener"><Icon name="external" />{{ $t('about.onGithub') }}</a></p>
      <div class="md" v-html="renderMarkdown(model.notes.text)"></div>
    </details>
  </section>
</template>

<script setup>
// The first part of the about page's "Software update": the state the update is in (src/updatestate.js) with its facts,
// and right under them the actions valid in that state - nothing else is offered. A copy that does not update itself
// (a checkout, a container) gets the check alone and one line saying it is updated by hand; the command is under
// "Advanced" (`show-command` opens it there). What a newer version brings is a link - to its entry in the changelog
// when this copy's changelog has it, else to its release page - never its notes here. It does nothing itself: it says
// which action was pressed (`act`), the page does it. (The UI lab feeds it made-up states: lab/sections/56-UpdateStates.vue.)
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText, num, when } from '../../i18n/format'
import { at } from '../../calendar'
import { actionTarget, releaseText, whatsNew } from '../../updatestate'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import InfoTip from '../../components/InfoTip.vue'

const props = defineProps({
  model: { type: Object, required: true },          // updateState(...)
  changelog: { type: Array, default: () => [] },    // the versions this copy's own changelog has
})
const emit = defineEmits(['act', 'show-command'])

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
// "What's new in 2.0.3": the changelog's entry when this copy's changelog has it, else the release's page (whatsNew)
const news = computed(() => whatsNew(m.value.notes, props.changelog))
</script>

<template>
  <div class="up-status" :data-state="model.id">
    <div class="up-state" role="status">
      <span v-if="moving" class="spin" aria-hidden="true"></span><span v-else class="up-dot" :class="model.tone" aria-hidden="true"></span>
      <span class="up-title">{{ title }}</span>
    </div>
    <div v-if="model.id === 'downloading' || model.id === 'preparing'" class="up-bar" :class="{ moving: model.id === 'preparing' }" role="progressbar" :aria-label="title"
      aria-valuemin="0" aria-valuemax="100" :aria-valuenow="model.id === 'downloading' ? model.progress : undefined"><span :style="{ width: (model.id === 'downloading' ? model.progress : 100) + '%' }"></span></div>
    <p v-if="line" class="up-line" :class="{ 'up-bad': model.id === 'failed', num: model.id === 'downloading' }">{{ line }}</p>
    <p v-if="model.notice" class="up-line up-warn">{{ $t(model.notice.key, model.notice.params) }}</p>

    <dl class="up-facts">
      <div v-for="f in model.facts" :key="f.id" class="up-fact" :data-fact="f.id">
        <dt>{{ FACT[f.id] }}<InfoTip v-if="FACT_HELP[f.id]" :text="FACT_HELP[f.id]" /></dt>
        <dd v-if="f.id === 'running'"><span>{{ f.release ? rel(f.release) : f.version }}</span><span v-if="f.release" class="up-raw">{{ f.release.name }}</span></dd>
        <dd v-else-if="f.id === 'latest'">
          <template v-if="f.release">
            <span>{{ f.release.version }}</span><span v-if="f.release.date" class="t-meta">{{ dayText(f.release.date) }}</span><span v-if="f.release.prerelease" class="tag info">{{ $t('about.rel.prerelease') }}</span>
            <RouterLink v-if="news && news.to" class="up-news" :to="news.to">{{ $t('about.whatsNew', { v: news.version }) }}<Icon name="chevron_right" /></RouterLink>
            <a v-else-if="news" class="up-news" :href="news.href" target="_blank" rel="noopener">{{ $t('about.whatsNew', { v: news.version }) }}<Icon name="external" /></a>
          </template>
          <span v-else class="muted">{{ $t('about.fact.none') }}</span>
        </dd>
        <dd v-else-if="f.id === 'whenIdle'">{{ f.version }}</dd>
        <dd v-else-if="f.id === 'checked'" class="atomic">{{ checkedAt(f.at) }}</dd>
        <dd v-else><span>{{ rel(f.release) }}</span><span v-if="f.release.local" class="up-raw">{{ f.release.name }}</span></dd>
      </div>
    </dl>

    <div v-if="model.actions.length" class="actions up-acts">
      <button v-for="a in model.actions" :key="a.id" type="button" :class="{ primary: a.primary }" :data-act="a.id" @click="emit('act', a)">
        <Icon :name="ICON[a.id] || (a.direction === 'forward' ? 'forward' : 'back')" />{{ label(a) }}
      </button>
      <HelpPop v-if="switches" :text="$t('about.howSwitch')" :label="$t('about.switch')" />
    </div>
    <p v-if="model.how === 'source' || model.how === 'container'" class="up-hand">
      <span>{{ $t('about.byHand.' + model.how) }}</span>
      <button type="button" class="up-link" @click="emit('show-command')">{{ $t('about.byHand.show') }}</button>
    </p>
    <p v-else-if="model.how === 'unmanaged'" class="up-hand">{{ $t('about.howUnmanaged') }}</p>
  </div>
</template>

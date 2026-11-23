<script setup>
// The first part of the about page's "Software update", its centre: the title with the state as a badge (what the
// update state model says, src/updatestate.js), then the two versions side by side - the one that runs and the one the
// state is about, an arrow between them when that one is ahead - with the progress of a download under them, what goes
// with the state (an error, what preparing or a switch does, a notice), the other facts on one quiet line, and the
// actions valid in the state with "What's new" - nothing else is offered. A copy that does not update itself (a
// checkout, a container) gets the check alone and one line saying it is updated by hand, its steps in a popover
// (UpdateSteps). What a newer version brings is a link - to its entry in the changelog when this copy's changelog has
// it, else to its release page - never its notes here. It does nothing itself: it says which action was pressed
// (`act`), the page does it. (The UI lab feeds it made-up states: lab/sections/56-UpdateStates.vue.)
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText, num, when } from '../../i18n/format'
import { at } from '../../calendar'
import { actionTarget, releaseText, whatsNew } from '../../updatestate'
import CardHead from '../../components/CardHead.vue'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import InfoTip from '../../components/InfoTip.vue'
import Popover from '../../components/Popover.vue'
import UpdateSteps from './UpdateSteps.vue'

const props = defineProps({
  model: { type: Object, required: true },          // updateState(...)
  changelog: { type: Array, default: () => [] },    // the versions this copy's own changelog has
})
const emit = defineEmits(['act'])

const m = computed(() => props.model)
const rel = (r) => releaseText(r, T, dayText)
// (when the last check was: the server's own wall clock, without a zone - updates.check - so read as calendar times are)
const checkedAt = (s) => when(at({ start: s }))

// the state in a short phrase (a copy that does not update itself: what the look found; `how` says the rest)
const badge = computed(() => {
  const s = m.value
  if (s.id === 'failed') return { check: T('about.state.checkFailed'), prepare: T('about.state.prepareFailed'), switch: T('about.state.switchFailed') }[s.error.stage]
  return {
    unchecked: T('about.state.unchecked'), checking: T('about.state.checking'), current: T('about.state.current'), newer: T('about.state.newer'),
    failed: T('about.state.checkFailed'), downloading: T('about.state.downloading'), preparing: T('about.state.preparing'),
    ready: s.how === 'unmanaged' ? T('about.state.prepared') : T('about.state.ready'), switching: T('about.state.switching'),
  }[s.found || s.id]
})
const moving = computed(() => ['checking', 'downloading', 'preparing', 'switching'].includes(m.value.id))

// the two versions: what runs, and the release the state is about (its name says which)
const cmp = computed(() => m.value.compare)
const TO = computed(() => ({ latest: T('about.fact.latest'), staged: T('about.fact.staged'), switching: T('about.fact.switching') }))
const versionOf = (r) => r.version || r.name
const latest = computed(() => { const f = m.value.facts.find((x) => x.id === 'latest'); return f ? f.release : null })
// the line under a version: a build of one's own and its day, or the day a release came out - known for the newest
// out (GitHub says it); a release fetched and unpacked here has only the day it was unpacked, so it borrows the day of
// the newest out when it is that version, else says nothing
function metaOf(r) {
  if (!r) return ''
  if (r.local) return r.date ? T('about.rel.localDay', { d: dayText(r.date) }) : T('about.rel.localOnly')
  const out = latest.value && latest.value.version === versionOf(r) ? latest.value.date : ''
  return out ? T('about.rel.published', { d: dayText(out) }) : ''
}

const FACT = computed(() => ({ latest: T('about.fact.latest'), staged: T('about.fact.staged'), switching: T('about.fact.switching'), pending: T('about.fact.pending'),
  whenIdle: T('about.fact.whenIdle'), previous: T('about.fact.previous'), checked: T('about.fact.checked') }))
const FACT_HELP = computed(() => ({ pending: T('about.fact.pendingHow'), whenIdle: T('about.fact.whenIdleHow') }))
const line = computed(() => {
  const s = m.value
  if (s.id === 'failed') return T(s.error.key, s.error.params)
  if (s.id === 'preparing') return T('about.preparingHow')
  if (s.id === 'switching') return T('about.switchingHow')
  return ''
})

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
// "What's new in 2.0.3": the changelog's entry when this copy's changelog has it, else the release's page (whatsNew) -
// in the row of actions right after the check, before what would change this copy
const news = computed(() => whatsNew(m.value.notes, props.changelog))
const row = computed(() => {
  const all = [...m.value.actions]
  if (news.value) all.splice(all.findIndex((a) => a.does === 'check') + 1, 0, { id: 'news' })
  return all
})
</script>

<template>
  <div class="up-status" :data-state="model.id">
    <CardHead :title="$t('about.softwareUpdate')">
      <span class="up-badge" role="status">
        <span v-if="moving" class="spin" aria-hidden="true"></span><span class="tag" :class="model.tone" data-badge>{{ badge }}</span>
      </span>
    </CardHead>

    <div class="up-cmp" :class="{ moves: cmp.moves }">
      <div class="up-ver" data-ver="from">
        <span class="up-ver-name">{{ $t('about.fact.running') }}</span>
        <span class="up-ver-num">{{ cmp.from.version }}</span>
        <span v-if="metaOf(cmp.from.release)" class="up-ver-meta">{{ metaOf(cmp.from.release) }}</span>
      </div>
      <span class="up-arrow" aria-hidden="true"><Icon v-if="cmp.moves" name="forward" /></span>
      <div class="up-ver" data-ver="to" :data-to="cmp.to.id">
        <span class="up-ver-name">{{ TO[cmp.to.id] }}</span>
        <template v-if="cmp.to.release">
          <span class="up-ver-num">{{ versionOf(cmp.to.release) }}</span>
          <span v-if="metaOf(cmp.to.release) || cmp.to.release.prerelease" class="up-ver-meta">
            <span v-if="metaOf(cmp.to.release)">{{ metaOf(cmp.to.release) }}</span><span v-if="cmp.to.release.prerelease" class="tag info">{{ $t('about.rel.prerelease') }}</span>
          </span>
        </template>
        <!-- (not looked yet: the badge says so; nothing to show here) -->
        <span v-else-if="cmp.to.known" class="up-ver-none">{{ $t('about.fact.none') }}</span>
        <span v-else class="up-ver-none none">—</span>
      </div>
      <div v-if="model.id === 'downloading' || model.id === 'preparing'" class="up-prog">
        <div class="up-bar" :class="{ moving: model.id === 'preparing' }" role="progressbar" :aria-label="badge" aria-valuemin="0" aria-valuemax="100"
          :aria-valuenow="model.id === 'downloading' ? model.progress : undefined"><span :style="{ width: (model.id === 'downloading' ? model.progress : 100) + '%' }"></span></div>
        <span v-if="model.id === 'downloading'" class="up-pct num">{{ num(model.progress / 100, { style: 'percent' }) }}</span>
      </div>
    </div>

    <p v-if="line" class="up-line" :class="{ 'up-bad': model.id === 'failed' }">{{ line }}</p>
    <p v-if="model.notice" class="up-line up-warn">{{ $t(model.notice.key, model.notice.params) }}</p>

    <dl v-if="cmp.others.length" class="up-more">
      <div v-for="f in cmp.others" :key="f.id" :data-fact="f.id">
        <dt>{{ FACT[f.id] }}<InfoTip v-if="FACT_HELP[f.id]" :text="FACT_HELP[f.id]" :label="FACT[f.id]" /></dt>
        <dd v-if="f.id === 'latest'">
          <template v-if="f.release">{{ f.release.version }}<span v-if="f.release.prerelease" class="tag info">{{ $t('about.rel.prerelease') }}</span></template>
          <span v-else class="muted">{{ $t('about.fact.none') }}</span>
        </dd>
        <dd v-else-if="f.id === 'whenIdle'">{{ f.version }}</dd>
        <dd v-else-if="f.id === 'checked'" class="atomic">{{ checkedAt(f.at) }}</dd>
        <dd v-else>{{ rel(f.release) }}</dd>
      </div>
    </dl>

    <div v-if="row.length" class="actions up-acts">
      <!-- (the (i) on how a switch works stays with the last action when the row wraps) -->
      <span v-for="(a, i) in row" :key="a.id" class="up-act">
        <template v-if="a.id === 'news'">
          <RouterLink v-if="news.to" class="btn" :to="news.to" data-act="news">{{ $t('about.whatsNew', { v: news.version }) }}</RouterLink>
          <a v-else class="btn" :href="news.href" target="_blank" rel="noopener" data-act="news">{{ $t('about.whatsNew', { v: news.version }) }}<Icon name="external" /></a>
        </template>
        <button v-else type="button" :class="{ primary: a.primary }" :data-act="a.id" @click="emit('act', a)">
          <Icon :name="ICON[a.id] || (a.direction === 'forward' ? 'forward' : 'back')" />{{ label(a) }}
        </button>
        <HelpPop v-if="switches && i === row.length - 1" :text="$t('about.howSwitch')" :label="$t('about.switch')" />
      </span>
    </div>

    <div v-if="model.how === 'source' || model.how === 'container'" class="up-hand">
      <span>{{ $t('about.byHand.' + model.how) }}</span>
      <Popover :label="$t('about.byHand.title')" :width="460">
        <template #trigger="{ toggle, attrs }">
          <button type="button" class="up-link" v-bind="attrs" data-act="steps" @click="toggle">{{ $t('about.byHand.show') }}</button>
        </template>
        <div class="up-steps-pop">
          <p class="pop-title">{{ $t('about.byHand.title') }}</p>
          <UpdateSteps :kind="model.how" />
        </div>
      </Popover>
    </div>
    <p v-else-if="model.how === 'unmanaged'" class="up-hand">{{ $t('about.howUnmanaged') }}</p>
  </div>
</template>

<script setup>
import { t as T } from '../i18n/catalog'
// About: this version and how it runs, updates (look, fetch, switch, go back; and whether the program does that by itself),
// what the update look sends where, and the components the program is made of.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import BrandLogo from '../components/BrandLogo.vue'
import DataTable from '../components/DataTable.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import CardHead from '../components/CardHead.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
import { renderMarkdown } from '../md'
import { ask, fmtTime, run, toast } from '../ui'

const about = ref(null)
const up = ref(null)
const mode = ref('notify')
const channel = ref('stable')
const win = ref({ from: '03:00', to: '05:00' })
let timer = null

const MODES = [['off', T('about.mode.off'), T('about.mode.offHow')], ['notify', T('about.mode.notify'), T('about.mode.notifyHow')],
  ['download', T('about.mode.download'), T('about.mode.downloadHow')], ['auto', T('about.mode.auto'), T('about.mode.autoHow')]]
const KINDS = { managed: T('about.kind.managed'), unmanaged: T('about.kind.unmanaged'), source: T('about.kind.source'), container: T('about.kind.container') }
const ERRORS = { 'no-repo': T('about.error.noRepo'), 'not-here': T('about.error.notHere'), 'no-package': T('about.error.noPackage'), 'no-uv': T('about.error.noUv'),
  checksum: T('about.error.checksum'), incomplete: T('about.error.incomplete'), interrupted: T('about.error.interrupted'), 'did-not-start': T('about.error.didNotStart'),
  'nothing prepared': T('about.error.nothingPrepared'), 'not-managed': T('about.error.notManaged'), 'no-previous': T('about.error.noPrevious') }
const said = (code) => (code ? ERRORS[code] || (code.startsWith('network:') ? T('about.error.network') : T('about.error.other', { code })) : '')

const busy = computed(() => up.value && ['downloading', 'preparing'].includes(up.value.status))
const canPrepare = computed(() => up.value && up.value.newer && ['managed', 'unmanaged'].includes(up.value.kind) && !busy.value && up.value.staged !== up.value.latest)
const canSwitch = computed(() => up.value && up.value.staged && up.value.kind === 'managed' && !busy.value)
const repoUrl = computed(() => (about.value && about.value.repo ? 'https://github.com/' + about.value.repo : ''))
const PARTS = [{ id: 'name', header: T('about.component'), min: 140, flex: 3 }, { id: 'version', header: T('about.componentVersion'), min: 90, flex: 1 }, { id: 'license', header: T('about.componentLicense'), min: 110, flex: 2 }]

async function loadUpdate() {
  up.value = await api.get('/system/update')
  clearTimeout(timer)
  if (busy.value) timer = setTimeout(loadUpdate, 2000)        // follows the download and the preparing while they go on
}
onMounted(async () => {
  about.value = await api.get('/about')
  await loadUpdate()
  mode.value = up.value.mode
  channel.value = up.value.channel
  if (up.value.window && up.value.window.from) win.value = { ...up.value.window }
})
onUnmounted(() => clearTimeout(timer))

const saveSetting = (key, value) => run(() => api.put('/settings', { settings: { [key]: value } }), T('about.saved'), loadUpdate)
const check = () => run(async () => { up.value = await api.post('/system/update/check') }, null, () => up.value.error && toast(said(up.value.error), 'bad'))
const prepare = () => run(async () => { up.value = await api.post('/system/update/prepare') }, null, () => { clearTimeout(timer); timer = setTimeout(loadUpdate, 1500) })
async function switchNow(back = false) {
  const to = back ? up.value.previous : up.value.staged
  if (!(await ask(back ? T('about.backAsk', { v: to }) : T('about.switchAsk', { v: to }), { ok: back ? T('about.goBack') : T('about.switch') }))) return
  try {
    up.value = await api.post('/system/update/switch', back ? { back: true } : {})
    toast(T('about.switching', { v: to }), 'ok')
  } catch (e) { toast(said(e.message) || e.message, 'bad') }
}
</script>

<template>
  <PageHead :title="$t('about.title')" />

  <div v-if="about" class="card about-head">
    <BrandLogo class="about-logo" />
    <div class="kv about-kv">
      <span class="k">{{ $t('about.version') }}</span><div><span class="t-primary">{{ about.version }}</span><span v-if="about.commit" class="t-meta"> · {{ about.commit }}</span></div>
      <span class="k">{{ $t('about.runs') }}</span><div>{{ KINDS[about.kind] || about.kind }}</div>
      <span class="k">{{ $t('about.python') }}</span><div>{{ about.python }} · <span class="muted">{{ about.system }}</span></div>
      <span class="k">{{ $t('about.data') }}</span><Trunc as="code" :text="about.data" />
    </div>
    <div class="row about-links">
      <a v-if="repoUrl" :href="repoUrl" target="_blank" rel="noopener"><Icon name="external" />{{ $t('about.source') }}</a>
      <a v-if="repoUrl" :href="repoUrl + '/releases'" target="_blank" rel="noopener"><Icon name="external" />{{ $t('about.releases') }}</a>
      <a v-if="repoUrl" :href="repoUrl + '/issues'" target="_blank" rel="noopener"><Icon name="external" />{{ $t('about.issues') }}</a>
      <a v-if="repoUrl" :href="repoUrl + '/blob/master/LICENSE'" target="_blank" rel="noopener"><Icon name="external" />{{ $t('about.license') }}</a>
    </div>
  </div>

  <div v-if="up" class="card">
    <CardHead :title="$t('about.updates')" />
    <p class="about-state">
      <template v-if="busy">
        <span>{{ up.status === 'downloading' ? $t('about.downloading', { v: up.latest, p: up.progress }) : $t('about.preparing', { v: up.latest }) }}</span>
        <span class="about-bar"><span :style="{ width: (up.status === 'downloading' ? up.progress : 100) + '%' }" :class="{ moving: up.status === 'preparing' }"></span></span>
      </template>
      <template v-else-if="up.staged"><span class="tag ok">{{ $t('about.ready') }}</span> {{ $t('about.readyLine', { v: up.staged }) }}</template>
      <template v-else-if="up.newer"><span class="tag ok">{{ $t('about.new') }}</span> {{ $t('about.newer', { v: up.latest, d: up.published }) }}</template>
      <Status v-else-if="up.checked_at && !up.error" tone="ok" :label="$t('about.latest', { v: up.current })" />
      <template v-else-if="!up.checked_at">{{ $t('about.notChecked') }}</template>
      <span v-if="up.checked_at" class="t-meta atomic">{{ $t('about.checkedAt', { t: fmtTime(up.checked_at) }) }}</span>
    </p>
    <p v-if="up.status === 'failed' || up.error" class="small bad-text">{{ said(up.error) }}</p>
    <div class="actions about-acts">
      <button @click="check"><Icon name="refresh" />{{ $t('about.check') }}</button>
      <button v-if="canPrepare" class="primary" @click="prepare"><Icon name="download" />{{ $t('about.prepare', { v: up.latest }) }}</button>
      <button v-if="canSwitch" class="primary" @click="switchNow(false)"><Icon name="play" />{{ $t('about.switchTo', { v: up.staged }) }}</button>
      <button v-if="up.previous && up.kind === 'managed' && !busy" class="ghost" @click="switchNow(true)"><Icon name="back" />{{ $t('about.backTo', { v: up.previous }) }}</button>
    </div>
    <p v-if="up.kind === 'source'" class="hint about-how">{{ $t('about.howSource') }} <code>git pull</code> · <code>uv sync</code> · <code>npm run build</code></p>
    <p v-else-if="up.kind === 'container'" class="hint about-how">{{ $t('about.howContainer') }} <code>docker compose pull && docker compose up -d</code></p>
    <p v-else-if="up.kind === 'unmanaged' && up.staged" class="hint about-how">{{ $t('about.howUnmanaged') }}</p>
    <details v-if="up.newer && up.notes" class="about-notes">
      <summary>{{ $t('about.whatsNew', { v: up.latest }) }} <a v-if="up.url" :href="up.url" target="_blank" rel="noopener" @click.stop>{{ $t('about.onGithub') }}</a></summary>
      <div class="md" v-html="renderMarkdown(up.notes)"></div>
    </details>

    <CardHead class="about-sub" :title="$t('about.byItself')" :help="$t('about.howSwitch')" />
    <div class="about-modes" role="radiogroup" :aria-label="$t('about.byItself')">
      <label v-for="[k, name, how] in MODES" :key="k" class="about-mode" :class="{ on: mode === k }">
        <input v-model="mode" type="radio" :value="k" @change="saveSetting('update.mode', k)" />
        <span><b>{{ name }}</b><span class="muted small">{{ how }}</span></span>
      </label>
    </div>
    <div class="kv about-set">
      <label for="u-channel">{{ $t('about.channel') }}</label>
      <div>
        <AaSelect id="u-channel" :model-value="channel" @update:model-value="channel = $event; saveSetting('update.channel', $event)">
          <option value="stable">{{ $t('about.stable') }}</option><option value="beta">{{ $t('about.beta') }}</option>
        </AaSelect>
      </div>
      <template v-if="mode === 'auto'">
        <label>{{ $t('about.window') }}</label>
        <div class="actions">
          <input v-model="win.from" type="time" :aria-label="$t('about.windowFrom')" @change="saveSetting('update.window', win)" />
          <span>–</span>
          <input v-model="win.to" type="time" :aria-label="$t('about.windowTo')" @change="saveSetting('update.window', win)" />
          <span class="meta small">{{ $t('about.windowHint') }}</span>
        </div>
      </template>
    </div>
    <p class="hint about-privacy">{{ $t('about.privacy') }}</p>
  </div>

  <div v-if="about && about.changes" class="card">
    <details>
      <summary class="card-title">{{ $t('about.thisVersion', { v: about.version }) }}</summary>
      <div class="md about-changes" v-html="renderMarkdown(about.changes)"></div>
    </details>
  </div>

  <div v-if="about" class="card">
    <CardHead :title="$t('about.components')" :note="about.components.length" :help="$t('about.componentsHint')" />
    <DataTable class="bare" :columns="PARTS" :rows="about.components" row-key="name" density="compact" :label="$t('about.components')" />
  </div>
</template>

<style scoped>
.about-head { display: grid; grid-template-columns: auto 1fr; gap: var(--s4); align-items: start; }
.about-logo { width: 160px; }
.about-kv { grid-template-columns: minmax(96px, 140px) minmax(0, 1fr); gap: var(--s2) var(--s4); }
.about-kv .k { color: var(--text-2); font-size: var(--fs-sm); }
.about-links { grid-column: 1 / -1; gap: var(--s4); flex-wrap: wrap; }
.about-links a { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.about-state { margin: 4px 0 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.about-bar { flex: 1 1 200px; max-width: 320px; height: 6px; border-radius: var(--r-pill); background: var(--neutral-soft); overflow: hidden; }
.about-bar > span { display: block; height: 100%; background: var(--primary); transition: width 0.4s; }
.about-bar > span.moving { animation: about-pulse 1.4s ease-in-out infinite; }
@keyframes about-pulse { 50% { opacity: 0.45; } }
.bad-text { color: var(--bad); }
.about-notes { margin-top: 10px; }
.about-notes summary { cursor: pointer; }
.about-acts { flex-wrap: wrap; }
.about-sub { margin-top: var(--s5); }
.about-how, .about-privacy { margin-top: var(--s3); max-width: 86ch; }
.about-set { margin-top: var(--s3); }
.about-changes { margin-top: var(--s2); }
details > summary.card-title { cursor: pointer; }
.about-modes { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; }
.about-mode { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--r-md); cursor: pointer; }
.about-mode.on { border-color: var(--primary); background: var(--primary-soft); }
.about-mode > span { display: flex; flex-direction: column; gap: 2px; }
.about-mode input { margin-top: 3px; }
@media (max-width: 700px) {
  .about-head { grid-template-columns: 1fr; }
  .about-kv { grid-template-columns: minmax(0, 1fr); }
}
</style>

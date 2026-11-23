<script setup>
import { t as T } from '../i18n/catalog'
// About, in three tabs with the tab in the address (/about, /about/changelog, /about/licenses): the overview - one
// column of reading width: a compact head (the product, this version and how it runs, the project's links) and one
// "Software update" card (the state with the two versions as its centre and its actions, the update settings as a
// summary with an editor, "Advanced") - then every version's changes and the components with their licences
// (views/about/ChangelogTab.vue and LicensesTab.vue load their own data).
// The updates follow one state model (src/updatestate.js): only the actions valid in the state are offered.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import DataState from '../components/DataState.vue'
import PageHead from '../components/PageHead.vue'
import Tabs from '../components/Tabs.vue'
import ChangelogTab from './about/ChangelogTab.vue'
import LicensesTab from './about/LicensesTab.vue'
import OverviewHead from './about/OverviewHead.vue'
import UpdateSection from './about/UpdateSection.vue'
import { dayText } from '../i18n/format'
import { ERRORS, actionTarget, updateState } from '../updatestate'
import { ask, run, toast } from '../ui'

const route = useRoute()
const router = useRouter()
const tab = computed(() => route.params.tab || 'overview')
const TABS = computed(() => [{ id: 'overview', label: T('about.tab.overview') }, { id: 'changelog', label: T('about.tab.changelog') }, { id: 'licenses', label: T('about.tab.licenses') }])
// (the route says its tabs are in the path - meta.tabs in main.js - so a tab chosen from the keyboard keeps the keyboard)
const pick = (id) => router.replace(id === 'overview' ? '/about' : '/about/' + id)

const about = ref(null)
const failed = ref('')
const up = ref(null)
const checking = ref(false)
const model = computed(() => (up.value ? updateState(up.value, { checking: checking.value }) : null))
let timer = null

async function load() {
  failed.value = ''
  try { about.value = await api.get('/about') } catch (e) { failed.value = e.message; return }
  if (tab.value === 'overview') await loadUpdate().catch((e) => { failed.value = e.message })
}
// Asked again while something goes on by itself: the download and the preparing, and a switch - during which the
// server restarts, so no answer for a while is what is expected, not an error.
async function loadUpdate() {
  clearTimeout(timer)
  const was = model.value && model.value.id
  try { up.value = await api.get('/system/update') } catch (e) { if (was !== 'switching') throw e }
  if (was === 'switching' && model.value.id !== 'switching') about.value = await api.get('/about').catch(() => about.value)      // (the version that runs now)
  if (model.value && model.value.follow) timer = setTimeout(() => loadUpdate().catch(() => {}), model.value.id === 'switching' ? 3000 : 2000)
}
onMounted(load)
onUnmounted(() => clearTimeout(timer))
watch(tab, (t) => { if (t === 'overview' && about.value && !up.value) loadUpdate().catch((e) => { failed.value = e.message }) })

// Which versions this copy's own changelog has: "What's new in 2.0.3" opens that entry there when it has it, else the
// release's page. Read once, and only when a newer version is known.
const changelog = ref([])
let readLog = false
watch(() => model.value && model.value.notes && model.value.notes.version, (v) => {
  if (!v || readLog) return
  readLog = true
  api.get('/about/changelog').then((d) => { changelog.value = (d.versions || []).filter((x) => !x.unreleased).map((x) => x.version) }).catch(() => {})
})

// (the switch endpoint refuses with a code - "not-managed", "no-previous" - said in words; anything else is already words)
const said = (message) => (ERRORS[message] ? T(ERRORS[message].key) : message)
const named = (a) => actionTarget(a, T, dayText)

async function check() {
  checking.value = true
  try {
    await run(async () => { up.value = await api.post('/system/update/check') }, null)
  } finally { checking.value = false }
}
const prepare = () => run(async () => { up.value = await api.post('/system/update/prepare') }, null, () => { clearTimeout(timer); timer = setTimeout(() => loadUpdate().catch(() => {}), 1500) })
async function switchTo(a) {
  const back = a.does === 'rollback'
  const v = named(a)
  const question = back && a.direction === 'back' ? T('about.backAsk', { v }) : T('about.switchAsk', { v })
  if (!(await ask(question, { ok: back && a.direction === 'back' ? T('about.goBack') : T('about.switch') }))) return
  try {
    up.value = await api.post('/system/update/switch', back ? { back: true } : {})
    toast(T('about.switching', { v }), 'ok')
    loadUpdate().catch(() => {})
  } catch (e) { toast(said(e.message), 'bad'); loadUpdate().catch(() => {}) }
}
function act(a) {
  if (a.does === 'check') return check()
  if (a.does === 'prepare') return prepare()
  return switchTo(a)
}
// The update settings that changed in the editor (update.mode, update.channel, update.window), saved together
// (PUT /settings) and said; the page shows them at once, then reads the state again. Truthy once saved.
const FIELD = { 'update.mode': 'mode', 'update.channel': 'channel', 'update.window': 'window' }
const savePolicy = (changes) => run(async () => {
  await api.put('/settings', { settings: changes })
  const s = { ...up.value }
  for (const [key, value] of Object.entries(changes)) if (FIELD[key]) s[FIELD[key]] = value
  up.value = s
}, T('about.saved'), () => loadUpdate())
</script>

<template>
  <PageHead :title="$t('about.title')" />
  <div class="tabs-bar">
    <Tabs id="about-tabs" :model-value="tab" :label="$t('about.title')" :items="TABS" controls="about-panel" @update:model-value="pick" />
  </div>
  <div id="about-panel" role="tabpanel" :aria-labelledby="'about-tabs-' + tab">
    <template v-if="tab === 'overview'">
      <DataState v-if="!about || failed" :s="{ phase: failed ? 'error' : 'loading', error: failed }" :what="$t('about.title')" @retry="load" />
      <div v-else class="about-overview">
        <OverviewHead :about="about" />
        <UpdateSection v-if="model" :model="model" :about="about" :status="up" :changelog="changelog" :save="savePolicy" @act="act" />
      </div>
    </template>
    <ChangelogTab v-else-if="tab === 'changelog'" :version="about ? about.version : ''" />
    <LicensesTab v-else />
  </div>
</template>

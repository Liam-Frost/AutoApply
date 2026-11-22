<script setup>
import { t as T } from '../i18n/catalog'
// The analysis page: four views over one time range. Each view asks the server for its own numbers; this file only
// holds what they share - which view, which range - and the loading / error states around them.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fromQuery, sameQuery, toQuery } from '../urlstate'
import { api } from '../api'
import { rangeQuery } from '../analytics'
import EmptyState from '../components/EmptyState.vue'
import HelpPop from '../components/HelpPop.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import AppsPanel from './analytics/AppsPanel.vue'
import AutoPanel from './analytics/AutoPanel.vue'
import CostPanel from './analytics/CostPanel.vue'
import SitesPanel from './analytics/SitesPanel.vue'

const VIEWS = [['apps', T('analytics.page.applications')], ['auto', T('analytics.page.automation')], ['sites', T('analytics.page.siteNotes')], ['ai', T('analytics.page.aiCost')]]
const RANGES = [['0', T('analytics.page.all')], ['90', T('analytics.page.lastDays')], ['30', T('analytics.page.lastDays2')], ['7', T('analytics.page.lastDays3')], ['today', T('analytics.page.today')], ['custom', T('analytics.page.custom')]]
// what each view shows and by which date it counts: beside the period, behind an (i)
const SUBS = {
  apps: T('analytics.page.whatCameOfThe'),
  auto: T('analytics.page.howOftenEachKind'),
  sites: T('analytics.page.whatTheAgentWrote'),
  ai: T('analytics.page.howManyTokensThe'),
}
const route = useRoute()
const router = useRouter()
// The name of the view comes from the list, never from the address itself: what the address says is only compared with it.
// (urlstate.js: which view and which stretch of time are in the address - a reload, Back, or a link from elsewhere
// shows the same thing. What the address says is only compared with the lists here, never used as it stands.)
const ADDR0 = { view: 'apps', range: '0', start: '', end: '' }
const DAY = /^\d{4}-\d{2}-\d{2}$/
const asked = () => { const st = fromQuery(route.query, ADDR0, { view: VIEWS.map(([k]) => k), range: RANGES.map(([k]) => k) }); return { ...st, start: DAY.test(st.start) ? st.start : '', end: DAY.test(st.end) ? st.end : '' } }
const view = ref(asked().view)
const range = reactive({ mode: asked().range, start: asked().start, end: asked().end })
const params = reactive({ apps: { bucket: '' }, auto: { kind: '' }, ai: { group: 'model', bucket: '', provider: '', model: '', feature: '' } })
const state = reactive({ apps: { data: null, error: '', loading: false }, auto: { data: null, error: '', loading: false }, sites: { data: null, error: '', loading: false }, ai: { data: null, error: '', loading: false } })
const PATH = { apps: '/analytics', auto: '/analytics/automation', sites: '/sites', ai: '/analytics/ai' }
const ready = computed(() => range.mode !== 'custom' || (range.start && range.end && range.start <= range.end))

let seq = 0
async function load() {
  if (!ready.value) return
  const v = view.value
  const st = state[v]
  const mine = ++seq
  st.loading = true
  st.error = ''
  try {
    const d = await api.get(PATH[v] + rangeQuery(range, params[v] || {}))
    if (mine === seq) st.data = d
  } catch (e) {
    if (mine === seq) st.error = e.message || T('analytics.page.couldNotReadThe')
  } finally {
    if (mine === seq) st.loading = false
  }
}
function pick(v) { view.value = v }
watch(() => ({ view: view.value, range: range.mode, start: range.mode === 'custom' ? range.start : '', end: range.mode === 'custom' ? range.end : '' }), (now) => {
  const q = toQuery(now, ADDR0)
  if (!sameQuery(q, route.query)) router.replace({ query: q })
}, { deep: true })
watch(() => route.query, () => { const st = asked(); view.value = st.view; if (st.range !== range.mode || st.start !== range.start || st.end !== range.end) Object.assign(range, { mode: st.range, start: st.start, end: st.end }) })
watch([view, () => range.mode, () => range.start, () => range.end, () => ({ ...params.apps }), () => ({ ...params.auto }), () => ({ ...params.ai })], load, { deep: true })
onMounted(load)
const cur = computed(() => state[view.value])
// The time scale of the charts (day, week, month) is the page's too: one control beside the period, for the views
// that draw something over time. A single day is drawn by the hour, whatever is chosen.
const SCALES = [['', T('analytics.page.scaleAuto')], ['day', T('analytics.page.scaleDay')], ['week', T('analytics.page.scaleWeek')], ['month', T('analytics.page.scaleMonth')]]
const scaled = computed(() => (view.value === 'apps' || view.value === 'ai') && range.mode !== 'today')
</script>

<template>
  <PageHead :title="$t('analytics.page.analytics')" />

  <div class="an-toolbar">
    <div class="seg" role="tablist" :aria-label="$t('analytics.page.views')">
      <button v-for="[v, l] in VIEWS" :key="v" role="tab" :aria-selected="view === v" :class="{ on: view === v }" @click="pick(v)">{{ l }}</button>
    </div>
    <div class="an-tools">
      <AaSelect v-if="scaled" v-model="params[view].bucket" :aria-label="$t('analytics.page.scale')"><option v-for="[k, l] in SCALES" :key="k" :value="k">{{ l }}</option></AaSelect>
      <div v-if="range.mode === 'custom'" class="an-dates">
        <input v-model="range.start" type="date" :max="range.end || undefined" :aria-label="$t('analytics.page.startDate')" />
        <span class="t-meta" aria-hidden="true">–</span>
        <input v-model="range.end" type="date" :min="range.start || undefined" :aria-label="$t('analytics.page.endDate')" />
      </div>
      <AaSelect v-model="range.mode" :aria-label="$t('analytics.page.period')"><option v-for="[v, l] in RANGES" :key="v" :value="v">{{ l }}</option></AaSelect>
      <HelpPop :text="SUBS[view]" :label="$t('analytics.page.analytics')" />
    </div>
  </div>

  <div v-if="!ready" class="card"><EmptyState icon="activity" :title="$t('analytics.page.chooseAStartDate')" :text="$t('analytics.page.bothDatesAreIncluded')" /></div>
  <div v-else-if="cur.error" class="callout bad"><Icon name="alert" /><div class="grow"><div class="t-primary">{{ $t('analytics.page.theDataForThis') }}</div><div class="t-secondary">{{ cur.error }}</div></div><button class="sm" @click="load">{{ $t('analytics.page.tryAgain') }}</button></div>
  <template v-else-if="!cur.data">
    <div class="kpis"><div v-for="i in 4" :key="i" class="skel tile"></div></div>
    <div class="skel tall"></div>
  </template>
  <div v-else class="an-view" :class="{ loading: cur.loading }" :aria-busy="cur.loading">
    <AppsPanel v-if="view === 'apps'" :d="state.apps.data" :params="params.apps" />
    <AutoPanel v-else-if="view === 'auto'" :d="state.auto.data" :params="params.auto" :range="range" />
    <SitesPanel v-else-if="view === 'sites'" :d="state.sites.data" @reload="load" />
    <CostPanel v-else :d="state.ai.data" :params="params.ai" @reload="load" />
  </div>
</template>

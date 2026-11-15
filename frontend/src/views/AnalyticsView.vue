<script setup>
// The analysis page: three views over one time range. Each view asks the server for its own numbers; this file only
// holds what they share - which view, which range - and the loading / error states around them.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { rangeQuery } from '../analytics'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import AppsPanel from './analytics/AppsPanel.vue'
import AutoPanel from './analytics/AutoPanel.vue'
import CostPanel from './analytics/CostPanel.vue'

const VIEWS = [['apps', '求职成效'], ['auto', '自动化效率'], ['ai', 'AI 成本']]
const RANGES = [['0', '全部'], ['90', '最近 90 天'], ['30', '最近 30 天'], ['custom', '自定义']]
const SUBS = {
  apps: '投出去的申请结果怎么样，什么样的岗位更容易有回音，哪些机会错过了。按投递日期统计。',
  auto: '程序的每一类任务跑了多少次、成了多少、卡在哪里、花了多少 AI。按任务开始的日期统计。',
  ai: '模型调用用了多少 Token、折合多少钱，花在哪个模型和哪项功能上。按调用发生的日期统计。',
}
const route = useRoute()
const router = useRouter()
const view = ref(VIEWS.some(([k]) => k === route.query.view) ? route.query.view : 'apps')
const range = reactive({ mode: '0', start: '', end: '' })
const params = reactive({ auto: { kind: '' }, ai: { group: 'model', bucket: '', provider: '', model: '', feature: '' } })
const state = reactive({ apps: { data: null, error: '', loading: false }, auto: { data: null, error: '', loading: false }, ai: { data: null, error: '', loading: false } })
const PATH = { apps: '/analytics', auto: '/analytics/automation', ai: '/analytics/ai' }
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
    if (mine === seq) st.error = e.message || '没有读到数据'
  } finally {
    if (mine === seq) st.loading = false
  }
}
function pick(v) {
  view.value = v
  router.replace({ query: v === 'apps' ? {} : { view: v } })
}
watch([view, () => range.mode, () => range.start, () => range.end, () => ({ ...params.auto }), () => ({ ...params.ai })], load, { deep: true })
onMounted(load)
const cur = computed(() => state[view.value])
</script>

<template>
  <PageHead title="数据分析" :sub="SUBS[view]">
    <div class="seg"><button v-for="[v, l] in RANGES" :key="v" :class="{ on: range.mode === v }" @click="range.mode = v">{{ l }}</button></div>
  </PageHead>

  <div class="an-bar">
    <div class="seg" role="tablist">
      <button v-for="[v, l] in VIEWS" :key="v" role="tab" :aria-selected="view === v" :class="{ on: view === v }" @click="pick(v)">{{ l }}</button>
    </div>
    <template v-if="range.mode === 'custom'">
      <span class="grow"></span>
      <label class="small muted">从 <input v-model="range.start" type="date" :max="range.end || undefined" aria-label="开始日期" /></label>
      <label class="small muted">到 <input v-model="range.end" type="date" :min="range.start || undefined" aria-label="结束日期" /></label>
    </template>
  </div>

  <div v-if="!ready" class="card"><EmptyState icon="activity" title="选一个开始日期和结束日期" text="两个日期都算在内。" /></div>
  <div v-else-if="cur.error" class="callout bad"><Icon name="alert" /><div><b>这一页的数据没有读出来</b><div class="small">{{ cur.error }}</div><button class="sm" style="margin-top: 8px" @click="load">再试一次</button></div></div>
  <template v-else-if="!cur.data">
    <div class="kpis" style="grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))"><div v-for="i in 4" :key="i" class="skel" style="height: 84px; margin: 0"></div></div>
    <div class="skel" style="height: 240px"></div>
  </template>
  <div v-else class="an-view" :style="{ opacity: cur.loading ? 0.55 : 1, transition: 'opacity 0.15s' }" :aria-busy="cur.loading">
    <AppsPanel v-if="view === 'apps'" :d="state.apps.data" />
    <AutoPanel v-else-if="view === 'auto'" :d="state.auto.data" :params="params.auto" :range="range" />
    <CostPanel v-else :d="state.ai.data" :params="params.ai" @reload="load" />
  </div>
</template>

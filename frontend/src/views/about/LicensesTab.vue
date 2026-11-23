<script setup>
// The about page's Licenses tab: the components the program runs on (backend/autoapply/licenses.py: its declared
// dependencies and theirs, from the installed packages' metadata), with their versions and licences. A row opens the
// licence's text in a drawer, as the package carries it.
import { computed, onMounted, reactive, ref } from 'vue'
import { t as T } from '../../i18n/catalog'
import { api } from '../../api'
import { dataState } from '../../data'
import { filterComponents, licenseOptions, sortComponents } from '../../changelog'
import DataState from '../../components/DataState.vue'
import DataTable from '../../components/DataTable.vue'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'
import SideDrawer from '../../components/SideDrawer.vue'
import Trunc from '../../components/Trunc.vue'

const rows = ref([])
const { st, load } = dataState(async () => { rows.value = (await api.get('/about/licenses')).components || [] })
onMounted(load)

const q = ref('')
const scope = ref('all')
const license = ref('')
const sort = ref({ by: 'name', dir: 'asc' })
const licenses = computed(() => licenseOptions(rows.value))
const shown = computed(() => sortComponents(filterComponents(rows.value, { q: q.value, scope: scope.value, license: license.value }), sort.value))
const directCount = computed(() => rows.value.filter((r) => r.direct).length)
const filtered = computed(() => !!(q.value.trim() || scope.value !== 'all' || license.value))
const clear = () => { q.value = ''; scope.value = 'all'; license.value = '' }

const COLS = [
  { id: 'name', header: T('about.licenses.col.name'), min: 160, flex: 3, sortable: true },
  { id: 'version', header: T('about.licenses.col.version'), min: 96, max: 160, flex: 1, sortable: true },
  { id: 'license', header: T('about.licenses.col.license'), min: 140, flex: 2, sortable: true },
  { id: 'dependency', header: T('about.licenses.col.dependency'), width: 112, sortable: true, priority: 1 },
]

// the component whose licence is open, and its text (read when it is opened)
const picked = ref(null)
const detail = reactive({ phase: '', data: null, error: '' })
async function openRow(row) {
  picked.value = row
  Object.assign(detail, { phase: 'loading', data: null, error: '' })
  try {
    const d = await api.get('/about/licenses/' + encodeURIComponent(row.name))
    if (picked.value === row) Object.assign(detail, { phase: 'ready', data: d })
  } catch (e) {
    if (picked.value === row) Object.assign(detail, { phase: 'error', error: (e && e.message) || '' })
  }
}
const safe = (u) => (/^https?:\/\/[^\s"'<>]+$/i.test(String(u || '')) ? u : '')
</script>

<template>
  <div class="lic">
    <DataState :s="st" :what="$t('about.licenses.title')" @retry="load" />
    <template v-if="st.at">
      <EmptyState v-if="!rows.length" icon="info" :title="$t('about.licenses.noneTitle')" :text="$t('about.licenses.noneText')" />
      <template v-else>
        <div class="filters lic-bar">
          <input v-model="q" class="search" type="search" :placeholder="$t('about.licenses.search')" :aria-label="$t('about.licenses.search')" />
          <div class="seg" role="group" :aria-label="$t('about.licenses.col.dependency')">
            <button :class="{ on: scope === 'all' }" :aria-pressed="scope === 'all' ? 'true' : 'false'" @click="scope = 'all'">{{ $t('about.licenses.all') }}<span class="n">{{ rows.length }}</span></button>
            <button :class="{ on: scope === 'direct' }" :aria-pressed="scope === 'direct' ? 'true' : 'false'" @click="scope = 'direct'">{{ $t('about.licenses.directOnly') }}<span class="n">{{ directCount }}</span></button>
          </div>
          <AaSelect v-model="license" small :aria-label="$t('about.licenses.col.license')">
            <option value="">{{ $t('about.licenses.allLicenses') }}</option>
            <option v-for="l in licenses" :key="l.license" :value="l.license">{{ l.license }} ({{ l.count }})</option>
          </AaSelect>
          <span class="count">{{ $t('about.licenses.count', { n: shown.length }, shown.length) }}</span>
        </div>
        <DataTable :columns="COLS" :rows="shown" row-key="name" density="compact" v-model:sort="sort" clickable :label="$t('about.licenses.title')" @row="openRow">
          <template #cell-name="{ row }"><Trunc class="t-primary" :text="row.name" /></template>
          <template #cell-version="{ row }"><span class="num">{{ row.version }}</span></template>
          <template #cell-license="{ row }"><Trunc v-if="row.license" :text="row.license" /><span v-else class="none">—</span></template>
          <template #cell-dependency="{ row }"><span class="meta small">{{ row.direct ? $t('about.licenses.direct') : $t('about.licenses.indirect') }}</span></template>
          <template #empty>
            <EmptyState icon="search" :title="$t('about.licenses.noMatch')"><button v-if="filtered" class="sm" @click="clear">{{ $t('about.changelog.clear') }}</button></EmptyState>
          </template>
        </DataTable>
        <p class="hint lic-source">{{ $t('about.licenses.source') }}</p>
      </template>
    </template>

    <SideDrawer v-if="picked" :title="picked.name" :sub="[picked.version, picked.license].filter(Boolean).join(' · ')" @close="picked = null">
      <p v-if="picked.summary" class="lic-summary">{{ picked.summary }}</p>
      <div class="kv lic-facts">
        <span class="k">{{ $t('about.licenses.col.version') }}</span><span class="num">{{ picked.version }}</span>
        <span class="k">{{ $t('about.licenses.col.license') }}</span><span>{{ picked.license || '—' }}</span>
        <span class="k">{{ $t('about.licenses.col.dependency') }}</span><span>{{ picked.direct ? $t('about.licenses.direct') : $t('about.licenses.indirect') }}</span>
        <template v-if="safe(picked.homepage)">
          <span class="k">{{ $t('about.licenses.homepage') }}</span>
          <a :href="safe(picked.homepage)" target="_blank" rel="noopener noreferrer"><Trunc :text="picked.homepage" /> <Icon name="external" /></a>
        </template>
        <template v-if="detail.data && detail.data.files && detail.data.files.length">
          <span class="k">{{ $t('about.licenses.file') }}</span>
          <span><Trunc v-for="f in detail.data.files" :key="f" as="code" class="lic-file" :text="f" /></span>
        </template>
      </div>
      <h4 class="lic-text-head">{{ $t('about.licenses.text') }}</h4>
      <div v-if="detail.phase === 'loading'" class="lic-wait" role="status"><span class="spin" aria-hidden="true"></span>{{ $t('common.loading') }}</div>
      <div v-else-if="detail.phase === 'error'" class="callout bad" role="alert"><Icon name="alert" />
        <div><b>{{ $t('common.notRead', { what: $t('about.licenses.textOf', { name: picked.name }) }) }}</b><div class="small">{{ detail.error }}</div>
          <button class="sm data-retry" @click="openRow(picked)"><Icon name="refresh" />{{ $t('common.retry') }}</button></div>
      </div>
      <template v-else-if="detail.data">
        <pre v-if="detail.data.text" class="lic-text" tabindex="0" :aria-label="$t('about.licenses.text')">{{ detail.data.text }}</pre>
        <p v-else class="t-secondary">{{ $t('about.licenses.noText') }}</p>
      </template>
    </SideDrawer>
  </div>
</template>

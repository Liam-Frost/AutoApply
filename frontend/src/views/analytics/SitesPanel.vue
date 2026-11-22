<script setup>
import { t as T } from '../../i18n/catalog'
// What the agent wrote down about the sites it worked: the notes it left for the next application there, and what
// is known about how the site signs in. One row a site; a row opened shows its notes. Clearing a site takes its
// notes and leaves its sign-in.
import { computed, ref } from 'vue'
import { api } from '../../api'
import { ask, toast } from '../../ui'
import { stampDay } from '../../i18n/format'
import CardHead from '../../components/CardHead.vue'
import DataTable from '../../components/DataTable.vue'
import EmptyState from '../../components/EmptyState.vue'
import Menu from '../../components/Menu.vue'
import Trunc from '../../components/Trunc.vue'

const props = defineProps({ d: { type: Array, required: true } })
const emit = defineEmits(['reload'])

// a recruiting system's notes hold for every employer on it; a sign-in provider has no notes of its own
const rows = computed(() => props.d.filter((r) => r.notes && !r.key.startsWith('idp:')))
const shown = (r) => r.employer || r.name
const COLS = [
  { id: 'site', header: T('analytics.sites.website'), flex: 2, min: 160 },
  { id: 'scope', header: T('analytics.sites.scope'), flex: 1, min: 150, max: 260, priority: 1 },
  { id: 'notes', header: T('analytics.sites.notes'), width: 80, align: 'end' },
  { id: 'updated', header: T('analytics.sites.lastUpdated'), width: 132 },
  { id: 'act', header: '', width: 48, align: 'end' },
]
const site = ref(null)
async function show(row) {
  if (site.value && site.value.key === row.key) { site.value = null; return }
  try { site.value = await api.get(`/sites/${encodeURIComponent(row.key)}`) } catch (e) { toast(e.message, 'bad') }
}
async function forget(row) {
  // (the question, then what follows from a yes - one text: ask() takes the words and the options apart)
  if (!(await ask(T('analytics.sites.clearTheNotesAbout') + ' ' + T('analytics.sites.theAgentWillFind'), { ok: T('analytics.sites.clear'), danger: true }))) return
  try { await api.post(`/sites/${encodeURIComponent(row.key)}/forget`); site.value = null; emit('reload') } catch (e) { toast(e.message, 'bad') }
}
</script>

<template>
  <div class="card">
    <CardHead :title="$t('analytics.sites.notesTheAgentKeeps')" :help="$t('analytics.sites.withEveryApplicationThe')" :note="rows.length || ''" />
    <EmptyState v-if="!rows.length" icon="wrench" :title="$t('analytics.sites.noNotesYet')" :text="$t('analytics.sites.onceTheAgentHas')" />
    <DataTable v-else class="bare" :columns="COLS" :rows="rows" row-key="key" density="compact" clickable :expanded-key="site ? site.key : null" :label="$t('analytics.sites.notesTheAgentKeeps')" @row="show">
      <template #cell-site="{ row }"><Trunc class="t-primary" data-notr :text="shown(row)" /></template>
      <template #cell-scope="{ row }"><span class="meta">{{ row.key.startsWith('system:') ? $t('analytics.sites.theWholeRecruitingSystem') : $t('analytics.sites.thisSiteOnly') }}</span></template>
      <template #cell-notes="{ row }"><span class="num">{{ row.notes }}</span></template>
      <template #cell-updated="{ row }"><span class="t-secondary atomic">{{ stampDay(row.updated) }}</span></template>
      <template #cell-act="{ row }"><Menu :label="$t('common.more')" size="sm" :items="[{ id: 'clear', label: $t('analytics.sites.clear'), icon: 'trash', danger: true }]" @pick="forget(row)" /></template>
      <template #expanded>
        <div v-if="site.signs_in_on" class="t-meta">{{ $t('analytics.sites.itsSignInIs') }}<span data-notr>{{ site.signs_in_on.replace(/^(generic:|idp:)/, '') }}</span></div>
        <ul class="site-notes"><li v-for="(n, i) in site.notes" :key="i" data-notr><span v-if="n.at" class="t-meta atomic">{{ n.at }}</span> {{ n.text }}</li></ul>
      </template>
    </DataTable>
  </div>
</template>

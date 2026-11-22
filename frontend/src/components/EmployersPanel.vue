<script setup>
import { t as T } from '../i18n/catalog'
// The employers to watch: the user's own list. Paste a careers-page address; the program works out how to read it.
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { ask, run, toast } from '../ui'
import CardHead from './CardHead.vue'
import DataTable from './DataTable.vue'
import Icon from './Icon.vue'
import IconButton from './IconButton.vue'
import InfoTip from './InfoTip.vue'
import Menu from './Menu.vue'
import Trunc from './Trunc.vue'
import EntityCell from './cells/EntityCell.vue'

const rows = ref([])
const form = ref({ name: '', url: '', priority: true })
const hint = ref(null)
const cat = ref({ field: '', employers: [] })
const moreCat = ref(false)
const shownCat = computed(() => (moreCat.value ? cat.value.employers : cat.value.employers.filter((e) => e.match || !cat.value.field).slice(0, 14)))
let t

const COLS = [
  { id: 'star', header: T('settings.employers.priority'), width: 64, align: 'center' },
  { id: 'name', header: T('settings.employers.company'), flex: 2, min: 200 },
  { id: 'kind', header: T('settings.employers.howToReadIt'), flex: 1, min: 140, max: 260, priority: 1 },
  { id: 'open', header: T('settings.employers.openJobs'), width: 112, align: 'end', priority: 2 },
  { id: 'on', header: T('settings.employers.enable'), width: 72, align: 'center' },
  { id: 'act', header: '', width: 48, align: 'end' },
]
const sorted = computed(() => [...rows.value].sort((a, b) => Number(b.priority) - Number(a.priority) || a.name.localeCompare(b.name)))
async function load() { rows.value = (await api.get('/employers')).employers; cat.value = await api.get('/employers/catalog') }
const quick = (e) => run(() => api.post('/employers', { name: e.name, url: e.url, priority: false }), T('settings.employers.added', { p0: e.name }), load)
watch(() => form.value.url, (u) => {
  clearTimeout(t); hint.value = null
  if (u.trim().length > 8) t = setTimeout(async () => { try { hint.value = await api.post('/employers/detect', { url: u }) } catch (e) { /* ignore */ } }, 350)
})
const add = () => run(async () => { const r = await api.post('/employers', form.value); form.value = { name: '', url: '', priority: true }; hint.value = null; return r }, (r) => T('settings.employers.addedItllBeRead', { p0: r.name, p1: r.kind_label }), load)
const patch = (e, body) => run(() => api.patch('/employers/' + e.id, body), '', load)
const remove = async (e) => (await ask(T('settings.employers.stopFollowingPostingsAlready', { p0: e.name }), { ok: T('settings.employers.remove'), danger: true })) && run(() => api.del('/employers/' + e.id), T('settings.employers.removed', { p0: e.name }), load)
onMounted(load)
</script>

<template>
  <div class="card">
    <CardHead :title="$t('settings.employers.employersYouFollow')" :note="rows.length || ''">
      <template #help>
        <p>{{ $t('settings.employers.companiesYouWantTo') }}</p>
        <p>{{ $t('settings.employers.addingRemovingAndThe') }}<router-link to="/settings/automation/prepare">{{ $t('settings.employers.settingsPrepareDraftsAutomatically') }}</router-link>{{ $t('settings.employers.whatIsSearchedFor') }}<router-link to="/settings/goals/search">{{ $t('settings.employers.settingsWhatToSearch') }}</router-link>{{ $t('settings.page.text') }}</p>
      </template>
    </CardHead>

    <div class="emp-add">
      <input v-model="form.url" class="grow" :placeholder="$t('settings.employers.careersPageUrlE')" @keyup.enter="form.url && add()" />
      <input v-model="form.name" class="w-short" :placeholder="$t('settings.employers.companyNameOptional')" @keyup.enter="form.url && add()" />
      <span class="set-check"><label class="atomic"><input v-model="form.priority" type="checkbox" /> {{ $t('settings.employers.priority') }}</label><InfoTip :text="$t('settings.employers.postingsFromPriorityEmployers')" /></span>
      <button class="primary" :disabled="!form.url.trim()" @click="add"><Icon name="plus" />{{ $t('settings.employers.add') }}</button>
    </div>
    <p v-if="hint" class="set-note">{{ $t('settings.employers.detectedAs') }} <span class="t-primary">{{ hint.kind_label }}</span>{{ hint.kind === 'page' ? $t('settings.employers.eachScanUsesThe') : hint.kind === 'feed' ? $t('settings.employers.thisIsAJob') : $t('settings.employers.soItsJobList') }}</p>

    <div v-if="cat.employers.length" class="emp-cat">
      <div class="t-meta">{{ $t('settings.employers.readyToAddAddress', { p0: cat.field ? $t('settings.employers.showingOnesRelatedTo') : '' }) }}</div>
      <div class="chips">
        <button v-for="e in shownCat" :key="e.url" v-tip="e.kind_label + ' · ' + e.url" class="sm chip" @click="quick(e)"><Icon name="plus" />{{ e.name }}</button>
        <button v-if="cat.employers.length > shownCat.length || moreCat" class="sm ghost" @click="moreCat = !moreCat">{{ moreCat ? $t('settings.employers.collapse') : $t('settings.employers.all', { p0: cat.employers.length }) }}</button>
      </div>
    </div>

    <DataTable v-if="rows.length" class="bare emp-table" :columns="COLS" :rows="sorted" row-key="id" density="standard" :row-class="(e) => (e.enabled ? '' : 'emp-off')" :label="$t('settings.employers.employersYouFollow')">
      <template #cell-star="{ row }"><IconButton icon="star" :pressed="!!row.priority" :label="row.priority ? $t('settings.employers.removePriority') : $t('settings.employers.markAsPriority')" @click="patch(row, { priority: !row.priority })" /></template>
      <template #cell-name="{ row }">
        <EntityCell :primary="row.name" :secondary="row.url.replace(/^https?:\/\//, '')">
          <template #after><a v-tip="$t('settings.employers.openPage')" class="icon-btn sm" :href="row.url" target="_blank" rel="noopener" :aria-label="$t('settings.employers.openPage')"><Icon name="external" /></a></template>
        </EntityCell>
      </template>
      <template #cell-kind="{ row }"><Trunc class="meta" :text="row.kind_label" /></template>
      <template #cell-open="{ row }"><span v-if="row.open_jobs" class="num">{{ row.open_jobs }}</span><span v-else class="none">—</span></template>
      <template #cell-on="{ row }"><input type="checkbox" :checked="row.enabled" :aria-label="$t('settings.employers.enableName', { name: row.name })" @change="patch(row, { enabled: !row.enabled })" /></template>
      <template #cell-act="{ row }"><Menu :label="$t('common.more')" :items="[{ id: 'remove', label: $t('settings.employers.remove'), icon: 'trash', danger: true }]" @pick="remove(row)" /></template>
    </DataTable>
    <p v-else class="set-note">{{ $t('settings.employers.noEmployersAddedYet') }}</p>
  </div>
</template>

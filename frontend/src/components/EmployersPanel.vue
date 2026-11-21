<script setup>
import { t as T } from '../i18n/catalog'
// The employers to watch: the user's own list. Paste a careers-page address; the program works out how to read it.
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { ask, run, toast } from '../ui'
import Icon from './Icon.vue'

const rows = ref([])
const form = ref({ name: '', url: '', priority: true })
const hint = ref(null)
const cat = ref({ field: '', employers: [] })
const moreCat = ref(false)
const shownCat = computed(() => (moreCat.value ? cat.value.employers : cat.value.employers.filter((e) => e.match || !cat.value.field).slice(0, 14)))
let t

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
const scan = () => run(() => api.post('/tasks', { kind: 'discover' }), T('settings.employers.scanningWellNotifyYou'))
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="row"><span class="card-title grow">{{ $t('settings.employers.employersYouFollow') }}</span><button @click="scan"><Icon name="search" />{{ $t('settings.employers.scanNow') }}</button></div>
    <p class="muted">{{ $t('settings.employers.companiesYouWantTo') }}</p>

    <div class="emp-add">
      <input v-model="form.url" class="grow" :placeholder="$t('settings.employers.careersPageUrlE')" @keyup.enter="form.url && add()" />
      <input v-model="form.name" style="width: 190px" :placeholder="$t('settings.employers.companyNameOptional')" @keyup.enter="form.url && add()" />
      <label class="nowrap" :title="$t('settings.employers.postingsFromPriorityEmployers')"><input v-model="form.priority" type="checkbox" /> {{ $t('settings.employers.priority') }}</label>
      <button class="primary" :disabled="!form.url.trim()" @click="add"><Icon name="check" />{{ $t('settings.employers.add') }}</button>
    </div>
    <p v-if="hint" class="hint" style="margin: 6px 0 0">{{ $t('settings.employers.detectedAs') }}<b>{{ hint.kind_label }}</b>{{ hint.kind === 'page' ? $t('settings.employers.eachScanUsesThe') : hint.kind === 'feed' ? $t('settings.employers.thisIsAJob') : $t('settings.employers.soItsJobList') }}</p>

    <div v-if="cat.employers.length" class="emp-cat">
      <div class="small muted">{{ $t('settings.employers.readyToAddAddress', { p0: cat.field ? $t('settings.employers.showingOnesRelatedTo') : '' }) }}</div>
      <div class="row" style="gap: 6px; margin-top: 6px">
        <button v-for="e in shownCat" :key="e.url" class="sm chip" :title="e.kind_label + ' · ' + e.url" @click="quick(e)">+ {{ e.name }}</button>
        <button v-if="cat.employers.length > shownCat.length || moreCat" class="sm ghost" @click="moreCat = !moreCat">{{ moreCat ? $t('settings.employers.collapse') : $t('settings.employers.all', { p0: cat.employers.length }) }}</button>
      </div>
    </div>

    <table v-if="rows.length" style="margin-top: 14px">
      <thead><tr><th style="width: 54px">{{ $t('settings.employers.priority') }}</th><th>{{ $t('settings.employers.company') }}</th><th>{{ $t('settings.employers.howToReadIt') }}</th><th>{{ $t('settings.employers.openJobs') }}</th><th style="width: 70px">{{ $t('settings.employers.enable') }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="e in sorted" :key="e.id" :style="e.enabled ? '' : 'opacity: 0.55'">
          <td><button class="star" :class="{ on: e.priority }" :aria-label="e.priority ? $t('settings.employers.removePriority') : $t('settings.employers.markAsPriority')" :title="e.priority ? $t('settings.employers.priorityEmployerClickTo') : $t('settings.employers.clickToMakeA')" @click="patch(e, { priority: !e.priority })">★</button></td>
          <td><b>{{ e.name }}</b><div class="small muted ell" style="max-width: 360px"><a :href="e.url" target="_blank" rel="noopener">{{ e.url.replace(/^https?:\/\//, '') }}</a></div></td>
          <td class="small">{{ e.kind_label }}</td>
          <td class="small">{{ e.open_jobs || '—' }}</td>
          <td><input type="checkbox" :checked="e.enabled" :aria-label="$t('settings.employers.enableName', { name: e.name })" @change="patch(e, { enabled: !e.enabled })" /></td>
          <td style="text-align: right"><button class="sm ghost danger" @click="remove(e)">{{ $t('settings.employers.remove') }}</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted" style="margin-top: 14px">{{ $t('settings.employers.noEmployersAddedYet') }}</p>

    <p class="hint" style="margin-top: 14px">{{ $t('settings.employers.addingRemovingAndThe') }}<router-link to="/settings/automation/prepare">{{ $t('settings.employers.settingsPrepareDraftsAutomatically') }}</router-link>{{ $t('settings.employers.whatIsSearchedFor') }}<router-link to="/settings/goals/search">{{ $t('settings.employers.settingsWhatToSearch') }}</router-link>。</p>
  </div>
</template>

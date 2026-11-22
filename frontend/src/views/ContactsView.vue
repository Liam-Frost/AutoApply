<script setup>
import { t as T } from '../i18n/catalog'
// People you know at employers: who can refer you, who you talked to, when to follow up. Shown next to that employer's postings.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import DataState from '../components/DataState.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import FormError from '../components/FormError.vue'
import Icon from '../components/Icon.vue'
import InfoTip from '../components/InfoTip.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import { dataState } from '../data'
import { dayText } from '../i18n/format'
import { ask, run } from '../ui'

const rows = ref([])
const blank = () => ({ id: 0, name: '', company: '', role: '', relation: '', how: '', status: 'none', follow_up: '', note: '' })
const form = ref(blank())
const editing = ref(false)
const q = ref('')
const STATUS = { none: [T('contacts.notContactedYet'), ''], asked: [T('contacts.contactedAwaitingReply'), 'warn'], referred: [T('contacts.referredMe'), 'ok'], talked: [T('contacts.talkedToThem'), 'info'], declined: [T('contacts.notConvenient'), ''] }
const today = new Date().toISOString().slice(0, 10)
const isDue = (r) => !!r.follow_up && r.follow_up <= today

// What a row must always show is who, where and how far; how you met and the note go first when the box is narrow.
const COLS = [
  { id: 'name', header: T('contacts.name'), min: 150, flex: 2 },
  { id: 'company', header: T('contacts.company'), min: 140, flex: 2 },
  { id: 'relation', header: T('contacts.howYouMet'), min: 140, flex: 2, priority: 1 },
  { id: 'status', header: T('contacts.progress'), min: 120, max: 190 },
  { id: 'follow', header: T('contacts.followUp'), width: 120 },
  { id: 'note', header: T('contacts.notes'), min: 160, flex: 3, priority: 2 },
  { id: 'more', header: '', width: 52, align: 'end' },
]

const shown = computed(() => {
  const n = q.value.trim().toLowerCase()
  return rows.value.filter((r) => !n || `${r.name} ${r.company} ${r.role} ${r.note}`.toLowerCase().includes(n))
})
const due = computed(() => rows.value.filter(isDue).length)
async function read() { rows.value = await api.get('/contacts') }
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
const save = () => run(async () => { await (form.value.id ? api.put('/contacts/' + form.value.id, form.value) : api.post('/contacts', form.value)); form.value = blank(); editing.value = false }, T('contacts.saved'), load, { form: 'contact', name: 'contact-save' })
const add = () => { form.value = blank(); editing.value = true }
const edit = (r) => { form.value = { ...blank(), ...r }; editing.value = true }
const remove = async (r) => (await ask(T('contacts.deleteContact', { p0: r.name }), { danger: true })) && run(() => api.del('/contacts/' + r.id), T('contacts.deleted'), load)
const rowMenu = [{ id: 'edit', label: T('contacts.edit'), icon: 'edit' }, { id: 'delete', label: T('contacts.delete'), icon: 'trash', danger: true }]
const onPick = (id, r) => (id === 'edit' ? edit(r) : remove(r))
onMounted(load)
</script>

<template>
  <PageHead :title="$t('contacts.contactsReferrals')" :help="$t('contacts.peopleYouKnowAt')">
    <button class="primary" @click="add"><Icon name="plus" />{{ $t('contacts.addContact') }}</button>
  </PageHead>
  <DataState :s="st" :what="$t('contacts.contactsReferrals')" @retry="load" />

  <template v-if="st.at">
    <div v-if="!rows.length" class="card"><EmptyState icon="user" :title="$t('contacts.noContactsRecordedYet')" :text="$t('contacts.forExperiencedJobSeekers')" /></div>
    <template v-else>
      <div class="filters">
        <input v-model="q" class="filter-search" type="search" :placeholder="$t('contacts.searchNamesCompaniesOr')" :aria-label="$t('contacts.searchNamesCompaniesOr')" />
        <span v-if="due" class="tag warn">{{ $t('contacts.dueForFollowUp', { p0: due }) }}</span>
        <span class="grow"></span><span class="t-meta atomic">{{ $t('contacts.count', { n: shown.length }, shown.length) }}</span>
      </div>
      <DataTable :columns="COLS" :rows="shown" clickable :label="$t('contacts.contactsReferrals')" @row="edit">
        <template #cell-name="{ row }"><EntityCell :primary="row.name" :secondary="row.role" /></template>
        <template #cell-company="{ row }">
          <EntityCell :primary="row.company" :secondary="row.open_jobs ? $t('contacts.openJobs', { n: row.open_jobs }, row.open_jobs) : ''" :to="row.open_jobs ? { path: '/jobs', query: { q: row.company } } : null" />
        </template>
        <template #cell-relation="{ row }"><EntityCell v-if="row.relation || row.how" :primary="row.relation || row.how" :secondary="row.relation ? row.how : ''" /><span v-else class="none">—</span></template>
        <template #cell-status="{ row }"><Status :tone="(STATUS[row.status] || [])[1]" :label="(STATUS[row.status] || [row.status])[0]" /></template>
        <template #cell-follow="{ row }"><DateTimeCell :primary="dayText(row.follow_up)" :secondary="isDue(row) ? $t('contacts.due') : ''" :tone="isDue(row) ? 'warn' : ''" /></template>
        <template #cell-note="{ row }"><Trunc v-if="row.note" class="t-secondary" :text="row.note" :lines="2" /><span v-else class="none">—</span></template>
        <template #cell-more="{ row }"><Menu :label="$t('common.more')" :items="rowMenu" @pick="(id) => onPick(id, row)" /></template>
        <template #empty><EmptyState icon="search" :title="$t('contacts.noMatch')" /></template>
      </DataTable>
    </template>
  </template>

  <SideDrawer v-if="editing" :title="form.id ? $t('contacts.editContact') : $t('contacts.addContact')" :wide="false" @close="editing = false">
    <form id="contact-form" class="kv" @submit.prevent="save">
      <label for="ct-name">{{ $t('contacts.name') }}</label><input id="ct-name" v-model="form.name" class="w-full" required />
      <label for="ct-company">{{ $t('contacts.company') }} <InfoTip :text="$t('contacts.mustMatchTheCompany')" /></label><input id="ct-company" v-model="form.company" class="w-full" required />
      <label for="ct-role">{{ $t('contacts.job') }}</label><input id="ct-role" v-model="form.role" class="w-full" :placeholder="$t('contacts.optional')" />
      <label for="ct-relation">{{ $t('contacts.howYouMet') }}</label><input id="ct-relation" v-model="form.relation" class="w-full" :placeholder="$t('contacts.eGAlumniFormer')" />
      <label for="ct-how">{{ $t('contacts.contactDetails') }}</label><input id="ct-how" v-model="form.how" class="w-full" :placeholder="$t('contacts.emailLinkedinLinkEtc')" />
      <label>{{ $t('contacts.progress') }}</label><AaSelect v-model="form.status" class="w-full"><option v-for="(v, k) in STATUS" :key="k" :value="k">{{ v[0] }}</option></AaSelect>
      <label for="ct-follow">{{ $t('contacts.followUpDate') }} <InfoTip :text="$t('contacts.onThisDateOverview')" /></label><input id="ct-follow" v-model="form.follow_up" type="date" />
      <label for="ct-note">{{ $t('contacts.notes') }}</label><textarea id="ct-note" v-model="form.note" class="prose" rows="4"></textarea>
    </form>
    <FormError name="contact" />
    <template #footer>
      <span class="grow"></span>
      <button type="button" @click="editing = false">{{ $t('contacts.cancel') }}</button>
      <button type="submit" form="contact-form" class="primary" :disabled="!form.name.trim() || !form.company.trim()"><Icon name="check" />{{ $t('contacts.save') }}</button>
    </template>
  </SideDrawer>
</template>

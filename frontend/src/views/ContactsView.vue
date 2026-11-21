<script setup>
import { t as T } from '../i18n/catalog'
// People you know at employers: who can refer you, who you talked to, when to follow up. Shown next to that employer's postings.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import { ask, run } from '../ui'

const rows = ref([])
const blank = () => ({ id: 0, name: '', company: '', role: '', relation: '', how: '', status: 'none', follow_up: '', note: '' })
const form = ref(blank())
const editing = ref(false)
const q = ref('')
const STATUS = { none: [T('contacts.notContactedYet'), ''], asked: [T('contacts.contactedAwaitingReply'), 'warn'], referred: [T('contacts.referredMe'), 'ok'], talked: [T('contacts.talkedToThem'), 'info'], declined: [T('contacts.notConvenient'), ''] }
const today = new Date().toISOString().slice(0, 10)

const shown = computed(() => {
  const n = q.value.trim().toLowerCase()
  return rows.value.filter((r) => !n || `${r.name} ${r.company} ${r.role} ${r.note}`.toLowerCase().includes(n))
})
const due = computed(() => rows.value.filter((r) => r.follow_up && r.follow_up <= today).length)
async function load() { rows.value = await api.get('/contacts') }
const save = () => run(async () => { await (form.value.id ? api.put('/contacts/' + form.value.id, form.value) : api.post('/contacts', form.value)); form.value = blank(); editing.value = false }, T('contacts.saved'), load)
const edit = (r) => { form.value = { ...r }; editing.value = true; window.scrollTo({ top: 0, behavior: 'smooth' }) }
const remove = async (r) => (await ask(T('contacts.deleteContact', { p0: r.name }))) && run(() => api.del('/contacts/' + r.id), T('contacts.deleted'), load)
onMounted(load)
</script>

<template>
  <PageHead :title="$t('contacts.contactsReferrals')" :sub="$t('contacts.peopleYouKnowAt')">
    <button class="primary" @click="form = blank(); editing = !editing"><Icon name="edit" />{{ editing ? $t('contacts.collapse') : $t('contacts.addContact') }}</button>
  </PageHead>

  <div v-if="editing" class="card">
    <div class="card-title">{{ form.id ? $t('contacts.editContact') : $t('contacts.addContact') }}</div>
    <div class="kv" style="margin-top: 12px">
      <label>{{ $t('contacts.name') }}</label><input v-model="form.name" />
      <label>{{ $t('contacts.company') }}</label><input v-model="form.company" :placeholder="$t('contacts.mustMatchTheCompany')" />
      <label>{{ $t('contacts.job') }}</label><input v-model="form.role" :placeholder="$t('contacts.optional')" />
      <label>{{ $t('contacts.howYouMet') }}</label><input v-model="form.relation" :placeholder="$t('contacts.eGAlumniFormer')" />
      <label>{{ $t('contacts.contactDetails') }}</label><input v-model="form.how" :placeholder="$t('contacts.emailLinkedinLinkEtc')" />
      <label>{{ $t('contacts.progress') }}</label><AaSelect v-model="form.status"><option v-for="(v, k) in STATUS" :key="k" :value="k">{{ v[0] }}</option></AaSelect>
      <label>{{ $t('contacts.followUpDate') }}</label><div><input v-model="form.follow_up" type="date" style="width: 180px" /> <span class="hint">{{ $t('contacts.onThisDateOverview') }}</span></div>
      <label>{{ $t('contacts.notes') }}</label><textarea v-model="form.note" rows="3" style="font-family: inherit; min-height: 0"></textarea>
    </div>
    <div class="row" style="margin-top: 12px"><button class="primary" :disabled="!form.name.trim() || !form.company.trim()" @click="save"><Icon name="check" />{{ $t('contacts.save') }}</button><button @click="editing = false">{{ $t('contacts.cancel') }}</button></div>
  </div>

  <div v-if="rows.length" class="filters">
    <input v-model="q" :placeholder="$t('contacts.searchNamesCompaniesOr')" style="width: 260px" />
    <span v-if="due" class="badge warn">{{ $t('contacts.dueForFollowUp', { p0: due }) }}</span>
    <span class="grow"></span><span class="muted small">{{ $t('contacts.people', { p0: shown.length }) }}</span>
  </div>
  <div class="table-wrap" style="max-height: none">
    <table v-if="rows.length">
      <thead><tr><th>{{ $t('contacts.name') }}</th><th>{{ $t('contacts.company') }}</th><th>{{ $t('contacts.howYouMet') }}</th><th>{{ $t('contacts.progress') }}</th><th>{{ $t('contacts.followUp') }}</th><th>{{ $t('contacts.notes') }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in shown" :key="r.id">
          <td><b>{{ r.name }}</b><div class="small muted">{{ r.role }}</div></td>
          <td>{{ r.company }}<div v-if="r.open_jobs" class="small"><router-link :to="{ path: '/jobs', query: { q: r.company } }">{{ $t('contacts.openPostings', { p0: r.open_jobs }) }}</router-link></div></td>
          <td class="small">{{ r.relation }}<div v-if="r.how" class="muted ell" style="max-width: 200px">{{ r.how }}</div></td>
          <td><span class="badge" :class="(STATUS[r.status] || [])[1]">{{ (STATUS[r.status] || [r.status])[0] }}</span></td>
          <td class="small nowrap"><span v-if="r.follow_up" :style="r.follow_up <= today ? 'color: var(--warn); font-weight: 600' : ''">{{ r.follow_up }}</span><span v-else class="muted">—</span></td>
          <td class="small muted" style="max-width: 320px"><div class="clamp2">{{ r.note }}</div></td>
          <td><div class="row" style="flex-wrap: nowrap"><button class="sm" @click="edit(r)">{{ $t('contacts.edit') }}</button><button class="sm ghost danger" @click="remove(r)">{{ $t('contacts.delete') }}</button></div></td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-else icon="user" :title="$t('contacts.noContactsRecordedYet')" :text="$t('contacts.forExperiencedJobSeekers')" />
  </div>
</template>

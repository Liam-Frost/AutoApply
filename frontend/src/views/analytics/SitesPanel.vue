<script setup>
import { t as T } from '../../i18n/catalog'
// What the agent wrote down about the sites it worked: the notes it left for the next application there, and what
// is known about how the site signs in. One row a site; a row opened shows its notes. Clearing a site takes its
// notes and leaves its sign-in.
import { computed, ref } from 'vue'
import { api } from '../../api'
import { ask, toast } from '../../ui'
import { stampDay } from '../../i18n/format'
import EmptyState from '../../components/EmptyState.vue'

const props = defineProps({ d: { type: Array, required: true } })
const emit = defineEmits(['reload'])

// a recruiting system's notes hold for every employer on it; a sign-in provider has no notes of its own
const rows = computed(() => props.d.filter((r) => r.notes && !r.key.startsWith('idp:')))
const shown = (r) => r.employer || r.name
const site = ref(null)
async function show(row) {
  if (site.value && site.value.key === row.key) { site.value = null; return }
  try { site.value = await api.get(`/sites/${encodeURIComponent(row.key)}`) } catch (e) { toast(e.message, 'bad') }
}
async function forget(row) {
  if (!(await ask({ title: T('analytics.sites.clearTheNotesAbout'), text: T('analytics.sites.theAgentWillFind'), ok: T('analytics.sites.clear'), danger: true }))) return
  try { await api.post(`/sites/${encodeURIComponent(row.key)}/forget`); site.value = null; emit('reload') } catch (e) { toast(e.message, 'bad') }
}
</script>

<template>
  <div class="card">
    <div class="card-title">{{ $t('analytics.sites.notesTheAgentKeeps') }}</div>
    <p class="muted">{{ $t('analytics.sites.withEveryApplicationThe') }}</p>
    <EmptyState v-if="!rows.length" icon="wrench" :title="$t('analytics.sites.noNotesYet')" :text="$t('analytics.sites.onceTheAgentHas')" />
    <div v-else class="an-scroll">
      <table class="an-table">
        <thead><tr><th>{{ $t('analytics.sites.website') }}</th><th>{{ $t('analytics.sites.scope') }}</th><th class="num">{{ $t('analytics.sites.notes') }}</th><th>{{ $t('analytics.sites.lastUpdated') }}</th><th></th></tr></thead>
        <tbody>
          <template v-for="row in rows" :key="row.key">
            <tr style="cursor: pointer" @click="show(row)">
              <td class="name" data-notr>{{ shown(row) }}</td>
              <td class="small muted">{{ row.key.startsWith('system:') ? $t('analytics.sites.theWholeRecruitingSystem') : $t('analytics.sites.thisSiteOnly') }}</td>
              <td class="num">{{ row.notes }}</td>
              <td class="small muted nowrap">{{ stampDay(row.updated) }}</td>
              <td class="nowrap" @click.stop><button class="sm ghost danger" @click="forget(row)">{{ $t('analytics.sites.clear') }}</button></td>
            </tr>
            <tr v-if="site && site.key === row.key">
              <td colspan="5" style="background: var(--surface-2)">
                <div v-if="site.signs_in_on" class="small muted">{{ $t('analytics.sites.itsSignInIs') }}<span data-notr>{{ site.signs_in_on.replace(/^(generic:|idp:)/, '') }}</span></div>
                <ul class="small" style="margin: 4px 0 0 18px"><li v-for="(n, i) in site.notes" :key="i" data-notr>{{ n.at ? '（' + n.at + '）' : '' }}{{ n.text }}</li></ul>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

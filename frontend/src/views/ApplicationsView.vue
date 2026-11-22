<script setup>
import { t as T } from '../i18n/catalog'
// Applications: every one the applicant began, from preparing it to its outcome (plan §8.4). Listed by where it stands,
// with whose move it is and, when it is the applicant's, the one thing to press. What was the drafts page is the
// "Waiting for you" group here; each row opens the application's own page.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ROOT } from '../api'
import DataState from '../components/DataState.vue'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import { dataState, useRefresh } from '../data'
import { deadlineLabel, keepVisible } from '../dates'
import { fromQuery, sameQuery, toQuery } from '../urlstate'
import { ask, fmtTime, run } from '../ui'
import { dateTimeOf, shortDayText, stampDay, asDate } from '../i18n/format'

const route = useRoute()
const router = useRouter()
const rows = ref([])
const GROUPS = ['me', 'agent', 'sent', 'progress', 'ended', 'archived']
const WHO = { me: ['applications.who.me', 'warn'], agent: ['applications.who.agent', 'info'], them: ['applications.who.them', ''] }
const ACT = { answer: 'applications.act.answer', approve: 'applications.act.approve', handle: 'applications.act.handle', rerun: 'applications.act.rerun', budget: 'applications.act.budget', check_mail: 'applications.act.checkMail' }
const f = reactive({ group: '', q: '', who: '', ats: '' })
const picked = ref(new Set())

async function read() { rows.value = (await api.get('/applications')).applications }
const count = (g) => rows.value.filter((r) => r.group === g).length
const inGroup = computed(() => rows.value.filter((r) => r.group === f.group))
const atsOptions = computed(() => [...new Set(inGroup.value.map((r) => r.ats_label).filter(Boolean))].sort())
const shown = computed(() => {
  const needle = f.q.trim().toLowerCase()
  const out = inGroup.value.filter((r) => (!f.who || r.who === f.who) && (!f.ats || r.ats_label === f.ats)
    && (!needle || `${r.company} ${r.title} ${r.location || ''}`.toLowerCase().includes(needle)))
  // what waits for the applicant or the agent: the nearest deadline first; the rest: the latest change first
  const byDeadline = ['me', 'agent'].includes(f.group)
  return out.sort((a, b) => (byDeadline ? (a.deadline || '9999').localeCompare(b.deadline || '9999') : 0) || (b.updated_at || '').localeCompare(a.updated_at || ''))
})
function pickGroup(g) { f.group = g; picked.value = new Set() }

// --- the date column: the deadline of what is not sent yet; else the next thing on the calendar ---------------------------
function dateOf(r) {
  if (r.next_date) return { text: r.next_date.all_day ? shortDayText(r.next_date.start) : dateTimeOf(asDate(r.next_date.start)), what: r.next_date.title, tone: '' }
  if (r.deadline) {
    const dl = deadlineLabel(r.deadline)
    return { text: shortDayText(r.deadline), what: dl.text, tone: dl.tone === 'soon' ? 'warn' : dl.tone === 'past' ? 'muted' : '' }
  }
  return null
}

// --- the one thing to press on a row ----------------------------------------------------------------------------------
async function press(r) {
  if (r.act === 'answer' || r.act === 'approve') return router.push(`/applications/${r.id}#record`)
  if (r.act === 'handle') return router.push(`/applications/${r.id}`)
  if (r.act === 'rerun') return run(() => api.post(`/jobs/${r.job_id}/draft`, {}), T('applications.rerunStarted'), load)
  if (r.act === 'budget') return run(() => api.post(`/applications/${r.id}/budget`), T('applications.budgetGiven'), load)
  if (r.act === 'check_mail') return run(() => api.post(`/applications/${r.id}/check-mail`), T('applications.checkingMail'), load)
}

// --- several at once ----------------------------------------------------------------------------------------------------
watch(() => shown.value, (now) => { picked.value = keepVisible(picked.value, now) })
const allPicked = computed(() => shown.value.length > 0 && shown.value.every((r) => picked.value.has(r.id)))
function togglePick(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function toggleAll() { picked.value = allPicked.value ? new Set() : new Set(shown.value.map((r) => r.id)) }
const exportUrl = computed(() => ROOT + '/api/applications.csv' + (picked.value.size ? '?ids=' + [...picked.value].join(',') : ''))
const said = (r, done) => T('applications.bulkDone', { n: r.done }, r.done) + (r.skipped ? T('applications.bulkSkipped', { n: r.skipped, why: Object.values(r.errors || {}).filter(Boolean)[0] || '' }, r.skipped) : '') + (done ? ' ' + done : '')
async function bulk(action) {
  const ids = [...picked.value]
  if (action === 'withdraw' && !(await ask(T('applications.withdrawAsk', { n: ids.length }, ids.length), { ok: T('applications.bulk.withdraw') }))) return
  if ((await run(() => api.post('/applications/bulk', { action, ids }), (r) => said(r), load)) !== false) picked.value = new Set()
}
// Approving several: each one's open answers and changes are listed first; only what has nothing open is approved.
const review = ref(null)
async function openReview() {
  review.value = { loading: true, items: [] }
  try { review.value = { loading: false, items: await api.get('/applications/review?ids=' + [...picked.value].join(',')) } } catch (e) { review.value = null; throw e }
}
const approvable = computed(() => (review.value ? review.value.items.filter((x) => x.can) : []))
async function approveReviewed() {
  const ids = approvable.value.map((x) => x.id)
  if ((await run(() => api.post('/applications/bulk', { action: 'approve', ids }), (r) => said(r), load)) !== false) { review.value = null; picked.value = new Set() }
}
const mailNow = () => run(() => api.post('/tasks', { kind: 'mail' }), T('applications.checkingMailbox'))

// --- what the list shows is in the address (?group=me&q=...) ----------------------------------------------------------
const LIST0 = { group: '', q: '', who: '', ats: '' }
function readAddress() {
  const st = fromQuery(route.query, LIST0)
  Object.assign(f, st)
  if (!GROUPS.includes(f.group)) f.group = ''
}
readAddress()
watch(() => ({ ...f }), (now) => { const q = toQuery(now, LIST0); if (!sameQuery(q, route.query)) router.replace({ query: q }) }, { deep: true })
watch(() => route.query, (q) => { if (!sameQuery(q, toQuery({ ...f }, LIST0))) readAddress() })
const { st, load } = dataState(read)
useRefresh(load)
onMounted(async () => {
  await load()
  // Opened without a group: what waits for the applicant, or - when nothing does - the first group that has anything.
  if (!f.group) f.group = GROUPS.find((g) => g !== 'archived' && count(g)) || 'me'
})
</script>

<template>
  <PageHead :title="$t('applications.title')" :sub="$t('applications.sub')">
    <button @click="mailNow"><Icon name="mail" />{{ $t('applications.checkMailbox') }}</button>
    <a class="btn ghost" :href="exportUrl" download><Icon name="table" />{{ picked.size ? $t('applications.exportPicked', { n: picked.size }) : $t('applications.export') }}</a>
  </PageHead>
  <DataState :s="st" :what="$t('applications.what')" @retry="load" />
  <template v-if="st.at">
    <div class="seg" style="margin-bottom: 12px" role="group" :aria-label="$t('applications.groupsLabel')">
      <button v-for="g in GROUPS" :key="g" :class="{ on: f.group === g }" @click="pickGroup(g)">{{ $t('applications.group.' + g) }}<span class="n">{{ count(g) }}</span></button>
    </div>

    <div class="filters">
      <input v-model="f.q" :placeholder="$t('applications.search')" :aria-label="$t('applications.search')" style="width: 220px" />
      <AaSelect v-model="f.who" :aria-label="$t('applications.whoFilter')"><option value="">{{ $t('applications.whoAll') }}</option><option v-for="(v, k) in WHO" :key="k" :value="k">{{ $t(v[0]) }}</option></AaSelect>
      <AaSelect v-if="atsOptions.length > 1" v-model="f.ats" :aria-label="$t('applications.atsFilter')"><option value="">{{ $t('applications.atsAll') }}</option><option v-for="x in atsOptions" :key="x" :value="x">{{ x }}</option></AaSelect>
      <span class="grow"></span>
      <span class="muted small nowrap">{{ $t('applications.count', { n: shown.length }, shown.length) }}</span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width: 36px"><input type="checkbox" :checked="allPicked" :aria-label="$t('applications.pickAll')" @change="toggleAll" /></th>
            <th>{{ $t('applications.col.job') }}</th><th>{{ $t('applications.col.stage') }}</th><th>{{ $t('applications.col.next') }}</th><th>{{ $t('applications.col.date') }}</th>
            <th class="col-more">{{ $t('applications.col.sent') }}</th><th class="col-more">{{ $t('applications.col.latest') }}</th><th class="col-more">{{ $t('applications.col.updated') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in shown" :key="r.id" class="clickable" @click="router.push('/applications/' + r.id)">
            <td @click.stop><input type="checkbox" :checked="picked.has(r.id)" :aria-label="$t('applications.pick', { name: r.company })" @change="togglePick(r.id)" /></td>
            <td class="jobcell"><div><router-link class="rowlink" :to="'/applications/' + r.id" @click.stop><b>{{ r.company }}</b></router-link></div><div>{{ r.title }}</div></td>
            <td class="nowrap"><span class="tag" :class="r.tone">{{ r.stage_label }}</span></td>
            <td style="min-width: 240px">
              <div><span v-if="r.who && WHO[r.who]" class="tag" :class="WHO[r.who][1]">{{ $t(WHO[r.who][0]) }}</span> <span class="small">{{ r.next }}</span></div>
              <button v-if="r.act && ACT[r.act]" class="sm primary" style="margin-top: 6px" @click.stop="press(r)">{{ $t(ACT[r.act]) }}</button>
            </td>
            <td class="small nowrap"><template v-if="dateOf(r)">{{ dateOf(r).text }}<span v-if="dateOf(r).what" class="tag" :class="dateOf(r).tone" style="margin-left: 6px" :title="dateOf(r).what">{{ dateOf(r).what }}</span></template><span v-else class="muted">—</span></td>
            <td class="small nowrap col-more">{{ stampDay(r.submitted_at) || '—' }}</td>
            <td class="small muted col-more" style="max-width: 260px"><div class="clamp2">{{ r.last_event }}</div></td>
            <td class="small nowrap muted col-more">{{ fmtTime(r.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" icon="briefcase" :title="$t('applications.emptyTitle')" :text="$t('applications.emptyText')"><router-link to="/jobs" class="btn">{{ $t('applications.toPostings') }}</router-link></EmptyState>
      <EmptyState v-else-if="!shown.length" icon="check" :title="$t('applications.groupEmpty.' + f.group)" :text="f.q || f.who || f.ats ? $t('applications.filteredOut') : ''" />
    </div>

    <div v-if="picked.size" class="bulkbar">
      <b>{{ $t('applications.picked', { n: picked.size }, picked.size) }}</b>
      <button v-if="f.group === 'me'" class="sm primary" @click="openReview">{{ $t('applications.bulk.approve') }}</button>
      <button v-if="['me', 'agent', 'ended'].includes(f.group)" class="sm" @click="bulk('rerun')">{{ $t('applications.bulk.rerun') }}</button>
      <button v-if="['me', 'agent'].includes(f.group)" class="sm" @click="bulk('withdraw')">{{ $t('applications.bulk.withdraw') }}</button>
      <button v-if="f.group !== 'archived'" class="sm" @click="bulk('archive')">{{ $t('applications.bulk.archive') }}</button>
      <button v-else class="sm" @click="bulk('unarchive')">{{ $t('applications.bulk.unarchive') }}</button>
      <a class="btn sm ghost" :href="exportUrl" download>{{ $t('applications.export') }}</a>
      <button class="sm ghost" style="border-color: transparent" @click="picked = new Set()">{{ $t('applications.unpick') }}</button>
    </div>

    <SideDrawer v-if="review" :title="$t('applications.reviewTitle', { n: picked.size }, picked.size)" :sub="$t('applications.reviewSub')" @close="review = null">
      <div v-if="review.loading" class="muted" style="margin-top: 12px">{{ $t('applications.reviewLoading') }}</div>
      <template v-else>
        <div v-for="x in review.items" :key="x.id" class="card" style="margin-top: 12px">
          <div class="row"><b class="grow">{{ x.company }} · {{ x.title }}</b><router-link :to="'/applications/' + x.id + '#record'" class="small" @click="review = null">{{ $t('applications.reviewOpen') }}</router-link></div>
          <div v-if="!x.draft_id" class="small muted" style="margin-top: 6px">{{ $t('applications.reviewNothing') }}</div>
          <div v-else-if="x.unresolved" class="small" style="margin-top: 6px"><span class="tag bad">{{ $t('applications.reviewOpenQuestions', { n: x.unresolved }, x.unresolved) }}</span></div>
          <template v-else>
            <div v-if="x.unsure.length" class="small" style="margin-top: 6px"><div class="muted">{{ $t('applications.reviewUnsure') }}</div><ul style="margin: 4px 0; padding-left: 18px"><li v-for="u in x.unsure" :key="u">{{ u }}</li></ul></div>
            <div v-if="x.changed.length" class="small" style="margin-top: 6px"><div class="muted">{{ $t('applications.reviewChanged') }}</div><ul style="margin: 4px 0; padding-left: 18px"><li v-for="c in x.changed" :key="c">{{ c }}</li></ul></div>
            <div v-if="!x.unsure.length && !x.changed.length" class="small muted" style="margin-top: 6px">{{ $t('applications.reviewClean') }}</div>
          </template>
        </div>
        <div class="row" style="position: sticky; bottom: 0; background: var(--surface); padding: 12px 0; margin-top: 8px">
          <button class="primary" :disabled="!approvable.length" @click="approveReviewed">{{ $t('applications.reviewApprove', { n: approvable.length }, approvable.length) }}</button>
          <button class="ghost" @click="review = null">{{ $t('applications.cancel') }}</button>
        </div>
      </template>
    </SideDrawer>
  </template>
</template>

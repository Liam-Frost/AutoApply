<script setup>
import { t as T, lang } from '../i18n/catalog'
// Applications: every one the applicant began, from preparing it to its outcome (plan §8.4). Listed by where it stands,
// with whose move it is and, when it is the applicant's, the one thing to press. What was the drafts page is the
// "Action required" group here; each row opens the application's own page.
//
// A column says one thing: the stage is where the hiring stands, the next step is what to do (and whose move it is),
// the next event is a dated point, the latest is what happened last - in a few words; the application's page has the
// whole of each.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ROOT } from '../api'
import BulkBar from '../components/BulkBar.vue'
import DataState from '../components/DataState.vue'
import DataTable from '../components/DataTable.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EmptyState from '../components/EmptyState.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import Icon from '../components/Icon.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import Status from '../components/Status.vue'
import Tabs from '../components/Tabs.vue'
import Trunc from '../components/Trunc.vue'
import { at } from '../calendar'
import { dataState, useRefresh } from '../data'
import { deadlineLabel, keepVisible, parseDeadline } from '../dates'
import { fromQuery, sameQuery, toQuery } from '../urlstate'
import { ask, fmtTime, run } from '../ui'
import { dateOf, dateTimeOf, stampDay } from '../i18n/format'

const route = useRoute()
const router = useRouter()
const rows = ref([])
const GROUPS = ['me', 'agent', 'sent', 'progress', 'ended', 'archived']
const WHO = { me: 'applications.who.me', agent: 'applications.who.agent', them: 'applications.who.them' }
const ACT = { answer: 'applications.act.answer', approve: 'applications.act.approve', handle: 'applications.act.handle', rerun: 'applications.act.rerun', budget: 'applications.act.budget', check_mail: 'applications.act.checkMail' }
const f = reactive({ group: '', q: '', who: '', ats: '' })
const picked = ref(new Set())

async function read() { rows.value = (await api.get('/applications')).applications }
const count = (g) => rows.value.filter((r) => r.group === g).length
const inGroup = computed(() => rows.value.filter((r) => r.group === f.group))
const atsOptions = computed(() => [...new Set(inGroup.value.map((r) => r.ats_label).filter(Boolean))].sort())
// (a group is mostly one owner's: the filter is offered where it can tell rows apart - or is set and must be seen to be cleared)
const whoOptions = computed(() => Object.keys(WHO).filter((k) => inGroup.value.some((r) => r.who === k)))
const shown = computed(() => {
  const needle = f.q.trim().toLowerCase()
  const out = inGroup.value.filter((r) => (!f.who || r.who === f.who) && (!f.ats || r.ats_label === f.ats)
    && (!needle || `${r.company} ${r.title} ${r.location || ''}`.toLowerCase().includes(needle)))
  // what waits for the applicant or the agent: the nearest deadline first; the rest: the latest change first
  const byDeadline = ['me', 'agent'].includes(f.group)
  return out.sort((a, b) => (byDeadline ? (a.deadline || '9999').localeCompare(b.deadline || '9999') : 0) || (b.updated_at || '').localeCompare(a.updated_at || ''))
})
function pickGroup(g) { f.group = g; picked.value = new Set() }
// (whose move it is says something only where the rows differ: when one owner has every row shown, the group says it)
const oneOwner = computed(() => new Set(shown.value.map((r) => r.who).filter(Boolean)).size <= 1)

// --- the columns: what must stay, and what goes first when the table is narrow (the highest priority first). Words in
// a Latin script take more room than the same in Chinese: there the columns that hold phrases get their comfortable
// width when the box has room for it (the optional columns give way), and a tighter one in a narrow window.
const box = ref(null)
const boxWidth = ref(0)
let sized = null
watch(box, (el) => {
  sized?.disconnect()
  if (!el || typeof ResizeObserver === 'undefined') return
  sized = new ResizeObserver(() => { boxWidth.value = el.clientWidth })
  sized.observe(el)
})
onBeforeUnmount(() => sized?.disconnect())
const columns = computed(() => {
  const latin = !/^(zh|ja|ko)/.test(lang.value)
  const wide = latin && boxWidth.value >= 900
  const narrow = boxWidth.value > 0 && boxWidth.value < 760      // (a phone-wide window: the four that stay, at their least)
  const [job, stage, next, schedule] = narrow ? (latin ? [184, 104, 144, 136] : [200, 88, 140, 132])
    : !latin ? [232, 96, 160, 140] : wide ? [240, 168, 172, 148] : [204, 120, 164, 144]
  return [
    { id: 'job', header: T('applications.col.job'), min: job, max: 360, flex: 4 },
    { id: 'stage', header: T('applications.col.stage'), min: stage, max: latin ? 176 : 128, flex: 2 },      // (a stage cut short says little: it is next to take what room is left)
    { id: 'next', header: T('applications.col.next'), min: next, max: 220, flex: 1 },
    { id: 'schedule', header: T('applications.col.schedule'), min: schedule, max: 168, flex: 1 },
    // (a group where nothing has gone out has no use for the day it went out: the room goes to the posting)
    ...(shown.value.some((r) => r.submitted_at) ? [{ id: 'sent', header: T('applications.col.sent'), min: 104, max: 120, flex: 0, priority: 1 }] : []),
    { id: 'latest', header: T('applications.col.latest'), min: 160, max: 240, flex: 1, priority: 3 },
    { id: 'updated', header: T('applications.col.updated'), min: 112, max: 136, flex: 0, priority: 2 },
    { id: 'more', header: '', width: 44, align: 'end' },
  ]
})

// --- stage: a filled tag for the few that must be seen - a dated step of the hiring (in the calendar's colour of its
// kind), a failure, something that waits on the applicant with nothing else moving; the rest a dot and words
const EV = { interview: 'ev-interview', assessment: 'ev-assessment', offer: 'ev-offer' }
const LOUD = ['needs_human', 'waiting', 'failed']

// --- the next event: the next item on the calendar (its time is the applicant's own clock, as the calendar reads it);
// for an application that has not gone out, the posting's deadline
function eventOf(r) {
  const x = r.next_date
  if (x) {
    const d = at(x)
    const kind = T('calendar.kind.' + x.kind)
    const passed = !x.all_day && d.getTime() < Date.now()
    return { primary: x.all_day ? dateOf(d) : dateTimeOf(d), secondary: kind, tone: passed ? 'muted' : '', tip: T('applications.eventTip', { kind, title: x.title || '' }) }
  }
  const d = ['me', 'agent'].includes(r.group) || (r.group === 'archived' && !r.sent) ? parseDeadline(r.deadline) : null
  if (!d) return null
  const dl = deadlineLabel(r.deadline)
  return { primary: dateOf(d), secondary: dl.text, tone: dl.tone === 'soon' ? 'warn' : dl.tone === 'past' ? 'muted' : '', tip: T('applications.dueTip', { when: dateTimeOf(d) }) }
}

// --- the one thing to press on a row ----------------------------------------------------------------------------------
async function press(r) {
  if (r.act === 'answer' || r.act === 'approve') return router.push(`/applications/${r.id}#record`)
  if (r.act === 'handle') return router.push(`/applications/${r.id}`)
  if (r.act === 'rerun') return run(() => api.post(`/jobs/${r.job_id}/draft`, {}), T('applications.rerunStarted'), load)
  if (r.act === 'budget') return run(() => api.post(`/applications/${r.id}/budget`), T('applications.budgetGiven'), load)
  if (r.act === 'check_mail') return run(() => api.post(`/applications/${r.id}/check-mail`), T('applications.checkingMail'), load)
}

// --- several at once, and the same for one row (its menu) -------------------------------------------------------------
watch(() => shown.value, (now) => { picked.value = keepVisible(picked.value, now) })
const exportUrl = (ids) => ROOT + '/api/applications.csv' + (ids && ids.size ? '?ids=' + [...ids].join(',') : '')
const said = (r) => T('applications.bulkDone', { n: r.done }, r.done) + (r.skipped ? T('applications.bulkSkipped', { n: r.skipped, why: Object.values(r.errors || {}).filter(Boolean)[0] || '' }, r.skipped) : '')
// -> false when it was not done (the applicant said no, or the server did)
async function several(action, ids) {
  if (action === 'withdraw' && !(await ask(T('applications.withdrawAsk', { n: ids.length }, ids.length), { ok: T('applications.bulk.withdraw'), danger: true }))) return false
  return run(() => api.post('/applications/bulk', { action, ids }), (r) => said(r), load)
}
async function bulk(action) { if ((await several(action, [...picked.value])) !== false) picked.value = new Set() }
// what a row can do besides its main action: what the bar offers for its group, where it applies to this row
const canRerun = (r) => ['me', 'agent', 'ended'].includes(r.group) && !r.sent && !r.unknown && r.status !== 'withdrawn'
const canWithdraw = (r) => ['me', 'agent'].includes(r.group) && !r.sent && !r.unknown
function menuOf(r) {
  return [
    { id: 'job', label: T('applications.row.openJob'), icon: 'briefcase' },
    ...(r.apply_url ? [{ id: 'link', label: T('applications.row.openLink'), icon: 'external' }] : []),
    { divider: true },
    ...(canRerun(r) ? [{ id: 'rerun', label: T('applications.bulk.rerun'), icon: 'refresh' }] : []),
    ...(canWithdraw(r) ? [{ id: 'withdraw', label: T('applications.bulk.withdraw'), icon: 'x' }] : []),
    r.archived ? { id: 'unarchive', label: T('applications.bulk.unarchive'), icon: 'inbox' } : { id: 'archive', label: T('applications.bulk.archive'), icon: 'inbox' },
  ]
}
function onMenu(r, id) {
  if (id === 'job') return router.push({ path: '/jobs', query: { open: r.job_id } })
  if (id === 'link') return window.open(r.apply_url, '_blank', 'noopener')
  return several(id, [r.id])
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
// (reads the mailbox for messages about applications and updates them: nothing is written back to the mailbox)
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
  <PageHead :title="$t('applications.title')">
    <button @click="mailNow"><Icon name="mail" />{{ $t('applications.checkMailbox') }}</button>
    <a class="btn" :href="exportUrl()" download><Icon name="download" />{{ $t('applications.export') }}</a>
  </PageHead>
  <DataState :s="st" :what="$t('applications.what')" @retry="load" />
  <template v-if="st.at">
    <Tabs class="list-tabs" :model-value="f.group" :label="$t('applications.groupsLabel')" :items="GROUPS.map((g) => ({ id: g, label: $t('applications.group.' + g), count: count(g) }))" @update:model-value="pickGroup" />

    <div class="filters" role="group" :aria-label="$t('applications.filters')">
      <input v-model="f.q" class="search" type="search" :placeholder="$t('applications.search')" :aria-label="$t('applications.search')" />
      <AaSelect v-if="whoOptions.length > 1 || f.who" v-model="f.who" :aria-label="$t('applications.whoFilter')"><option value="">{{ $t('applications.whoAll') }}</option><option v-for="k in Object.keys(WHO)" :key="k" :value="k">{{ $t(WHO[k]) }}</option></AaSelect>
      <AaSelect v-if="atsOptions.length > 1 || f.ats" v-model="f.ats" :aria-label="$t('applications.atsFilter')"><option value="">{{ $t('applications.atsAll') }}</option><option v-for="x in atsOptions" :key="x" :value="x">{{ x }}</option></AaSelect>
      <span class="grow"></span>
      <span class="count">{{ $t('applications.count', { n: shown.length }, shown.length) }}</span>
    </div>

    <div ref="box">
    <DataTable v-model:selected="picked" :columns="columns" :rows="shown" row-key="id" density="comfortable" selectable clickable :label="$t('applications.title')"
               :select-all-label="$t('applications.pickAll')" :select-label="(r) => $t('applications.pick', { name: r.company })" @row="(r) => router.push('/applications/' + r.id)">
      <template #cell-job="{ row }"><EntityCell :primary="row.company" :secondary="row.title" :to="'/applications/' + row.id" /></template>
      <template #cell-stage="{ row }">
        <Trunc v-if="EV[row.stage]" class="tag ev-tag" :class="EV[row.stage]" :text="row.stage_label" />
        <Trunc v-else-if="LOUD.includes(row.stage)" class="tag" :class="row.tone" :text="row.stage_label" />
        <Status v-else :tone="row.tone" :label="row.stage_label" />
      </template>
      <template #cell-next="{ row }">
        <div v-if="row.who && (row.next || row.act)" class="next-step">
          <button v-if="row.act && ACT[row.act]" class="sm ghost" @click.stop="press(row)">{{ $t(ACT[row.act]) }}</button>
          <Trunc v-else class="next-what" :text="row.next" />
          <span v-if="WHO[row.who] && !oneOwner" class="t-meta atomic">{{ $t('applications.owner', { who: $t(WHO[row.who]) }) }}</span>
        </div>
        <span v-else class="none">—</span>
      </template>
      <template #cell-schedule="{ row }">
        <DateTimeCell v-if="eventOf(row)" v-bind="eventOf(row)" />
        <span v-else class="none">—</span>
      </template>
      <template #cell-sent="{ row }"><span v-if="row.submitted_at" class="num atomic">{{ stampDay(row.submitted_at) }}</span><span v-else class="none">—</span></template>
      <template #cell-latest="{ row }"><Trunc v-if="row.latest" class="t-secondary" :text="row.latest" /><span v-else class="none">—</span></template>
      <template #cell-updated="{ row }"><span class="t-secondary num atomic">{{ fmtTime(row.updated_at) }}</span></template>
      <template #cell-more="{ row }"><Menu :label="$t('applications.row.menu')" :items="menuOf(row)" @pick="(id) => onMenu(row, id)" /></template>
      <template #empty>
        <EmptyState v-if="!rows.length" icon="briefcase" :title="$t('applications.emptyTitle')" :text="$t('applications.emptyText')"><router-link to="/jobs" class="btn">{{ $t('applications.toPostings') }}</router-link></EmptyState>
        <EmptyState v-else icon="check" :title="$t('applications.groupEmpty.' + f.group)" :text="f.q || f.who || f.ats ? $t('applications.filteredOut') : ''" />
      </template>
    </DataTable>
    </div>

    <BulkBar :count="picked.size" @clear="picked = new Set()">
      <button v-if="f.group === 'me'" class="sm primary" @click="openReview">{{ $t('applications.bulk.approve') }}</button>
      <button v-if="['me', 'agent', 'ended'].includes(f.group)" class="sm" @click="bulk('rerun')">{{ $t('applications.bulk.rerun') }}</button>
      <button v-if="['me', 'agent'].includes(f.group)" class="sm" @click="bulk('withdraw')">{{ $t('applications.bulk.withdraw') }}</button>
      <button v-if="f.group !== 'archived'" class="sm" @click="bulk('archive')">{{ $t('applications.bulk.archive') }}</button>
      <button v-else class="sm" @click="bulk('unarchive')">{{ $t('applications.bulk.unarchive') }}</button>
      <a class="btn sm" :href="exportUrl(picked)" download>{{ $t('applications.export') }}</a>
    </BulkBar>

    <SideDrawer v-if="review" :title="$t('applications.reviewTitle', { n: picked.size }, picked.size)" :sub="$t('applications.reviewSub')" @close="review = null">
      <div v-if="review.loading" class="review-note">{{ $t('applications.reviewLoading') }}</div>
      <template v-else>
        <div v-for="x in review.items" :key="x.id" class="card review-item">
          <div class="review-head">
            <EntityCell :primary="x.company" :secondary="x.title" />
            <router-link :to="'/applications/' + x.id + '#record'" class="btn sm ghost" @click="review = null">{{ $t('applications.reviewOpen') }}</router-link>
          </div>
          <div v-if="!x.draft_id" class="review-note">{{ $t('applications.reviewNothing') }}</div>
          <div v-else-if="x.unresolved" class="review-part"><span class="tag bad">{{ $t('applications.reviewOpenQuestions', { n: x.unresolved }, x.unresolved) }}</span></div>
          <template v-else>
            <div v-if="x.unsure.length" class="review-part"><div class="t-meta">{{ $t('applications.reviewUnsure') }}</div><ul><li v-for="u in x.unsure" :key="u">{{ u }}</li></ul></div>
            <div v-if="x.changed.length" class="review-part"><div class="t-meta">{{ $t('applications.reviewChanged') }}</div><ul><li v-for="c in x.changed" :key="c">{{ c }}</li></ul></div>
            <div v-if="!x.unsure.length && !x.changed.length" class="review-note">{{ $t('applications.reviewClean') }}</div>
          </template>
        </div>
      </template>
      <template v-if="!review.loading" #footer>
        <button class="ghost" @click="review = null">{{ $t('applications.cancel') }}</button>
        <button class="primary" :disabled="!approvable.length" @click="approveReviewed">{{ $t('applications.reviewApprove', { n: approvable.length }, approvable.length) }}</button>
      </template>
    </SideDrawer>
  </template>
</template>

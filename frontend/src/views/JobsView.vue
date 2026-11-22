<script setup>
import { t as T } from '../i18n/catalog'
// Postings: what is out there and whether to apply (plan §8.3). A posting is here until an application is begun; then
// it only leads to that application (the applications page follows it from there).
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmt } from '../api'
import DataState from '../components/DataState.vue'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import TechDetails from '../components/TechDetails.vue'
import { dataState, useRefresh } from '../data'
import { daysUntil, deadlineLabel, isPast, keepVisible } from '../dates'
import { renderMarkdown } from '../md'
import { fromQuery, sameQuery, toQuery } from '../urlstate'
import { ask, persona, run, toast } from '../ui'
import { dayText, shortDayText } from '../i18n/format'

const route = useRoute()
const router = useRouter()
const jobs = ref([])
const GROUPS = ['todo', 'started', 'skip', 'closed', 'archived']
const group = ref('todo')
const sortKey = ref('score')
const sortDir = ref(-1)
const sel = ref(null)
const picked = ref(new Set())
const showJd = ref(false)
const adding = ref(false)
const add = ref({ url: '', company: '', title: '' })

// Optional columns. The fixed ones (score, job, deadline, application) answer "what is it, how good, how urgent, did I
// begin"; the rest is detail that lives in the drawer unless the applicant asks for it here.
const COLS = { source: 'postings.col.source', direction: 'postings.col.direction', salary: 'postings.col.salary', channel: 'postings.col.channel', posted: 'postings.col.posted', first_seen: 'postings.col.firstSeen' }
let saved = null
try { saved = JSON.parse(localStorage.getItem('jobs.cols') || 'null') } catch { /* private window */ }
const cols = ref(new Set(Array.isArray(saved) ? saved : persona.features.job_columns || ['source']))
function toggleCol(k) {
  const s = new Set(cols.value); s.has(k) ? s.delete(k) : s.add(k); cols.value = s
  try { localStorage.setItem('jobs.cols', JSON.stringify([...s])) } catch { /* ignore */ }
}

// Filters. Empty string / 0 / false = not filtering on that field.
const F0 = { q: '', minScore: 0, direction: '', term: '', channel: '', deadline: '', link: false, prio: false }
const f = reactive({ ...F0 })
const DEADLINES = { '': 'postings.deadline.any', 3: 'postings.deadline.in3', 7: 'postings.deadline.in7', 14: 'postings.deadline.in14', none: 'postings.deadline.none' }
const activeFilters = computed(() => ['q', 'direction', 'term', 'channel', 'deadline'].filter((k) => f[k]).length + (f.minScore ? 1 : 0) + (f.link ? 1 : 0) + (f.prio ? 1 : 0))
function clearFilters() { Object.assign(f, F0) }

const inScope = computed(() => jobs.value.filter((j) => j.group === group.value))
const options = (key) => computed(() => {
  const m = new Map()
  for (const j of inScope.value) { const v = j[key]; if (v) m.set(v, (m.get(v) || 0) + 1) }
  return [...m.entries()].sort((a, b) => b[1] - a[1])
})
const directions = options('direction')
const terms = options('term')
const channels = options('channel_label')
const groupCount = (g) => jobs.value.filter((j) => j.group === g).length
function pickGroup(k) { group.value = k; picked.value = new Set() }

const matches = (j, needle) => `${j.company} ${j.title} ${j.source_id} ${j.direction} ${j.summary} ${j.location}`.toLowerCase().includes(needle)
// A search looks in the group that is open; what it would find in the others is counted, so that one result does not
// read as "this posting is not here" when it sits under "not applying" or "started".
const elsewhere = computed(() => {
  const needle = f.q.trim().toLowerCase()
  return needle ? jobs.value.filter((j) => j.group !== group.value && matches(j, needle)).length : 0
})
const rows = computed(() => {
  const needle = f.q.trim().toLowerCase()
  const out = inScope.value.filter((j) => {
    if (f.minScore && (j.score ?? -1) < f.minScore) return false
    if (f.direction && j.direction !== f.direction) return false
    if (f.term && j.term !== f.term) return false
    if (f.channel && j.channel_label !== f.channel) return false
    if (f.link && !j.apply_url) return false
    if (f.prio && !j.priority) return false
    if (f.deadline === 'none' && j.deadline) return false
    if (f.deadline && f.deadline !== 'none') { const d = daysUntil(j.deadline); if (d == null || isPast(j.deadline) || d > +f.deadline) return false }      // (dates.js: calendar days; what is over is not "due soon")
    return !needle || matches(j, needle)
  })
  const k = sortKey.value
  return out.sort((a, b) => {
    const x = a[k] ?? (k === 'score' ? -1 : ''), y = b[k] ?? (k === 'score' ? -1 : '')
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir.value || Number(b.priority) - Number(a.priority) || (b.score ?? -1) - (a.score ?? -1)
  })
})
function sortBy(k) { if (sortKey.value === k) sortDir.value *= -1; else { sortKey.value = k; sortDir.value = k === 'score' ? -1 : 1 } }
const arrow = (k) => (sortKey.value === k ? (sortDir.value > 0 ? ' ↑' : ' ↓') : '')
const sorted = (k) => (sortKey.value === k ? (sortDir.value > 0 ? 'ascending' : 'descending') : 'none')       // (what a screen reader is told; the arrow is for the eye)
const scoreCls = (s) => (s == null ? '' : s >= 9 ? 'hi' : s >= 7.5 ? 'mid' : s < 6 ? 'lo' : '')
const fmtScore = (s) => (s == null ? '—' : s.toFixed(1))

// selection: of the rows that are shown. A filter, a search or a reload that takes a row off the page unticks it -
// a batch never acts on what cannot be seen.
watch(() => rows.value, (now) => { picked.value = keepVisible(picked.value, now) })
const allPicked = computed(() => rows.value.length > 0 && rows.value.every((j) => picked.value.has(j.id)))
function togglePick(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function toggleAll() { picked.value = allPicked.value ? new Set() : new Set(rows.value.map((j) => j.id)) }
const BULK = {
  draft: ['postings.bulk.start', 'postings.bulkDone.start', 'postings.bulkSkipped.start'],
  mark_submitted: ['postings.bulk.markSubmitted', 'postings.bulkDone.markSubmitted', 'postings.bulkSkipped.markSubmitted'],
  skip: ['postings.bulk.skip', 'postings.bulkDone.skip', 'postings.bulkSkipped.skip'],
  restore: ['postings.bulk.restore', 'postings.bulkDone.restore', 'postings.bulkSkipped.restore'],
  score: ['postings.bulk.score', 'postings.bulkDone.score', 'postings.bulkSkipped.score'],
  archive: ['postings.bulk.archive', 'postings.bulkDone.archive', ''],
  unarchive: ['postings.bulk.unarchive', 'postings.bulkDone.unarchive', ''],
}
const bulkSaid = (action) => (r) => T(BULK[action][1], { n: r.done }, r.done) + (r.skipped && BULK[action][2] ? T(BULK[action][2], { n: r.skipped }, r.skipped) : '')
async function bulk(action) {
  const ids = [...picked.value]
  if (action === 'draft' && ids.length > 5 && !(await ask(T('postings.startManyAsk', { n: ids.length })))) return
  if (action === 'mark_submitted' && !(await ask(T('postings.markManyAsk', { n: ids.length }, ids.length)))) return
  // (when the batch did not go through, what was ticked stays ticked: it can be tried again without ticking it all once more)
  if ((await run(() => api.post('/jobs/bulk', { action, ids }), bulkSaid(action), load)) !== false) picked.value = new Set()
}

async function read() { jobs.value = (await api.get('/jobs')).jobs }
// Which posting is open is in the address (?open=ID): the drawer opens for it, the browser's Back closes it, and the
// address can be kept or sent. Opening by a click adds a step to the history; closing takes that step back.
let stepped = false
function open(j) { router.push({ query: { ...route.query, open: String(j.id) } }) }
function closeSel() {
  editing.value = null
  if (stepped && window.history.state && window.history.state.back) { stepped = false; router.back(); return }
  const q = { ...route.query }
  delete q.open
  router.replace({ query: q })
}
async function show(id) {
  if (!id) { sel.value = null; editing.value = null; return }
  try { sel.value = await api.get('/jobs/' + id); showJd.value = false } catch (e) { toast(e.message, 'bad'); closeSel() }
}
const refreshSel = async () => { if (sel.value) sel.value = await api.get('/jobs/' + sel.value.id) }
const briefing = ref(false)
async function writeBrief() {
  briefing.value = true
  try { const r = await api.post(`/jobs/${sel.value.id}/brief`); if (r.brief) sel.value = { ...sel.value, brief: r.brief }; else toast(T('postings.noBrief'), 'bad') } catch (e) { toast(e.message, 'bad') } finally { briefing.value = false }
}
const act = (fn, ok) => run(fn, ok, async () => { await load(); await refreshSel() })

// --- one posting ------------------------------------------------------------------------------------------------------
const appEnded = (a) => !a || ['withdrawn', 'returned'].includes(a.stage)
const sent = computed(() => !!sel.value && ['submitted', 'confirmed', 'rejected', 'interview', 'assessment', 'offer'].includes(sel.value.app_status))
const start = () => act(() => api.post(`/jobs/${sel.value.id}/draft`), T('postings.started'))
const startRow = (j) => run(() => api.post(`/jobs/${j.id}/draft`), T('postings.started'), load)
const rescore = () => act(() => api.post(`/jobs/${sel.value.id}/score`), T('postings.scoring'))
const setStatus = (s) => act(() => api.patch(`/jobs/${sel.value.id}`, { status: s }), s === 'skipped' ? T('postings.skipped') : T('postings.restored'))
const setArchived = (on) => act(() => api.post('/jobs/bulk', { action: on ? 'archive' : 'unarchive', ids: [sel.value.id] }), on ? T('postings.archived') : T('postings.unarchived'))
async function markSubmitted() {
  if (!(await ask(T('postings.markAsk'), { ok: T('postings.do.markSubmitted') }))) return
  await act(() => api.post(`/jobs/${sel.value.id}/mark-submitted`), T('postings.markedSubmitted'))
}
async function remove() {
  if (!(await ask(T('postings.deleteAsk', { name: `${sel.value.company} · ${sel.value.title}` }), { ok: T('postings.do.delete'), danger: true }))) return
  if (await run(() => api.del('/jobs/' + sel.value.id), T('postings.deleted'), load)) closeSel()
}

// Correcting a posting: what the applicant changes stays theirs - the next scan does not write over it, and says what
// the source has now when that is different ("use the source's" takes it back).
const EDIT = ['company', 'title', 'deadline', 'apply_url', 'jd_text']
const editing = ref(null)
function startEdit() { editing.value = Object.fromEntries(EDIT.map((k) => [k, sel.value[k] || ''])) }
async function saveEdit() {
  const body = Object.fromEntries(EDIT.filter((k) => (editing.value[k] || '') !== (sel.value[k] || '')).map((k) => [k, editing.value[k]]))
  if (!Object.keys(body).length) { editing.value = null; return }
  if (await act(() => api.patch(`/jobs/${sel.value.id}`, body), T('postings.saved'))) editing.value = null
}
const useSource = (k) => act(() => api.patch(`/jobs/${sel.value.id}`, { use_source: [k] }), T('postings.sourceUsed')).then(() => { if (editing.value) editing.value[k] = sel.value[k] || '' })
const sourceSays = (k) => (sel.value && sel.value.edited ? sel.value.edited[k] : null)

const addJob = () => run(async () => { await api.post('/jobs', add.value); add.value = { url: '', company: '', title: '' }; adding.value = false }, T('postings.addedScoring'), load)
const scan = () => run(() => api.post('/tasks', { kind: 'discover' }), T('postings.scanning'))
const facts = computed(() => {
  const j = sel.value
  if (!j) return []
  return [['postings.fact.term', j.term], ['postings.fact.months', j.months ? T('postings.months', { n: j.months }) : ''], ['postings.fact.salary', j.salary], ['postings.fact.location', j.location || j.work_type],
    ['postings.fact.deadline', j.deadline], ['postings.fact.where', j.channel_label], ['postings.fact.docs', j.docs_required], ['postings.fact.direction', j.direction],
    ['postings.fact.source', j.source_label], ['postings.fact.posted', j.posted], ['postings.fact.id', j.source_id && j.source_id.length <= 12 ? j.source_id : '']].filter((x) => x[1])
})
watch(() => route.query.open, (id, was) => { if (id && !was) stepped = true; show(id) })      // (opened from within the page: a step that Back, or closing, takes back)

// What the list shows - the group, the filters, the sort - is in the address too (urlstate.js). It is written in
// place (no step in the history for every letter typed in the search box) and read when the address changes.
// The groups that were about applications before (in progress, applied...) lead to the applications page now.
const TO_APPLICATIONS = { active: 'agent', applied: 'sent', progress: 'progress', rejected: 'ended' }
const OLD = { all: 'todo', skipped: 'skip' }
const LIST0 = { group: 'todo', sort: 'score', dir: -1, ...F0 }
const SORTS = ['score', 'company', 'posted', 'first_seen', 'deadline']
const shownNow = () => ({ group: group.value, sort: sortKey.value, dir: sortDir.value, ...f })
function readAddress() {
  const g = String(route.query.group || '')
  if (TO_APPLICATIONS[g]) { router.replace({ path: '/applications', query: { group: TO_APPLICATIONS[g] } }); return }
  const st = fromQuery({ ...route.query, group: OLD[g] || g }, LIST0, { sort: SORTS, dir: [1, -1], group: GROUPS })
  group.value = st.group
  sortKey.value = st.sort
  sortDir.value = st.dir
  for (const k of Object.keys(F0)) f[k] = st[k]
}
readAddress()
watch(() => shownNow(), (now) => {
  const q = { ...toQuery(now, LIST0), ...(route.query.open ? { open: route.query.open } : {}) }
  if (!sameQuery(q, route.query)) router.replace({ query: q })
}, { deep: true })
watch(() => route.query, (q, was) => { const a = { ...q }, b = { ...was }; delete a.open; delete b.open; if (!sameQuery(a, b) && !sameQuery(a, toQuery(shownNow(), LIST0))) readAddress() })
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load)
onMounted(async () => { await load(); if (route.query.open) show(route.query.open) })
</script>

<template>
  <PageHead :title="$t('postings.title')" :sub="$t('postings.sub')">
    <router-link to="/jobs/sources" class="btn primary"><Icon name="search" />{{ $t('postings.sources') }}</router-link>
    <button @click="scan"><Icon name="refresh" />{{ $t('postings.scan') }}</button>
    <button class="ghost" @click="adding = !adding"><Icon name="edit" />{{ $t('postings.addByHand') }}</button>
  </PageHead>
  <DataState :s="st" :what="$t('postings.what')" @retry="load" />
  <template v-if="st.at">

  <div v-if="adding" class="card">
    <div class="card-title">{{ $t('postings.addTitle') }}</div>
    <div class="kv">
      <label for="add-url">{{ $t('postings.addUrl') }}</label><input id="add-url" v-model="add.url" placeholder="https://" />
      <label for="add-company">{{ $t('postings.addCompany') }}</label><input id="add-company" v-model="add.company" :placeholder="$t('postings.optional')" />
      <label for="add-title">{{ $t('postings.addJobTitle') }}</label><input id="add-title" v-model="add.title" :placeholder="$t('postings.optional')" />
    </div>
    <p class="hint">{{ $t('postings.addHint') }}</p>
    <div class="row"><button class="primary" :disabled="!add.url" @click="addJob">{{ $t('postings.add') }}</button><button class="ghost" @click="adding = false">{{ $t('postings.cancel') }}</button></div>
  </div>

  <div class="seg" style="margin-bottom: 12px" role="group" :aria-label="$t('postings.groupsLabel')">
    <button v-for="g in GROUPS" :key="g" :class="{ on: group === g }" @click="pickGroup(g)">{{ $t('postings.group.' + g) }}<span class="n">{{ groupCount(g) }}</span></button>
  </div>

  <div class="filters">
    <input v-model="f.q" :placeholder="$t('postings.search')" :aria-label="$t('postings.search')" style="width: 240px" />
    <AaSelect v-model="f.direction" :aria-label="$t('postings.filter.direction')"><option value="">{{ $t('postings.filter.allDirections') }}</option><option v-for="[v, n] in directions" :key="v" :value="v">{{ v }} ({{ n }})</option></AaSelect>
    <AaSelect v-if="persona.features.term" v-model="f.term" :aria-label="$t('postings.filter.term')"><option value="">{{ $t('postings.filter.allTerms') }}</option><option v-for="[v, n] in terms" :key="v" :value="v">{{ v }} ({{ n }})</option></AaSelect>
    <AaSelect v-model="f.channel" :aria-label="$t('postings.filter.channel')"><option value="">{{ $t('postings.filter.anyChannel') }}</option><option v-for="[v, n] in channels" :key="v" :value="v">{{ v }} ({{ n }})</option></AaSelect>
    <AaSelect v-model="f.deadline" :aria-label="$t('postings.filter.deadline')"><option v-for="(l, k) in DEADLINES" :key="k" :value="k">{{ $t(l) }}</option></AaSelect>
    <label class="muted nowrap">{{ $t('postings.filter.minScore') }} <input v-model.number="f.minScore" type="number" min="0" max="10" step="0.5" style="width: 68px" /></label>
    <label class="muted nowrap"><input v-model="f.link" type="checkbox" /> {{ $t('postings.filter.withLink') }}</label>
    <label v-if="jobs.some((j) => j.priority)" class="muted nowrap"><input v-model="f.prio" type="checkbox" /> {{ $t('postings.filter.priority') }}</label>
    <button v-if="activeFilters" class="ghost sm" @click="clearFilters"><Icon name="x" />{{ $t('postings.filter.clear') }}</button>
    <span class="grow"></span>
    <span class="muted small nowrap">{{ $t('postings.count', { n: rows.length }, rows.length) }}</span>
    <details class="colpick">
      <summary class="btn sm ghost">{{ $t('postings.columns') }}</summary>
      <div class="menu"><label v-for="(l, k) in COLS" :key="k"><input type="checkbox" :checked="cols.has(k)" @change="toggleCol(k)" /> {{ $t(l) }}</label></div>
    </details>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th style="width: 36px"><input type="checkbox" :checked="allPicked" :aria-label="$t('postings.pickAll')" @change="toggleAll" /></th>
          <th :aria-sort="sorted('score')"><button type="button" class="th-sort" @click="sortBy('score')">{{ $t('postings.col.score') }}{{ arrow('score') }}</button></th>
          <th :aria-sort="sorted('company')"><button type="button" class="th-sort" @click="sortBy('company')">{{ $t('postings.col.job') }}{{ arrow('company') }}</button></th>
          <th v-if="cols.has('source')" class="col-more">{{ $t('postings.col.source') }}</th>
          <th v-if="cols.has('direction')" class="col-more">{{ $t('postings.col.direction') }}</th>
          <th v-if="cols.has('salary')" class="col-more">{{ $t('postings.col.salary') }}</th>
          <th v-if="cols.has('channel')" class="col-more">{{ $t('postings.col.channel') }}</th>
          <th v-if="cols.has('posted')" class="col-more" :aria-sort="sorted('posted')"><button type="button" class="th-sort" @click="sortBy('posted')">{{ $t('postings.col.posted') }}{{ arrow('posted') }}</button></th>
          <th v-if="cols.has('first_seen')" class="col-more" :aria-sort="sorted('first_seen')"><button type="button" class="th-sort" @click="sortBy('first_seen')">{{ $t('postings.col.firstSeen') }}{{ arrow('first_seen') }}</button></th>
          <th :aria-sort="sorted('deadline')"><button type="button" class="th-sort" @click="sortBy('deadline')">{{ $t('postings.col.deadline') }}{{ arrow('deadline') }}</button></th>
          <th>{{ $t('postings.col.application') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="j in rows" :key="j.id" class="clickable" @click="open(j)">
          <td @click.stop><input type="checkbox" :checked="picked.has(j.id)" :aria-label="$t('postings.pick', { name: j.company })" @change="togglePick(j.id)" /></td>
          <td><span class="score" :class="scoreCls(j.score)">{{ fmtScore(j.score) }}</span></td>
          <td class="jobcell">
            <div><span v-if="j.priority" class="star on" :title="$t('postings.priority')" style="cursor: default">★</span><router-link class="rowlink" :to="{ path: '/jobs', query: { ...$route.query, open: j.id } }" :aria-label="$t('postings.openRow', { company: j.company, title: j.title })" @click.stop><b>{{ j.company }}</b></router-link>
              <span v-if="j.source === 'manual'" class="tag" style="margin-left: 4px">{{ $t('postings.manual') }}</span>
              <span v-if="j.also_listed" class="tag" :title="$t('postings.alsoListedHow')">{{ $t('postings.alsoListed', { n: j.also_listed }) }}</span></div>
            <div>{{ j.title }} <a v-if="j.apply_url" :href="j.apply_url" target="_blank" rel="noopener" :title="$t('postings.openLink')" @click.stop>↗</a></div>
            <div class="small muted">{{ [j.location, persona.features.term ? j.term : '', persona.features.term && j.months ? $t('postings.months', { n: j.months }) : ''].filter(Boolean).join(' · ') }}</div>
          </td>
          <td v-if="cols.has('source')" class="small nowrap col-more">{{ j.source_label }}</td>
          <td v-if="cols.has('direction')" class="small col-more">{{ j.direction }}</td>
          <td v-if="cols.has('salary')" class="small col-more">{{ j.salary }}</td>
          <td v-if="cols.has('channel')" class="small nowrap col-more">{{ j.channel_label }}</td>
          <td v-if="cols.has('posted')" class="small nowrap col-more">{{ dayText(j.posted) || '—' }}</td>
          <td v-if="cols.has('first_seen')" class="small nowrap col-more">{{ j.first_seen || '—' }}</td>
          <td class="small nowrap" :title="deadlineLabel(j.deadline).text">{{ shortDayText(j.deadline) || '—' }}<span v-if="deadlineLabel(j.deadline).tone === 'soon'" class="tag warn" style="margin-left: 6px">{{ daysUntil(j.deadline) === 0 ? $t('postings.today') : $t('postings.tomorrow') }}</span></td>
          <td class="nowrap" @click.stop>
            <router-link v-if="j.app && !appEnded(j.app)" :to="'/applications/' + j.app.id" class="tag" :class="j.app.tone">{{ j.app.stage_label }} →</router-link>
            <span v-else-if="j.group === 'skip'" class="tag" :title="j.exclusion">{{ j.exclusion ? $t('postings.byRule', { rule: j.exclusion }) : $t('postings.byYou') }}</span>
            <span v-else-if="j.group === 'closed'" class="tag">{{ j.online ? $t('postings.deadlinePassed') : $t('postings.takenDown') }}</span>
            <button v-else-if="j.group === 'todo' && j.apply_url" class="sm" @click="startRow(j)">{{ $t('postings.do.start') }}</button>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="elsewhere" class="callout" style="margin: 10px 0 0">
      <Icon name="info" /><div>{{ $t('postings.elsewhere', { n: elsewhere }, elsewhere) }}</div>
    </div>
    <EmptyState v-if="!rows.length" icon="briefcase" :title="$t('postings.empty')" :text="activeFilters ? $t('postings.emptyFiltered') : $t('postings.emptyHint')">
      <button v-if="activeFilters" @click="clearFilters">{{ $t('postings.filter.clear') }}</button>
    </EmptyState>
  </div>

  <div v-if="picked.size" class="bulkbar">
    <b>{{ $t('postings.picked', { n: picked.size }, picked.size) }}</b>
    <template v-if="group === 'archived'"><button class="sm" @click="bulk('unarchive')">{{ $t(BULK.unarchive[0]) }}</button></template>
    <template v-else>
      <button v-if="['todo', 'skip'].includes(group)" class="sm primary" @click="bulk('draft')">{{ $t(BULK.draft[0]) }}</button>
      <button v-if="group !== 'started'" class="sm" @click="bulk('mark_submitted')">{{ $t(BULK.mark_submitted[0]) }}</button>
      <button v-if="group === 'todo'" class="sm" @click="bulk('skip')">{{ $t(BULK.skip[0]) }}</button>
      <button v-if="group === 'skip'" class="sm" @click="bulk('restore')">{{ $t(BULK.restore[0]) }}</button>
      <button class="sm" @click="bulk('score')">{{ $t(BULK.score[0]) }}</button>
      <button class="sm" @click="bulk('archive')">{{ $t(BULK.archive[0]) }}</button>
    </template>
    <button class="sm ghost" style="border-color: transparent" @click="picked = new Set()">{{ $t('postings.unpick') }}</button>
  </div>

  <!-- one posting -->
  <SideDrawer v-if="sel" :title="sel.company" :sub="sel.title" :wide="false" @close="closeSel">
    <div class="row" style="margin: 12px 0; flex-wrap: wrap">
      <span class="score" :class="scoreCls(sel.score)">{{ sel.score == null ? $t('postings.notScored') : $t('postings.scoreIs', { n: sel.score }) }}</span>
      <span v-if="!sel.online" class="tag">{{ $t('postings.takenDown') }}</span>
      <span v-if="sel.exclusion" class="tag bad">{{ sel.exclusion }}</span>
      <span v-if="sel.status === 'skipped' && !sel.exclusion" class="tag">{{ $t('postings.group.skip') }}</span>
      <span v-if="sel.archived" class="tag">{{ $t('postings.group.archived') }}</span>
      <span v-if="sel.source === 'manual'" class="tag">{{ $t('postings.manual') }}</span>
    </div>

    <div v-if="sel.app && !appEnded(sel.app)" class="callout" style="display: flex; margin-bottom: 12px">
      <Icon name="check" /><div class="grow">{{ $t('postings.hasApplication') }} <span class="tag" :class="sel.app.tone">{{ sel.app.stage_label }}</span></div>
      <router-link :to="'/applications/' + sel.app.id" class="btn sm primary">{{ $t('postings.do.openApplication') }}</router-link>
    </div>

    <div class="row" style="margin-bottom: 16px; flex-wrap: wrap; gap: 8px">
      <button v-if="!sel.app || appEnded(sel.app)" class="primary" :disabled="!sel.apply_url || !sel.online" @click="start"><Icon name="draft" />{{ $t('postings.do.start') }}</button>
      <a v-if="sel.apply_url" :href="sel.apply_url" target="_blank" rel="noopener" class="btn"><Icon name="external" />{{ $t('postings.do.seePosting') }}</a>
      <button v-if="!sent" @click="markSubmitted">{{ $t('postings.do.markSubmitted') }}</button>
      <button v-if="sel.status !== 'skipped'" :disabled="sent" @click="setStatus('skipped')">{{ $t('postings.do.skip') }}</button>
      <button v-else @click="setStatus('scored')">{{ $t('postings.do.restore') }}</button>
      <button :disabled="!sel.has_jd" :title="sel.has_jd ? '' : $t('postings.noJdToScore')" @click="rescore">{{ $t('postings.do.score') }}</button>
      <button @click="editing ? (editing = null) : startEdit()"><Icon name="edit" />{{ $t('postings.do.edit') }}</button>
      <button v-if="!sel.archived" :title="$t('postings.archiveHow')" @click="setArchived(true)">{{ $t('postings.do.archive') }}</button>
      <button v-else @click="setArchived(false)">{{ $t('postings.do.unarchive') }}</button>
      <button v-if="sel.deletable" class="danger" @click="remove">{{ $t('postings.do.delete') }}</button>
    </div>
    <p v-if="!sel.apply_url" class="callout warn"><Icon name="alert" /><span>{{ $t('postings.noLink') }}</span></p>

    <div v-if="editing" class="card">
      <div class="card-title">{{ $t('postings.editTitle') }}</div>
      <p class="hint" style="margin-top: 0">{{ $t('postings.editHow') }}</p>
      <div class="kv">
        <template v-for="k in EDIT" :key="k">
          <label :for="'edit-' + k">{{ $t('postings.edit.' + k) }}</label>
          <div>
            <textarea v-if="k === 'jd_text'" :id="'edit-' + k" v-model="editing[k]" rows="6" style="width: 100%; font-family: inherit"></textarea>
            <input v-else :id="'edit-' + k" v-model="editing[k]" style="width: 100%" :placeholder="k === 'deadline' ? 'YYYY-MM-DD HH:MM' : ''" />
            <div v-if="sourceSays(k)" class="hint">{{ $t('postings.sourceSays', { v: k === 'jd_text' ? sourceSays(k).slice(0, 80) + '…' : sourceSays(k) }) }} <a href="#" @click.prevent="useSource(k)">{{ $t('postings.useSource') }}</a></div>
          </div>
        </template>
      </div>
      <div class="row" style="margin-top: 12px"><button class="primary" @click="saveEdit">{{ $t('postings.save') }}</button><button class="ghost" @click="editing = null">{{ $t('postings.cancel') }}</button></div>
    </div>

    <div class="card">
      <div class="facts">
        <div v-for="[k, v] in facts" :key="k"><div class="k">{{ $t(k) }}</div><div class="v">{{ v }}</div></div>
      </div>
    </div>

    <div v-if="sel.contacts && sel.contacts.length" class="callout">
      <Icon name="user" />
      <div>
        <b>{{ $t('postings.contacts', { n: sel.contacts.length }, sel.contacts.length) }}</b>
        <div v-for="c in sel.contacts" :key="c.id" class="small" style="margin-top: 4px">{{ c.name }}<span v-if="c.role" class="muted"> ({{ c.role }})</span><span v-if="c.relation"> · {{ c.relation }}</span><span v-if="c.status === 'referred'" class="tag ok" style="margin-left: 6px">{{ $t('postings.referred') }}</span></div>
        <router-link to="/contacts" class="small">{{ $t('postings.toContacts') }}</router-link>
      </div>
    </div>

    <div v-if="sel.duplicates && sel.duplicates.length" class="callout">
      <Icon name="link" />
      <div>
        <b>{{ $t('postings.duplicates', { source: sel.source_label }) }}</b>
        <div v-for="dup in sel.duplicates" :key="dup.id" class="small" style="margin-top: 4px">
          {{ dup.source_label }}: <a v-if="dup.apply_url" :href="dup.apply_url" target="_blank" rel="noopener">{{ dup.title }}</a><span v-else>{{ dup.title }}</span><span v-if="!dup.online" class="muted"> ({{ $t('postings.takenDown') }})</span>
        </div>
      </div>
    </div>

    <div v-if="sel.history && sel.history.length" class="callout">
      <Icon name="activity" />
      <div>
        <b>{{ $t('postings.history') }}</b>
        <div v-for="h in sel.history" :key="h.id" class="small" style="margin-top: 4px">
          {{ h.first_seen.slice(0, 7) }} · <a href="#" @click.prevent="open(h)">{{ h.title }}</a><span v-if="h.term" class="muted"> ({{ h.term }})</span>
          <span class="tag" :class="h.stage_tone" style="margin-left: 6px">{{ h.applied ? $t('postings.appliedBefore', { stage: h.stage_label }) : h.stage_label }}</span>
        </div>
      </div>
    </div>

    <template v-if="sel.app_status && sel.app_explained && sel.app_explained.message">
      <h3>{{ $t('postings.progress') }}</h3>
      <div class="card">
        <div>{{ sel.app_explained.message }}</div>
        <div v-if="sel.submitted_at" class="muted small" style="margin-top: 4px">{{ $t('postings.submittedAt', { at: fmt(sel.submitted_at) }) }}</div>
        <TechDetails :text="sel.app_explained.detail" />
      </div>
    </template>

    <template v-if="sel.score_reason">
      <h3>{{ $t('postings.whyScore') }}</h3>
      <div class="card">{{ sel.score_reason }}</div>
    </template>

    <template v-if="sel.brief">
      <h3>{{ $t('postings.brief') }}</h3>
      <div class="card md" v-html="renderMarkdown(sel.brief)"></div>
    </template>
    <p v-else-if="sel.has_jd !== false && sel.score != null" class="small muted">
      {{ $t('postings.noBriefWritten') }}
      <button class="sm ghost" :disabled="briefing" @click="writeBrief">{{ briefing ? $t('postings.writing') : $t('postings.writeBrief') }}</button>
    </p>

    <h3>{{ $t('postings.jd') }}</h3>
    <div class="card">
      <p v-if="sel.jd_partial === 'summary'" class="callout warn small" style="display: block; margin: 0 0 10px">{{ $t('postings.jdSummary') }}</p>
      <p v-else-if="sel.jd_partial === 'cut'" class="callout small" style="display: block; margin: 0 0 10px">{{ $t('postings.jdCut') }}</p>
      <template v-if="sel.jd_text && sel.jd_text.length >= 200">
        <pre style="font-family: inherit; font-size: 13.5px; line-height: 1.6" :style="showJd || sel.jd_text.length < 900 ? '' : 'max-height: 200px; overflow: hidden; -webkit-mask-image: linear-gradient(#000 60%, transparent)'">{{ sel.jd_text }}</pre>
        <button v-if="sel.jd_text.length >= 900" class="ghost sm" style="margin-top: 6px" @click="showJd = !showJd">{{ showJd ? $t('postings.less') : $t('postings.more') }}</button>
      </template>
      <template v-else>
        <p v-if="sel.summary || sel.note || sel.jd_text" style="margin-bottom: 8px">{{ sel.jd_text || sel.summary || sel.note }}</p>
        <p class="muted small" style="margin: 0">{{ $t('postings.jdNone') }}</p>
      </template>
    </div>
  </SideDrawer>
  </template>
</template>

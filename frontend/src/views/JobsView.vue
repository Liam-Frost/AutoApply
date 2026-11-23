<script setup>
import { t as T, lang } from '../i18n/catalog'
// Postings: what is out there and whether to apply (plan §8.3). A posting is here until an application is begun; then
// it only leads to that application (the applications page follows it from there).
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmt } from '../api'
import BulkBar from '../components/BulkBar.vue'
import DataState from '../components/DataState.vue'
import DataTable from '../components/DataTable.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EmptyState from '../components/EmptyState.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import Icon from '../components/Icon.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import Popover from '../components/Popover.vue'
import SectionHead from '../components/SectionHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import Status from '../components/Status.vue'
import Tabs from '../components/Tabs.vue'
import TechDetails from '../components/TechDetails.vue'
import Trunc from '../components/Trunc.vue'
import { dataState, useRefresh } from '../data'
import { daysUntil, deadlineLabel, isPast, keepVisible, parseDeadline } from '../dates'
import { renderMarkdown } from '../md'
import { fromQuery, sameQuery, toQuery } from '../urlstate'
import { ask, persona, run, toast } from '../ui'
import { dateOf, dateTimeOf, dayText } from '../i18n/format'
import { dirLabel, filterOptions, under } from '../directions'

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
const COLS = { place: 'postings.col.place', source: 'postings.col.source', direction: 'postings.col.direction', salary: 'postings.col.salary', channel: 'postings.col.channel', posted: 'postings.col.posted', first_seen: 'postings.col.firstSeen' }
let saved = null
try { saved = JSON.parse(localStorage.getItem('jobs.cols') || 'null') } catch { /* private window */ }
// (the place stood under every title before it was a column: it is shown unless the applicant has chosen the columns)
const cols = ref(new Set(Array.isArray(saved) ? saved : ['place', ...(persona.features.job_columns || ['source'])]))
function toggleCol(k) {
  const s = new Set(cols.value); s.has(k) ? s.delete(k) : s.add(k); cols.value = s
  try { localStorage.setItem('jobs.cols', JSON.stringify([...s])) } catch { /* ignore */ }
}

// Filters. Empty string / 0 / false = not filtering on that field.
const F0 = { q: '', minScore: 0, direction: '', term: '', channel: '', deadline: '', link: false, prio: false }
const f = reactive({ ...F0 })
const DEADLINES = { '': 'postings.deadline.any', 3: 'postings.deadline.in3', 7: 'postings.deadline.in7', 14: 'postings.deadline.in14', none: 'postings.deadline.none' }
// the conditions that are used now and then are behind "Filters": how many of them are set is said on its button
const behind = computed(() => ['term', 'channel'].filter((k) => f[k]).length + (f.minScore ? 1 : 0) + (f.link ? 1 : 0) + (f.prio ? 1 : 0))
const activeFilters = computed(() => ['q', 'direction', 'deadline'].filter((k) => f[k]).length + behind.value)
function clearFilters() { Object.assign(f, F0) }

const inScope = computed(() => jobs.value.filter((j) => j.group === group.value))
const options = (key) => computed(() => {
  const m = new Map()
  for (const j of inScope.value) { const v = j[key]; if (v) m.set(v, (m.get(v) || 0) + 1) }
  return [...m.entries()].sort((a, b) => b[1] - a[1])
})
// (fields from the fixed list, each with its specialties under it; what is not sorted yet last)
const directions = computed(() => filterOptions(inScope.value.map((j) => j.direction)))
const terms = options('term')
const channels = options('channel_label')
const groupCount = (g) => jobs.value.filter((j) => j.group === g).length
function pickGroup(k) { group.value = k; picked.value = new Set() }

const matches = (j, needle) => `${j.company} ${j.title} ${j.source_id} ${dirLabel(j.direction, { whole: true })} ${j.summary} ${j.location}`.toLowerCase().includes(needle)
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
    if (f.direction && !under(j.direction, f.direction)) return false
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
// The table's sort is this page's (kept in the address): a header pressed for the first time sorts upwards - the score
// downwards, the best first - and turns round when pressed again.
const SORT_OF = { job: 'company' }
const sort = computed({
  get: () => ({ by: Object.keys(SORT_OF).find((c) => SORT_OF[c] === sortKey.value) || sortKey.value, dir: sortDir.value > 0 ? 'asc' : 'desc' }),
  set: (v) => { const k = SORT_OF[v.by] || v.by; if (sortKey.value === k) sortDir.value *= -1; else { sortKey.value = k; sortDir.value = k === 'score' ? -1 : 1 } },
})
const scoreCls = (s) => (s == null ? '' : s >= 9 ? 'hi' : s >= 7.5 ? 'mid' : s < 6 ? 'lo' : '')
const fmtScore = (s) => (s == null ? '—' : s.toFixed(1))

// --- the columns: score, posting, deadline and the application always; what the applicant chose besides goes first
// when the table is narrow (the highest priority first). Nothing a cell holds changes a width.
// The row's action ("Start an application") is never cut: the column is at least as wide as its words in the language
// shown, measured on a copy nobody sees (as the accounts page does) - "Commencer une candidature" is twice "开始申请".
const startProbe = ref(null)
const startW = ref(0)
function fitStart() { if (startProbe.value && startProbe.value.offsetWidth) startW.value = Math.ceil(startProbe.value.offsetWidth) + 24 + 2 }      // + the cell's padding; +2 for fractions
watch(() => lang.value, () => nextTick(fitStart))
// (measured again whenever the copy changes size: the web font arriving, the language changing)
let sizedStart = null
onMounted(() => { fitStart(); if (typeof ResizeObserver !== 'undefined' && startProbe.value) { sizedStart = new ResizeObserver(fitStart); sizedStart.observe(startProbe.value) } })
onBeforeUnmount(() => sizedStart && sizedStart.disconnect())
const columns = computed(() => {
  const latin = !/^(zh|ja|ko)/.test(lang.value)
  const more = [
    { id: 'place', min: 120, max: 200, priority: 1 },
    { id: 'source', min: 104, max: 160, priority: 2 },
    { id: 'direction', min: 104, max: 180, priority: 3 },
    { id: 'salary', min: 104, max: 180, priority: 4 },
    { id: 'channel', min: 104, max: 160, priority: 5 },
    { id: 'posted', min: 104, max: 120, flex: 0, priority: 6, sortable: true },
    { id: 'first_seen', min: 104, max: 120, flex: 0, priority: 7, sortable: true },
  ].filter((c) => cols.value.has(c.id)).map((c) => ({ ...c, header: T(COLS[c.id]) }))
  return [
    { id: 'score', header: T('postings.col.score'), width: latin ? 76 : 68, align: 'end', sortable: true },
    { id: 'job', header: T('postings.col.job'), min: 200, max: 440, flex: 4, sortable: true },
    ...more,
    { id: 'deadline', header: T('postings.col.deadline'), min: latin ? 128 : 116, max: 148, flex: 0, sortable: true },
    { id: 'app', header: T('postings.col.application'), min: Math.max(latin ? 176 : 132, startW.value), max: Math.max(220, startW.value), flex: 1 },
    { id: 'more', header: '', width: 44, align: 'end' },
  ]
})
const placeOf = (j) => j.location || j.work_type || ''
const termOf = (j) => (persona.features.term ? [j.term, j.months ? T('postings.months', { n: j.months }) : ''].filter(Boolean).join(' · ') : '')
function dueOf(j) {
  const d = parseDeadline(j.deadline)
  if (!d) return null
  const tip = T('postings.dueTip', { when: dateTimeOf(d) })
  if (isSent(j)) return { primary: dateOf(d), tone: 'muted', tip }      // (applied: how many days are left no longer matters)
  const dl = deadlineLabel(j.deadline)
  return { primary: dateOf(d), secondary: dl.text, tone: dl.tone === 'soon' ? 'warn' : dl.tone === 'past' ? 'muted' : '', tip }
}

// selection: of the rows that are shown. A filter, a search or a reload that takes a row off the page unticks it -
// a batch never acts on what cannot be seen.
watch(() => rows.value, (now) => { picked.value = keepVisible(picked.value, now) })
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
let editNext = false      // "Edit" in a row's menu: the posting opens with its form
async function show(id) {
  if (!id) { sel.value = null; editing.value = null; return }
  try { sel.value = await api.get('/jobs/' + id); showJd.value = false; if (editNext) startEdit() } catch (e) { toast(e.message, 'bad'); closeSel() } finally { editNext = false }
}
const refreshSel = async () => { if (sel.value) sel.value = await api.get('/jobs/' + sel.value.id) }
const briefing = ref(false)
async function writeBrief() {
  briefing.value = true
  try { const r = await api.post(`/jobs/${sel.value.id}/brief`); if (r.brief) sel.value = { ...sel.value, brief: r.brief }; else toast(T('postings.noBrief'), 'bad') } catch (e) { toast(e.message, 'bad') } finally { briefing.value = false }
}
const act = (fn, ok) => run(fn, ok, async () => { await load(); await refreshSel() })

// --- one posting: from its row (the row's button and menu) or from its drawer - the same actions, on the posting given
const appEnded = (a) => !a || ['withdrawn', 'returned'].includes(a.stage)
const live = (j) => !!j.app && !appEnded(j.app)
const isSent = (j) => ['submitted', 'confirmed', 'rejected', 'interview', 'assessment', 'offer'].includes(j.app_status)
const canStart = (j) => !live(j) && !!j.apply_url && j.online
const start = (j) => act(() => api.post(`/jobs/${j.id}/draft`), T('postings.started'))
const rescore = (j) => act(() => api.post(`/jobs/${j.id}/score`), T('postings.scoring'))
const setStatus = (j, s) => act(() => api.patch(`/jobs/${j.id}`, { status: s }), s === 'skipped' ? T('postings.skipped') : T('postings.restored'))
const setArchived = (j, on) => act(() => api.post('/jobs/bulk', { action: on ? 'archive' : 'unarchive', ids: [j.id] }), on ? T('postings.archived') : T('postings.unarchived'))
async function markSubmitted(j) {
  if (!(await ask(T('postings.markAsk'), { ok: T('postings.do.markSubmitted') }))) return
  await act(() => api.post(`/jobs/${j.id}/mark-submitted`), T('postings.markedSubmitted'))
}
async function remove(j) {
  if (!(await ask(T('postings.deleteAsk', { name: `${j.company} · ${j.title}` }), { ok: T('postings.do.delete'), danger: true }))) return
  if ((await run(() => api.del('/jobs/' + j.id), T('postings.deleted'), load)) && sel.value && sel.value.id === j.id) closeSel()
}
function edit(j) {
  if (sel.value && sel.value.id === j.id) return editing.value ? (editing.value = null) : startEdit()
  editNext = true
  open(j)
}
// What can be done with a posting besides its main action (the row's button, the drawer's first two buttons): the
// same list in the row's menu and in the drawer's - what does not apply now is left out or shown as not available.
function menuOf(j, inDrawer = false) {
  const deletable = j.deletable ?? (j.source === 'manual' && !j.app_id)      // (only a posting the applicant added, with nothing begun)
  const startShown = inDrawer || (j.group === 'todo' && canStart(j))          // (it is the button beside the menu)
  return [
    ...(!inDrawer && live(j) ? [{ id: 'application', label: T('postings.do.openApplication'), icon: 'forward' }] : []),
    ...(!inDrawer && j.apply_url ? [{ id: 'link', label: T('postings.do.seePosting'), icon: 'external' }] : []),
    ...(!startShown && !live(j) ? [{ id: 'start', label: T('postings.do.start'), icon: 'draft', disabled: !canStart(j) }] : []),
    ...(!isSent(j) ? [{ id: 'mark', label: T('postings.do.markSubmitted'), icon: 'check' }] : []),
    j.status !== 'skipped' ? { id: 'skip', label: T('postings.do.skip'), icon: 'x', disabled: isSent(j) } : { id: 'restore', label: T('postings.do.restore'), icon: 'back' },
    { id: 'score', label: T('postings.do.score'), icon: 'refresh', disabled: !j.has_jd, hint: j.has_jd ? '' : T('postings.noJdToScore') },
    { id: 'edit', label: T('postings.do.edit'), icon: 'edit' },
    j.archived ? { id: 'unarchive', label: T('postings.do.unarchive'), icon: 'inbox' } : { id: 'archive', label: T('postings.do.archive'), icon: 'inbox', hint: T('postings.archiveHow') },
    ...(deletable ? [{ divider: true }, { id: 'delete', label: T('postings.do.delete'), icon: 'trash', danger: true }] : []),
  ]
}
function onMenu(j, id) {
  if (id === 'application') return router.push('/applications/' + j.app.id)
  if (id === 'link') return window.open(j.apply_url, '_blank', 'noopener')
  if (id === 'start') return start(j)
  if (id === 'mark') return markSubmitted(j)
  if (id === 'skip') return setStatus(j, 'skipped')
  if (id === 'restore') return setStatus(j, 'scored')
  if (id === 'score') return rescore(j)
  if (id === 'edit') return edit(j)
  if (id === 'archive' || id === 'unarchive') return setArchived(j, id === 'archive')
  if (id === 'delete') return remove(j)
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
  const due = parseDeadline(j.deadline)
  return [['postings.fact.term', j.term], ['postings.fact.months', j.months ? T('postings.months', { n: j.months }) : ''], ['postings.fact.salary', j.salary], ['postings.fact.location', j.location || j.work_type],
    ['postings.fact.deadline', due ? dateTimeOf(due) : j.deadline], ['postings.fact.where', j.channel_label], ['postings.fact.docs', j.docs_required], ['postings.fact.direction', dirLabel(j.direction, { whole: true })],
    ['postings.fact.source', j.source_label], ['postings.fact.posted', dayText(j.posted) || j.posted], ['postings.fact.id', j.source_id && j.source_id.length <= 12 ? j.source_id : '']].filter((x) => x[1])
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
  <button ref="startProbe" type="button" class="sm ghost acc-probe" tabindex="-1" aria-hidden="true"><Icon name="draft" />{{ $t('postings.do.start') }}</button>
  <PageHead :title="$t('postings.title')" :help="$t('postings.help')">
    <router-link to="/jobs/sources" class="btn tonal"><Icon name="search" />{{ $t('postings.sources') }}</router-link>
    <button :aria-expanded="adding" @click="adding = !adding"><Icon name="plus" />{{ $t('postings.addByHand') }}</button>
    <button class="primary" @click="scan"><Icon name="refresh" />{{ $t('postings.scan') }}</button>
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
    <div class="actions"><button class="primary" :disabled="!add.url" @click="addJob">{{ $t('postings.add') }}</button><button class="ghost" @click="adding = false">{{ $t('postings.cancel') }}</button></div>
  </div>

  <Tabs class="list-tabs" :model-value="group" :label="$t('postings.groupsLabel')" :items="GROUPS.map((g) => ({ id: g, label: $t('postings.group.' + g), count: groupCount(g) }))" @update:model-value="pickGroup" />

  <div class="filters" role="group" :aria-label="$t('postings.filter.more')">
    <input v-model="f.q" class="search" type="search" :placeholder="$t('postings.search')" :aria-label="$t('postings.search')" />
    <AaSelect v-model="f.direction" :aria-label="$t('postings.filter.direction')"><option value="">{{ $t('postings.filter.allDirections') }}</option><option v-for="o in directions" :key="o.value" :value="o.value" :data-sub="o.sub || null">{{ o.label }} ({{ o.n }})</option></AaSelect>
    <AaSelect v-model="f.deadline" :aria-label="$t('postings.filter.deadline')"><option v-for="(l, k) in DEADLINES" :key="k" :value="k">{{ $t(l) }}</option></AaSelect>
    <!-- what is used now and then: behind one button, which says how many of them are set -->
    <Popover :label="$t('postings.filter.more')" :width="280">
      <template #trigger="{ toggle, attrs }"><button v-bind="attrs" @click="toggle"><Icon name="filter" />{{ behind ? $t('postings.filter.moreActive', { n: behind }) : $t('postings.filter.more') }}</button></template>
      <div class="pop-form">
        <label v-if="persona.features.term">{{ $t('postings.filter.term') }}
          <AaSelect v-model="f.term"><option value="">{{ $t('postings.filter.allTerms') }}</option><option v-for="[v, n] in terms" :key="v" :value="v">{{ v }} ({{ n }})</option></AaSelect></label>
        <label>{{ $t('postings.filter.channel') }}
          <AaSelect v-model="f.channel"><option value="">{{ $t('postings.filter.anyChannel') }}</option><option v-for="[v, n] in channels" :key="v" :value="v">{{ v }} ({{ n }})</option></AaSelect></label>
        <label>{{ $t('postings.filter.minScore') }}<input v-model.number="f.minScore" type="number" min="0" max="10" step="0.5" /></label>
        <label class="check"><input v-model="f.link" type="checkbox" />{{ $t('postings.filter.withLink') }}</label>
        <label v-if="jobs.some((j) => j.priority)" class="check"><input v-model="f.prio" type="checkbox" />{{ $t('postings.filter.priority') }}</label>
      </div>
    </Popover>
    <button v-if="activeFilters" class="ghost" @click="clearFilters"><Icon name="x" />{{ $t('postings.filter.clear') }}</button>
    <span class="grow"></span>
    <span class="count">{{ $t('postings.count', { n: rows.length }, rows.length) }}</span>
    <Popover :label="$t('postings.columns')" align="end" :width="220">
      <template #trigger="{ toggle, attrs }"><button class="ghost" v-bind="attrs" @click="toggle"><Icon name="table" />{{ $t('postings.columns') }}</button></template>
      <div class="pop-form"><label v-for="(l, k) in COLS" :key="k" class="check"><input type="checkbox" :checked="cols.has(k)" @change="toggleCol(k)" />{{ $t(l) }}</label></div>
    </Popover>
  </div>

  <DataTable v-model:selected="picked" v-model:sort="sort" :columns="columns" :rows="rows" row-key="id" density="comfortable" selectable clickable :label="$t('postings.title')"
             :select-all-label="$t('postings.pickAll')" :select-label="(j) => $t('postings.pick', { name: j.company })" @row="open">
    <template #cell-score="{ row }"><span v-tip="row.score == null ? $t('postings.notScored') : ''" class="score-num" :class="scoreCls(row.score)">{{ fmtScore(row.score) }}</span></template>
    <template #cell-job="{ row }">
      <EntityCell :primary="row.company" :secondary="row.title" :to="{ path: '/jobs', query: { ...$route.query, open: row.id } }">
        <template v-if="row.priority || row.source === 'manual' || row.also_listed" #after>
          <span v-if="row.priority" v-tip="$t('postings.priority')" class="mark prio" role="img" :aria-label="$t('postings.priority')"><Icon name="star" /></span>
          <span v-if="row.source === 'manual'" v-tip="$t('postings.manual')" class="mark" role="img" :aria-label="$t('postings.manual')"><Icon name="edit" /></span>
          <span v-if="row.also_listed" v-tip="$t('postings.alsoListedHow')" class="mark num">{{ $t('postings.alsoListed', { n: row.also_listed }) }}</span>
        </template>
      </EntityCell>
    </template>
    <template #cell-place="{ row }">
      <div v-if="placeOf(row) || termOf(row)" class="entity"><Trunc as="div" class="t-secondary" :text="placeOf(row) || termOf(row)" /><Trunc v-if="placeOf(row) && termOf(row)" as="div" class="t-meta" :text="termOf(row)" /></div>
      <span v-else class="none">—</span>
    </template>
    <template #cell-source="{ row }"><Trunc v-if="row.source_label" class="t-secondary" :text="row.source_label" /><span v-else class="none">—</span></template>
    <template #cell-direction="{ row }"><Trunc v-if="row.direction" class="t-secondary" :text="dirLabel(row.direction)" /><span v-else class="none">—</span></template>
    <template #cell-salary="{ row }"><Trunc v-if="row.salary" class="t-secondary" :text="row.salary" /><span v-else class="none">—</span></template>
    <template #cell-channel="{ row }"><Trunc v-if="row.channel_label" class="t-secondary" :text="row.channel_label" /><span v-else class="none">—</span></template>
    <template #cell-posted="{ row }"><span v-if="dayText(row.posted)" class="t-secondary num atomic">{{ dayText(row.posted) }}</span><span v-else class="none">—</span></template>
    <template #cell-first_seen="{ row }"><span v-if="dayText(row.first_seen)" class="t-secondary num atomic">{{ dayText(row.first_seen) }}</span><span v-else class="none">—</span></template>
    <template #cell-deadline="{ row }">
      <DateTimeCell v-if="dueOf(row)" v-bind="dueOf(row)" />
      <span v-else v-tip="$t('postings.noDeadline')" class="none">—</span>
    </template>
    <!-- the application it led to; else why nothing is begun; else the one thing to do with it -->
    <template #cell-app="{ row }">
      <router-link v-if="live(row)" :to="'/applications/' + row.app.id" class="app-link"><Status :tone="row.app.tone" :label="row.app.stage_label" /><Icon name="chevron_right" /></router-link>
      <Status v-else-if="row.group === 'skip'" :label="row.exclusion ? $t('postings.byRule', { rule: row.exclusion }) : $t('postings.byYou')" />
      <Status v-else-if="row.group === 'closed'" :label="row.online ? $t('postings.deadlinePassed') : $t('postings.takenDown')" />
      <button v-else-if="row.group === 'todo' && canStart(row)" class="sm ghost" @click="start(row)"><Icon name="draft" />{{ $t('postings.do.start') }}</button>
      <span v-else class="none">—</span>
    </template>
    <template #cell-more="{ row }"><Menu :label="$t('postings.row.menu')" :items="menuOf(row)" @pick="(id) => onMenu(row, id)" /></template>
    <template #empty>
      <EmptyState icon="briefcase" :title="$t('postings.empty')" :text="activeFilters ? $t('postings.emptyFiltered') : $t('postings.emptyHint')">
        <button v-if="activeFilters" @click="clearFilters">{{ $t('postings.filter.clear') }}</button>
      </EmptyState>
    </template>
  </DataTable>
  <div v-if="elsewhere" class="callout list-note"><Icon name="info" /><div>{{ $t('postings.elsewhere', { n: elsewhere }, elsewhere) }}</div></div>

  <BulkBar :count="picked.size" @clear="picked = new Set()">
    <template v-if="group === 'archived'"><button class="sm" @click="bulk('unarchive')">{{ $t(BULK.unarchive[0]) }}</button></template>
    <template v-else>
      <button v-if="['todo', 'skip'].includes(group)" class="sm primary" @click="bulk('draft')">{{ $t(BULK.draft[0]) }}</button>
      <button v-if="group !== 'started'" class="sm" @click="bulk('mark_submitted')">{{ $t(BULK.mark_submitted[0]) }}</button>
      <button v-if="group === 'todo'" class="sm" @click="bulk('skip')">{{ $t(BULK.skip[0]) }}</button>
      <button v-if="group === 'skip'" class="sm" @click="bulk('restore')">{{ $t(BULK.restore[0]) }}</button>
      <button class="sm" @click="bulk('score')">{{ $t(BULK.score[0]) }}</button>
      <button class="sm" @click="bulk('archive')">{{ $t(BULK.archive[0]) }}</button>
    </template>
  </BulkBar>

  <!-- one posting -->
  <SideDrawer v-if="sel" :title="sel.company" :sub="sel.title" :wide="false" @close="closeSel">
    <div class="job-state">
      <span class="score-num" :class="scoreCls(sel.score)">{{ sel.score == null ? $t('postings.notScored') : $t('postings.scoreIs', { n: sel.score }) }}</span>
      <span v-if="!sel.online" class="tag">{{ $t('postings.takenDown') }}</span>
      <Trunc v-if="sel.exclusion" class="tag bad" :text="sel.exclusion" />
      <span v-if="sel.status === 'skipped' && !sel.exclusion" class="meta">{{ $t('postings.group.skip') }}</span>
      <span v-if="sel.archived" class="meta">{{ $t('postings.group.archived') }}</span>
      <span v-if="sel.source === 'manual'" class="meta">{{ $t('postings.manual') }}</span>
    </div>

    <div v-if="live(sel)" class="callout job-has-app">
      <Icon name="check" /><div class="grow">{{ $t('postings.hasApplication') }} <Status :tone="sel.app.tone" :label="sel.app.stage_label" /></div>
      <router-link :to="'/applications/' + sel.app.id" class="btn sm primary">{{ $t('postings.do.openApplication') }}</router-link>
    </div>

    <!-- the two things done most, then everything else in one menu (the destructive one last) -->
    <div class="actions job-acts">
      <button v-if="!live(sel)" class="primary" :disabled="!canStart(sel)" @click="start(sel)"><Icon name="draft" />{{ $t('postings.do.start') }}</button>
      <a v-if="sel.apply_url" :href="sel.apply_url" target="_blank" rel="noopener" class="btn"><Icon name="external" />{{ $t('postings.do.seePosting') }}</a>
      <Menu :label="$t('postings.row.menu')" :items="menuOf(sel, true)" align="start" @pick="(id) => onMenu(sel, id)" />
    </div>
    <p v-if="!sel.apply_url" class="callout warn"><Icon name="alert" /><span>{{ $t('postings.noLink') }}</span></p>

    <div v-if="editing" class="card">
      <SectionHead :title="$t('postings.editTitle')" :help="$t('postings.editHow')" />
      <div class="kv">
        <template v-for="k in EDIT" :key="k">
          <label :for="'edit-' + k">{{ $t('postings.edit.' + k) }}</label>
          <div class="job-edit">
            <textarea v-if="k === 'jd_text'" :id="'edit-' + k" v-model="editing[k]" rows="6"></textarea>
            <input v-else :id="'edit-' + k" v-model="editing[k]" :placeholder="k === 'deadline' ? 'YYYY-MM-DD HH:MM' : ''" />
            <div v-if="sourceSays(k)" class="hint"><Trunc v-if="k !== 'jd_text'" as="div" :text="$t('postings.sourceSays', { v: sourceSays(k) })" /><template v-else>{{ $t('postings.sourceSaysJd') }}</template> <a href="#" @click.prevent="useSource(k)">{{ $t('postings.useSource') }}</a></div>
          </div>
        </template>
      </div>
      <div class="actions job-form-acts"><button class="primary" @click="saveEdit">{{ $t('postings.save') }}</button><button class="ghost" @click="editing = null">{{ $t('postings.cancel') }}</button></div>
    </div>

    <div class="card">
      <div class="facts">
        <div v-for="[k, v] in facts" :key="k"><div class="k">{{ $t(k) }}</div><div class="v">{{ v }}</div></div>
      </div>
    </div>

    <template v-if="sel.contacts && sel.contacts.length">
      <SectionHead :title="$t('postings.contacts', { n: sel.contacts.length }, sel.contacts.length)"><router-link to="/contacts" class="btn sm ghost">{{ $t('postings.toContacts') }}</router-link></SectionHead>
      <div class="card job-list">
        <div v-for="c in sel.contacts" :key="c.id">{{ c.name }}<span v-if="c.role" class="muted"> ({{ c.role }})</span><span v-if="c.relation"> · {{ c.relation }}</span> <Status v-if="c.status === 'referred'" tone="ok" :label="$t('postings.referred')" /></div>
      </div>
    </template>

    <template v-if="sel.duplicates && sel.duplicates.length">
      <SectionHead :title="$t('postings.duplicates', { source: sel.source_label })" />
      <div class="card job-list">
        <div v-for="dup in sel.duplicates" :key="dup.id">
          {{ dup.source_label }}: <a v-if="dup.apply_url" :href="dup.apply_url" target="_blank" rel="noopener">{{ dup.title }}</a><span v-else>{{ dup.title }}</span><span v-if="!dup.online" class="muted"> ({{ $t('postings.takenDown') }})</span>
        </div>
      </div>
    </template>

    <template v-if="sel.history && sel.history.length">
      <SectionHead :title="$t('postings.history')" />
      <div class="card job-list">
        <div v-for="h in sel.history" :key="h.id">
          <span class="num">{{ h.first_seen.slice(0, 7) }}</span> · <a href="#" @click.prevent="open(h)">{{ h.title }}</a><span v-if="h.term" class="muted"> ({{ h.term }})</span>
          <Status :tone="h.stage_tone" :label="h.applied ? $t('postings.appliedBefore', { stage: h.stage_label }) : h.stage_label" />
        </div>
      </div>
    </template>

    <template v-if="sel.app_status && sel.app_explained && sel.app_explained.message">
      <SectionHead :title="$t('postings.progress')" />
      <div class="card">
        <div>{{ sel.app_explained.message }}</div>
        <div v-if="sel.submitted_at" class="t-meta">{{ $t('postings.submittedAt', { at: fmt(sel.submitted_at) }) }}</div>
        <TechDetails :text="sel.app_explained.detail" />
      </div>
    </template>

    <template v-if="sel.score_reason">
      <SectionHead :title="$t('postings.whyScore')" />
      <div class="card">{{ sel.score_reason }}</div>
    </template>

    <template v-if="sel.brief">
      <SectionHead :title="$t('postings.brief')" />
      <div class="card md" v-html="renderMarkdown(sel.brief)"></div>
    </template>
    <p v-else-if="sel.has_jd !== false && sel.score != null" class="t-secondary">
      {{ $t('postings.noBriefWritten') }}
      <button class="sm ghost" :disabled="briefing" @click="writeBrief">{{ briefing ? $t('postings.writing') : $t('postings.writeBrief') }}</button>
    </p>

    <SectionHead :title="$t('postings.jd')" />
    <div class="card">
      <p v-if="sel.jd_partial === 'summary'" class="callout warn job-jd-note">{{ $t('postings.jdSummary') }}</p>
      <p v-else-if="sel.jd_partial === 'cut'" class="callout job-jd-note">{{ $t('postings.jdCut') }}</p>
      <template v-if="sel.jd_text && sel.jd_text.length >= 200">
        <pre class="job-jd" :class="{ folded: !showJd && sel.jd_text.length >= 900 }">{{ sel.jd_text }}</pre>
        <button v-if="sel.jd_text.length >= 900" class="ghost sm" @click="showJd = !showJd">{{ showJd ? $t('postings.less') : $t('postings.more') }}</button>
      </template>
      <template v-else>
        <p v-if="sel.summary || sel.note || sel.jd_text">{{ sel.jd_text || sel.summary || sel.note }}</p>
        <p class="t-meta">{{ $t('postings.jdNone') }}</p>
      </template>
    </div>
  </SideDrawer>
  </template>
</template>

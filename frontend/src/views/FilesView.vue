<script setup>
import { t as T } from '../i18n/catalog'
import { computed, onMounted, ref } from 'vue'
import { api, ROOT } from '../api'
import BulkBar from '../components/BulkBar.vue'
import EmptyState from '../components/EmptyState.vue'
import FileButton from '../components/FileButton.vue'
import HelpPop from '../components/HelpPop.vue'
import Icon from '../components/Icon.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import Popover from '../components/Popover.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import PdfView from '../components/PdfView.vue'
import { fmtTime, run, toast, ask, persona } from '../ui'
import { t, tag } from '../i18n/catalog'

const docs = ref([])
const folder = ref('base') // base | generated | all | kind:<k> | job:<id>
const q = ref('')
const showInactive = ref(false)
const cur = ref(null)
const renaming = ref(false)
const newName = ref('')
const upKind = ref('resume_site')
const picked = ref(new Set())

// What a file is used as. `base` kinds are things you upload once; `generated` are written per job.
const KINDS = {
  resume_docx: T('files.page.originalRSumIn'), resume_site: T('files.page.rSumForCompany'), resume_portal: T('files.page.rSumForPd'), transcript: T('files.page.transcript'), summary_sheet: 'Summary Sheet',
  cl_template: T('files.page.coverLetterTemplate'), cl_example: T('files.page.sampleCoverLetter'), portfolio: T('files.page.portfolio'), certificate: T('files.page.certificatesProof'), reference: T('files.page.referenceLetter'), research_statement: T('files.page.researchStatement'), teaching_statement: T('files.page.teachingStatement'), publications: T('files.page.publications'), writing_sample: T('files.page.writingWorkSamples'), diversity_statement: T('files.page.diversityStatement'), source: T('files.page.materialForBuildingYour'), other: T('files.page.other'),
  cover_letter: T('files.page.coverLetter'), tailored_resume: T('files.page.tailorRSum'), made: t('files.kind.made'),
}
const GENERATED = ['cover_letter', 'tailored_resume', 'made']
const UPLOADABLE = Object.keys(KINDS).filter((k) => !GENERATED.includes(k) && (!persona.features.doc_kinds || persona.features.doc_kinds.includes(k)))
const GROUPS = [
  [T('files.page.rSum'), ['resume_site', 'resume_portal', 'resume_docx']], [T('files.page.transcriptsAndCertificates'), ['transcript', 'summary_sheet', 'certificate', 'reference']],
  [T('files.page.coverLetterTemplatesAnd'), ['cl_template', 'cl_example']], [T('files.page.portfolioAndStatements'), ['portfolio', 'writing_sample', 'research_statement', 'teaching_statement', 'publications', 'diversity_statement']], [T('files.page.other'), ['source', 'other']],
]
const isGen = (d) => GENERATED.includes(d.kind)
// What a row's controls are called: two writings of one letter have the same file name, so the version is part of it.
const rowName = (d) => (d.version ? T('files.page.version2', { p0: d.name, p1: d.version }) : d.name)
const openLabel = (d) => T('files.page.open', { p0: rowName(d) })
const pickLabel = (d) => T('files.page.select', { p0: rowName(d) })
const base = computed(() => docs.value.filter((d) => !isGen(d)))
const generated = computed(() => docs.value.filter(isGen))
const count = (kinds) => base.value.filter((d) => kinds.includes(d.kind) && d.active).length

// generated files grouped by the job they were written for, newest job first
const jobs = computed(() => {
  const m = new Map()
  for (const d of generated.value) {
    const k = d.job_id || 0
    if (!m.has(k)) m.set(k, { id: k, name: d.for_job || T('files.page.noLinkedPosting'), company: d.job_company || '', title: d.job_title || '', where: d.job_where || '', stage: d.job_stage, tone: d.job_tone, archived: d.job_archived, sent: d.job_sent, files: [] })
    m.get(k).files.push(d)
  }
  return [...m.values()].sort((a, b) => b.files[0].id - a.files[0].id)
})
// The jobs in three groups, by where the application stands. What is being prepared is what one looks for; what was
// sent or shelved is kept, folded away, so that the list stays as short as the work in hand.
const SECTIONS = [['open', T('files.page.inPreparation')], ['sent', T('files.page.submitted')], ['old', T('files.page.archived')]]
const sectionOf = (j) => (j.archived ? 'old' : j.sent ? 'sent' : 'open')
const bySection = computed(() => Object.fromEntries(SECTIONS.map(([k]) => [k, jobs.value.filter((j) => sectionOf(j) === k)])))
const unfolded = ref(new Set(['open']))
function fold(k) { const s = new Set(unfolded.value); s.has(k) ? s.delete(k) : s.add(k); unfolded.value = s }
const isOpen = (k) => unfolded.value.has(k) || bySection.value[k].some((j) => folder.value === 'job:' + j.id)
// what is narrowed to: files that went out with an application, files an application being prepared still uses; and
// whether the archived ones are shown (archived: put away, kept - a file that went out is what was sent)
const onlySent = ref(false)
const onlyInUse = ref(false)
const showArchived = ref(false)
const archivedCount = computed(() => docs.value.filter((d) => d.archived).length)
const filtersOn = computed(() => [onlySent.value, onlyInUse.value, showArchived.value, showInactive.value].filter(Boolean).length)
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  let rows = docs.value.filter((d) => showArchived.value || !d.archived)
  if (onlySent.value) rows = rows.filter((d) => d.sent)
  if (onlyInUse.value) rows = rows.filter((d) => d.in_use)
  if (folder.value === 'base') rows = rows.filter((d) => !isGen(d))
  else if (folder.value === 'generated') rows = rows.filter(isGen)
  else if (folder.value.startsWith('group:')) rows = rows.filter((d) => !isGen(d) && GROUPS[+folder.value.slice(6)][1].includes(d.kind))
  else if (folder.value.startsWith('job:')) rows = rows.filter((d) => isGen(d) && String(d.job_id || 0) === folder.value.slice(4))
  if (!showInactive.value && !folder.value.startsWith('job:')) rows = rows.filter((d) => d.active)
  if (needle) rows = rows.filter((d) => `${d.name} ${d.for_job} ${KINDS[d.kind] || ''}`.toLowerCase().includes(needle))
  return rows
})
const inactiveCount = computed(() => docs.value.filter((d) => !d.active).length)
const totalSize = computed(() => docs.value.reduce((a, d) => a + (d.size || 0), 0))
// several things in one line, joined the way the language joins them
const listed = (xs) => new Intl.ListFormat(tag(), { style: 'short', type: 'conjunction' }).format(xs)
// A row's second line (what the file is, for which posting, since when) and its one state. Of the states only a
// missing file is loud (a .tag, in the template); the others are ordinary, the reason behind an (i).
const subOf = (d) => [(KINDS[d.kind] || d.kind) + (d.version ? ' ' + T('files.page.version', { p0: d.version }) : ''), d.for_job && !folder.value.startsWith('job:') ? d.for_job : '', fmtTime(d.created_at)].filter(Boolean).join(' · ')
const metaOf = (d) => [KINDS[d.kind] || d.kind, fmtTime(d.created_at), sizeText(d.size) + (d.pages ? ' ' + T('files.page.pages', { p0: d.pages }) : '') + (d.version ? ' ' + T('files.page.version', { p0: d.version }) : '')].join(' · ')
function stateOf(d) {
  if (d.problems.length) return { tone: 'warn', label: T('files.page.hasIssues'), tip: T('files.page.selfCheckFoundProblems') }
  if (d.overwritten) return { tone: 'warn', label: T('files.page.overwritten'), tip: T('files.page.theFileOfThis') }
  if (d.archived) return { tone: '', label: t('files.archivedBadge') }
  if (d.sent) return { tone: 'ok', label: t('files.sentBadge') }
  if (!d.active) return { tone: '', label: isGen(d) ? T('files.page.versionNotInUse') : T('files.page.notInUse') }
  return null
}
const sizeText = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')
const title = computed(() => {
  if (folder.value === 'base') return T('files.page.filesIUploaded')
  if (folder.value === 'generated') return T('files.page.filesMadeForPostings')
  if (folder.value === 'all') return T('files.page.allFiles')
  if (folder.value.startsWith('group:')) return GROUPS[+folder.value.slice(6)][0]
  const j = jobs.value.find((x) => String(x.id) === folder.value.slice(4))
  return j ? j.name : ''
})

async function read() { docs.value = await api.get('/documents'); if (cur.value) cur.value = docs.value.find((d) => d.id === cur.value.id) || null }
const act = (fn, ok) => run(fn, ok, load)
function go(f) { folder.value = f; picked.value = new Set(); cur.value = null }
function pick(d) { cur.value = d; renaming.value = false }
function togglePick(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function upload(ev) {
  const files = [...ev.target.files]
  if (!files.length) return
  run(async () => {
    let last = null
    for (const f of files) { const fd = new FormData(); fd.append('kind', upKind.value); fd.append('file', f); last = await api.upload('/documents', fd) }
    await load()
    if (last) cur.value = docs.value.find((d) => d.id === last.id) || null
  }, files.length > 1 ? T('files.page.uploadedFiles', { p0: files.length }) : T('files.page.uploaded', { p0: files[0].name }))
  ev.target.value = ''
}
const rename = () => act(async () => { await api.patch('/documents/' + cur.value.id, { name: newName.value }); renaming.value = false }, T('files.page.renamed'))
const setKind = (k) => act(() => api.patch('/documents/' + cur.value.id, { kind: k }), T('files.page.purposeChanged'))
const setActive = (on) => act(() => api.patch('/documents/' + cur.value.id, { active: on }), on ? (isGen(cur.value) ? T('files.page.thisVersionIsNow') : T('files.page.turnedOnOtherFiles')) : T('files.page.turnedOffFutureDrafts'))
const destroy = async () => (await ask(T('files.page.permanentlyDeleteTheFile', { p0: cur.value.name }), { danger: true })) && act(async () => { await api.del('/documents/' + cur.value.id + '?permanent=true'); cur.value = null }, T('files.page.deleted'))
async function bulk(action) {
  const ids = [...picked.value]
  if (action === 'delete' && !(await ask(t('files.deleteAsk', { n: ids.length }, ids.length), { danger: true }))) return
  await act(() => api.post('/documents/bulk', { action, ids }), (r) => (action === 'delete' ? (r.archived_instead ? t('files.deletedKept', { n: r.done - r.archived_instead, kept: r.archived_instead }) : T('files.page.deletedFiles', { p0: ids.length }))
    : action === 'archive' ? t('files.archived', { n: ids.length }, ids.length) : T('files.page.disabledFiles', { p0: ids.length })))
  picked.value = new Set()
}
// Files made for applications that are over (or versions no longer used), that nothing being prepared still uses: put
// away in one go. Archived, never deleted - one that went out is what was sent (the server says which, `cleanable`).
const stale = computed(() => docs.value.filter((d) => d.cleanable))
async function cleanUp() {
  if (!stale.value.length) return toast(t('files.nothingToClean'))
  if (!(await ask(t('files.cleanAsk', { n: stale.value.length }, stale.value.length)))) return
  await act(() => api.post('/documents/bulk', { action: 'archive', ids: stale.value.map((d) => d.id) }), t('files.archived', { n: stale.value.length }, stale.value.length))
}
const setArchived = (on) => act(() => api.post('/documents/bulk', { action: on ? 'archive' : 'unarchive', ids: [cur.value.id] }), on ? t('files.archived', { n: 1 }, 1) : t('files.unarchived'))
// what else can be done with the open file: rarely, so behind a menu - the one that cannot be undone last
const curMenu = computed(() => {
  const d = cur.value
  if (!d) return []
  return [
    d.active ? { id: 'stop', label: T('files.page.disable'), icon: 'pause' } : { id: 'use', label: isGen(d) ? T('files.page.useThisVersion') : T('files.page.reEnable'), icon: 'check', disabled: d.missing || d.overwritten },
    { id: 'archive', label: d.archived ? t('files.unarchive') : t('files.archive'), icon: 'inbox' },
    ...(d.sent ? [] : [{ divider: true }, { id: 'delete', label: T('files.page.deletePermanently'), icon: 'trash', danger: true }]),
  ]
})
const onCur = (id) => (id === 'stop' ? setActive(false) : id === 'use' ? setActive(true) : id === 'archive' ? setArchived(!cur.value.archived) : destroy())
const PURPOSE = { mine: 'files.purpose.mine', for_job: 'files.purpose.forJob', made: 'files.purpose.made' }
const previewable = (d) => ['pdf', 'docx', 'doc'].includes(d.ext)
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load)
onMounted(load)
</script>

<template>
  <PageHead :title="$t('files.page.files2')">
    <AaSelect v-model="upKind" :aria-label="$t('files.page.whatTheUploadedFile')"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect>
    <FileButton class="primary" multiple @change="upload"><Icon name="draft" />{{ $t('files.page.upload') }}</FileButton>
  </PageHead>
  <DataState :s="st" :what="$t('files.page.files2')" @retry="load" />
  <template v-if="st.at">

  <!-- (the three panes are laid out by the width of this box, not of the window: the side bar and a narrow page are the same to it) -->
  <div class="fm-box">
  <div class="fm">
    <!-- folders -->
    <nav class="card fm-nav" :aria-label="$t('files.page.folders')">
      <button :class="{ on: folder === 'base' }" @click="go('base')"><Icon name="user" /><Trunc :text="$t('files.page.filesIUploaded')" /><span class="n">{{ base.filter((d) => d.active).length }}</span></button>
      <button v-for="(g, i) in GROUPS" :key="i" class="sub" :class="{ on: folder === 'group:' + i }" @click="go('group:' + i)"><Trunc :text="g[0]" /><span class="n">{{ count(g[1]) }}</span></button>

      <button class="fm-top" :class="{ on: folder === 'generated' }" @click="go('generated')"><Icon name="briefcase" /><Trunc :text="$t('files.page.generatedForThisPosting')" /><span class="n">{{ generated.length }}</span></button>
      <template v-for="[k, label] in SECTIONS" :key="k">
        <template v-if="bySection[k].length">
          <button class="sub fold" :aria-expanded="isOpen(k)" @click="fold(k)"><Icon :name="isOpen(k) ? 'chevron_up' : 'chevron'" />{{ label }}<span class="n">{{ bySection[k].length }}</span></button>
          <template v-if="isOpen(k)">
            <button v-for="j in bySection[k]" :key="j.id" class="sub deep" :class="{ on: folder === 'job:' + j.id }" @click="go('job:' + j.id)">
              <span v-if="j.company" class="fm-job"><Trunc class="fm-co" :text="j.company" /><Trunc :text="j.where ? j.title + ' · ' + j.where : j.title" /></span>
              <Trunc v-else :text="j.name" /><span class="n">{{ j.files.length }}</span>
            </button>
          </template>
        </template>
      </template>
      <div v-if="!jobs.length" class="hint fm-hint">{{ $t('files.page.coverLettersAppearHere') }}</div>

      <button class="fm-top" :class="{ on: folder === 'all' }" @click="go('all')"><Icon name="inbox" /><Trunc :text="$t('files.page.allFiles')" /><span class="n">{{ docs.length }}</span></button>
      <div class="fm-foot">
        <div>{{ $t('files.page.files', { p0: docs.length, p1: sizeText(totalSize) }) }}</div>
        <button v-if="stale.length" class="sm ghost fm-clean" @click="cleanUp">{{ $t('files.clean', { n: stale.length }, stale.length) }}</button>
      </div>
    </nav>

    <!-- list -->
    <div class="card fm-list">
      <div class="fm-list-head">
        <Trunc class="t-primary grow" :text="title" />
        <Popover :label="$t('files.filter.label')" :width="280" align="end">
          <template #trigger="{ toggle, attrs }"><button class="sm" v-bind="attrs" @click="toggle"><Icon name="filter" />{{ $t('files.filter.label') }}<span v-if="filtersOn" class="n">{{ filtersOn }}</span></button></template>
          <div class="fm-filters">
            <label><input v-model="onlySent" type="checkbox" /> {{ $t('files.filter.sent') }}</label>
            <label><input v-model="onlyInUse" type="checkbox" /> {{ $t('files.filter.inUse') }}</label>
            <label v-if="archivedCount"><input v-model="showArchived" type="checkbox" /> {{ $t('files.filter.archived', { n: archivedCount }) }}</label>
            <label v-if="inactiveCount && !folder.startsWith('job:')"><input v-model="showInactive" type="checkbox" /> {{ $t('files.page.alsoShowUnused', { p0: inactiveCount }) }}</label>
          </div>
        </Popover>
      </div>
      <input v-model="q" class="w-full fm-search" type="search" :placeholder="$t('files.page.searchFileNamesOr')" :aria-label="$t('files.page.searchFileNamesOr')" />
      <div class="fm-rows">
        <div v-for="d in shown" :key="d.id" class="mat-item" :class="{ on: cur && cur.id === d.id }" @click="pick(d)">
          <input type="checkbox" :checked="picked.has(d.id)" :aria-label="pickLabel(d)" @click.stop @change="togglePick(d.id)" />
          <span class="ext" :class="d.ext">{{ (d.ext || '?').toUpperCase().slice(0, 4) }}</span>
          <span class="mat-main">
            <button v-tip.overflow="d.name" type="button" class="name mat-open" :aria-current="cur && cur.id === d.id ? 'true' : undefined" :aria-label="openLabel(d)" @click.stop="pick(d)">{{ d.name }}</button>
            <Trunc class="sub" :text="subOf(d)" />
          </span>
          <span v-if="d.missing" class="tag bad">{{ $t('files.page.fileMissing') }}</span>
          <Status v-else-if="stateOf(d)" :tone="stateOf(d).tone" :label="stateOf(d).label" :tip="stateOf(d).tip" />
        </div>
        <EmptyState v-if="!shown.length" icon="draft" :title="q ? $t('files.page.notFound') : $t('files.page.noFilesHereYet')" :text="folder === 'base' && !q ? $t('files.page.uploadARSum') : ''" />
      </div>
    </div>

    <!-- preview -->
    <div class="card fm-view" :class="{ idle: !cur }">
      <template v-if="cur">
        <div class="fm-view-head">
          <div class="grow">
            <form v-if="renaming" class="actions" @submit.prevent="rename"><input v-model="newName" v-focus class="grow" :aria-label="$t('files.page.rename')" /><button type="submit" class="primary sm">{{ $t('files.page.save') }}</button><button type="button" class="sm ghost" @click="renaming = false">{{ $t('files.page.cancel') }}</button></form>
            <Trunc v-else as="div" class="card-title" :text="cur.name" />
            <Trunc as="div" class="t-meta" :text="metaOf(cur)" />
          </div>
          <span v-if="cur.missing" class="tag bad">{{ $t('files.page.fileMissing') }}</span>
          <Status v-else :tone="cur.active ? 'ok' : ''" :label="cur.active ? $t('files.page.inUse') : isGen(cur) ? $t('files.page.versionNotInUse') : $t('files.page.notInUse')" />
        </div>
        <dl class="fm-facts">
          <template v-if="cur.for_job"><dt>{{ $t('files.writtenFor') }}</dt>
            <dd><router-link :to="{ path: '/jobs', query: { open: cur.job_id } }">{{ cur.for_job }}</router-link> <Status v-if="cur.job_stage" :tone="cur.job_tone" :label="cur.job_stage" /></dd></template>
          <dt>{{ $t('files.purpose.label') }}</dt><dd>{{ $t(PURPOSE[cur.purpose] || 'files.purpose.mine') }}</dd>
          <template v-if="!isGen(cur)"><dt><label id="fm-kind">{{ $t('files.page.whatThisFileIs') }}</label></dt>
            <dd><AaSelect small :model-value="cur.kind" aria-labelledby="fm-kind" @update:model-value="setKind"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect></dd></template>
          <template v-if="cur.made_from.length"><dt>{{ $t('files.madeFrom') }}</dt><dd>{{ listed(cur.made_from) }}</dd></template>
          <template v-if="cur.application"><dt>{{ $t('files.belongs') }}</dt>
            <dd><router-link :to="`/applications/${cur.application.id}`">{{ cur.for_job }}</router-link> <span class="meta small">{{ cur.application.label }}</span> <span v-if="cur.application.ended" class="meta small">· {{ $t('files.ended') }}</span></dd></template>
          <dt>{{ $t('files.went') }}</dt>
          <dd>
            <span v-if="!cur.went.length" class="none">{{ $t('files.wentNowhere') }}</span>
            <div v-for="(w, k) in cur.went" :key="k" class="fm-went">
              <Status :tone="w.sent ? 'ok' : ''" :label="w.how === 'mail' ? $t('files.how.mail') : w.sent ? $t('files.how.sent') : $t('files.how.record')" />
              <router-link v-if="w.application_id" :to="`/applications/${w.application_id}`">{{ w.company }} · {{ w.title }}</router-link>
              <span v-if="w.field" class="muted">· {{ w.field }}</span>
            </div>
          </dd>
        </dl>
        <p v-if="cur.in_draft && !cur.active" class="callout fm-note"><Icon name="info" /><span>{{ $t('files.page.theDraftThatExists') }}</span></p>
        <p v-if="cur.overwritten" class="callout warn fm-note"><Icon name="alert" /><span class="grow">{{ $t('files.page.thisVersionsFileHas') }}</span><HelpPop :label="$t('files.page.overwritten')" :text="$t('files.page.earlierVersionsOfThe')" /></p>
        <div v-if="cur.problems.length" class="callout warn fm-note"><Icon name="alert" /><div><div class="t-primary">{{ $t('files.page.issuesFoundInSelf') }}</div><div v-for="(x, k) in cur.problems" :key="k" class="small">{{ x }}</div></div></div>
        <div class="actions fm-acts">
          <a :href="`api/documents/${cur.id}/file`" :download="cur.name" class="btn sm"><Icon name="download" />{{ $t('files.page.download') }}</a>
          <button v-if="!renaming" class="sm" @click="renaming = true; newName = cur.name"><Icon name="edit" />{{ $t('files.page.rename') }}</button>
          <Menu :label="$t('common.more')" :items="curMenu" @pick="onCur" />
        </div>
        <div v-if="cur.missing" class="empty"><div class="t">{{ $t('files.page.theFileIsNo') }}</div><div>{{ $t('files.page.onlyOneRecordLeft') }}</div></div>
        <PdfView v-else-if="previewable(cur)" :key="cur.id" :src="`${ROOT}/api/documents/${cur.id}/bytes`" />
        <div v-else class="empty"><div class="t">{{ $t('files.page.thisFileTypeCant') }}</div><div>{{ $t('files.page.clickDownloadToView') }}</div></div>
      </template>
      <EmptyState v-else icon="search" :title="$t('files.page.clickAFileTo')" :text="$t('files.page.youCanViewPdf')" />
    </div>
  </div>
  </div>
  </template>

  <BulkBar :count="picked.size" @clear="picked = new Set()">
    <button class="sm" @click="bulk('archive')">{{ $t('files.archive') }}</button>
    <button class="sm" @click="bulk('stop')">{{ $t('files.page.disable') }}</button>
    <Menu :label="$t('common.more')" :items="[{ id: 'delete', label: $t('files.page.deletePermanently'), icon: 'trash', danger: true }]" placement="top" @pick="bulk('delete')" />
  </BulkBar>
</template>

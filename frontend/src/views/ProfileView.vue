<script setup>
import { t as T } from '../i18n/catalog'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { renderMarkdown } from '../md'
import CardHead from '../components/CardHead.vue'
import DataState from '../components/DataState.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import FileButton from '../components/FileButton.vue'
import HelpPop from '../components/HelpPop.vue'
import Icon from '../components/Icon.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
import DateTimeCell from '../components/cells/DateTimeCell.vue'
import EntityCell from '../components/cells/EntityCell.vue'
import { dataState } from '../data'
import { fmtTime, run as runAction, toast, ask } from '../ui'
import { clone, mayLeave, same, useUnsaved } from '../dirty'
import { useProfileInit } from '../profileInit'
import { useRoute } from 'vue-router'

const route = useRoute()
const tab = ref(['sections', 'pay', 'stories', 'init', 'scoring', 'markdown', 'history'].includes(route.query.tab) ? route.query.tab : 'sections')
// salary, notice period, referees: a form that keeps two sections of the profile up to date
const st = ref({ compensation: {}, referees: [], suggested: {} })
const CONTACT = [['ask_first', T('profile.askMeBeforeSharing')], ['after_offer', T('profile.contactOnlyAfterAn')], ['anytime', T('profile.canBeContactedAnytime')]]
const loadSt = async () => {
  const d = await api.get('/profile/structured')
  take('st', st, { ...d, compensation: { period: 'year', policy: 'state', ...d.compensation }, referees: d.referees.length ? d.referees : [] })
}
// What each editor of this page held when it was last read or saved. Saving one of them reads the page afresh; that
// used to put every other editor back to what is saved, with whatever had been typed in it.
const base = reactive({ md: '', stories: '', scoring: '', st: { compensation: {}, referees: [], suggested: {} } })
const take = (k, r, fresh) => { if (same(r.value, base[k])) r.value = clone(fresh); base[k] = clone(fresh) }
const regions = ref({ packs: [] })
const addRef = () => st.value.referees.push({ name: '', title: '', org: '', relation: '', email: '', phone: '', contact: 'ask_first' })
// (a referee that has nothing written in it yet goes without a question)
async function removeRef(i) {
  const r = st.value.referees[i]
  const filled = ['name', 'title', 'org', 'relation', 'email', 'phone'].some((k) => (r[k] || '').trim())
  if (filled && !(await ask(T('profile.deleteRefAsk', { name: r.name || T('profile.referenceN', { n: i + 1 }) }), { danger: true }))) return
  st.value.referees.splice(i, 1)
}
const saveSt = () => run(async () => { await api.put('/profile/structured', { compensation: st.value.compensation, referees: st.value.referees }); base.st = clone(st.value) }, T('profile.savedAndAddedTo'))
const p = ref({ markdown: '', sections: [], versions: [], agent_added: [] })
const scoring = ref('')
const stories = ref('')
const docs = ref([])
const editIdx = ref(-1)
const editBody = ref('')
const md = ref('')
const notes = ref('')
// "从简历生成" is a task on the server (profileInit.js): this page asks where it stands - also when it is opened again
// after another page - and what was written is kept there until it is adopted or discarded. What is edited here is
// the proposal's text.
const { st: gen, phase: genPhase, working: genWorking, load: loadGen, start: startGen } = useProfileInit((now) => {
  if (now === 'applied') { toast(T('profile.yourProfileHasBeen')); load() }
  else if (now === 'proposal') toast(T('profile.aDraftOfYour'))
})
const genTask = computed(() => (gen.value && gen.value.task) || {})
const draftOf = ref(0)        // the task whose proposal is being edited here
const draftText = ref('')
const draftDirty = computed(() => !!draftOf.value && draftText.value !== (genTask.value.draft || ''))
watch(gen, (s) => {
  const t = (s && s.task) || {}
  if (t.draft) { if (draftOf.value !== t.id) { draftOf.value = t.id; draftText.value = t.draft } }
  else { draftOf.value = 0; draftText.value = '' }
  if (!notes.value && t.notes && (t.draft || ['queued', 'running'].includes(t.status))) notes.value = t.notes      // what this run was asked with
})
const upKind = ref('resume_site')
const mdPreview = ref(true)
const mdDirty = computed(() => md.value !== base.md)
const stDirty = computed(() => !same(st.value, base.st))
const sectionDirty = computed(() => editIdx.value >= 0 && !!p.value.sections[editIdx.value] && editBody.value !== p.value.sections[editIdx.value].body)

const KINDS = {
  resume_site: T('profile.rSumForEmployer'), resume_portal: T('profile.rSumForPd'), transcript: T('profile.transcript'), cl_template: T('profile.coverLetterTemplateWord'),
  cl_example: T('profile.sampleCoverLetter'), source: T('profile.otherSetupFiles'), cover_letter: T('profile.generatedCoverLetter'), other: T('profile.other'), resume_docx: T('profile.rSumWordFor'),
}
const UPLOADABLE = ['resume_site', 'resume_portal', 'transcript', 'cl_template', 'cl_example', 'source']

async function read() {
  p.value = await api.get('/profile')
  take('md', md, p.value.markdown)
  take('scoring', scoring, (await api.get('/profile?doc=scoring')).markdown)
  take('stories', stories, (await api.get('/profile?doc=stories')).markdown)
  docs.value = await api.get('/documents')
  await loadSt()
  regions.value = await api.get('/regions')
  await loadGen().catch(() => {})
}
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st: page, load } = dataState(read)
const run = (fn, ok) => runAction(fn, ok, load)
// what the applicant put here themselves: not what the program wrote for one posting (a résumé rewritten for it, its cover
// letter) - those are the posting's, and are in the library
const active = computed(() => docs.value.filter((d) => d.active && !d.job_id && d.kind !== 'cover_letter' && d.kind !== 'tailored_resume'))
const todoCount = computed(() => (p.value.markdown.match(/TODO:/g) || []).length)

async function startEdit(i) { if (!(await mayLeave(['profile-section']))) return; editIdx.value = i; editBody.value = p.value.sections[i].body }
const saveSection = () => run(async () => {
  const secs = p.value.sections.map((s, i) => (i === editIdx.value ? { ...s, body: editBody.value } : s))
  await api.put('/profile', { sections: secs, note: T('profile.edit2') + p.value.sections[editIdx.value].title })
  editIdx.value = -1
}, T('profile.saved'))
const saveMd = () => run(async () => { await api.put('/profile', { markdown: md.value, note: T('profile.editTheFullText') }); base.md = md.value }, T('profile.saved'))
const saveStories = () => run(async () => { await api.put('/profile', { doc: 'stories', markdown: stories.value }); base.stories = stories.value }, T('profile.saved'))
const saveScoring = () => run(async () => { await api.put('/profile', { doc: 'scoring', markdown: scoring.value }); base.scoring = scoring.value }, T('profile.scoreRulesSaved'))
const restore = async (v) => (await ask(T('profile.rollBackToThis'), { ok: T('profile.revertToThisVersion') })) && run(() => api.post('/profile/restore/' + v.id), T('profile.reverted'))
const undo = async (a) => (await ask(T('profile.revokeAsk'), { ok: T('profile.revoke'), danger: true })) && run(() => api.post('/profile/remove-line', { fragment: a.note.slice(0, 40) }), T('profile.ruleUndone'))
const SOURCES = { user: T('profile.yourEdit'), agent: T('profile.recordedByTheApp'), init: T('profile.generateFromRSum') }
const VERSION_COLS = [{ id: 'note', header: T('profile.col.change'), min: 180, flex: 3 }, { id: 'source', header: T('profile.col.by'), min: 120, max: 200, flex: 2, priority: 1 }, { id: 'when', header: T('profile.col.saved'), width: 132 }, { id: 'act', header: '', width: 190, align: 'end' }]

function upload(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('kind', upKind.value); fd.append('file', f)
  run(async () => { const r = await api.upload('/documents', fd); pickAfter = r.id }, T('profile.uploaded', { p0: f.name })).then(() => { if (pickAfter) { cur.value = docs.value.find((d) => d.id === pickAfter) || cur.value; docFilter.value = 'active'; pickAfter = null } })
  ev.target.value = ''
}
let pickAfter = null
const docFilter = ref('active')
const cur = ref(null)
const renaming = ref(false)
const newName = ref('')
const shownDocs = computed(() => docs.value.filter((d) => (docFilter.value === 'all' ? true : docFilter.value === 'letters' ? d.kind === 'cover_letter' : d.active && d.kind !== 'cover_letter')))
const sizeText = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')
function pick(d) { cur.value = d; renaming.value = false }
async function docAct(fn, ok) { const id = cur.value && cur.value.id; await run(fn, ok); cur.value = docs.value.find((d) => d.id === id) || null }
const rename = () => docAct(async () => { await api.patch('/documents/' + cur.value.id, { name: newName.value }); renaming.value = false }, T('profile.renamed'))
const setKind = (k) => docAct(() => api.patch('/documents/' + cur.value.id, { kind: k }), T('profile.purposeChanged'))
const setActive = (on) => docAct(() => api.patch('/documents/' + cur.value.id, { active: on }), on ? T('profile.turnedOnOtherFiles') : T('profile.disabledDraftsWontUse'))
const destroy = async () => (await ask(T('profile.permanentlyDeleteTheFile', { p0: cur.value.name }), { danger: true })) && docAct(() => api.del('/documents/' + cur.value.id + '?permanent=true'), T('profile.deleted'))
async function init() {
  try { await startGen(notes.value) } catch (e) { toast(e.message, 'bad') }
}
const adopt = () => run(async () => { await api.post(`/profile/init/${draftOf.value}/adopt`, { markdown: draftText.value }); await loadGen() }, T('profile.draftedProfileApplied'))
const dropDraft = async () => (await ask(T('profile.notAdoptThisDraft'), { ok: T('profile.doNotUse'), danger: true })) && run(async () => { await api.post(`/profile/init/${draftOf.value}/discard`); await loadGen() }, T('profile.draftDiscarded'))

// What is edited on each tab, and is asked about before it is left: another tab, another section, another page.
const TAB_LABELS = { sections: T('profile.myInfo'), pay: T('profile.salaryReferences'), stories: T('profile.myExperienceStories'), init: T('profile.generateFromRSum'), scoring: T('profile.postingScoreRules'), markdown: T('profile.editSource'), history: T('profile.versionHistory') }
const EDITED_ON = { sections: ['profile-section'], pay: ['profile-pay'], stories: ['profile-stories'], init: ['profile-draft'], scoring: ['profile-scoring'], markdown: ['profile-md'] }
useUnsaved({ id: 'profile-section', get label() { const s = p.value.sections[editIdx.value]; return s ? T('profile.profileSection', { p0: s.title === 'preamble' ? T('profile.notes') : s.title }) : T('profile.myInfo') }, dirty: () => sectionDirty.value, save: () => saveSection(), discard: () => { editIdx.value = -1 } })
useUnsaved({ id: 'profile-pay', label: T('profile.salaryReferences'), dirty: () => stDirty.value, save: () => saveSt(), discard: () => { st.value = clone(base.st) } })
useUnsaved({ id: 'profile-stories', label: T('profile.myExperienceStories'), dirty: () => stories.value !== base.stories, save: () => saveStories(), discard: () => { stories.value = base.stories } })
useUnsaved({ id: 'profile-scoring', label: T('profile.postingScoreRules'), dirty: () => scoring.value !== base.scoring, save: () => saveScoring(), discard: () => { scoring.value = base.scoring } })
useUnsaved({ id: 'profile-md', label: T('profile.editSource'), dirty: () => mdDirty.value, save: () => saveMd(), discard: () => { md.value = base.md } })
// (the proposal itself is kept on the server; what would be lost by leaving is only what was changed in it here)
useUnsaved({ id: 'profile-draft', label: T('profile.yourChangesToThe'), dirty: () => draftDirty.value, save: () => adopt(), discard: () => { draftText.value = genTask.value.draft || '' } })
const marked = (k) => (EDITED_ON[k] || []).some((id) => ({ 'profile-section': sectionDirty.value, 'profile-pay': stDirty.value, 'profile-stories': stories.value !== base.stories,
  'profile-scoring': scoring.value !== base.scoring, 'profile-md': mdDirty.value, 'profile-draft': draftDirty.value })[id])
async function go(k) { if (k !== tab.value && (await mayLeave(EDITED_ON[tab.value] || []))) tab.value = k }
onMounted(load)
</script>

<template>
  <PageHead :title="$t('profile.profile')" :help="$t('profile.everythingUsedToFill')">
    <!-- (what the profile still lacks, and a generation under way, are states: under the title, not among the actions) -->
    <template v-if="genWorking || todoCount" #sub>
      <span class="actions">
        <Status v-if="genWorking" tone="info" :label="$t('profile.generatingFromYourR')" />
        <Status v-if="todoCount" tone="warn" :label="$t('profile.fieldsStillEmpty', { p0: todoCount })" />
      </span>
    </template>
    <button v-if="!genWorking && genPhase === 'proposal' && tab !== 'init'" @click="go('init')">{{ $t('profile.aGeneratedDraftIs') }}</button>
    <router-link to="/files" class="btn"><Icon name="inbox" />{{ $t('profile.openTheLibrary') }}</router-link>
  </PageHead>
  <DataState :s="page" :what="$t('profile.profile')" @retry="load" />
  <template v-if="page.at">
  <div class="seg tabs page-tabs" role="tablist" :aria-label="$t('profile.profile')">
    <button v-for="(l, k) in TAB_LABELS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="go(k)">{{ l }}<span v-if="marked(k)" v-tip="$t('profile.unsavedChanges')" class="unsaved-dot" role="img" :aria-label="$t('profile.unsavedChanges')"></span></button>
  </div>

  <template v-if="tab === 'sections'">
    <div v-if="p.agent_added.length" class="card">
      <CardHead :title="$t('profile.whatTheAppNoted')" :note="p.agent_added.length" />
      <div class="rows tight">
        <div v-for="a in p.agent_added" :key="a.id" class="r">
          <Trunc class="grow" :text="a.note" :lines="2" />
          <span class="end"><span class="t-meta atomic">{{ fmtTime(a.created_at) }}</span><button class="ghost sm" @click="undo(a)">{{ $t('profile.revoke') }}</button></span>
        </div>
      </div>
    </div>
    <details v-if="regions.packs.length" class="card region-notes">
      <summary><span class="card-title">{{ $t('profile.applicationFormsInThe') }}</span> <span class="t-meta">{{ $t('profile.regionsNote', { regions: regions.packs.map((r) => r.name).join(', ') }) }}</span></summary>
      <div v-for="r in regions.packs" :key="r.code" class="region">
        <div class="t-primary">{{ r.name }}</div>
        <ul><li v-for="x in r.profile" :key="x">{{ x }}</li></ul>
        <div v-if="r.diversity" class="t-meta">{{ $t('profile.diversityEqualOpportunitySurvey', { p0: r.diversity }) }}</div>
        <div v-if="r.consents" class="t-meta">{{ $t('profile.consent', { p0: r.consents }) }}</div>
        <div v-if="r.never" class="t-meta">{{ $t('profile.theAppWontFill', { p0: r.never }) }}</div>
      </div>
    </details>
    <div v-for="(s, i) in p.sections" :key="i" class="card">
      <CardHead :title="s.title === 'preamble' ? $t('profile.notes') : s.title">
        <button v-if="editIdx !== i" class="ghost sm" @click="startEdit(i)"><Icon name="edit" />{{ $t('profile.edit') }}</button>
      </CardHead>
      <template v-if="editIdx === i">
        <textarea v-model="editBody" :rows="Math.min(30, Math.max(6, editBody.split('\n').length + 1))" :aria-label="s.title === 'preamble' ? $t('profile.notes') : s.title"></textarea>
        <div class="actions form-acts"><span class="grow"></span><button @click="editIdx = -1">{{ $t('profile.cancel') }}</button><button class="primary" :disabled="!sectionDirty" @click="saveSection">{{ $t('profile.save') }}</button></div>
      </template>
      <div v-else-if="s.body" class="md" v-html="renderMarkdown(s.body)"></div>
      <p v-else class="none">{{ $t('profile.empty') }}</p>
    </div>
  </template>

  <template v-if="tab === 'pay'">
    <div class="card">
      <CardHead :title="$t('profile.expectedSalary')" />
      <p class="card-sub">{{ $t('profile.usedWhenAnApplication') }}</p>
      <div class="pay-policy" role="radiogroup" :aria-label="$t('profile.expectedSalary')">
        <label><input v-model="st.compensation.policy" type="radio" value="state" /> {{ $t('profile.answerWithinTheRange') }}</label>
        <label><input v-model="st.compensation.policy" type="radio" value="ask" /> {{ $t('profile.dontFillInNumbers') }}</label>
      </div>
      <div class="fields">
        <template v-if="st.compensation.policy !== 'ask'">
          <label class="f">{{ $t('profile.min') }}<input v-model="st.compensation.min" placeholder="70000" inputmode="numeric" /></label>
          <label class="f">{{ $t('profile.max') }}<input v-model="st.compensation.max" placeholder="85000" inputmode="numeric" /></label>
          <label class="f">{{ $t('profile.currency') }}<input v-model="st.compensation.currency" placeholder="CAD" /></label>
          <div class="f"><span id="pay-per">{{ $t('profile.per') }}</span>
            <AaSelect v-model="st.compensation.period" aria-labelledby="pay-per"><option value="year">{{ $t('profile.year') }}</option><option value="month">{{ $t('profile.month') }}</option><option value="hour">{{ $t('profile.hour') }}</option></AaSelect>
          </div>
          <label class="check"><input v-model="st.compensation.negotiable" type="checkbox" /> {{ $t('profile.negotiable') }}</label>
        </template>
        <label class="f span2">{{ $t('profile.currentSalaryOptional') }}<input v-model="st.compensation.current" :placeholder="$t('profile.eGCadYear')" /></label>
        <label class="check span2"><input v-model="st.compensation.share_current" type="checkbox" /> {{ $t('profile.shareCurrentSalaryWhen') }}</label>
      </div>
      <CardHead class="sub-head" :title="$t('profile.noticePeriodStartDate')" />
      <div class="fields">
        <label class="f span2">{{ $t('profile.noticePeriod') }}<input v-model="st.compensation.notice" :placeholder="$t('profile.eGWeeksOne')" /></label>
        <label class="f span2">{{ $t('profile.earliestStartDate') }}<input v-model="st.compensation.start" :placeholder="$t('profile.eGTwoWeeks')" /></label>
        <label class="f all">{{ $t('profile.notesOptional') }}<input v-model="st.compensation.notes" :placeholder="$t('profile.eGCadPer')" /></label>
      </div>
    </div>
    <div class="card">
      <CardHead :title="$t('profile.references')" :help="$t('profile.onlyFilledInWhen')" :note="st.referees.length || ''">
        <button class="sm" @click="addRef"><Icon name="plus" />{{ $t('profile.addOne') }}</button>
      </CardHead>
      <p v-if="!st.referees.length" class="muted">{{ $t('profile.noReferencesAddedYet', { p0: st.suggested.referees ? $t('profile.applicationsForJobsLike') : '' }) }}</p>
      <div v-for="(r, i) in st.referees" :key="i" class="ref-card">
        <div class="ref-head">
          <Trunc class="t-primary grow" :text="r.name || $t('profile.referenceN', { n: i + 1 })" />
          <Menu :label="$t('common.more')" :items="[{ id: 'delete', label: $t('profile.delete'), icon: 'trash', danger: true }]" @pick="removeRef(i)" />
        </div>
        <div class="fields">
          <label class="f">{{ $t('profile.name') }}<input v-model="r.name" autocomplete="off" /></label>
          <label class="f">{{ $t('profile.job') }}<input v-model="r.title" /></label>
          <label class="f">{{ $t('profile.unit') }}<input v-model="r.org" /></label>
          <label class="f">{{ $t('profile.relationshipToYou') }}<input v-model="r.relation" :placeholder="$t('profile.eGDirectManager')" /></label>
          <label class="f">{{ $t('profile.email') }}<input v-model="r.email" type="email" autocomplete="off" /></label>
          <label class="f">{{ $t('profile.phone') }}<input v-model="r.phone" type="tel" autocomplete="off" /></label>
          <div class="f"><span :id="'ref-contact-' + i">{{ $t('profile.whenTheyCanBe') }}</span>
            <AaSelect v-model="r.contact" :aria-labelledby="'ref-contact-' + i"><option v-for="[k, l] in CONTACT" :key="k" :value="k">{{ l }}</option></AaSelect>
          </div>
        </div>
      </div>
    </div>
    <div class="actions form-acts"><span class="grow"></span><HelpPop :label="$t('profile.save')" :text="$t('profile.savingWritesThisTo')" /><button class="primary" :disabled="!stDirty" @click="saveSt"><Icon name="check" />{{ $t('profile.save') }}</button></div>
  </template>

  <template v-if="tab === 'init'">
    <div class="card">
      <CardHead :title="$t('profile.uploadYourFiles')" />
      <div class="actions">
        <AaSelect v-model="upKind" :aria-label="$t('profile.fileKind')"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect>
        <FileButton @change="upload"><Icon name="inbox" />{{ $t('profile.chooseFile') }}</FileButton>
      </div>
      <div v-if="active.length" class="rows tight init-files">
        <div v-for="d in active" :key="d.id" class="r"><span class="meta lead">{{ KINDS[d.kind] || KINDS.other }}</span><Trunc as="a" :href="`api/documents/${d.id}/file`" target="_blank" rel="noopener" :text="d.name" /></div>
      </div>
      <p v-else class="muted mt-2">{{ $t('profile.nothingHasBeenUploaded') }}</p>
      <p class="hint mt-2">{{ $t('profile.onlyWhatYouUploaded') }} <router-link to="/files">{{ $t('profile.openTheLibrary') }}</router-link></p>
      <CardHead class="sub-head" :title="$t('profile.additionalNotesOptional')" />
      <textarea v-model="notes" class="prose" rows="4" :placeholder="$t('profile.thingsApplicationFormsOften')" :aria-label="$t('profile.additionalNotesOptional')"></textarea>
      <p class="hint mt-2">{{ $t('profile.theProgramOnlyCopies') }}</p>
      <div class="actions form-acts"><button class="primary" :disabled="genWorking" @click="init">{{ genWorking ? $t('profile.generating') : $t('profile.generateProfileDraft') }}</button></div>
      <p v-if="genPhase === 'queued'" class="callout mt-3"><Icon name="clock" /><span>{{ $t('profile.queuedItStartsIn') }}</span></p>
      <p v-else-if="genPhase === 'running'" class="callout mt-3"><Icon name="clock" /><span>{{ $t('profile.theAiIsReading') }}</span></p>
      <p v-else-if="genPhase === 'failed'" class="callout warn mt-3"><Icon name="alert" /><span>{{ $t('profile.theLastAttemptDid', { p0: genTask.error }) }}</span></p>
      <p v-else-if="genPhase === 'applied'" class="callout ok mt-3"><Icon name="check" /><span>{{ $t('profile.whatWasGeneratedAt', { p0: fmtTime(genTask.finished_at) }) }}</span></p>
    </div>
    <div v-if="genPhase === 'proposal'" class="cols">
      <div class="card"><CardHead :title="$t('profile.currentProfile')" /><pre>{{ gen.current }}</pre></div>
      <div class="card is-new">
        <CardHead :title="$t('profile.generatedDraft')" :note="fmtTime(genTask.finished_at)">
          <button class="sm" @click="dropDraft">{{ $t('profile.doNotUse') }}</button><button class="sm primary" @click="adopt">{{ $t('profile.use') }}</button>
        </CardHead>
        <textarea v-model="draftText" rows="40" :aria-label="$t('profile.generatedDraft')"></textarea>
      </div>
    </div>
  </template>

  <template v-if="tab === 'markdown'">
    <div class="card">
      <CardHead :title="$t('profile.editTheFullText')">
        <label class="meta"><input v-model="mdPreview" type="checkbox" /> {{ $t('profile.previewAlongside') }}</label>
        <button class="sm" :disabled="!mdDirty" @click="md = base.md">{{ $t('profile.discardChanges') }}</button>
        <button class="sm primary" :disabled="!mdDirty" @click="saveMd"><Icon name="check" />{{ $t('profile.save') }}</button>
      </CardHead>
      <p class="card-sub">{{ $t('profile.writtenInMarkdownEditing') }}</p>
      <div :class="mdPreview ? 'cols' : ''">
        <textarea v-model="md" class="editor tall" :aria-label="$t('profile.editTheFullText')"></textarea>
        <div v-if="mdPreview" class="md editor-preview tall" v-html="renderMarkdown(md)"></div>
      </div>
    </div>
  </template>

  <template v-if="tab === 'stories'">
    <div class="card">
      <CardHead :title="$t('profile.myExperienceStories')">
        <template #help><p>{{ $t('profile.applicationFormsOftenHave') }}</p><p>{{ $t('profile.writeInChineseOr') }}</p></template>
        <button class="sm primary" :disabled="stories === base.stories" @click="saveStories"><Icon name="check" />{{ $t('profile.save') }}</button>
      </CardHead>
      <textarea v-model="stories" class="editor prose" :aria-label="$t('profile.myExperienceStories')"></textarea>
    </div>
  </template>

  <template v-if="tab === 'scoring'">
    <div class="card">
      <CardHead :title="$t('profile.postingScoreRules')" :help="$t('profile.writeInPlainLanguage')">
        <button class="sm primary" :disabled="scoring === base.scoring" @click="saveScoring"><Icon name="check" />{{ $t('profile.save') }}</button>
      </CardHead>
      <textarea v-model="scoring" class="editor" :aria-label="$t('profile.postingScoreRules')"></textarea>
    </div>
  </template>

  <template v-if="tab === 'history'">
    <div class="card">
      <CardHead :title="$t('profile.versionHistory')" :help="$t('profile.everySaveKeepsA')" :note="p.versions.length || ''" />
      <DataTable v-if="p.versions.length" class="bare" :columns="VERSION_COLS" :rows="p.versions" :label="$t('profile.versionHistory')">
        <template #cell-note="{ row, index }"><EntityCell :primary="row.note || $t('profile.save')" :secondary="$t('profile.sizeOf', { n: row.size })"><template v-if="index === 0" #after><span class="meta small">{{ $t('profile.mostRecent') }}</span></template></EntityCell></template>
        <template #cell-source="{ row }"><Status :tone="row.source === 'agent' ? 'info' : ''" :label="SOURCES[row.source] || row.source" /></template>
        <template #cell-when="{ row }"><DateTimeCell :primary="fmtTime(row.created_at)" /></template>
        <template #cell-act="{ row }"><button class="ghost sm" @click="restore(row)">{{ $t('profile.revertToThisVersion') }}</button></template>
      </DataTable>
      <EmptyState v-else icon="clock" :title="$t('profile.noPastVersionsYet')" :text="$t('profile.recordsWillStartAppearing')" />
    </div>
  </template>
  </template>
</template>

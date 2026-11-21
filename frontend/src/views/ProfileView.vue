<script setup>
import { t as T } from '../i18n/catalog'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, fmt } from '../api'
import { renderMarkdown } from '../md'
import EmptyState from '../components/EmptyState.vue'
import FileButton from '../components/FileButton.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
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

async function load() {
  p.value = await api.get('/profile')
  take('md', md, p.value.markdown)
  take('scoring', scoring, (await api.get('/profile?doc=scoring')).markdown)
  take('stories', stories, (await api.get('/profile?doc=stories')).markdown)
  docs.value = await api.get('/documents')
  await loadSt()
  regions.value = await api.get('/regions')
  await loadGen().catch(() => {})
}
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
const restore = async (v) => (await ask(T('profile.rollBackToThis'))) && run(() => api.post('/profile/restore/' + v.id), T('profile.reverted'))
const undo = (a) => run(() => api.post('/profile/remove-line', { fragment: a.note.slice(0, 40) }), T('profile.ruleUndone'))

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
const destroy = async () => (await ask(T('profile.permanentlyDeleteTheFile', { p0: cur.value.name }))) && docAct(() => api.del('/documents/' + cur.value.id + '?permanent=true'), T('profile.deleted'))
async function init() {
  try { await startGen(notes.value) } catch (e) { toast(e.message, 'bad') }
}
const adopt = () => run(async () => { await api.post(`/profile/init/${draftOf.value}/adopt`, { markdown: draftText.value }); await loadGen() }, T('profile.draftedProfileApplied'))
const dropDraft = async () => (await ask(T('profile.notAdoptThisDraft'))) && run(async () => { await api.post(`/profile/init/${draftOf.value}/discard`); await loadGen() }, T('profile.draftDiscarded'))

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
  <PageHead :title="$t('profile.profile')" :sub="$t('profile.everythingUsedToFill')">
    <span v-if="genWorking" class="badge info">{{ $t('profile.generatingFromYourR') }}</span>
    <button v-else-if="genPhase === 'proposal' && tab !== 'init'" class="sm" @click="go('init')">{{ $t('profile.aGeneratedDraftIs') }}</button>
    <span v-if="todoCount" class="badge warn">{{ $t('profile.fieldsStillEmpty', { p0: todoCount }) }}</span>
  </PageHead>
  <div class="seg" style="margin-bottom: 16px">
    <router-link to="/files" class="btn ghost sm" style="order: 9; margin-left: 6px">{{ $t('profile.rSumSAnd') }}</router-link>
    <button v-for="(l, k) in TAB_LABELS" :key="k" :class="{ on: tab === k }" @click="go(k)">{{ l }}<span v-if="marked(k)" class="unsaved-dot" :title="$t('profile.unsavedChanges')" :aria-label="$t('profile.unsavedChanges')"></span></button>
  </div>

  <template v-if="tab === 'sections'">
    <div v-if="p.agent_added.length" class="panel" style="border-color: var(--info)">
      <h3 style="margin-top: 0">{{ $t('profile.whatTheAppNoted') }}</h3>
      <div v-for="a in p.agent_added" :key="a.id" class="row small" style="margin-bottom: 4px">
        <span class="grow">{{ a.note }}</span><span class="muted">{{ fmt(a.created_at) }}</span><button @click="undo(a)">{{ $t('profile.revoke') }}</button>
      </div>
    </div>
    <details v-if="regions.packs.length" class="panel">
      <summary><b>{{ $t('profile.applicationFormsInThe') }}</b> <span class="muted small">{{ $t('profile.regionsNote', { regions: regions.packs.map((r) => r.name).join(', ') }) }}</span></summary>
      <div v-for="r in regions.packs" :key="r.code" style="margin-top: 10px">
        <b>{{ r.name }}</b>
        <ul style="margin: 4px 0 4px 18px"><li v-for="x in r.profile" :key="x" class="small">{{ x }}</li></ul>
        <div v-if="r.diversity" class="small muted">{{ $t('profile.diversityEqualOpportunitySurvey', { p0: r.diversity }) }}</div>
        <div v-if="r.consents" class="small muted">{{ $t('profile.consent', { p0: r.consents }) }}</div>
        <div v-if="r.never" class="small muted">{{ $t('profile.theAppWontFill', { p0: r.never }) }}</div>
      </div>
    </details>
    <div v-for="(s, i) in p.sections" :key="i" class="panel">
      <div class="row"><h3 class="grow" style="margin: 0">{{ s.title === 'preamble' ? $t('profile.notes') : s.title }}</h3><button v-if="editIdx !== i" @click="startEdit(i)">{{ $t('profile.edit') }}</button></div>
      <template v-if="editIdx === i">
        <textarea v-model="editBody" :rows="Math.min(30, Math.max(6, editBody.split('\n').length + 1))" style="margin-top: 8px"></textarea>
        <div class="row" style="margin-top: 8px"><button class="primary" @click="saveSection">{{ $t('profile.save') }}</button><button @click="editIdx = -1">{{ $t('profile.cancel') }}</button><span v-if="sectionDirty" class="badge warn">{{ $t('profile.unsavedChanges') }}</span></div>
      </template>
      <div v-else-if="s.body" class="md" style="margin-top: 8px" v-html="renderMarkdown(s.body)"></div>
      <p v-else class="muted">{{ $t('profile.empty') }}</p>
    </div>
  </template>

  <template v-if="tab === 'pay'">
    <div class="panel">
      <h3 style="margin-top: 0">{{ $t('profile.expectedSalary') }}</h3>
      <p class="muted small">{{ $t('profile.usedWhenAnApplication') }}</p>
      <div class="row" style="gap: 16px; flex-wrap: wrap; margin-bottom: 10px">
        <label><input v-model="st.compensation.policy" type="radio" value="state" /> {{ $t('profile.answerWithinTheRange') }}</label>
        <label><input v-model="st.compensation.policy" type="radio" value="ask" /> {{ $t('profile.dontFillInNumbers') }}</label>
      </div>
      <div v-if="st.compensation.policy !== 'ask'" class="row" style="gap: 8px; flex-wrap: wrap; align-items: end">
        <label class="small">{{ $t('profile.min') }}<input v-model="st.compensation.min" placeholder="70000" style="width: 110px; display: block" /></label>
        <label class="small">{{ $t('profile.max') }}<input v-model="st.compensation.max" placeholder="85000" style="width: 110px; display: block" /></label>
        <label class="small">{{ $t('profile.currency') }}<input v-model="st.compensation.currency" placeholder="CAD" style="width: 80px; display: block" /></label>
        <label class="small">{{ $t('profile.per') }}
          <AaSelect v-model="st.compensation.period" style="display: flex"><option value="year">{{ $t('profile.year') }}</option><option value="month">{{ $t('profile.month') }}</option><option value="hour">{{ $t('profile.hour') }}</option></AaSelect>
        </label>
        <label class="small"><input v-model="st.compensation.negotiable" type="checkbox" /> {{ $t('profile.negotiable') }}</label>
      </div>
      <div class="row" style="gap: 8px; flex-wrap: wrap; align-items: end; margin-top: 12px">
        <label class="small">{{ $t('profile.currentSalaryOptional') }}<input v-model="st.compensation.current" :placeholder="$t('profile.eGCadYear')" style="width: 220px; display: block" /></label>
        <label class="small"><input v-model="st.compensation.share_current" type="checkbox" /> {{ $t('profile.shareCurrentSalaryWhen') }}</label>
      </div>
      <h3>{{ $t('profile.noticePeriodStartDate') }}</h3>
      <div class="row" style="gap: 8px; flex-wrap: wrap">
        <label class="small">{{ $t('profile.noticePeriod') }}<input v-model="st.compensation.notice" :placeholder="$t('profile.eGWeeksOne')" style="width: 240px; display: block" /></label>
        <label class="small">{{ $t('profile.earliestStartDate') }}<input v-model="st.compensation.start" :placeholder="$t('profile.eGTwoWeeks')" style="width: 240px; display: block" /></label>
      </div>
      <label class="small" style="display: block; margin-top: 12px">{{ $t('profile.notesOptional') }}<input v-model="st.compensation.notes" :placeholder="$t('profile.eGCadPer')" style="display: block; width: 100%" /></label>
    </div>
    <div class="panel">
      <div class="row"><h3 class="grow" style="margin: 0">{{ $t('profile.references') }}</h3><button @click="addRef"><Icon name="plus" />{{ $t('profile.addOne') }}</button></div>
      <p class="muted small">{{ $t('profile.onlyFilledInWhen') }}</p>
      <p v-if="!st.referees.length" class="muted">{{ $t('profile.noReferencesAddedYet', { p0: st.suggested.referees ? $t('profile.applicationsForJobsLike') : '' }) }}</p>
      <div v-for="(r, i) in st.referees" :key="i" class="panel" style="background: var(--bg2)">
        <div class="row" style="gap: 8px; flex-wrap: wrap; align-items: end">
          <label class="small">{{ $t('profile.name') }}<input v-model="r.name" style="width: 170px; display: block" /></label>
          <label class="small">{{ $t('profile.job') }}<input v-model="r.title" style="width: 170px; display: block" /></label>
          <label class="small">{{ $t('profile.unit') }}<input v-model="r.org" style="width: 190px; display: block" /></label>
          <label class="small">{{ $t('profile.relationshipToYou') }}<input v-model="r.relation" :placeholder="$t('profile.eGDirectManager')" style="width: 170px; display: block" /></label>
          <label class="small">{{ $t('profile.email') }}<input v-model="r.email" style="width: 210px; display: block" /></label>
          <label class="small">{{ $t('profile.phone') }}<input v-model="r.phone" style="width: 150px; display: block" /></label>
          <label class="small">{{ $t('profile.whenTheyCanBe') }}
            <AaSelect v-model="r.contact" style="display: flex"><option v-for="[k, l] in CONTACT" :key="k" :value="k">{{ l }}</option></AaSelect>
          </label>
          <button class="ghost" @click="st.referees.splice(i, 1)">{{ $t('profile.delete') }}</button>
        </div>
      </div>
    </div>
    <div class="row"><button class="primary" :disabled="!stDirty" @click="saveSt">{{ $t('profile.save') }}</button><span v-if="stDirty" class="badge warn">{{ $t('profile.unsavedChanges') }}</span><span class="muted small">{{ $t('profile.savingWritesThisTo') }}</span></div>
  </template>

  <template v-if="tab === 'init'">
    <div class="card">
      <h3 style="margin-top: 0">{{ $t('profile.uploadYourFiles') }}</h3>
      <div class="row">
        <AaSelect v-model="upKind"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect>
        <FileButton @change="upload"><Icon name="inbox" />{{ $t('profile.chooseFile') }}</FileButton>
      </div>
      <ul class="small"><li v-for="d in active" :key="d.id">{{ KINDS[d.kind] || KINDS.other }}：<a :href="`api/documents/${d.id}/file`" target="_blank" rel="noopener">{{ d.name }}</a></li></ul>
      <p v-if="!active.length" class="muted small">{{ $t('profile.nothingHasBeenUploaded') }}</p>
      <p class="muted small">{{ $t('profile.onlyWhatYouUploaded') }} <router-link to="/files">{{ $t('profile.openTheLibrary') }}</router-link></p>
      <h3>{{ $t('profile.additionalNotesOptional') }}</h3>
      <textarea v-model="notes" style="font-family: inherit" :placeholder="$t('profile.thingsApplicationFormsOften')"></textarea>
      <div class="row" style="margin-top: 8px"><button class="primary" :disabled="genWorking" @click="init">{{ genWorking ? $t('profile.generating') : $t('profile.generateProfileDraft') }}</button></div>
      <p v-if="genPhase === 'queued'" class="callout" style="margin-top: 12px"><Icon name="clock" /><span>{{ $t('profile.queuedItStartsIn') }}</span></p>
      <p v-else-if="genPhase === 'running'" class="callout" style="margin-top: 12px"><Icon name="clock" /><span>{{ $t('profile.theAiIsReading') }}</span></p>
      <p v-else-if="genPhase === 'failed'" class="callout warn" style="margin-top: 12px"><Icon name="alert" /><span>{{ $t('profile.theLastAttemptDid', { p0: genTask.error }) }}</span></p>
      <p v-else-if="genPhase === 'applied'" class="callout ok" style="margin-top: 12px"><Icon name="check" /><span>{{ $t('profile.whatWasGeneratedAt', { p0: fmtTime(genTask.finished_at) }) }}</span></p>
      <p class="muted small">{{ $t('profile.theProgramOnlyCopies') }}</p>
    </div>
    <div v-if="genPhase === 'proposal'" class="cols">
      <div class="panel"><h3 style="margin-top: 0">{{ $t('profile.currentProfile') }}</h3><pre>{{ gen.current }}</pre></div>
      <div class="panel" style="border-color: var(--ok)">
        <div class="row"><h3 class="grow" style="margin: 0">{{ $t('profile.generatedDraft') }}</h3><span class="muted small">{{ fmtTime(genTask.finished_at) }}</span><button @click="dropDraft">{{ $t('profile.doNotUse') }}</button><button class="primary" @click="adopt">{{ $t('profile.use') }}</button></div>
        <textarea v-model="draftText" rows="40" style="margin-top: 8px"></textarea>
      </div>
    </div>
  </template>

  <template v-if="tab === 'markdown'">
    <div class="card">
      <div class="row">
        <div class="grow"><div class="card-title">{{ $t('profile.editTheFullText') }}</div><div class="muted small">{{ $t('profile.writtenInMarkdownEditing') }}</div></div>
        <label class="small muted"><input v-model="mdPreview" type="checkbox" /> {{ $t('profile.previewAlongside') }}</label>
        <span v-if="mdDirty" class="badge warn">{{ $t('profile.unsavedChanges') }}</span>
        <button :disabled="!mdDirty" @click="md = base.md">{{ $t('profile.discardChanges') }}</button>
        <button class="primary" :disabled="!mdDirty" @click="saveMd"><Icon name="check" />{{ $t('profile.save') }}</button>
      </div>
      <div :class="mdPreview ? 'cols' : ''" style="margin-top: 14px">
        <textarea v-model="md" style="height: 68vh; resize: vertical"></textarea>
        <div v-if="mdPreview" class="md" style="height: 68vh; overflow: auto; border: 1px solid var(--border); border-radius: var(--r-sm); padding: 12px 16px" v-html="renderMarkdown(md)"></div>
      </div>
    </div>
  </template>

  <template v-if="tab === 'stories'">
    <div class="card">
      <div class="row">
        <div class="grow"><div class="card-title">{{ $t('profile.myExperienceStories') }}</div><div class="muted small">{{ $t('profile.applicationFormsOftenHave') }}</div></div>
        <span v-if="stories !== base.stories" class="badge warn">{{ $t('profile.unsavedChanges') }}</span>
        <button class="primary" :disabled="stories === base.stories" @click="saveStories"><Icon name="check" />{{ $t('profile.save') }}</button>
      </div>
      <textarea v-model="stories" style="height: 60vh; margin-top: 14px; resize: vertical; font-family: inherit; font-size: 14px"></textarea>
      <p class="hint" style="margin-top: 8px">{{ $t('profile.writeInChineseOr') }}</p>
    </div>
  </template>

  <template v-if="tab === 'scoring'">
    <div class="card">
      <div class="row">
        <div class="grow"><div class="card-title">{{ $t('profile.postingScoreRules') }}</div><div class="muted small">{{ $t('profile.writeInPlainLanguage') }}</div></div>
        <span v-if="scoring !== base.scoring" class="badge warn">{{ $t('profile.unsavedChanges') }}</span>
        <button class="primary" :disabled="scoring === base.scoring" @click="saveScoring"><Icon name="check" />{{ $t('profile.save') }}</button>
      </div>
      <textarea v-model="scoring" style="height: 60vh; margin-top: 14px; resize: vertical"></textarea>
    </div>
  </template>

  <template v-if="tab === 'history'">
    <div class="card">
      <div class="card-title">{{ $t('profile.versionHistory') }}</div>
      <p class="muted">{{ $t('profile.everySaveKeepsA') }}</p>
      <div class="list">
        <div v-for="(v, i) in p.versions" :key="v.id" class="item">
          <span class="badge" :class="v.source === 'agent' ? 'info' : ''" style="min-width: 76px; justify-content: center">{{ { user: $t('profile.yourEdit'), agent: $t('profile.recordedByTheApp'), init: $t('profile.generateFromRSum') }[v.source] || v.source }}</span>
          <div><div class="main">{{ v.note || $t('profile.save') }}</div><div class="sub">{{ $t('profile.characters', { p0: fmtTime(v.created_at), p1: v.size }) }}</div></div>
          <div><span v-if="i === 0" class="small muted">{{ $t('profile.mostRecent') }}</span><button class="sm" style="margin-left: 8px" @click="restore(v)">{{ $t('profile.revertToThisVersion') }}</button></div>
        </div>
      </div>
      <EmptyState v-if="!p.versions.length" icon="clock" :title="$t('profile.noPastVersionsYet')" :text="$t('profile.recordsWillStartAppearing')" />
    </div>
  </template>
</template>

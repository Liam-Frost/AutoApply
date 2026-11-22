<script setup>
import { t as T } from '../i18n/catalog'
// First-run guide. Asks who is using the program, then proposes what to look for; nothing is saved until the last step.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import AiPanel from '../components/AiPanel.vue'
import EmployersPanel from '../components/EmployersPanel.vue'
import FileButton from '../components/FileButton.vue'
import Icon from '../components/Icon.vue'
import Status from '../components/Status.vue'
import { useProfileInit } from '../profileInit'
import { loadPersona, toast } from '../ui'
import { tag } from '../i18n/catalog'

const router = useRouter()
// several things in one line, joined the way the language joins them (A, B and C)
const listed = (xs) => new Intl.ListFormat(tag(), { style: 'short', type: 'conjunction' }).format(xs)
const STEPS = [T('welcome.start'), T('welcome.connectAi'), T('welcome.yourSituation'), T('welcome.rSum'), T('welcome.whatJobsToLook'), T('welcome.whereToLook'), T('welcome.done'), T('welcome.tryOnce')]
const step = ref(0)
const meta = ref(null)
const p = ref({ stage: '', field: '', targets: [], countries: ['CA'], sponsorship: false, portal: '', strategy: 'volume' })
const portals = ref([])
api.get('/portals').then((d) => (portals.value = d.portals)).catch(() => {})
const targetsText = ref('')
const s = ref({})   // llm settings for the AI panel
const sec = ref({ claude_oauth_token: '' })
const info = ref({ secrets: {} })
const aiOk = ref(null)
const busy = ref('')
const sug = ref(null)
const roles = ref('')
const none = ref('')
const kinds = ref('')
const scoring = ref('')
const tried = ref([])
const resume = ref({ uploaded: false, name: '' })
// The profile is written from the résumé by a task that starts when the résumé is uploaded: the guide goes on meanwhile
// and says where it stands (profileInit.js).
const { st: piSt, phase: piPhase, working: piWorking, load: piLoad, start: piStart } = useProfileInit()
const hasProfile = computed(() => (piSt.value ? !piSt.value.blank : !!(meta.value && meta.value.has_profile)))
const piTask = computed(() => (piSt.value && piSt.value.task) || {})
const bigtech = ref({})
const trial = ref({ url: '', state: '', message: '', draft: 0, job: 0 })
let trialTimer
const COUNTRIES = [['CA', T('welcome.canada')], ['US', T('welcome.unitedStates')], ['GB', T('welcome.unitedKingdom')], ['AU', T('welcome.australia')], ['DE', T('welcome.germany')], ['SG', T('welcome.singapore')], ['CN', T('welcome.china')], ['HK', T('welcome.hongKongChina')]]
const BIG = [['amazon', 'Amazon'], ['apple', 'Apple'], ['google', 'Google'], ['microsoft', 'Microsoft'], ['meta', 'Meta'], ['nvidia', 'NVIDIA'], ['amd', 'AMD'], ['intel', 'Intel']]
const list = (t) => t.split(/[,，\n]/).map((x) => x.trim().toLowerCase()).filter(Boolean)
const ready = computed(() => p.value.stage && p.value.field && (p.value.field !== 'other' || targetsText.value.trim()))

async function load() {
  meta.value = await api.get('/persona')
  if (meta.value.persona.stage) { p.value = { ...p.value, ...meta.value.persona }; targetsText.value = (p.value.targets || []).join(', ') }
  resume.value.uploaded = meta.value.resume_uploaded
  await piLoad().catch(() => {})
  const d = await api.get('/settings'); s.value = d.settings; info.value = d
}
async function testAi() {
  busy.value = 'ai'; aiOk.value = null
  try { await api.put('/settings', { settings: { 'llm.model': s.value['llm.model'], 'llm.small_model': s.value['llm.small_model'], 'llm.effort': s.value['llm.effort'] } }); await api.post('/settings/llm-test'); aiOk.value = true } catch (e) { aiOk.value = e.message }
  busy.value = ''
}
function toggleCountry(c) { const cur = new Set(p.value.countries); cur.has(c) ? cur.delete(c) : cur.add(c); p.value.countries = [...cur] }
async function upload(ev) {
  const f = ev.target.files[0]
  if (!f) return
  busy.value = 'up'
  try {
    const word = /\.docx$/i.test(f.name)
    const fd = new FormData(); fd.append('kind', word ? 'resume_docx' : 'resume_site'); fd.append('file', f)
    await api.upload('/documents', fd)
    if (word) { const fd2 = new FormData(); fd2.append('kind', 'source'); fd2.append('file', f); await api.upload('/documents', fd2) }
    resume.value.uploaded = true; resume.value.name = f.name
    await piLoad()      // with no profile yet, the upload has started the writing of one
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''; ev.target.value = ''
}
async function makeProfile() {
  busy.value = 'profile'
  try { await piStart() } catch (e) { toast(e.message, 'bad') }
  busy.value = ''
}
async function suggest() {
  busy.value = 'sug'
  p.value.targets = targetsText.value.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)
  try {
    sug.value = await api.post('/persona/suggest', { persona: p.value })
    const st = sug.value.settings
    kinds.value = st['intake.title_any'].join(', '); roles.value = st['intake.title_role_any'].join(', '); none.value = st['intake.title_none'].join(', ')
    scoring.value = sug.value.scoring_md; bigtech.value = { ...st['sources.bigtech'] }
    await tryRules()
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''
}
const chosen = () => ({ ...sug.value.settings, 'intake.title_any': list(kinds.value), 'intake.title_role_any': list(roles.value), 'intake.title_none': list(none.value), 'intake.countries': p.value.countries, 'sources.bigtech': bigtech.value })
async function tryRules() {
  if (!sug.value || !sug.value.examples.length) { tried.value = []; return }
  const c = chosen()
  tried.value = (await api.post('/sources/try-rules', { rules: { title_any: c['intake.title_any'], title_role_any: c['intake.title_role_any'], title_none: c['intake.title_none'], countries: c['intake.countries'], max_age_days: 0 }, examples: sug.value.examples })).results
}
async function go(n) {
  if (n === 4 && !sug.value) { step.value = 4; await suggest(); return }
  step.value = n
}
async function finish(scan) {
  busy.value = 'done'
  try {
    await api.post('/persona/apply', { persona: p.value, settings: chosen(), scoring_md: scoring.value, scan })
    await loadPersona()
    toast(scan ? T('welcome.settingsSavedScanningPostings') : T('welcome.settingsSaved'))
    step.value = 7
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''
}
async function tryOne() {
  const t = trial.value
  t.state = 'running'; t.message = T('welcome.openingThisPostingsApplication'); t.draft = 0
  try {
    t.job = (await api.post('/jobs', { url: t.url.trim() })).id
    const task = (await api.post(`/jobs/${t.job}/draft`)).task_id
    clearInterval(trialTimer)
    trialTimer = setInterval(async () => {
      const row = (await api.get('/tasks?limit=40')).find((x) => x.id === task)
      if (!row || ['queued', 'running'].includes(row.status)) return
      clearInterval(trialTimer)
      if (row.status === 'done' && row.result && row.result.draft_id) { t.state = 'done'; t.draft = row.result.draft_id; t.message = T('welcome.yourDraftIsReady') }
      else if (row.status === 'waiting_human') { t.state = 'needs'; t.message = T('welcome.thisSiteNeedsYou') }
      else { t.state = 'failed'; t.message = (row.explained && row.explained.message) || T('welcome.thatDidntWorkTry') }
    }, 5000)
  } catch (e) { t.state = 'failed'; t.message = e.message }
}
// where postings will come from, as the last step sums it up
const sources = computed(() => [...BIG.filter(([k]) => bigtech.value[k]).map(([, n]) => n), ...(p.value.portal ? [T('welcome.schoolCareerPortal')] : [])])
async function skip() { await api.post('/persona/skip'); await loadPersona(); router.push('/home') }
onMounted(load)
</script>

<template>
  <div v-if="meta" class="wiz">
    <ol class="wiz-steps">
      <li v-for="(l, i) in STEPS" :key="l" :class="{ on: i === step, done: i < step }"><span>{{ i < step ? '✓' : i + 1 }}</span>{{ l }}</li>
    </ol>

    <div v-if="step === 0" class="card wiz-card">
      <h2>{{ $t('welcome.welcomeToAutoapply') }}</h2>
      <p>{{ $t('welcome.itFindsPostingsScores') }}</p>
      <ul class="wiz-list">
        <li><Icon name="check" /><span><b>{{ $t('welcome.wontMakeAnythingUp') }}</b>{{ $t('welcome.anythingAboutYouIn') }}</span></li>
        <li><Icon name="check" /><span><b>{{ $t('welcome.showMeFirstThen') }}</b>{{ $t('welcome.eachApplicationStartsAs') }}</span></li>
        <li><Icon name="check" /><span><b>{{ $t('welcome.yourDataStaysOn') }}</b>{{ $t('welcome.yourRSumPasswords') }}</span></li>
        <li><Icon name="check" /><span><b>{{ $t('welcome.itDoesntGetAround') }}</b>{{ $t('welcome.ifASiteShows') }}</span></li>
      </ul>
      <div class="actions wiz-acts"><button class="ghost" @click="skip">{{ $t('welcome.skipForNowAnd') }}</button><button class="primary" @click="go(1)">{{ $t('welcome.getStarted') }}</button></div>
    </div>

    <div v-else-if="step === 1">
      <div class="card"><div class="card-title">{{ $t('welcome.connectAi') }}</div><p class="muted wiz-lead">{{ $t('welcome.aiIsNeededTo') }}</p></div>
      <AiPanel :s="s" :sec="sec" :secrets="info.secrets" @changed="load" />
      <div class="card">
        <div class="row"><button :disabled="busy === 'ai'" @click="testAi"><Icon name="refresh" />{{ busy === 'ai' ? $t('welcome.testing') : $t('welcome.testIt') }}</button>
          <Status v-if="aiOk === true" tone="ok" :label="$t('welcome.usable')" /><span v-else-if="aiOk" class="small bad-text">{{ aiOk }}</span></div>
      </div>
      <div class="row"><button @click="go(0)">{{ $t('welcome.back') }}</button><button class="primary" @click="go(2)">{{ aiOk === true ? $t('welcome.next') : $t('welcome.nextYouCanConnect') }}</button></div>
    </div>

    <div v-else-if="step === 2" class="card wiz-card">
      <h2>{{ $t('welcome.yourSituation') }}</h2>
      <p class="muted">{{ $t('welcome.theseDecideWhatPostings') }}</p>
      <div class="field"><label>{{ $t('welcome.whereAreYouIn') }}</label>
        <div class="wiz-opts"><button v-for="x in meta.stages" :key="x.key" :class="{ on: p.stage === x.key }" @click="p.stage = x.key">{{ x.name }}</button></div></div>
      <div class="field"><label>{{ $t('welcome.whichField') }}</label>
        <div class="wiz-opts"><button v-for="x in meta.fields" :key="x.key" :class="{ on: p.field === x.key }" @click="p.field = x.key">{{ x.name }}</button></div></div>
      <div class="field"><label>{{ $t('welcome.jobsYouWant', { p0: p.field === 'other' ? $t('welcome.required') : $t('welcome.optionalMoreAccurateIf') }) }}</label>
        <input v-model="targetsText" :placeholder="$t('welcome.separateWithCommasE')" /></div>
      <div class="field"><label>{{ $t('welcome.countriesOrRegionsYou') }}</label>
        <div class="row"><label v-for="[c, n] in COUNTRIES" :key="c" class="nowrap"><input type="checkbox" :checked="p.countries.includes(c)" @change="toggleCountry(c)" /> {{ n }}</label></div>
        <div class="hint">{{ $t('welcome.leaveAllUnselectedFor') }}</div></div>
      <div class="field"><label><input v-model="p.sponsorship" type="checkbox" /> {{ $t('welcome.iNeedEmployerVisa') }}</label></div>
      <div class="field"><label>{{ $t('welcome.howDoYouPrefer') }}</label>
        <div class="choice wiz-choice">
          <label :class="{ on: p.strategy === 'volume' }"><input v-model="p.strategy" type="radio" value="volume" /><div><b>{{ $t('welcome.applyBroadly') }}</b><span>{{ $t('welcome.draftsArePreparedAutomatically') }}</span></div></label>
          <label :class="{ on: p.strategy === 'targeted' }"><input v-model="p.strategy" type="radio" value="targeted" /><div><b>{{ $t('welcome.targeted') }}</b><span>{{ $t('welcome.theAppOnlyFinds') }}</span></div></label>
        </div></div>
      <div class="row"><button @click="go(1)">{{ $t('welcome.back') }}</button><button class="primary" :disabled="!ready" @click="go(3)">{{ $t('welcome.next') }}</button></div>
    </div>

    <div v-else-if="step === 3" class="card wiz-card">
      <h2>{{ $t('welcome.uploadRSum') }}</h2>
      <p class="muted">{{ $t('welcome.theProgramReadsYour') }}</p>
      <div class="row">
        <FileButton :class="{ primary: !resume.uploaded }" accept=".pdf,.docx,.doc" :disabled="busy === 'up'" @change="upload"><Icon name="inbox" />{{ busy === 'up' ? $t('welcome.uploading') : resume.uploaded ? $t('welcome.uploadAnother') : $t('welcome.chooseRSumFile') }}</FileButton>
        <Status v-if="resume.uploaded" tone="ok" :label="resume.name ? $t('welcome.uploadedFile', { name: resume.name }) : $t('welcome.uploadedOk')" />
      </div>
      <div v-if="resume.uploaded || hasProfile" class="mt-4">
        <p v-if="piWorking" class="callout"><Icon name="clock" /><span>{{ $t('welcome.theAiIsReading') }}</span></p>
        <template v-else>
          <p v-if="piPhase === 'failed'" class="callout warn"><Icon name="alert" /><span>{{ $t('welcome.yourProfileWasNot', { p0: piTask.error }) }}</span></p>
          <p v-else-if="piPhase === 'proposal'" class="callout"><Icon name="check" /><span>{{ $t('welcome.aNewVersionWas') }}</span></p>
          <p v-else-if="hasProfile && piSt && piSt.todos" class="callout"><Icon name="check" /><span>{{ $t('welcome.yourProfileHasBeen', { p0: piSt.todos }) }}</span></p>
          <p v-else-if="hasProfile" class="callout"><Icon name="check" /><span>{{ $t('welcome.yourProfileHasBeen2') }}</span></p>
          <button v-if="resume.uploaded" :class="{ primary: !hasProfile }" :disabled="busy === 'profile'" @click="makeProfile"><Icon name="edit" />{{ piPhase === 'failed' ? $t('welcome.tryAgain') : hasProfile ? $t('welcome.writeANewVersion') : $t('welcome.generateProfile') }}</button>
        </template>
      </div>
      <p class="hint mt-3">{{ $t('welcome.thisStepNeedsAn') }}</p>
      <div class="row mt-2"><button @click="go(2)">{{ $t('welcome.back') }}</button><button class="primary" @click="go(4)">{{ resume.uploaded || hasProfile ? $t('welcome.next') : $t('welcome.skipNext') }}</button></div>
    </div>

    <div v-else-if="step === 4" class="card wiz-card">
      <h2>{{ $t('welcome.whatJobsToLook') }}</h2>
      <p v-if="busy === 'sug'" class="muted">{{ $t('welcome.preparingSuggestionsForYou') }}</p>
      <template v-else-if="sug">
        <p class="muted">{{ sug.by === 'ai' ? $t('welcome.suggestionsByAi') : $t('welcome.suggestionsGeneric') }}</p>
        <p v-if="sug.note" class="callout warn"><Icon name="alert" /><span>{{ sug.note }}</span></p>
        <div class="field"><label>{{ $t('welcome.titleMustIncludeOne') }}</label><input v-model="kinds" @change="tryRules" /><div class="hint">{{ $t('welcome.leaveBlankForNo') }}</div></div>
        <div class="field"><label>{{ $t('welcome.andHasOneOf') }}</label><textarea v-model="roles" class="prose" rows="3" @change="tryRules"></textarea></div>
        <div class="field"><label>{{ $t('welcome.titlesCantContainThese') }}</label><textarea v-model="none" class="prose" rows="2" @change="tryRules"></textarea></div>
        <div v-if="tried.length" class="field"><label>{{ $t('welcome.howThesePostingsWould') }}</label>
          <div class="list"><div v-for="t in tried" :key="t.title" class="item"><Status :tone="t.kept ? 'ok' : ''" :label="t.kept ? $t('welcome.keep') : $t('welcome.discard')" /><div><div class="main">{{ t.title }}</div><div class="sub">{{ t.location }}{{ t.why ? ' · ' + t.why : '' }}</div></div></div></div></div>
        <details class="tech"><summary>{{ $t('welcome.scoringRulesWhatThe') }}</summary><textarea v-model="scoring" rows="14"></textarea></details>
        <div class="row mt-3"><button @click="go(3)">{{ $t('welcome.back') }}</button><button :disabled="busy === 'sug'" @click="suggest"><Icon name="refresh" />{{ $t('welcome.regenerateSuggestions') }}</button><button class="primary" @click="go(5)">{{ $t('welcome.next') }}</button></div>
      </template>
    </div>

    <div v-else-if="step === 5" class="card wiz-card">
      <h2>{{ $t('welcome.whereToLook') }}</h2>
      <p class="muted">{{ $t('welcome.pickAFewTo') }}</p>
      <div class="field"><label>{{ $t('welcome.bigTechCompanyWebsites') }}</label>
        <div class="row"><label v-for="[k, n] in BIG" :key="k" class="nowrap"><input type="checkbox" :checked="!!bigtech[k]" @change="bigtech = { ...bigtech, [k]: !bigtech[k] }" /> {{ n }}</label></div>
        <div class="hint">{{ $t('welcome.theseCompaniesHavePostings', { p0: ['software', 'engineering', 'design'].includes(p.field) ? '' : $t('welcome.yourFieldIsntChecked') }) }}</div></div>
      <div class="field"><label>{{ $t('welcome.schoolCareerPortal') }}</label>
        <AaSelect v-model="p.portal">
          <option value="">{{ $t('welcome.noneOrNotFor') }}</option>
          <option v-for="x in portals.filter((x) => x.status === 'supported')" :key="x.key" :value="x.key">{{ x.school }} · {{ x.name }}</option>
          <option v-for="x in portals.filter((x) => x.status !== 'supported')" :key="x.key" :value="'other:' + x.key" disabled>{{ $t('welcome.portalOption', { name: (x.school ? x.school + ' · ' : '') + x.name, note: x.status === 'same_system' ? $t('welcome.sameSystemNotSupported') : $t('welcome.noImporterYet') }) }}</option>
        </AaSelect>
        <div class="hint">{{ $t('welcome.aSchoolPortalUses') }}</div></div>
      <div class="field"><label>{{ $t('welcome.companiesYouWantTo') }}</label>
        <div class="hint">{{ $t('welcome.pasteTheUrlOf') }}</div></div>
      <EmployersPanel :s="s" />
      <div class="row"><button @click="go(4)">{{ $t('welcome.back') }}</button><button class="primary" @click="go(6)">{{ $t('welcome.next') }}</button></div>
    </div>

    <div v-else-if="step === 7" class="card wiz-card">
      <h2>{{ $t('welcome.tryOnce') }}</h2>
      <i18n-t keypath="welcome.tryIntro" tag="p" class="muted" scope="global"><template #strong><b>{{ $t('welcome.nothingIsSubmittedAt') }}</b></template></i18n-t>
      <div class="row mt-3">
        <input v-model="trial.url" class="grow" :placeholder="$t('welcome.postingUrlEG')" :disabled="trial.state === 'running'" />
        <button class="primary" :disabled="!trial.url.trim() || trial.state === 'running' || !hasProfile" @click="tryOne"><Icon name="draft" />{{ trial.state === 'running' ? $t('welcome.preparing') : $t('welcome.prepareADraft') }}</button>
      </div>
      <p v-if="trial.message" class="callout mt-3" :class="trial.state === 'failed' ? 'warn' : ''"><Icon :name="trial.state === 'done' ? 'check' : trial.state === 'failed' ? 'alert' : 'clock'" /><span>{{ trial.message }}</span></p>
      <p v-if="piWorking" class="callout mt-3"><Icon name="clock" /><span>{{ $t('welcome.yourProfileIsStill') }}</span></p>
      <p v-else-if="!hasProfile" class="callout warn mt-3"><Icon name="alert" /><span>{{ $t('welcome.yourProfileIsStill2') }}</span></p>
      <div class="row mt-4">
        <router-link v-if="trial.draft" :to="'/drafts/' + trial.draft" class="btn primary"><Icon name="draft" />{{ $t('welcome.viewThisDraft') }}</router-link>
        <router-link v-if="trial.state === 'needs'" to="/todos" class="btn primary">{{ $t('welcome.goToNeedsYou') }}</router-link>
        <router-link v-if="!hasProfile && !piWorking" to="/profile?tab=init" class="btn primary">{{ $t('welcome.goToProfile') }}</router-link>
        <router-link to="/home" class="btn">{{ trial.state ? $t('welcome.goToOverview') : $t('welcome.skipForNowGo') }}</router-link>
      </div>
    </div>

    <div v-else class="card wiz-card">
      <h2>{{ $t('welcome.allSet') }}</h2>
      <p class="muted">{{ $t('welcome.takeALookThen') }}</p>
      <div class="facts wiz-facts">
        <div><div class="k">{{ $t('welcome.stage') }}</div><div class="v">{{ (meta.stages.find((x) => x.key === p.stage) || {}).name }}</div></div>
        <div><div class="k">{{ $t('welcome.field') }}</div><div class="v">{{ (meta.fields.find((x) => x.key === p.field) || {}).name }}</div></div>
        <div><div class="k">{{ $t('welcome.region') }}</div><div class="v">{{ p.countries.length ? listed(p.countries) : $t('welcome.any') }}</div></div>
        <div><div class="k">{{ $t('welcome.approach') }}</div><div class="v">{{ p.strategy === 'targeted' ? $t('welcome.targetedIPickAnd') : $t('welcome.moreApplicationsDraftsPrepared') }}</div></div>
        <div><div class="k">{{ $t('welcome.jobSource') }}</div><div class="v">{{ sources.length ? listed(sources) : $t('welcome.noneChosenAddLater') }}</div></div>
        <div><div class="k">{{ $t('welcome.profile') }}</div><div class="v">{{ hasProfile ? $t('welcome.generated') : piWorking ? $t('welcome.beingGeneratedItFinishes') : $t('welcome.notYetFillIt') }}</div></div>
      </div>
      <p v-if="piWorking" class="callout"><Icon name="clock" /><span>{{ $t('welcome.yourProfileIsStill3') }}</span></p>
      <p v-else-if="!hasProfile" class="callout warn"><Icon name="alert" /><span>{{ $t('welcome.yourProfileIsStill4') }}</span></p>
      <p class="hint">{{ $t('welcome.youCanAlsoSet') }}</p>
      <div class="row mt-3">
        <button @click="go(5)">{{ $t('welcome.back') }}</button>
        <button class="primary" :disabled="busy === 'done'" @click="finish(BIG.some(([k]) => bigtech[k]))"><Icon name="check" />{{ BIG.some(([k]) => bigtech[k]) ? $t('welcome.doneAndScanFor') : $t('welcome.done') }}</button>
      </div>
    </div>
  </div>
</template>

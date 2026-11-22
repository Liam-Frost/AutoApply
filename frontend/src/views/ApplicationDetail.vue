<script setup>
import { t as T } from '../i18n/catalog'
// One application, its only home (plan §8.4): where it stands and whose move it is, with what can be done now - and
// everything that can be done under "More"; then the record (every answer), the agent, the materials, the mail, the
// whole story and the posting. What was the draft page is the record here (RecordPanel).
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import AgentJournal from '../components/AgentJournal.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import RecordPanel from '../components/RecordPanel.vue'
import TechDetails from '../components/TechDetails.vue'
import { deadlineLabel } from '../dates'
import { renderMarkdown } from '../md'
import { ask, fmtTime, run, toast } from '../ui'
import { stampDay } from '../i18n/format'

const props = defineProps({ id: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const a = ref(null)
const d = ref(null)              // the record (the draft that counts), when there is one
const failed = ref('')
const panel = ref('')            // the form open under the status: outcome | note | fix
const more = ref(false)
const others = ref(null)         // mails the program could not put on any application
const showJd = ref(false)

async function load() {
  try {
    const got = await api.get('/applications/' + props.id)
    d.value = got.draft_id ? await api.get('/drafts/' + got.draft_id).catch(() => null) : null
    a.value = got
    failed.value = ''
  } catch (e) { failed.value = e.message }
}
// one action at a time: they all change where the application stands
const act = (fn, ok, opts = {}) => run(fn, ok, load, { name: 'app', ...opts })

// --- the tabs: the record, the agent, materials, mail, the story, the posting (the open one is in the address: #record)
const TABS = ['record', 'agent', 'materials', 'mail', 'timeline', 'job']
const tab = ref('')
const firstTab = () => {
  const h = (route.hash || '').slice(1)
  if (TABS.includes(h)) return h
  if (d.value && ['pending', 'approved'].includes(d.value.review_status)) return 'record'
  if (a.value && (a.value.running_task || a.value.run_expected)) return 'agent'
  return a.value && a.value.mails.length ? 'mail' : 'timeline'
}
function openTab(k) { tab.value = k; router.replace({ hash: '#' + k }) }
watch(() => route.hash, () => { const h = (route.hash || '').slice(1); if (TABS.includes(h)) tab.value = h })
const tabCount = (k) => (!a.value ? 0 : k === 'mail' ? a.value.mails.length : k === 'materials' ? a.value.materials.length : k === 'timeline' ? a.value.timeline.length : 0)

// --- what can be done, and the few that matter now --------------------------------------------------------------------
const pending = computed(() => !!d.value && d.value.review_status === 'pending')
const notOut = computed(() => !!a.value && !a.value.sent && !a.value.unknown && a.value.status !== 'withdrawn')
const WHO = { me: 'application.who.me', agent: 'application.who.agent', them: 'application.who.them' }

async function withdraw() {
  if (!(await ask(T('application.withdrawAsk'), { ok: T('application.do.withdraw') }))) return
  await act(() => api.post(`/applications/${props.id}/withdraw`), T('application.withdrawn'))
}
async function notSubmitted() {
  if (!(await ask(T('application.notSubmittedAsk'), { ok: T('application.notSubmittedOk') }))) return
  await act(() => api.post(`/applications/${props.id}/not-submitted`), T('application.rerunStarted'))
}
async function discard() {
  if (!(await ask(T('application.discardAsk'), { ok: T('application.do.discard') }))) return
  await act(() => api.post(`/drafts/${d.value.id}/reject`, { withdraw: false }), T('application.discarded'))
}
function answer() { openTab('record') }

const ACTIONS = {
  approve: { label: () => (d.value && d.value.policy === 'hand_over' ? T('application.do.approveHandOver') : T('application.do.approve')), when: () => pending.value,
    disabled: () => (d.value.unresolved.length ? T('application.answerFirst') : ''), run: () => act(() => api.post(`/drafts/${d.value.id}/approve`), T('application.approved')) },
  rework: { label: () => T('application.do.rework'), when: () => pending.value, run: () => act(() => api.post(`/drafts/${d.value.id}/reanswer`), T('application.reworkStarted')) },
  answer: { label: () => T('application.do.answer'), when: () => a.value.act === 'answer', run: answer },
  execute: { label: () => T('application.do.execute'), when: () => !!d.value && d.value.review_status === 'approved' && ['failed', 'needs_human', 'approved', 'drifted'].includes(a.value.status) && !a.value.running_task,
    run: () => act(() => api.post(`/drafts/${d.value.id}/execute`), T('application.rerunStarted')) },
  rerun: { label: () => T('application.do.rerun'), when: () => notOut.value && !a.value.running_task && !pending.value && !(d.value && d.value.review_status === 'approved'),
    run: () => act(() => api.post(`/jobs/${a.value.job_id}/draft`, {}), T('application.rerunStarted')) },
  budget: { label: () => T('application.do.budget'), when: () => a.value.act === 'budget', run: () => act(() => api.post(`/applications/${props.id}/budget`), T('application.budgetGiven')) },
  check_mail: { label: () => T('application.do.checkMail'), when: () => a.value.unknown || a.value.status === 'submitted', run: () => act(() => api.post(`/applications/${props.id}/check-mail`), T('application.checkingMail')) },
  not_submitted: { label: () => T('application.do.notSubmitted'), when: () => a.value.unknown, run: notSubmitted },
  mark_submitted: { label: () => T('application.do.markSubmitted'), when: () => notOut.value || a.value.unknown, run: () => act(() => api.post(`/applications/${props.id}/mark-submitted`), T('application.markedSubmitted')) },
  handle: { label: () => T('application.do.handle'), when: () => a.value.act === 'handle' || a.value.cards.length > 0, run: () => router.push('/todos') },
  stop: { label: () => T('application.do.stop'), when: () => !!a.value.running_task, run: () => act(() => api.post(`/tasks/${a.value.running_task}/stop`), T('journal.stopped')) },
  outcome: { label: () => T('application.do.outcome'), when: () => a.value.sent || a.value.unknown, run: () => openPanel('outcome') },
  withdraw: { label: () => T('application.do.withdraw'), when: () => notOut.value, run: withdraw },
  note: { label: () => (a.value.note ? T('application.do.editNote') : T('application.do.note')), when: () => true, run: () => openPanel('note') },
  fix: { label: () => T('application.do.fix'), when: () => true, run: () => openPanel('fix') },
  discard: { label: () => T('application.do.discard'), when: () => pending.value, run: discard },
  archive: { label: () => (a.value.archived ? T('application.do.unarchive') : T('application.do.archive')), when: () => true,
    run: () => act(() => api.post('/applications/bulk', { action: a.value.archived ? 'unarchive' : 'archive', ids: [a.value.id] }), a.value.archived ? T('application.unarchived') : T('application.archivedOk')) },
  open_job: { label: () => T('application.do.openJob'), when: () => true, run: () => router.push({ path: '/jobs', query: { open: a.value.job_id } }) },
}
// what matters now, by where it stands: at most three, the first one the main one
const mainKeys = computed(() => {
  const x = a.value
  if (!x) return []
  let keys
  if (pending.value) keys = ['approve', 'rework', 'answer']
  else if (x.act === 'budget') keys = ['budget', 'withdraw']
  else if (x.act === 'check_mail') keys = ['check_mail', 'mark_submitted', 'not_submitted']
  else if (x.act === 'rerun') keys = ['execute', 'rerun', 'mark_submitted']
  else if (x.act === 'answer') keys = ['answer', 'rerun']
  else if (x.act === 'handle') keys = ['handle', 'mark_submitted']
  else if (x.group === 'agent') keys = ['stop']
  else if (x.group === 'sent') keys = ['check_mail', 'outcome']
  else if (x.group === 'progress') keys = ['outcome']
  else if (x.archived) keys = ['archive']
  else keys = []
  return keys.filter((k) => ACTIONS[k].when()).slice(0, 3)
})
const moreKeys = computed(() => (a.value ? Object.keys(ACTIONS).filter((k) => ACTIONS[k].when()) : []))
function doAction(k) { more.value = false; ACTIONS[k].run() }

// --- the forms under the status: what came back, a note, a correction of the record -----------------------------------
const today = () => new Date().toISOString().slice(0, 10)
const outcome = ref({ status: 'interview', date: '', time: '', note: '' })
const note = ref('')
const fix = ref({ status: '', date: '', note: '' })
const BY_HAND = ['submitted', 'confirmed', 'assessment', 'interview', 'offer', 'rejected', 'withdrawn']
const OUTCOMES = ['confirmed', 'assessment', 'interview', 'offer', 'rejected']
function openPanel(k) {
  panel.value = k
  if (k === 'outcome') outcome.value = { status: 'interview', date: today(), time: '', note: '' }
  if (k === 'note') note.value = a.value.note || ''
  if (k === 'fix') fix.value = { status: a.value.sent || a.value.status === 'withdrawn' ? a.value.status : '', date: a.value.submitted_at ? a.value.submitted_at.slice(0, 10) : '', note: '' }
}
async function saveOutcome() {
  if (await act(() => api.post(`/applications/${props.id}/outcome`, outcome.value), T('application.outcomeSaved'))) panel.value = ''
}
async function saveNote() {
  if (await act(() => api.put(`/applications/${props.id}/note`, { note: note.value }), T('application.noteSaved'))) panel.value = ''
}
async function saveFix() {
  const body = { note: fix.value.note }
  if (fix.value.status && fix.value.status !== a.value.status) body.status = fix.value.status
  if (fix.value.date && fix.value.date !== (a.value.submitted_at || '').slice(0, 10)) body.submitted_at = fix.value.date + 'T12:00:00'
  if (!body.status && !body.submitted_at && !body.note) { panel.value = ''; return }
  if (await act(() => api.post(`/applications/${props.id}/correct`, body), T('application.recorded'))) panel.value = ''
}

// --- mail -------------------------------------------------------------------------------------------------------------
async function unlink(m) {
  if (!(await ask(T('application.unlinkAsk', { subject: m.subject }), { ok: T('application.unlinkOk') }))) return
  await act(() => api.post(`/applications/${props.id}/mails/unlink`, { message_id: m.message_id }), T('application.unlinked'))
}
async function showOthers() {
  try { others.value = await api.get(`/applications/${props.id}/mail-candidates`) } catch (e) { toast(e.message, 'bad') }
}
async function link(m) {
  await act(() => api.post(`/applications/${props.id}/mails/link`, { message_id: m.message_id }), T('application.linked'))
  others.value = null
}

const due = computed(() => (a.value && a.value.deadline ? deadlineLabel(a.value.deadline) : null))
const facts = computed(() => {
  const j = a.value && a.value.job
  if (!j) return []
  return [['application.job.term', j.term], ['application.job.months', j.months], ['application.job.salary', j.salary], ['application.job.location', j.location],
    ['application.job.deadline', j.deadline], ['application.job.direction', j.direction], ['application.job.where', j.ats_label], ['application.job.posted', j.posted]].filter((x) => x[1])
})

watch(() => props.id, async () => { a.value = null; await load(); tab.value = firstTab() })
onMounted(async () => { await load(); tab.value = firstTab() })
</script>

<template>
  <div v-if="!a && !failed" class="empty"><div class="t">{{ $t('application.loading') }}</div></div>
  <div v-else-if="failed" class="empty"><div class="t">{{ $t('application.couldNotLoad') }}</div><div class="muted">{{ failed }}</div>
    <div class="row" style="justify-content: center; margin-top: 8px"><button @click="load">{{ $t('application.tryAgain') }}</button><button class="ghost" @click="router.push('/applications')">{{ $t('application.backToList') }}</button></div>
  </div>
  <template v-else>
    <PageHead :title="a.company + ' · ' + a.title">
      <template #sub>
        <router-link to="/applications">{{ $t('application.backToList') }}</router-link>
        <template v-if="a.ats_label"> · {{ a.ats_label }}</template>
        <template v-if="a.location"> · {{ a.location }}</template>
        <template v-if="due && due.text"> · <span :class="{ 'warn-text': due.tone === 'soon' }">{{ due.text }}</span></template>
        <template v-if="a.apply_url"> · <a :href="a.apply_url" target="_blank" rel="noopener">{{ $t('application.posting') }} ↗</a></template>
      </template>
    </PageHead>

    <!-- where it stands, whose move it is, and what can be done now -->
    <div class="card status-card" :class="'edge-' + (a.tone || 'none')">
      <div class="row" style="flex-wrap: wrap; gap: 8px; align-items: baseline">
        <span class="tag" :class="a.tone" style="font-size: 14px">{{ a.stage_label }}</span>
        <span v-if="a.who">{{ $t(WHO[a.who]) }}</span>
        <span v-if="a.submitted_at" class="muted small">{{ $t('application.sentOn', { day: stampDay(a.submitted_at) }) }}</span>
        <span v-if="a.auto_approved" class="muted small">· {{ $t('application.autoApproved') }}</span>
        <span v-if="a.archived" class="tag">{{ $t('application.archived') }}</span>
      </div>
      <p v-if="a.next" style="margin: 10px 0 0">{{ a.next }}</p>
      <div v-if="a.explained.message" class="muted" style="margin-top: 6px">{{ a.explained.message }}</div>
      <TechDetails :text="a.explained.detail" />
      <div v-if="a.cards.length" style="margin-top: 10px">
        <span class="small muted">{{ $t('application.waitingForYou') }}</span>
        <router-link v-for="c in a.cards" :key="c.id" to="/todos" class="tag warn" style="margin: 4px 6px 0 0">{{ c.title }}</router-link>
      </div>
      <div class="row" style="margin-top: 12px; flex-wrap: wrap; gap: 8px">
        <button v-for="(k, i) in mainKeys" :key="k" :class="{ primary: i === 0 }" :disabled="!!(ACTIONS[k].disabled && ACTIONS[k].disabled())" :title="ACTIONS[k].disabled ? ACTIONS[k].disabled() : ''" @click="doAction(k)">{{ ACTIONS[k].label() }}</button>
        <div class="more-wrap">
          <button class="ghost" :aria-expanded="more" @click="more = !more">{{ $t('application.more') }} ▾</button>
          <div v-if="more" class="menu-backdrop" @click="more = false"></div>
          <div v-if="more" class="more-menu" role="menu" @keydown.esc="more = false">
            <button v-for="k in moreKeys" :key="k" role="menuitem" :disabled="!!(ACTIONS[k].disabled && ACTIONS[k].disabled())" @click="doAction(k)">{{ ACTIONS[k].label() }}</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="panel === 'outcome'" class="card">
      <div class="card-title">{{ $t('application.outcomeTitle') }}</div>
      <p class="muted" style="margin-top: 0">{{ $t('application.outcomeHow') }}</p>
      <div class="kv">
        <label for="o-status">{{ $t('application.outcomeWhat') }}</label>
        <AaSelect id="o-status" v-model="outcome.status"><option v-for="k in OUTCOMES" :key="k" :value="k">{{ $t('application.status.' + k) }}</option></AaSelect>
        <label for="o-date">{{ $t('application.outcomeWhen') }}</label>
        <div class="row" style="gap: 6px"><input id="o-date" v-model="outcome.date" type="date" style="width: 170px" /><input v-model="outcome.time" type="time" :aria-label="$t('application.outcomeTime')" style="width: 120px" />
          <span v-if="['assessment', 'interview'].includes(outcome.status)" class="hint">{{ $t('application.outcomeCalendar') }}</span></div>
        <label for="o-note">{{ $t('application.outcomeNote') }}</label>
        <input id="o-note" v-model="outcome.note" maxlength="240" :placeholder="$t('application.outcomeNotePlaceholder')" />
      </div>
      <div class="row" style="margin-top: 12px"><button class="primary" @click="saveOutcome">{{ $t('application.save') }}</button><button class="ghost" @click="panel = ''">{{ $t('application.cancel') }}</button></div>
    </div>

    <div v-if="panel === 'note'" class="card">
      <div class="card-title">{{ $t('application.noteTitle') }}</div>
      <textarea v-model="note" rows="4" maxlength="4000" :placeholder="$t('application.notePlaceholder')" style="font-family: inherit"></textarea>
      <div class="row" style="margin-top: 8px"><button class="primary" @click="saveNote">{{ $t('application.save') }}</button><button class="ghost" @click="panel = ''">{{ $t('application.cancel') }}</button></div>
    </div>
    <div v-else-if="a.note" class="card note-card">
      <div class="row"><span class="card-title grow">{{ $t('application.noteTitle') }}</span><button class="ghost sm" @click="openPanel('note')"><Icon name="edit" />{{ $t('application.do.editNote') }}</button></div>
      <div style="white-space: pre-wrap">{{ a.note }}</div>
    </div>

    <div v-if="panel === 'fix'" class="card">
      <div class="card-title">{{ $t('application.do.fix') }}</div>
      <p class="muted" style="margin-top: 0">{{ $t('application.fixHow') }}</p>
      <div class="kv">
        <label for="fix-status">{{ $t('application.fixStatus') }}</label>
        <AaSelect id="fix-status" v-model="fix.status"><option value="">{{ $t('application.fixNoChange') }}</option><option v-for="k in BY_HAND" :key="k" :value="k">{{ $t('application.status.' + k) }}</option></AaSelect>
        <label for="fix-date">{{ $t('application.fixDate') }}</label>
        <div><input id="fix-date" v-model="fix.date" type="date" style="width: 180px" /> <span class="hint">{{ $t('application.fixDateHint') }}</span></div>
        <label for="fix-note">{{ $t('application.fixNote') }}</label>
        <input id="fix-note" v-model="fix.note" maxlength="300" :placeholder="$t('application.fixNotePlaceholder')" />
      </div>
      <div class="row" style="margin-top: 12px"><button class="primary" @click="saveFix">{{ $t('application.save') }}</button><button class="ghost" @click="panel = ''">{{ $t('application.cancel') }}</button></div>
    </div>

    <div class="seg tabs" role="tablist" style="margin: 16px 0 12px">
      <button v-for="k in TABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="openTab(k)">{{ $t('application.tab.' + k) }}<span v-if="tabCount(k)" class="n">{{ tabCount(k) }}</span></button>
    </div>

    <section v-if="tab === 'record'" id="record">
      <RecordPanel v-if="d" :d="d" @update="d = $event" @reload="load" />
      <div v-else class="card muted">{{ $t('application.noRecord') }}</div>
    </section>

    <section v-else-if="tab === 'agent'">
      <AgentJournal :journal="a.journal || []" :spent="a.spent" :running-task="a.running_task || 0" :expected="!!a.run_expected" :application-id="a.id" :note="$t('application.journalNote')" @refresh="load" />
      <div v-if="!(a.journal || []).length && !a.running_task" class="card muted">{{ a.run_expected ? $t('application.agentQueued') : $t('application.agentNothing') }}</div>
    </section>

    <section v-else-if="tab === 'materials'" class="cols">
      <div>
        <div class="card">
          <div class="card-title">{{ $t('application.materials') }}</div>
          <template v-if="a.materials.length">
            <div v-for="(m, i) in a.materials" :key="i" class="row" style="justify-content: space-between; padding: 4px 0">
              <span><span v-if="m.slot" class="muted">{{ m.slot }}: </span>
                <a v-if="m.document_id && m.exists" :href="`api/documents/${m.document_id}/file`" target="_blank" rel="noopener" data-notr>{{ m.name }}</a>
                <span v-else data-notr>{{ m.name }}<span v-if="!m.exists" class="muted">{{ $t('application.fileGone') }}</span></span>
              </span>
            </div>
            <router-link to="/files" class="small">{{ $t('application.inFiles') }}</router-link>
          </template>
          <div v-else class="muted">{{ $t('application.noMaterials') }}</div>
        </div>
        <div class="card">
          <div class="card-title">{{ $t('application.contacts') }}</div>
          <template v-if="a.contacts.length">
            <div v-for="c in a.contacts" :key="c.id" style="padding: 4px 0"><b>{{ c.name }}</b> <span class="muted">{{ [c.role, c.relation].filter(Boolean).join(' · ') }}</span>
              <span v-if="c.follow_up" class="tag" style="margin-left: 6px">{{ $t('application.followUp', { day: c.follow_up }) }}</span>
              <div v-if="c.note" class="small muted">{{ c.note }}</div>
            </div>
          </template>
          <div v-else class="muted">{{ $t('application.noContacts') }} <router-link to="/contacts">{{ $t('application.addContact') }}</router-link></div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">{{ $t('application.evidence') }}</div>
          <template v-if="a.evidence.text || a.evidence.url || a.evidence.mail_ids.length || a.evidence.by_user">
            <div v-if="a.evidence.text || a.evidence.url">
              <div class="small muted">{{ a.evidence.already_applied ? $t('application.evidenceAlready') : $t('application.evidencePage') }}<template v-if="a.evidence.read_by === 'model'">{{ $t('application.evidenceByAi') }}</template></div>
              <details class="tech" open><summary>{{ a.evidence.url || $t('application.evidencePageText') }}</summary><pre>{{ a.evidence.text }}</pre></details>
              <div v-if="a.evidence.has_screenshot" class="small" style="margin-top: 6px"><a :href="`api/applications/${a.id}/confirmation.png`" target="_blank" rel="noopener">{{ $t('application.evidenceShot') }}</a></div>
            </div>
            <div v-if="a.evidence.mail_ids.length" class="small" style="margin-top: 8px">{{ $t('application.evidenceMails', { n: a.evidence.mail_ids.length }, a.evidence.mail_ids.length) }}</div>
            <div v-if="a.evidence.by_user" class="small" style="margin-top: 8px">{{ $t('application.evidenceByYou') }}</div>
          </template>
          <div v-else class="muted">{{ a.sent ? $t('application.evidenceNone') : $t('application.notSentYet') }}</div>
        </div>
      </div>
    </section>

    <section v-else-if="tab === 'mail'">
      <div class="card">
        <template v-if="a.mails.length">
          <div v-for="m in a.mails" :key="m.message_id" class="mail-row">
            <div class="row" style="justify-content: space-between; align-items: baseline">
              <span><span class="tag" :class="m.is_evidence ? 'ok' : ''">{{ m.label }}</span> <b>{{ m.subject }}</b></span>
              <span class="small muted nowrap">{{ fmtTime(m.received_at) }}</span>
            </div>
            <div class="small muted">{{ m.sender }}<template v-if="m.linked_by === 'user'"> · {{ $t('application.linkedByYou') }}</template><template v-else-if="m.linked_by === 'site'"> · {{ $t('application.linkedBySite') }}</template></div>
            <div class="small" style="margin-top: 2px">{{ m.summary }}</div>
            <button class="sm ghost" style="margin-top: 4px" @click="unlink(m)">{{ $t('application.unlinkOk') }}</button>
          </div>
        </template>
        <div v-else class="muted">{{ $t('application.noMail') }}</div>
        <div style="margin-top: 10px">
          <button v-if="others === null" class="sm" @click="showOthers">{{ $t('application.otherMail') }}</button>
          <template v-else>
            <div class="small muted">{{ $t('application.otherMailList') }}</div>
            <div v-for="m in others" :key="m.message_id" class="row" style="justify-content: space-between; padding: 4px 0">
              <span class="small"><span class="tag">{{ m.label }}</span> {{ m.subject }} <span class="muted">{{ fmtTime(m.received_at) }}</span></span>
              <button class="sm" @click="link(m)">{{ $t('application.isThisOne') }}</button>
            </div>
            <div v-if="!others.length" class="small muted">{{ $t('application.noOtherMail') }}</div>
          </template>
        </div>
        <p class="small muted" style="margin-bottom: 0">{{ $t('application.mailWritten') }} <router-link to="/todos">{{ $t('application.openTodos') }}</router-link></p>
      </div>
    </section>

    <section v-else-if="tab === 'timeline'">
      <div class="card">
        <div v-for="(e, i) in a.timeline" :key="i" class="row" style="align-items: baseline; padding: 4px 0; gap: 10px">
          <span class="small muted nowrap" style="min-width: 118px">{{ fmtTime(e.at) }}</span>
          <span v-if="e.kind === 'status'" class="small">
            <template v-if="e.old !== e.new">{{ e.old || $t('application.created') }} → <b>{{ e.new }}</b></template><template v-else>{{ e.note }}</template>
            <span v-if="e.by" class="muted">{{ $t('application.by', { who: e.by }) }}</span><span v-if="e.note && e.old !== e.new" class="muted"> {{ e.note }}</span>
          </span>
          <span v-else-if="e.kind === 'run'" class="small">{{ e.what }}: <span :class="e.ok ? '' : 'muted'">{{ e.ok ? $t('application.runDone') : $t('application.runNotDone') }}</span><span v-if="e.said" class="muted" data-notr> {{ e.said }}</span> <router-link to="/runs" class="muted">{{ $t('application.runRecord') }}</router-link></span>
          <span v-else class="small">{{ $t('application.mailEvent', { label: e.label }) }} <span class="muted">{{ e.subject }}</span></span>
        </div>
        <div v-if="!a.timeline.length" class="muted">{{ $t('application.noTimeline') }}</div>
      </div>
    </section>

    <section v-else-if="tab === 'job'">
      <div class="card">
        <div class="row" style="gap: 10px; flex-wrap: wrap">
          <span class="score">{{ a.job.score == null ? $t('application.job.noScore') : $t('application.job.score', { n: a.job.score }) }}</span>
          <router-link :to="{ path: '/jobs', query: { open: a.job_id } }" class="btn sm">{{ $t('application.do.openJob') }}</router-link>
          <a v-if="a.apply_url" :href="a.apply_url" target="_blank" rel="noopener" class="btn sm"><Icon name="external" />{{ $t('application.posting') }}</a>
        </div>
        <div class="facts" style="margin-top: 12px">
          <div v-for="[k, v] in facts" :key="k"><div class="k">{{ $t(k) }}</div><div class="v">{{ v }}</div></div>
        </div>
        <p v-if="a.job.score_reason" class="small" style="margin-top: 12px">{{ a.job.score_reason }}</p>
      </div>
      <div v-if="a.job.brief" class="card md" v-html="renderMarkdown(a.job.brief)"></div>
      <div v-if="a.job.jd_text" class="card">
        <div class="card-title">{{ $t('application.job.text') }}</div>
        <pre style="font-family: inherit; font-size: 13.5px; line-height: 1.6" :style="showJd || a.job.jd_text.length < 900 ? '' : 'max-height: 200px; overflow: hidden; -webkit-mask-image: linear-gradient(#000 60%, transparent)'">{{ a.job.jd_text }}</pre>
        <button v-if="a.job.jd_text.length >= 900" class="ghost sm" style="margin-top: 6px" @click="showJd = !showJd">{{ showJd ? $t('application.job.less') : $t('application.job.more') }}</button>
      </div>
    </section>
  </template>
</template>

<style scoped>
.status-card { border-left: 3px solid var(--border); }
.status-card.edge-warn { border-left-color: var(--warn); }
.status-card.edge-bad { border-left-color: var(--bad); }
.status-card.edge-ok { border-left-color: var(--ok); }
.status-card.edge-info { border-left-color: var(--info); }
.more-wrap { position: relative; }
.menu-backdrop { position: fixed; inset: 0; z-index: 19; }
.more-menu { position: absolute; z-index: 20; top: calc(100% + 4px); left: 0; min-width: 220px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md);
  box-shadow: var(--shadow-md); padding: 4px; display: flex; flex-direction: column; }
.more-menu button { justify-content: flex-start; border: 0; background: transparent; text-align: left; }
.more-menu button:hover { background: var(--surface-2); }
.mail-row { padding: 6px 0; border-bottom: 1px solid var(--border); }
.warn-text { color: var(--warn); }
.note-card { background: var(--surface-2); }
</style>

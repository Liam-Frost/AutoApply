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
import IconButton from '../components/IconButton.vue'
import Menu from '../components/Menu.vue'
import PageHead from '../components/PageHead.vue'
import RecordPanel from '../components/RecordPanel.vue'
import SectionHead from '../components/SectionHead.vue'
import Status from '../components/Status.vue'
import TechDetails from '../components/TechDetails.vue'
import Trunc from '../components/Trunc.vue'
import { deadlineLabel, parseDeadline } from '../dates'
import { renderMarkdown } from '../md'
import { ask, fmtTime, run, toast } from '../ui'
import { asDate, dateTimeOf, dayText, stampDay } from '../i18n/format'

const props = defineProps({ id: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const a = ref(null)
const d = ref(null)              // the record (the draft that counts), when there is one
const failed = ref('')
const panel = ref('')            // the form open under the status: outcome | note | fix
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
const WHO = { me: 'applications.who.me', agent: 'applications.who.agent', them: 'applications.who.them' }      // (the list's words: one name for whose move it is)
// a dated step of the hiring wears the calendar's colour of its kind, as in the list
const EV = { interview: 'ev-interview', assessment: 'ev-assessment', offer: 'ev-offer' }

async function withdraw() {
  if (!(await ask(T('application.withdrawAsk'), { ok: T('application.do.withdraw'), danger: true }))) return
  await act(() => api.post(`/applications/${props.id}/withdraw`), T('application.withdrawn'))
}
async function notSubmitted() {
  if (!(await ask(T('application.notSubmittedAsk'), { ok: T('application.notSubmittedOk') }))) return
  await act(() => api.post(`/applications/${props.id}/not-submitted`), T('application.rerunStarted'))
}
async function discard() {
  if (!(await ask(T('application.discardAsk'), { ok: T('application.do.discard'), danger: true }))) return
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
// Everything else that can be done, in one menu: not again what stands beside it as a button, and what takes the
// application or its record away last, apart.
const LAST = ['withdraw', 'discard']
const menuItems = computed(() => {
  if (!a.value) return []
  const keys = Object.keys(ACTIONS).filter((k) => ACTIONS[k].when() && !mainKeys.value.includes(k))
  const item = (k) => ({ id: k, label: ACTIONS[k].label(), disabled: !!(ACTIONS[k].disabled && ACTIONS[k].disabled()), danger: LAST.includes(k) })
  const calm = keys.filter((k) => !LAST.includes(k)), last = keys.filter((k) => LAST.includes(k))
  return [...calm.map(item), ...(calm.length && last.length ? [{ divider: true }] : []), ...last.map(item)]
})
// why a button that matters now cannot be pressed (a button that is off says nothing to a keyboard or a finger)
const blocked = computed(() => mainKeys.value.map((k) => (ACTIONS[k].disabled ? ACTIONS[k].disabled() : '')).find(Boolean) || '')
function doAction(k) { ACTIONS[k].run() }

// --- the forms under the status: what came back, a note, a correction of the record -----------------------------------
// (a day in the applicant's own calendar: toISOString would give the UTC day, a day off in the evening west of Greenwich)
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const today = () => ymd(new Date())
const outcome = ref({ status: 'interview', date: '', time: '', note: '' })
const note = ref('')
const fix = ref({ status: '', date: '', note: '' })
const BY_HAND = ['submitted', 'confirmed', 'assessment', 'interview', 'offer', 'rejected', 'withdrawn']
const OUTCOMES = ['confirmed', 'assessment', 'interview', 'offer', 'rejected']
function openPanel(k) {
  panel.value = k
  if (k === 'outcome') outcome.value = { status: 'interview', date: today(), time: '', note: '' }
  if (k === 'note') note.value = a.value.note || ''
  if (k === 'fix') fix.value = { status: a.value.sent || a.value.status === 'withdrawn' ? a.value.status : '', date: a.value.submitted_at ? ymd(asDate(a.value.submitted_at)) : '', note: '' }
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
  const end = parseDeadline(j.deadline)
  return [['application.job.term', j.term], ['application.job.months', j.months], ['application.job.salary', j.salary], ['application.job.location', j.location],
    ['application.job.deadline', end ? dateTimeOf(end) : j.deadline], ['application.job.direction', j.direction], ['application.job.where', j.ats_label], ['application.job.posted', dayText(j.posted) || j.posted]].filter((x) => x[1])
})

watch(() => props.id, async () => { a.value = null; await load(); tab.value = firstTab() })
onMounted(async () => { await load(); tab.value = firstTab() })
</script>

<template>
  <div v-if="!a && !failed" class="empty"><div class="t">{{ $t('application.loading') }}</div></div>
  <div v-else-if="failed" class="empty"><div class="t">{{ $t('application.couldNotLoad') }}</div><div class="muted">{{ failed }}</div>
    <div class="row empty-acts"><button @click="load">{{ $t('application.tryAgain') }}</button><button class="ghost" @click="router.push('/applications')">{{ $t('application.backToList') }}</button></div>
  </div>
  <template v-else>
    <PageHead class="app-head" :title="a.company">
      <template #sub>
        <div class="app-sub">
          <router-link to="/applications" class="app-back"><Icon name="back" />{{ $t('application.backToList') }}</router-link>
          <Trunc v-if="a.title" class="app-job" :text="a.title" />
          <span v-if="a.ats_label" class="meta">{{ a.ats_label }}</span>
          <Trunc v-if="a.location" class="meta app-place" :text="a.location" />
          <span v-if="due && due.text" class="meta" :class="{ 'warn-text': due.tone === 'soon' }">{{ due.text }}</span>
        </div>
      </template>
      <a v-if="a.apply_url" :href="a.apply_url" target="_blank" rel="noopener" class="btn ghost"><Icon name="external" />{{ $t('application.posting') }}</a>
    </PageHead>

    <!-- where it stands, whose move it is, and what can be done now -->
    <div class="card status-card" :class="'edge-' + (a.tone || 'none')">
      <div class="status-line">
        <span v-if="EV[a.stage]" class="tag ev-tag" :class="EV[a.stage]">{{ a.stage_label }}</span>
        <span v-else class="tag" :class="a.tone">{{ a.stage_label }}</span>
        <span v-if="a.archived" class="meta">{{ $t('application.archived') }}</span>
        <span v-if="a.who" class="t-secondary">{{ $t('applications.owner', { who: $t(WHO[a.who]) }) }}</span>
        <span v-if="a.submitted_at" class="t-meta atomic">{{ $t('application.sentOn', { day: stampDay(a.submitted_at) }) }}</span>
        <span v-if="a.auto_approved" class="t-meta atomic">{{ $t('application.autoApproved') }}</span>
      </div>
      <p v-if="a.next" class="status-next">{{ a.next }}</p>
      <p v-if="a.next_why" class="status-why">{{ a.next_why }}</p>
      <p v-if="a.explained.message" class="status-why">{{ a.explained.message }}</p>
      <TechDetails :text="a.explained.detail" />
      <div v-if="a.cards.length" class="status-cards">
        <span class="t-meta">{{ $t('application.waitingForYou') }}</span>
        <router-link v-for="c in a.cards" :key="c.id" to="/todos" class="tag warn cut" v-tip.overflow>{{ c.title }}</router-link>
      </div>
      <!-- at most three that matter now, the first the main one; everything else in the menu, what cannot be undone last -->
      <div class="actions status-acts">
        <button v-for="(k, i) in mainKeys" :key="k" :class="{ primary: i === 0 }" :disabled="!!(ACTIONS[k].disabled && ACTIONS[k].disabled())" @click="doAction(k)">{{ ACTIONS[k].label() }}</button>
        <Menu v-if="menuItems.length" :label="$t('application.more')" :items="menuItems" align="start" @pick="doAction">
          <template #trigger="{ toggle, attrs }"><button class="ghost" v-bind="attrs" @click="toggle">{{ $t('application.more') }}<Icon name="chevron" /></button></template>
        </Menu>
      </div>
      <p v-if="blocked" class="t-meta status-blocked">{{ blocked }}</p>
    </div>

    <div v-if="panel === 'outcome'" class="card">
      <SectionHead :title="$t('application.outcomeTitle')" :help="$t('application.outcomeHow')" />
      <div class="kv">
        <label for="o-status">{{ $t('application.outcomeWhat') }}</label>
        <AaSelect id="o-status" v-model="outcome.status"><option v-for="k in OUTCOMES" :key="k" :value="k">{{ $t('application.status.' + k) }}</option></AaSelect>
        <label for="o-date">{{ $t('application.outcomeWhen') }}</label>
        <div class="form-line"><input id="o-date" v-model="outcome.date" type="date" /><input v-model="outcome.time" type="time" :aria-label="$t('application.outcomeTime')" />
          <span v-if="['assessment', 'interview'].includes(outcome.status)" class="hint">{{ $t('application.outcomeCalendar') }}</span></div>
        <label for="o-note">{{ $t('application.outcomeNote') }}</label>
        <input id="o-note" v-model="outcome.note" maxlength="240" :placeholder="$t('application.outcomeNotePlaceholder')" />
      </div>
      <div class="actions form-acts"><button class="primary" @click="saveOutcome">{{ $t('application.save') }}</button><button class="ghost" @click="panel = ''">{{ $t('application.cancel') }}</button></div>
    </div>

    <div v-if="panel === 'note'" class="card">
      <SectionHead :title="$t('application.noteTitle')" />
      <textarea v-model="note" class="note-text" rows="4" maxlength="4000" :aria-label="$t('application.noteTitle')" :placeholder="$t('application.notePlaceholder')"></textarea>
      <div class="actions form-acts"><button class="primary" @click="saveNote">{{ $t('application.save') }}</button><button class="ghost" @click="panel = ''">{{ $t('application.cancel') }}</button></div>
    </div>
    <div v-else-if="a.note" class="card note-card">
      <SectionHead :title="$t('application.noteTitle')"><IconButton icon="edit" :label="$t('application.do.editNote')" @click="openPanel('note')" /></SectionHead>
      <div class="note-body">{{ a.note }}</div>
    </div>

    <div v-if="panel === 'fix'" class="card">
      <SectionHead :title="$t('application.do.fix')" :help="$t('application.fixHow')" />
      <div class="kv">
        <label for="fix-status">{{ $t('application.fixStatus') }}</label>
        <AaSelect id="fix-status" v-model="fix.status"><option value="">{{ $t('application.fixNoChange') }}</option><option v-for="k in BY_HAND" :key="k" :value="k">{{ $t('application.status.' + k) }}</option></AaSelect>
        <label for="fix-date">{{ $t('application.fixDate') }}</label>
        <div class="form-line"><input id="fix-date" v-model="fix.date" type="date" /><span class="hint">{{ $t('application.fixDateHint') }}</span></div>
        <label for="fix-note">{{ $t('application.fixNote') }}</label>
        <input id="fix-note" v-model="fix.note" maxlength="300" :placeholder="$t('application.fixNotePlaceholder')" />
      </div>
      <div class="actions form-acts"><button class="primary" @click="saveFix">{{ $t('application.save') }}</button><button class="ghost" @click="panel = ''">{{ $t('application.cancel') }}</button></div>
    </div>

    <div class="seg tabs app-tabs" role="tablist">
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
          <SectionHead :title="$t('application.materials')"><router-link v-if="a.materials.length" to="/files" class="btn sm ghost">{{ $t('application.inFiles') }}</router-link></SectionHead>
          <div v-if="a.materials.length" class="plain-list">
            <div v-for="(m, i) in a.materials" :key="i" class="file-line">
              <span v-if="m.slot" class="meta">{{ m.slot }}</span>
              <Trunc v-if="m.document_id && m.exists" as="a" :href="`api/documents/${m.document_id}/file`" target="_blank" rel="noopener" data-notr :text="m.name" />
              <template v-else><Trunc data-notr :text="m.name" /><span v-if="!m.exists" class="t-meta atomic">{{ $t('application.fileGone') }}</span></template>
            </div>
          </div>
          <div v-else class="muted">{{ $t('application.noMaterials') }}</div>
        </div>
        <div class="card">
          <SectionHead :title="$t('application.contacts')" />
          <div v-if="a.contacts.length" class="plain-list">
            <div v-for="c in a.contacts" :key="c.id"><span class="t-primary">{{ c.name }}</span> <span class="t-secondary">{{ [c.role, c.relation].filter(Boolean).join(' · ') }}</span>
              <span v-if="c.follow_up" class="meta small"> · {{ $t('application.followUp', { day: dayText(c.follow_up) || c.follow_up }) }}</span>
              <div v-if="c.note" class="t-meta">{{ c.note }}</div>
            </div>
          </div>
          <div v-else class="muted">{{ $t('application.noContacts') }} <router-link to="/contacts">{{ $t('application.addContact') }}</router-link></div>
        </div>
      </div>
      <div>
        <div class="card">
          <SectionHead :title="$t('application.evidence')" />
          <template v-if="a.evidence.text || a.evidence.url || a.evidence.mail_ids.length || a.evidence.by_user">
            <div v-if="a.evidence.text || a.evidence.url">
              <div class="t-meta">{{ a.evidence.already_applied ? $t('application.evidenceAlready') : $t('application.evidencePage') }}<template v-if="a.evidence.read_by === 'model'">{{ $t('application.evidenceByAi') }}</template></div>
              <details class="tech" open><summary><Trunc :text="a.evidence.url || $t('application.evidencePageText')" /></summary><pre>{{ a.evidence.text }}</pre></details>
              <div v-if="a.evidence.has_screenshot" class="evidence-line"><a :href="`api/applications/${a.id}/confirmation.png`" target="_blank" rel="noopener">{{ $t('application.evidenceShot') }}</a></div>
            </div>
            <div v-if="a.evidence.mail_ids.length" class="evidence-line">{{ $t('application.evidenceMails', { n: a.evidence.mail_ids.length }, a.evidence.mail_ids.length) }}</div>
            <div v-if="a.evidence.by_user" class="evidence-line">{{ $t('application.evidenceByYou') }}</div>
          </template>
          <div v-else class="muted">{{ a.sent ? $t('application.evidenceNone') : $t('application.notSentYet') }}</div>
        </div>
      </div>
    </section>

    <section v-else-if="tab === 'mail'">
      <div class="card">
        <template v-if="a.mails.length">
          <div v-for="m in a.mails" :key="m.message_id" class="mail-row">
            <div class="mail-head">
              <Status :tone="m.is_evidence ? 'ok' : ''" :label="m.label" />
              <Trunc class="t-primary mail-subject" :text="m.subject" />
              <span class="t-meta num atomic">{{ fmtTime(m.received_at) }}</span>
              <Menu :label="$t('application.more')" :items="[{ id: 'unlink', label: $t('application.unlinkOk'), icon: 'x' }]" @pick="unlink(m)" />
            </div>
            <div class="t-meta"><Trunc :text="m.sender" /><template v-if="m.linked_by === 'user'"> · {{ $t('application.linkedByYou') }}</template><template v-else-if="m.linked_by === 'site'"> · {{ $t('application.linkedBySite') }}</template></div>
            <div class="mail-summary">{{ m.summary }}</div>
          </div>
        </template>
        <div v-else class="muted">{{ $t('application.noMail') }}</div>
        <div class="mail-others">
          <button v-if="others === null" class="sm" @click="showOthers">{{ $t('application.otherMail') }}</button>
          <template v-else>
            <div class="t-meta">{{ $t('application.otherMailList') }}</div>
            <div v-for="m in others" :key="m.message_id" class="mail-head">
              <Status :label="m.label" /><Trunc class="mail-subject" :text="m.subject" /><span class="t-meta num atomic">{{ fmtTime(m.received_at) }}</span>
              <button class="sm" @click="link(m)">{{ $t('application.isThisOne') }}</button>
            </div>
            <div v-if="!others.length" class="t-meta">{{ $t('application.noOtherMail') }}</div>
          </template>
        </div>
        <p class="t-meta mail-foot">{{ $t('application.mailWritten') }} <router-link to="/todos">{{ $t('application.openTodos') }}</router-link></p>
      </div>
    </section>

    <section v-else-if="tab === 'timeline'">
      <div class="card">
        <div v-for="(e, i) in a.timeline" :key="i" class="tl-row">
          <span class="t-meta num atomic tl-when">{{ fmtTime(e.at) }}</span>
          <span v-if="e.kind === 'status'" class="tl-what">
            <template v-if="e.old !== e.new">{{ e.old || $t('application.created') }} → <span class="t-primary">{{ e.new }}</span></template><template v-else>{{ e.note }}</template>
            <span v-if="e.by" class="muted">{{ $t('application.by', { who: e.by }) }}</span><span v-if="e.note && e.old !== e.new" class="muted"> {{ e.note }}</span>
          </span>
          <span v-else-if="e.kind === 'run'" class="tl-what">{{ e.what }}: <span :class="e.ok ? '' : 'muted'">{{ e.ok ? $t('application.runDone') : $t('application.runNotDone') }}</span><span v-if="e.said" class="muted" data-notr> {{ e.said }}</span> <router-link to="/runs" class="muted">{{ $t('application.runRecord') }}</router-link></span>
          <span v-else class="tl-what">{{ $t('application.mailEvent', { label: e.label }) }} <span class="muted">{{ e.subject }}</span></span>
        </div>
        <div v-if="!a.timeline.length" class="muted">{{ $t('application.noTimeline') }}</div>
      </div>
    </section>

    <section v-else-if="tab === 'job'">
      <div class="card">
        <div class="job-state">
          <span class="score-num">{{ a.job.score == null ? $t('application.job.noScore') : $t('application.job.score', { n: a.job.score }) }}</span>
          <span class="grow"></span>
          <router-link :to="{ path: '/jobs', query: { open: a.job_id } }" class="btn sm">{{ $t('application.do.openJob') }}</router-link>
        </div>
        <div class="facts">
          <div v-for="[k, v] in facts" :key="k"><div class="k">{{ $t(k) }}</div><div class="v">{{ v }}</div></div>
        </div>
        <p v-if="a.job.score_reason" class="t-secondary job-why">{{ a.job.score_reason }}</p>
      </div>
      <div v-if="a.job.brief" class="card md" v-html="renderMarkdown(a.job.brief)"></div>
      <div v-if="a.job.jd_text" class="card">
        <SectionHead :title="$t('application.job.text')" />
        <pre class="job-jd" :class="{ folded: !showJd && a.job.jd_text.length >= 900 }">{{ a.job.jd_text }}</pre>
        <button v-if="a.job.jd_text.length >= 900" class="ghost sm" @click="showJd = !showJd">{{ showJd ? $t('application.job.less') : $t('application.job.more') }}</button>
      </div>
    </section>
  </template>
</template>

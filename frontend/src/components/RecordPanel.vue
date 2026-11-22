<script setup>
import { t as T } from '../i18n/catalog'
// The record of an application (what was the draft page): every answer the agent gave, where it came from and how sure
// it was; the questions still open; the files that go with it; what the applicant wants changed. It lives on the
// application's page (ApplicationDetail), which has the buttons that decide about it (approve, send back).
import { computed, nextTick, ref } from 'vue'
import { api } from '../api'
import { decisions, toDecide } from '../draftsum'
import { ask, run, toast } from '../ui'

const props = defineProps({ d: { type: Object, required: true } })
const emit = defineEmits(['update', 'reload'])
const editing = ref(null)
const editVal = ref('')
const typeOwn = ref(false)      // a choice that is not among the ones the record lists
const saveRule = ref('')
const remember = ref(false)
const comment = ref('')

const pending = computed(() => props.d.review_status === 'pending')
// Anything in a record can be changed for as long as the application has not gone out - before approving and after.
// The server says when it cannot (an old version, already sent, a run in progress) and why.
const editable = computed(() => !props.d.locked)
const approvedOpen = computed(() => editable.value && props.d.review_status === 'approved')
const isFilled = (a) => a.value !== '' && a.value != null && !(Array.isArray(a.value) && !a.value.length)
const filled = computed(() => props.d.answers.filter(isFilled))
const blank = computed(() => props.d.answers.filter((a) => !isFilled(a) && !isUnresolved(a)))
const shown = computed(() => props.d.answers.filter((x) => isFilled(x) || isUnresolved(x) || x.dropped || editing.value === x.id))
const show = (a) => (a.type === 'file' ? String(a.value).split(/[\\/]/).pop() : Array.isArray(a.value) ? a.value.join(', ') : a.type === 'checkbox' ? (a.value ? T('record.ticked') : T('record.notTicked')) : a.value)
const isUnresolved = (a) => props.d.unresolved.some((u) => u.id === a.id)
const SURE = { high: ['record.sure.high', 'ok'], medium: ['record.sure.medium', 'warn'], low: ['record.sure.low', 'bad'] }

// What needs a decision, before the table of everything (draftsum.js); each line leads to its row.
const toLook = computed(() => (pending.value ? decisions(props.d) : []))
const lit = ref('')
const lineOf = (g) => (g.items.length ? g.items.map((i) => i.label).join('; ') : T('record.seeTheWholeFlow'))
async function goTo(id, where) {
  await nextTick()
  const el = document.getElementById(id ? 'ans-' + id : 'draft-' + where)
  if (!el) return
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
  lit.value = id || where
  setTimeout(() => { if (lit.value === (id || where)) lit.value = '' }, 2200)
}

// The résumé of this application: one rewritten for the posting (when there is one and the applicant has not chosen
// the one they uploaded), or the one they uploaded. The agent's next run on the application uses what is chosen here.
const CHANGE = { reorder_bullets: 'record.change.reorderBullets', reorder_entries: 'record.change.reorderEntries', skills: 'record.change.skills', drop: 'record.change.drop', rewrite: 'record.change.rewrite', rewrite_rejected: 'record.change.rewriteRejected' }
const tailorNote = ref('')
const written = computed(() => (props.d.tailor ? props.d.tailor.written : null))
const usesWritten = computed(() => !!written.value && props.d.tailor.use === 'tailored')
const useResume = (which) => run(() => api.post(`/drafts/${props.d.id}/resume`, { which }), which === 'base' ? T('record.usesBase') : T('record.usesTailored'), () => emit('reload'))
async function tailorNow() {
  try {
    await api.post(`/jobs/${props.d.job.id}/tailor`, { instructions: tailorNote.value })
    toast(T('record.tailorStarted'))
    tailorNote.value = ''
    const before = written.value ? written.value.name : ''
    let n = 0
    const timer = setInterval(() => { emit('reload'); if (++n > 60 || (written.value && written.value.name !== before)) clearInterval(timer) }, 5000)
  } catch (e) { toast(e.message, 'bad') }
}

async function dropQuestion(a) {
  if (!(await ask(T('record.dropAsk', { q: a.label }), { ok: T('record.dropOk'), danger: false }))) return
  try { emit('update', await api.del(`/drafts/${props.d.id}/answers/${encodeURIComponent(a.id)}`)); editing.value = null } catch (e) { toast(e.message, 'bad') }
}
// An answer belongs to this application. "Also from now on" writes it to the profile: offered ticked for a question
// the agent said is about the applicant in general, unticked for one about this job.
// (a question the agent asked with a suggestion of its own opens with that suggestion in the box: taken with one press, or changed)
const takeSuggestion = (a) => { startEdit(a); return commitEdit(a) }
function startEdit(a) {
  typeOwn.value = false
  editing.value = a.id
  editVal.value = Array.isArray(a.value) ? a.value.join(' || ') : a.value === true ? 'true' : a.value === false ? 'false' : (a.value === '' || a.value == null) && a.suggested ? a.suggested : a.value
  saveRule.value = ''
  remember.value = isUnresolved(a) && a.about === 'applicant'
}
async function commitEdit(a) {
  let v = editVal.value
  if (a.type === 'checkbox') v = String(v).toLowerCase() === 'true'
  if (a.type === 'multiselect') v = String(v).split('||').map((x) => x.trim()).filter(Boolean)
  try {
    emit('update', await api.patch(`/drafts/${props.d.id}/answers/${encodeURIComponent(a.id)}`, { value: v, save_rule: remember.value ? saveRule.value : '', remember: remember.value }))
    if (remember.value) toast(T('record.savedToProfile'))
    else if (approvedOpen.value) toast(T('record.savedStillApproved'))
    editing.value = null
  } catch (e) { toast(e.message, 'bad') }
}
async function sendComment() {
  if (await run(() => api.post(`/drafts/${props.d.id}/comment`, { comment: comment.value }), T('record.commentSent'), () => emit('reload'), { name: 'comment' })) comment.value = ''
}
const workAgain = () => run(() => api.post(`/drafts/${props.d.id}/reanswer`), T('record.workAgainStarted'), () => emit('reload'), { name: 'reanswer' })
</script>

<template>
  <div v-if="d.unresolved.length" class="callout bad" style="display: block">
    <b>{{ $t('record.questionsForYou', { n: d.unresolved.length }, d.unresolved.length) }}</b>
    <div class="muted small">{{ $t('record.questionsForYouHow') }}</div>
    <ul style="margin: 8px 0 0; padding-left: 20px"><li v-for="u in d.unresolved" :key="u.id">{{ u.label }}</li></ul>
    <div v-if="editable" class="row" style="margin-top: 10px"><button @click="workAgain">{{ $t('record.workAgain') }}</button>
      <span class="muted small">{{ $t('record.workAgainWhen') }}</span></div>
  </div>

  <div v-if="toLook.length" class="panel look" aria-labelledby="look-h">
    <h3 id="look-h" style="margin-top: 0">{{ $t('record.lookFirst') }}<span class="muted small" style="font-weight: 400; margin-left: 10px">{{ toDecide(toLook) ? $t('record.toDecide', { n: toDecide(toLook) }, toDecide(toLook)) : $t('record.nothingToDecide') }}</span></h3>
    <div v-for="g in toLook" :key="g.key" class="look-group">
      <span class="tag" :class="g.tone">{{ g.label }}</span>
      <button v-if="g.to" class="look-item" @click="goTo('', g.to)">{{ lineOf(g) }}</button>
      <template v-else>
        <button v-for="i in g.items" :key="i.id" class="look-item" @click="goTo(i.id)">{{ i.label }}<span v-if="i.note" class="muted">{{ $t('record.lookNote', { note: i.note }) }}</span></button>
      </template>
    </div>
  </div>

  <div v-if="d.notes_display.length" class="callout" style="display: block">
    <b>{{ $t('record.agentSummary') }}</b>
    <ul style="margin: 6px 0 0; padding-left: 20px"><li v-for="(n, i) in d.notes_display" :key="i">{{ n }}</li></ul>
  </div>

  <div class="row"><h3 class="grow">{{ $t('record.answers', { n: filled.length }, filled.length) }}</h3><span class="small muted">{{ $t('record.version', { n: d.version }) }} · {{ d.review_label }}</span></div>
  <div class="table-wrap" style="max-height: none">
    <table>
      <thead><tr><th style="width: 34%">{{ $t('record.question') }}</th><th>{{ $t('record.answer') }}</th><th style="width: 22%">{{ $t('record.basis') }}</th><th>{{ $t('record.sure.title') }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="a in shown" :id="'ans-' + a.id" :key="a.id" :class="{ lit: lit === a.id }">
          <td>
            {{ a.label }}<span v-if="a.required" style="color: var(--bad)"> *</span>
            <span v-if="isUnresolved(a) && a.about === 'job'" class="tag" style="margin-left: 4px">{{ $t('record.onlyThisJob') }}</span>
          </td>
          <td>
            <template v-if="editing === a.id">
              <template v-if="a.options && a.options.length && a.type !== 'multiselect' && !a.searchable && !typeOwn">
                <AaSelect v-model="editVal" style="max-width: 100%"><option v-for="o in a.options" :key="o">{{ o }}</option></AaSelect>
                <div><button class="ghost sm" @click="typeOwn = true">{{ $t('record.notInList') }}</button></div>
              </template>
              <template v-else-if="a.options && a.options.length && a.type !== 'multiselect'">
                <input v-model="editVal" :list="'opts-' + a.page + '-' + a.label.length" style="width: 100%" />
                <datalist :id="'opts-' + a.page + '-' + a.label.length"><option v-for="o in a.options" :key="o" :value="o"></option></datalist>
                <div class="small muted">{{ $t('record.optionsHint') }}</div>
              </template>
              <AaSelect v-else-if="a.type === 'checkbox'" v-model="editVal"><option value="true">{{ $t('record.tick') }}</option><option value="false">{{ $t('record.dontTick') }}</option></AaSelect>
              <textarea v-else v-model="editVal" rows="3"></textarea>
              <div v-if="a.type === 'multiselect'" class="small muted">{{ $t('record.multiHint', { options: a.options.join(' / ') }) }}</div>
              <label class="small" style="display: block; margin-top: 8px"><input v-model="remember" type="checkbox" /> {{ $t('record.remember') }}</label>
              <input v-if="remember" v-model="saveRule" :placeholder="$t('record.rulePlaceholder')" style="width: 100%; margin-top: 6px" />
              <div class="row" style="margin-top: 6px"><button class="primary" @click="commitEdit(a)">{{ $t('record.save') }}</button><button @click="editing = null">{{ $t('record.cancel') }}</button>
                <button v-if="isUnresolved(a) && a.source === 'unresolved'" class="ghost" :title="$t('record.notMineHow')" @click="dropQuestion(a)">{{ $t('record.notMine') }}</button></div>
            </template>
            <template v-else>
              <span v-if="isUnresolved(a)" class="tag bad">{{ $t('record.noAnswerYet') }}</span>
              <template v-if="isUnresolved(a) && a.suggested">
                <span class="small muted" style="margin-left: 8px">{{ $t('record.suggested', { v: a.suggested }) }}</span>
                <button v-if="editable" class="sm" style="margin-left: 6px" @click="takeSuggestion(a)">{{ $t('record.takeSuggestion') }}</button>
              </template>
              <span v-else-if="a.dropped" class="tag">{{ $t('record.dropped') }}</span>
              <pre v-else style="font-family: inherit; font-size: 14px">{{ show(a) }}</pre>
            </template>
          </td>
          <td class="small muted">{{ a.basis_display }}</td>
          <td><span v-if="SURE[a.confidence]" class="tag" :class="SURE[a.confidence][1]">{{ $t(SURE[a.confidence][0]) }}</span></td>
          <td><button v-if="editable && a.type !== 'file' && editing !== a.id" class="sm" @click="startEdit(a)">{{ $t('record.change.button') }}</button></td>
        </tr>
      </tbody>
    </table>
  </div>
  <details v-if="blank.length" style="margin: 8px 0">
    <summary class="muted">{{ $t('record.blankOptional', { n: blank.length }, blank.length) }}</summary>
    <ul class="small"><li v-for="b in blank" :key="b.id">{{ b.label }} <button v-if="editable && b.type !== 'file'" class="sm" @click="startEdit(b)">{{ $t('record.fillIn') }}</button></li></ul>
  </details>

  <div class="cols">
    <div>
      <h3 id="draft-materials" :class="{ lit: lit === 'materials' }">{{ $t('record.files') }}</h3>
      <div class="panel">
        <div v-for="m in d.materials" :key="m.slot" class="row" style="margin-bottom: 6px">
          <span class="tag info">{{ m.slot_label || m.label || m.slot }}</span>
          <a v-if="m.document_id" :href="`api/documents/${m.document_id}/file`" target="_blank" rel="noopener" data-notr>{{ m.name }}</a>
          <span v-else data-notr>{{ m.name }}</span>
          <span v-if="m.overwritten" class="badge warn" :title="$t('record.overwrittenHow')">{{ $t('record.overwritten') }}</span>
        </div>
        <div v-if="!d.materials.length" class="muted">{{ $t('record.noFiles') }}</div>
        <div v-if="written" class="tailor">
          <div><b>{{ usesWritten ? $t('record.usesWritten') : $t('record.hasWritten') }}</b><span v-if="written.focus">: {{ written.focus }}</span></div>
          <div v-if="written.keywords && written.keywords.length" class="row" style="gap: 6px; margin-top: 8px"><span v-for="k in written.keywords" :key="k" class="tag">{{ k }}</span></div>
          <details v-if="written.changes && written.changes.length" class="tech">
            <summary>{{ $t('record.changesFromBase', { n: written.changes.length }, written.changes.length) }}</summary>
            <div v-for="(c, i) in written.changes" :key="i" class="chg">
              <div><span class="tag" :class="c.type === 'rewrite_rejected' ? 'warn' : c.type === 'rewrite' || c.type === 'drop' ? 'info' : ''">{{ CHANGE[c.type] ? $t(CHANGE[c.type]) : c.type }}</span> <span class="muted small">{{ c.where }}</span></div>
              <ol v-if="Array.isArray(c.after)"><li v-for="x in c.after" :key="x">{{ x }}</li></ol>
              <template v-else>
                <div v-if="c.before" class="small"><span class="muted">{{ $t('record.before') }}</span>{{ c.before }}</div>
                <div v-if="c.after" class="small"><span class="muted">{{ c.type === 'rewrite_rejected' ? $t('record.droppedRewrite') : $t('record.now') }}</span>{{ c.after }}</div>
              </template>
            </div>
          </details>
          <div v-if="editable" class="row" style="margin-top: 10px">
            <button v-if="usesWritten" class="sm" @click="useResume('base')">{{ $t('record.useBase') }}</button>
            <button v-else class="sm" @click="useResume('tailored')">{{ $t('record.useTailored') }}</button>
          </div>
        </div>
        <div v-if="editable && d.tailor && d.tailor.mode !== 'off'" class="tailor">
          <template v-if="d.tailor.available">
            <div class="small muted" style="margin-bottom: 6px">{{ written ? $t('record.tailorAgainHint') : $t('record.tailorHint') }}</div>
            <div class="row"><input v-model="tailorNote" class="grow" :placeholder="$t('record.tailorPlaceholder')" /><button class="sm" @click="tailorNow">{{ written ? $t('record.tailorAgain') : $t('record.tailor') }}</button></div>
          </template>
          <div v-else class="small muted">{{ $t('record.tailorNeedsWord') }} <router-link to="/files">{{ $t('record.openFiles') }}</router-link></div>
        </div>
      </div>
    </div>
    <div>
      <h3 id="draft-after" :class="{ lit: lit === 'after' }">{{ $t('record.afterApproval') }}</h3>
      <div class="panel">
        <p style="margin: 0">{{ d.policy === 'hand_over' ? $t('record.afterHandOver') : $t('record.afterSubmit') }}</p>
        <p class="small" style="margin: 8px 0 0"><router-link to="/settings/automation/submit">{{ $t('record.whoSubmits') }}</router-link></p>
      </div>
    </div>
  </div>

  <div v-if="d.locked && ['pending', 'approved'].includes(d.review_status)" class="callout" style="display: block"><span class="muted">{{ d.locked }}</span></div>

  <template v-if="pending || approvedOpen">
    <h3>{{ $t('record.wantChanges') }}</h3>
    <div class="panel">
      <textarea v-model="comment" :placeholder="$t('record.wantChangesPlaceholder')" style="font-family: inherit"></textarea>
      <div class="row" style="margin-top: 8px"><button :disabled="!comment.trim()" @click="sendComment">{{ $t('record.changeIt') }}</button></div>
      <div v-for="(c, i) in d.comments || []" :key="i" class="small muted" style="margin-top: 6px">{{ $t('record.youSaid', { text: c.comment }) }}<template v-if="c.result"> → {{ c.result }}</template></div>
    </div>
  </template>
</template>

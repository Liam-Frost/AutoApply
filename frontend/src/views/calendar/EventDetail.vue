<script setup>
// One item, the same from the month, the week and the day: what it is and where it stands, its time (as the mail wrote
// it too), what it is about, and what can be done with it - only what the program can do: a posting's deadline is the
// source's and is not moved here; a card's date and link are the applicant's to change; what happened is only shown.
// Its reminders (alarms.py) are at the bottom. Nothing is shown that the item does not have.
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'
import { at, saidEnd, status } from '../../calendar'
import { deadlineLabel } from '../../dates'
import { t } from '../../i18n/catalog'
import { clockOf } from '../../i18n/format'
import { ask, run, toast } from '../../ui'
import { formatReminder } from '../../reminders'
import { companyOf, family, GLYPH, kindName, longDate, scoreOf, statusName, statusTone, titleOf } from './look'

const props = defineProps({ item: { type: Object, required: true }, now: { type: Date, required: true }, back: { type: String, default: '' }, zone: { type: Object, default: null } })
const emit = defineEmits(['close', 'back', 'changed'])
const x = computed(() => props.item)
const st = computed(() => status(x.value, props.now))
const when = computed(() => {
  const d = at(x.value)
  if (x.value.all_day) return t('calendar.allDayOn', { day: longDate(d) })
  const e = saidEnd(x.value)      // (the end the mail said: "10:00–10:45")
  return t('time.dayAt', { day: longDate(d), time: e ? t('calendar.clockRange', { from: clockOf(d), to: clockOf(e) }) : clockOf(d) })
})
// the time as the mail said it, on the clock the mail used (what the time above was converted from)
const said = computed(() => {
  const d = at({ start: x.value.due_said })
  return Number.isNaN(d.getTime()) ? '' : t('time.dayAt', { day: longDate(d), time: clockOf(d) })
})
const left = computed(() => (x.value.kind === 'deadline' && st.value === 'open' ? deadlineLabel(x.value.start.replace('T', ' '), props.now) : null))
const isCard = computed(() => !!x.value.about.todo_id && x.value.kind !== 'snoozed')
const mailLinks = computed(() => (x.value.links || []).filter((l) => l.url !== x.value.link))

// --- what can be done --------------------------------------------------------------------------------------------------
const dueEdit = ref(null)
const linkEdit = ref(null)
watch(() => x.value.id, () => { dueEdit.value = null; linkEdit.value = null })
const changed = () => { dueEdit.value = null; linkEdit.value = null; emit('changed') }
const done = () => run(() => api.post(`/todos/${x.value.about.todo_id}/done`, {}), t('calendar.doneMsg'), changed)
// an item of the applicant's own calendar is removed here - it is nowhere else (not a card on the to-do page) - and the
// notice after it can undo that
async function remove() {
  const id = x.value.about.todo_id
  if (!(await ask(t('calendar.removeAsk', { title: titleOf(x.value) }), { ok: t('calendar.remove'), danger: true }))) return
  const gone = await run(() => api.post(`/todos/${id}/done`, { status: 'dismissed', resume: false }), '', changed)
  if (gone !== false) {
    toast(t('calendar.removedMsg'), '', { act: () => run(() => api.post(`/todos/${id}/reopen`), t('calendar.backMsg'), changed), link: t('calendar.undo') })
    emit('close')
  }
}
const saveDue = () => run(() => api.post(`/todos/${x.value.about.todo_id}/due`, { due: dueEdit.value }), t('calendar.movedMsg'), changed)
const saveLink = (link) => run(() => api.post(`/calendar/items/${x.value.about.todo_id}/link`, { link }), t('calendar.linkSaved'), changed)
const startApplication = () => run(() => api.post(`/jobs/${x.value.about.job_id}/draft`, {}), t('calendar.started'), changed)
const notApplying = () => run(() => api.patch(`/jobs/${x.value.about.job_id}`, { status: 'skipped' }), t('calendar.skipped'), changed)

// --- its reminders: "this long before", as many as wanted -------------------------------------------------------------
const itemKey = computed(() => (x.value.about.todo_id && x.value.id.startsWith('todo:') ? x.value.id : x.value.kind === 'deadline' ? x.value.id : ''))
const alarms = ref(null)
const choices = ref([])
const custom = ref('')
watch(itemKey, async (k) => {
  alarms.value = null
  if (!k) return
  const r = await api.get('/calendar/alarms?item=' + encodeURIComponent(k))
  if (k === itemKey.value) { alarms.value = r.alarms; choices.value = r.choices }
}, { immediate: true })
// "30 minutes before", "1 day before" - for a whole-day item, the morning of that many days before
// (one wording with the settings: 0 before a timed item is its start, not "the morning of the day")
const ahead = (before, allDay) => formatReminder(before, { allDay })
const addAlarm = (before) => run(async () => { alarms.value = (await api.post('/calendar/alarms', { item: itemKey.value, before: Number(before) })).alarms }, t('calendar.alarm.added'))
const removeAlarm = (a) => run(async () => { await api.del(`/calendar/alarms/${a.id}`); alarms.value = alarms.value.filter((y) => y.id !== a.id) }, t('calendar.alarm.removed'))
</script>

<template>
  <div class="cal-pane">
    <button v-if="back" type="button" class="ghost sm back" @click="emit('back')"><Icon name="back" />{{ back }}</button>
    <div class="cal-pane-head">
      <div class="grow stack" style="gap: 8px">
        <div class="row" style="gap: 6px; flex-wrap: wrap">
          <span class="ev-kind" :class="family(x)"><Icon :name="GLYPH[x.kind] || 'info'" />{{ kindName(x) }}</span>
          <span class="tag" :class="statusTone(st)">{{ statusName(x, now) }}</span>
          <span v-if="x.priority" class="tag warn"><Icon name="star" class="star" />{{ $t('calendar.priorityEmployer') }}</span>
        </div>
        <div>
          <h3>{{ titleOf(x) }}</h3>
          <div v-if="companyOf(x)" class="sub">{{ companyOf(x) }}</div>
        </div>
      </div>
      <button type="button" class="ghost close" :aria-label="$t('common.close')" @click="emit('close')"><Icon name="x" /></button>
    </div>

    <dl class="cal-fields">
      <template v-if="x.kind === 'deadline'">
        <dt>{{ $t('calendar.field.deadline') }}</dt>
        <dd>{{ when }}<span v-if="left && left.text" class="muted"> · {{ left.text }}</span></dd>
        <template v-if="x.state"><dt>{{ $t('calendar.state.label') }}</dt><dd>{{ $t('calendar.state.' + x.state) }}</dd></template>
        <template v-if="scoreOf(x)"><dt>{{ $t('calendar.field.score') }}</dt><dd>{{ scoreOf(x) }}</dd></template>
      </template>
      <template v-else>
        <dt>{{ $t('calendar.field.when') }}</dt><dd>{{ when }}</dd>
        <template v-if="x.due_text"><dt>{{ $t('calendar.field.mail') }}</dt><dd>{{ x.due_text }}</dd></template>
        <template v-if="x.due_zone && said"><dt>{{ $t('calendar.field.zone') }}</dt><dd>{{ $t('calendar.zoneFrom', { time: said, zone: x.due_zone }) }}</dd></template>
        <template v-if="!x.all_day && zone"><dt>{{ $t('calendar.field.timezone') }}</dt><dd>{{ zone.name }}</dd></template>
        <template v-if="x.subject"><dt>{{ $t('calendar.field.posting') }}</dt><dd>{{ x.subject }}</dd></template>
        <template v-if="x.state"><dt>{{ $t('calendar.state.label') }}</dt><dd>{{ $t('calendar.state.' + x.state) }}</dd></template>
      </template>
      <template v-if="x.note"><dt>{{ $t('calendar.field.note') }}</dt><dd class="pre">{{ x.note }}</dd></template>
      <template v-if="x.link"><dt>{{ $t('calendar.field.link') }}</dt><dd><a :href="x.link" target="_blank" rel="noopener" class="clamp2">{{ x.link }}</a></dd></template>
    </dl>
    <div v-if="x.zone_assumed && !x.all_day && !x.done" class="hint">{{ $t('calendar.zoneAssumed') }}</div>
    <div v-if="zone && zone.other && !x.all_day" class="hint">{{ zone.other }}</div>

    <div class="cal-acts">
      <template v-if="x.kind === 'deadline'">
        <button v-if="x.state === 'unapplied' && st === 'open'" type="button" class="primary" @click="startApplication">{{ $t('calendar.start') }}</button>
        <router-link :to="{ path: '/jobs', query: { open: x.about.job_id } }" class="btn">{{ $t('calendar.openPosting') }}</router-link>
        <a v-if="x.link" :href="x.link" target="_blank" rel="noopener" class="btn"><Icon name="external" />{{ $t('calendar.openSource') }}</a>
        <button v-if="x.state === 'unapplied'" type="button" class="ghost" @click="notApplying">{{ $t('calendar.notApplying') }}</button>
      </template>
      <template v-else>
        <a v-if="x.link" :href="x.link" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />{{ $t('calendar.openLink') }}</a>
        <template v-if="isCard">
          <button v-if="!x.done" type="button" @click="done"><Icon name="check" />{{ $t('calendar.done') }}</button>
          <button type="button" @click="dueEdit = x.start.slice(0, 16)"><Icon name="clock" />{{ $t('calendar.move') }}</button>
          <button type="button" @click="linkEdit = x.link || ''"><Icon name="link" />{{ x.link ? $t('calendar.linkChange') : $t('calendar.linkAdd') }}</button>
          <button v-if="x.kind === 'own'" type="button" class="ghost danger" @click="remove"><Icon name="trash" />{{ $t('calendar.remove') }}</button>
        </template>
      </template>
      <router-link v-if="x.about.application_id" :to="`/applications/${x.about.application_id}`" class="btn">{{ $t('calendar.openApplication') }}</router-link>
      <router-link v-if="x.about.contact_id" to="/contacts" class="btn">{{ $t('calendar.openContacts') }}</router-link>
    </div>
    <div v-if="dueEdit !== null" class="cal-edit">
      <input v-model="dueEdit" type="datetime-local" :aria-label="$t('calendar.move')" />
      <button type="button" class="primary sm" @click="saveDue">{{ $t('calendar.save') }}</button><button type="button" class="ghost sm" @click="dueEdit = null">{{ $t('calendar.cancel') }}</button>
    </div>
    <div v-if="linkEdit !== null" class="cal-edit">
      <input v-model="linkEdit" placeholder="https://" :aria-label="$t('calendar.field.link')" />
      <button type="button" class="primary sm" @click="saveLink(linkEdit)">{{ $t('calendar.save') }}</button><button type="button" class="ghost sm" @click="linkEdit = null">{{ $t('calendar.cancel') }}</button>
    </div>
    <div v-if="isCard && mailLinks.length" class="cal-sec">
      <div class="cal-sec-title">{{ $t('calendar.links.fromMail') }}</div>
      <div v-for="l in mailLinks" :key="l.url" class="row small" style="gap: 8px; margin-top: 4px">
        <span class="grow clamp2">{{ l.what || l.url }} <span class="muted">{{ l.what ? l.url : '' }}</span></span>
        <button type="button" class="sm" @click="saveLink(l.url)">{{ $t('calendar.links.use') }}</button>
      </div>
    </div>

    <div v-if="alarms" class="cal-sec">
      <div class="cal-sec-title">{{ $t('calendar.alarm.title') }}</div>
      <div v-if="!alarms.length" class="small muted">{{ $t('calendar.alarm.none') }}</div>
      <div class="row" style="flex-wrap: wrap; gap: 6px">
        <span v-for="a in alarms" :key="a.id" class="fchip lg" :class="{ ok: a.sent }">{{ ahead(a.before, x.all_day) }}<button type="button" v-tip="$t('calendar.alarm.remove')" :aria-label="$t('calendar.alarm.remove')" @click="removeAlarm(a)"><Icon name="x" /></button></span>
      </div>
      <div class="row" style="flex-wrap: wrap; gap: 6px; margin-top: 8px">
        <button v-for="c in choices.filter((c) => !x.all_day || c % 1440 === 0 || c === 0)" :key="c" type="button" class="sm chip" :disabled="alarms.some((a) => a.before === c)" @click="addAlarm(c)">+ {{ ahead(c, x.all_day) }}</button>
        <span class="nowrap small"><input v-model.number="custom" type="number" min="0" style="width: 72px" :aria-label="$t('calendar.alarm.customLabel')" /> {{ $t('calendar.alarm.customUnit') }}
          <button type="button" class="sm" :disabled="!(custom >= 0) || custom === ''" @click="addAlarm(custom); custom = ''">{{ $t('calendar.alarm.add') }}</button></span>
      </div>
      <div class="hint" style="margin-top: 6px">{{ x.all_day ? $t('calendar.alarm.hintAllDay') : $t('calendar.alarm.hint') }}</div>
    </div>
  </div>
</template>

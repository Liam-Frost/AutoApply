<script setup>
// The calendar: everything with a time, by month (the default), week or day (server: agenda.py). The page draws its
// own grid - no calendar library - so it looks like the rest of the program. What is shown (the view, the day, the
// filters) is in the address: it can be bookmarked, and a notification can lead to it.
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import { t, tag } from '../i18n/catalog'
import { clockOf, dateOf, weekStart } from '../i18n/format'
import { ask, run, toast } from '../ui'

const route = useRoute()
const router = useRouter()
const KINDS = ['deadline', 'interview', 'assessment', 'offer', 'info_request', 'contact', 'own', 'snoozed', 'sent', 'reply', 'task']
const SHOWN = ['deadline', 'interview', 'assessment', 'offer', 'info_request', 'contact', 'own']
const STATES = ['unapplied', 'in_progress', 'sent', 'progressed']
const TONE = { deadline: 'warn', interview: 'ok', assessment: 'info', offer: 'ok', info_request: 'warn', contact: '', own: 'info', snoozed: '', sent: '', reply: '', task: '' }

// --- what is shown: from the address -------------------------------------------------------------------------------
const pad = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const parseDay = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ''); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null }
const today = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()) }
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)

const view = computed(() => (['month', 'week', 'day'].includes(route.query.view) ? route.query.view : 'month'))
const day = computed(() => parseDay(route.query.date) || today())
const kinds = computed(() => (route.query.kinds ? String(route.query.kinds).split(',').filter((k) => KINDS.includes(k)) : SHOWN))
const f = ref({ state: route.query.state || '', company: route.query.company || '', prio: route.query.prio === '1', min: +route.query.min || 0, all: route.query.all === '1' })
const go = (q) => router.replace({ query: { ...route.query, ...q } })
const setView = (v) => go({ view: v })
const setDay = (d) => go({ date: iso(d) })
const toggleKind = (k) => { const s = new Set(kinds.value); s.has(k) ? s.delete(k) : s.add(k); go({ kinds: [...s].join(',') || 'none' }) }
watch(f, (v) => go({ state: v.state || undefined, company: v.company || undefined, prio: v.prio ? '1' : undefined, min: v.min || undefined, all: v.all ? '1' : undefined }), { deep: true })

// the days on the page: a month as whole weeks from the language's first day of the week; a week; a day
const first = computed(() => weekStart() % 7)       // 0 Sunday ... 6 Saturday
const startOfWeek = (d) => addDays(d, -((d.getDay() - first.value + 7) % 7))
const range = computed(() => {
  const d = day.value
  if (view.value === 'day') return [d, addDays(d, 1)]
  if (view.value === 'week') { const s = startOfWeek(d); return [s, addDays(s, 7)] }
  const next = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  return [startOfWeek(new Date(d.getFullYear(), d.getMonth(), 1)), next.getDay() === first.value ? next : addDays(startOfWeek(next), 7)]
})
const days = computed(() => { const out = []; for (let d = range.value[0]; d < range.value[1]; d = addDays(d, 1)) out.push(d); return out })
const weekdays = computed(() => days.value.slice(0, 7).map((d) => new Intl.DateTimeFormat(tag(), { weekday: 'short' }).format(d)))
const title = computed(() => {
  const d = day.value
  if (view.value === 'month') return new Intl.DateTimeFormat(tag(), { year: 'numeric', month: 'long' }).format(d)
  if (view.value === 'week') return new Intl.DateTimeFormat(tag(), { month: 'short', day: 'numeric' }).formatRange(range.value[0], addDays(range.value[1], -1))
  return new Intl.DateTimeFormat(tag(), { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).format(d)
})
const step = (n) => {
  const d = day.value
  setDay(view.value === 'month' ? new Date(d.getFullYear(), d.getMonth() + n, 1) : addDays(d, n * (view.value === 'week' ? 7 : 1)))
}

// --- the items ----------------------------------------------------------------------------------------------------
const items = ref([])
const { st, load } = dataState(async () => {
  const q = new URLSearchParams({ start: iso(range.value[0]), end: iso(range.value[1]), kinds: kinds.value.join(','), states: f.value.state, company: f.value.company,
    priority: f.value.prio ? 'true' : 'false', min_score: String(f.value.min || 0), all_deadlines: f.value.all ? 'true' : 'false' })
  items.value = (await api.get('/calendar?' + q)).items
})
watch(() => route.fullPath, () => load(), { immediate: true })
useRefresh(load)
const on = (d) => items.value.filter((x) => x.start.slice(0, 10) === iso(d))
const isToday = (d) => iso(d) === iso(today())
const label = (x) => t('calendar.kind.' + x.kind)
const timeOf = (x) => (x.all_day ? t('calendar.allDay') : clockOf(new Date(x.start)))
// a month cell: deadlines as one count (a day can have a dozen), up to three other items, and how many more
const MAX = 3
const cell = (d) => {
  const all = on(d)
  const dl = all.filter((x) => x.kind === 'deadline')
  const rest = all.filter((x) => x.kind !== 'deadline')
  return { deadlines: dl.length, shown: rest.slice(0, MAX), more: Math.max(0, rest.length - MAX) }
}
const openDay = (d) => go({ view: 'day', date: iso(d) })
// on a day: the most pressing first - what has a time and is not done, then whole-day things, then what is done
const dayList = computed(() => on(day.value).slice().sort((a, b) => (a.done - b.done) || (a.kind === 'deadline') - (b.kind === 'deadline') || a.start.localeCompare(b.start)))
const timed = computed(() => dayList.value.filter((x) => !x.all_day))

// --- one item -----------------------------------------------------------------------------------------------------
const sel = ref(null)
const linkEdit = ref(null)
const dueEdit = ref(null)
const after = () => { sel.value = null; load() }
const done = (x) => run(() => api.post(`/todos/${x.about.todo_id}/done`, {}), t('calendar.doneMsg'), after)
const saveDue = (x) => run(() => api.post(`/todos/${x.about.todo_id}/due`, { due: dueEdit.value }), t('calendar.movedMsg'), () => { dueEdit.value = null; after() })
const saveLink = (x) => run(() => api.post(`/calendar/items/${x.about.todo_id}/link`, { link: linkEdit.value }), t('calendar.linkSaved'), () => { linkEdit.value = null; after() })
const startApplication = (x) => run(() => api.post(`/jobs/${x.about.job_id}/draft`, {}), t('calendar.started'), after)
const notApplying = (x) => run(() => api.patch(`/jobs/${x.about.job_id}`, { status: 'skipped' }), t('calendar.skipped'), after)

// --- an item of the applicant's own ---------------------------------------------------------------------------------
const draft = ref(null)
const newItem = (d) => { draft.value = { title: '', day: iso(d || day.value), time: '', link: '', note: '' } }
const saveNew = () => run(() => api.post('/calendar/items', draft.value), t('calendar.added'), () => { draft.value = null; load() })

// --- the reminders of an item (alarms.py): "this long before", as many as wanted -------------------------------------
const itemKey = (x) => (x.about.todo_id && x.id.startsWith('todo:') ? x.id : x.kind === 'deadline' ? x.id : '')
const alarms = ref(null)
const choices = ref([])
const custom = ref('')
watch(sel, async (x) => {
  alarms.value = null
  if (!x || !itemKey(x)) return
  const r = await api.get('/calendar/alarms?item=' + encodeURIComponent(itemKey(x)))
  alarms.value = r.alarms
  choices.value = r.choices
})
// "30 minutes before", "1 day before" - for a whole-day item, the morning of that many days before
function ahead(before, allDay) {
  if (allDay || before % 1440 === 0) { const d = Math.ceil(before / 1440); return d === 0 ? t('calendar.alarm.sameDay') : t('calendar.alarm.days', { n: d }, d) }
  if (before % 60 === 0) return t('calendar.alarm.hours', { n: before / 60 }, before / 60)
  return t('calendar.alarm.minutes', { n: before }, before)
}
const addAlarm = (before) => run(async () => { alarms.value = (await api.post('/calendar/alarms', { item: itemKey(sel.value), before: Number(before) })).alarms }, t('calendar.alarm.added'))
const removeAlarm = (a) => run(async () => { await api.del(`/calendar/alarms/${a.id}`); alarms.value = alarms.value.filter((x) => x.id !== a.id) }, t('calendar.alarm.removed'))

// --- the calendar as a file, and the address to subscribe to (ics.py) -------------------------------------------------
const share = ref(null)
const exportUrl = computed(() => 'api/calendar/export.ics?' + new URLSearchParams({ start: iso(range.value[0]), end: iso(range.value[1]), kinds: kinds.value.join(','),
  states: f.value.state, company: f.value.company, priority: f.value.prio ? 'true' : 'false', min_score: String(f.value.min || 0), all_deadlines: f.value.all ? 'true' : 'false' }))
const openShare = async () => { share.value = await api.get('/calendar/feed') }
const copyFeed = async () => { try { await navigator.clipboard.writeText(share.value.url); toast(t('calendar.share.copied')) } catch (e) { toast(t('calendar.share.copyFailed'), 'bad') } }
const renew = async () => { if (await ask(t('calendar.share.renewAsk'), { ok: t('calendar.share.renew'), danger: true })) run(async () => { share.value = await api.post('/calendar/feed/renew') }, t('calendar.share.renewed')) }
</script>

<template>
  <PageHead :title="$t('calendar.title')" :sub="$t('calendar.sub')">
    <button @click="openShare"><Icon name="clock" />{{ $t('calendar.share.button') }}</button>
    <button class="primary" @click="newItem()"><Icon name="edit" />{{ $t('calendar.add') }}</button>
  </PageHead>

  <div class="row cal-bar">
    <button class="ghost" :aria-label="$t('calendar.prev')" @click="step(-1)"><Icon name="back" /></button>
    <button @click="setDay(today())">{{ $t('calendar.today') }}</button>
    <button class="ghost" :aria-label="$t('calendar.next')" @click="step(1)"><Icon name="back" style="transform: rotate(180deg)" /></button>
    <h3 class="cal-title">{{ title }}</h3>
    <span class="grow"></span>
    <div class="seg">
      <button v-for="v in ['month', 'week', 'day']" :key="v" :class="{ on: view === v }" @click="setView(v)">{{ $t('calendar.view.' + v) }}</button>
    </div>
  </div>

  <div class="filters">
    <div class="cal-kinds">
      <button v-for="k in KINDS" :key="k" class="chip" :class="{ on: kinds.includes(k) }" :aria-pressed="kinds.includes(k)" @click="toggleKind(k)">{{ $t('calendar.kind.' + k) }}</button>
    </div>
    <AaSelect v-model="f.state" :aria-label="$t('calendar.state.label')">
      <option value="">{{ $t('calendar.state.any') }}</option>
      <option v-for="s in STATES" :key="s" :value="s">{{ $t('calendar.state.' + s) }}</option>
    </AaSelect>
    <input v-model.lazy="f.company" :placeholder="$t('calendar.company')" style="width: 160px" />
    <label class="muted nowrap"><input v-model="f.prio" type="checkbox" /> {{ $t('calendar.priority') }}</label>
    <label class="muted nowrap">{{ $t('calendar.minScore') }} <input v-model.number="f.min" type="number" min="0" max="10" step="0.5" style="width: 64px" /></label>
    <label class="muted nowrap"><input v-model="f.all" type="checkbox" /> {{ $t('calendar.allDeadlines') }}</label>
  </div>

  <DataState :s="st" :what="$t('calendar.title')" @retry="load" />

  <!-- month -->
  <div v-if="view === 'month'" class="cal-month">
    <div v-for="w in weekdays" :key="w" class="cal-wd">{{ w }}</div>
    <div v-for="d in days" :key="iso(d)" class="cal-cell" :class="{ out: d.getMonth() !== day.getMonth(), today: isToday(d) }" @click="openDay(d)">
      <div class="cal-num">{{ d.getDate() }}</div>
      <button v-if="cell(d).deadlines" class="cal-dl tag warn" @click.stop="openDay(d)">{{ $t('calendar.deadlines', { n: cell(d).deadlines }, cell(d).deadlines) }}</button>
      <button v-for="x in cell(d).shown" :key="x.id" class="cal-item" :class="[TONE[x.kind], { done: x.done }]" :title="x.subject || x.title" @click.stop="sel = x">
        <span v-if="!x.all_day" class="muted">{{ clockOf(new Date(x.start)) }}</span> {{ x.company || x.title }}
      </button>
      <div v-if="cell(d).more" class="small muted">{{ $t('calendar.more', { n: cell(d).more }) }}</div>
    </div>
  </div>

  <!-- week -->
  <div v-else-if="view === 'week'" class="cal-week">
    <div v-for="d in days" :key="iso(d)" class="cal-col" :class="{ today: isToday(d) }">
      <button class="cal-head" @click="openDay(d)">{{ new Intl.DateTimeFormat(tag(), { weekday: 'short', month: 'numeric', day: 'numeric' }).format(d) }}</button>
      <div class="cal-allday">
        <button v-for="x in on(d).filter((y) => y.all_day)" :key="x.id" class="cal-item" :class="[TONE[x.kind], { done: x.done }]" @click="sel = x">{{ x.company || x.title }}</button>
      </div>
      <button v-for="x in on(d).filter((y) => !y.all_day)" :key="x.id" class="cal-item" :class="[TONE[x.kind], { done: x.done }]" @click="sel = x">
        <span class="muted">{{ clockOf(new Date(x.start)) }}</span> {{ x.company || x.title }}<div class="small muted">{{ label(x) }}</div>
      </button>
      <button class="ghost sm cal-add" :aria-label="$t('calendar.addOn', { day: dateOf(d) })" @click="newItem(d)">+</button>
    </div>
  </div>

  <!-- day -->
  <div v-else class="an-row c11">
    <div class="card">
      <div class="card-title">{{ $t('calendar.timeline') }}</div>
      <div v-if="!timed.length" class="small muted">{{ $t('calendar.nothingTimed') }}</div>
      <div v-for="x in timed" :key="x.id" class="cal-tl" @click="sel = x"><span class="cal-tl-at">{{ clockOf(new Date(x.start)) }}</span><span class="tag" :class="TONE[x.kind]">{{ label(x) }}</span> {{ x.subject || x.title }}</div>
    </div>
    <div class="card">
      <div class="row"><span class="card-title grow">{{ $t('calendar.list') }}</span><button class="sm" @click="newItem(day)">{{ $t('calendar.add') }}</button></div>
      <div v-if="!dayList.length" class="small muted">{{ $t('calendar.nothing') }}</div>
      <div v-for="x in dayList" :key="x.id" class="item cal-row" :class="{ done: x.done }">
        <div class="grow" style="cursor: pointer" @click="sel = x">
          <div><span class="tag" :class="TONE[x.kind]">{{ label(x) }}</span> <b>{{ x.title }}</b></div>
          <div class="small muted">{{ timeOf(x) }}<template v-if="x.subject"> · {{ x.subject }}</template></div>
        </div>
        <a v-if="x.link" :href="x.link" target="_blank" rel="noopener" class="btn sm"><Icon name="external" />{{ $t('calendar.open') }}</a>
        <button v-if="x.about.todo_id && !x.done && !['snoozed'].includes(x.kind)" class="sm" @click="done(x)">{{ $t('calendar.done') }}</button>
      </div>
    </div>
  </div>

  <SideDrawer v-if="sel" :title="sel.title" :sub="`${label(sel)} · ${timeOf(sel)} · ${dateOf(new Date(sel.start))}`" :wide="false" @close="sel = null; linkEdit = null; dueEdit = null">
    <div class="stack">
      <div v-if="sel.subject" class="small">{{ sel.subject }}</div>
      <p v-if="sel.note" class="small" style="white-space: pre-line">{{ sel.note }}</p>
      <div v-if="sel.link" class="row"><a :href="sel.link" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />{{ $t('calendar.open') }}</a><span class="small muted clamp2">{{ sel.link }}</span></div>
      <div class="row" style="flex-wrap: wrap; gap: 8px">
        <template v-if="sel.about.todo_id && !['snoozed'].includes(sel.kind)">
          <button v-if="!sel.done" @click="done(sel)"><Icon name="check" />{{ $t('calendar.done') }}</button>
          <button @click="dueEdit = sel.start.slice(0, 16)"><Icon name="edit" />{{ $t('calendar.move') }}</button>
          <button @click="linkEdit = sel.link || ''"><Icon name="link" />{{ sel.link ? $t('calendar.linkChange') : $t('calendar.linkAdd') }}</button>
        </template>
        <template v-if="sel.kind === 'deadline'">
          <router-link :to="{ path: '/jobs', query: { open: sel.about.job_id } }" class="btn">{{ $t('calendar.openPosting') }}</router-link>
          <button v-if="sel.state === 'unapplied'" class="primary" @click="startApplication(sel)">{{ $t('calendar.start') }}</button>
          <button v-if="sel.state === 'unapplied'" @click="notApplying(sel)">{{ $t('calendar.notApplying') }}</button>
        </template>
        <router-link v-if="sel.about.application_id" :to="`/applications/${sel.about.application_id}`" class="btn">{{ $t('calendar.openApplication') }}</router-link>
        <router-link v-if="sel.about.contact_id" to="/contacts" class="btn">{{ $t('calendar.openContacts') }}</router-link>
      </div>
      <div v-if="dueEdit !== null" class="row"><input v-model="dueEdit" type="datetime-local" /><button class="primary" @click="saveDue(sel)">{{ $t('calendar.save') }}</button><button class="ghost" @click="dueEdit = null">{{ $t('calendar.cancel') }}</button></div>
      <div v-if="linkEdit !== null" class="row"><input v-model="linkEdit" placeholder="https://" style="flex: 1" /><button class="primary" @click="saveLink(sel)">{{ $t('calendar.save') }}</button><button class="ghost" @click="linkEdit = null">{{ $t('calendar.cancel') }}</button></div>
      <div v-if="alarms" class="card" style="margin: 4px 0 0">
        <div class="card-title">{{ $t('calendar.alarm.title') }}</div>
        <div v-if="!alarms.length" class="small muted">{{ $t('calendar.alarm.none') }}</div>
        <div class="row" style="flex-wrap: wrap; gap: 6px">
          <span v-for="a in alarms" :key="a.id" class="tag" :class="{ ok: a.sent }">{{ ahead(a.before, sel.all_day) }}<button class="ghost sm" style="padding: 0 4px; min-height: 0" :aria-label="$t('calendar.alarm.remove')" @click="removeAlarm(a)">×</button></span>
        </div>
        <div class="row" style="flex-wrap: wrap; gap: 6px; margin-top: 8px">
          <button v-for="c in choices.filter((c) => !sel.all_day || c % 1440 === 0 || c === 0)" :key="c" class="sm chip" :disabled="alarms.some((a) => a.before === c)" @click="addAlarm(c)">+ {{ ahead(c, sel.all_day) }}</button>
          <span class="nowrap small"><input v-model.number="custom" type="number" min="0" style="width: 72px" :aria-label="$t('calendar.alarm.customLabel')" /> {{ $t('calendar.alarm.customUnit') }}
            <button class="sm" :disabled="!(custom >= 0) || custom === ''" @click="addAlarm(custom); custom = ''">{{ $t('calendar.alarm.add') }}</button></span>
        </div>
        <div class="hint" style="margin-top: 6px">{{ sel.all_day ? $t('calendar.alarm.hintAllDay') : $t('calendar.alarm.hint') }}</div>
      </div>
    </div>
  </SideDrawer>

  <SideDrawer v-if="share" :title="$t('calendar.share.title')" :wide="false" @close="share = null">
    <div class="stack">
      <div class="card-title">{{ $t('calendar.share.exportTitle') }}</div>
      <p class="small muted">{{ $t('calendar.share.exportText') }}</p>
      <div><a class="btn" :href="exportUrl" download><Icon name="clock" />{{ $t('calendar.share.export') }}</a></div>
      <div class="card-title" style="margin-top: 12px">{{ $t('calendar.share.subscribeTitle') }}</div>
      <p class="small muted">{{ $t('calendar.share.subscribeText') }}</p>
      <div class="row"><input :value="share.url" readonly style="flex: 1" @focus="$event.target.select()" /><button @click="copyFeed">{{ $t('calendar.share.copy') }}</button></div>
      <p class="hint">{{ share.local_only ? $t('calendar.share.localOnly') : $t('calendar.share.reachable') }}</p>
      <div><button class="ghost sm danger" @click="renew">{{ $t('calendar.share.renew') }}</button></div>
    </div>
  </SideDrawer>

  <SideDrawer v-if="draft" :title="$t('calendar.add')" :wide="false" @close="draft = null">
    <div class="kv">
      <label for="c-title">{{ $t('calendar.form.title') }}</label><input id="c-title" v-model="draft.title" v-focus :placeholder="$t('calendar.form.titleHint')" />
      <label for="c-day">{{ $t('calendar.form.day') }}</label><input id="c-day" v-model="draft.day" type="date" />
      <label for="c-time">{{ $t('calendar.form.time') }}</label><div><input id="c-time" v-model="draft.time" type="time" /><div class="hint">{{ $t('calendar.form.timeHint') }}</div></div>
      <label for="c-link">{{ $t('calendar.form.link') }}</label><input id="c-link" v-model="draft.link" placeholder="https://" />
      <label for="c-note">{{ $t('calendar.form.note') }}</label><textarea id="c-note" v-model="draft.note" rows="3"></textarea>
    </div>
    <div class="row" style="margin-top: 12px"><button class="primary" :disabled="!draft.title.trim() || !draft.day" @click="saveNew">{{ $t('calendar.save') }}</button><button class="ghost" @click="draft = null">{{ $t('calendar.cancel') }}</button></div>
  </SideDrawer>
</template>

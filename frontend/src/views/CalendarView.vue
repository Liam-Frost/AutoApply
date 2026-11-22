<script setup>
// The calendar of a job search: everything with a time, in three views with three jobs - the month to plan (what is
// coming, where it bunches), the week to schedule (which hours are taken), the day to do (what to handle, one thing at
// a time). The items are the program's own data (agenda.py); calendar.js says where each stands, how much it matters
// and how a day is laid out; views/calendar/ draws them. The page draws its own grid - no calendar library.
//
// One state for the three views, in the address (it can be bookmarked; a notification can lead to it): the view, the
// date (the day chosen - its week, its month), the filters, the search and the item open. Changing the view keeps
// the date; "Today" goes back to today. The month's whole weeks are read once and serve the week and the day too.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import SideDrawer from '../components/SideDrawer.vue'
import DataState from '../components/DataState.vue'
import MonthView from './calendar/MonthView.vue'
import WeekView from './calendar/WeekView.vue'
import DayView from './calendar/DayView.vue'
import EventDetail from './calendar/EventDetail.vue'
import ListPanel from './calendar/ListPanel.vue'
import FilterMenu from './calendar/FilterMenu.vue'
import CalPanel from './calendar/CalPanel.vue'
import { dataState, useRefresh } from '../data'
import { t, tag } from '../i18n/catalog'
import { num, weekStart } from '../i18n/format'
import { addDays, addMonths, dayKey, daysOf, iso, KINDS, matches, monthGrid, parseDay, pressQuick, QUICK, quickState, RECORDS, SHOWN, startOfDay, status, summary, weekOf } from '../calendar'
import { longDate, longDay } from './calendar/look'
import { ask, run, toast } from '../ui'

const route = useRoute()
const router = useRouter()
const now = ref(new Date())
let clock = null

// --- what is shown: from the address ------------------------------------------------------------------------------------
const view = computed(() => (['month', 'week', 'day'].includes(route.query.view) ? route.query.view : 'month'))
const date = computed(() => parseDay(String(route.query.date || '')) || startOfDay(now.value))
const kinds = computed(() => {
  const k = route.query.kinds
  if (k === undefined) return [...SHOWN]
  return k === 'none' ? [] : String(k).split(',').filter((x) => KINDS.includes(x))
})
const f = computed(() => ({ state: String(route.query.state || ''), company: String(route.query.company || ''), prio: route.query.prio === '1',
  min: Number(route.query.min) || 0, all: route.query.all === '1', hideDone: route.query.done === '0' }))
const go = (patch) => router.replace({ query: Object.fromEntries(Object.entries({ ...route.query, ...patch }).filter(([, v]) => v !== undefined && v !== '')) })
const same = (a, b) => a.length === b.length && a.every((x) => b.includes(x))
const setKinds = (k) => go({ kinds: same(k, SHOWN) ? undefined : k.length ? k.join(',') : 'none' })
const setF = (patch) => {
  const v = { ...f.value, ...patch }
  go({ state: v.state || undefined, company: v.company || undefined, prio: v.prio ? '1' : undefined, min: v.min || undefined, all: v.all ? '1' : undefined, done: v.hideDone ? '0' : undefined })
}
const setView = (v) => go({ view: v === 'month' ? undefined : v })
const setDate = (d) => go({ date: iso(d) === iso(now.value) ? undefined : iso(d) })
const toToday = () => setDate(startOfDay(now.value))
const step = (n) => setDate(view.value === 'month' ? addMonths(date.value, n) : addDays(date.value, n * (view.value === 'week' ? 7 : 1)))
const openDayView = (d) => go({ view: 'day', date: iso(d) === iso(now.value) ? undefined : iso(d) })

// the days on the page: the month as whole weeks from the language's first day of the week; its week; the day
const first = computed(() => weekStart() % 7)
const range = computed(() => monthGrid(date.value, first.value))
const monthDays = computed(() => daysOf(range.value))
const weekDays = computed(() => { const s = weekOf(date.value, first.value); return daysOf([s, addDays(s, 7)]) })
const title = computed(() => {
  const d = date.value
  if (view.value === 'month') return new Intl.DateTimeFormat(tag(), { year: 'numeric', month: 'long' }).format(d)
  if (view.value === 'week') return new Intl.DateTimeFormat(tag(), { year: 'numeric', month: 'short', day: 'numeric' }).formatRange(weekDays.value[0], weekDays.value[6])
  return longDate(d)
})
const picker = ref(null)
const pick = () => { const el = picker.value; if (!el) return; try { el.showPicker() } catch (e) { el.focus(); el.click() } }
const picked = (e) => { const d = parseDay(e.target.value); if (d) setDate(d) }

// --- the search: typed here, kept in the address ----------------------------------------------------------------------
const search = ref(String(route.query.q || ''))
const searching = ref(!!search.value)
const findBox = ref(null)
let typing = null
watch(search, (v) => { clearTimeout(typing); typing = setTimeout(() => go({ q: v.trim() || undefined }), 200) })
const openSearch = async () => { searching.value = true; await nextTick(); findBox.value?.focus() }
const closeSearch = () => { if (!search.value) searching.value = false }
const clearSearch = () => { search.value = ''; searching.value = false }

// --- the items ------------------------------------------------------------------------------------------------------------
const items = ref([])
const serverOffset = ref(null)
const fetchKey = computed(() => [iso(range.value[0]), iso(range.value[1]), kinds.value.join(','), f.value.state, f.value.company, f.value.prio, f.value.min, f.value.all].join('|'))
const query = (start, end, k, g) => new URLSearchParams({ start: iso(start), end: iso(end), kinds: k.join(','), states: g.state, company: g.company,
  priority: g.prio ? 'true' : 'false', min_score: String(g.min || 0), all_deadlines: g.all ? 'true' : 'false' })
const { st, load } = dataState(async () => {
  const key = fetchKey.value
  if (!kinds.value.length) { items.value = []; return }
  const r = await api.get('/calendar?' + query(range.value[0], range.value[1], kinds.value, f.value))
  if (key !== fetchKey.value) return          // (overtaken by another month or filter)
  items.value = r.items
  serverOffset.value = r.utc_offset
})
watch(fetchKey, () => load(), { immediate: true })
// what the views show: the search and "completed items" are applied here, to what was read
const shown = computed(() => items.value.filter((x) => matches(x, route.query.q) && !(f.value.hideDone && x.done)))
const onDay = (d) => shown.value.filter((x) => dayKey(x) === iso(d))

// The line above the calendar: the days around today as they are, whatever the filters (it says what is coming, not
// what is shown). The same items fill the list each number opens - what is counted is what is listed.
const near = ref([])
const SUMMARY_SHOWN = 'calendar.summary'
const showSummary = ref(true)
try { showSummary.value = localStorage.getItem(SUMMARY_SHOWN) !== '0' } catch (e) { /* (no storage: shown) */ }
const setSummary = (v) => { showSummary.value = v; try { localStorage.setItem(SUMMARY_SHOWN, v ? '1' : '0') } catch (e) { /* kept for this visit */ } }
async function loadNear() {
  const today = startOfDay(new Date())
  try { near.value = (await api.get('/calendar?' + query(addDays(today, -14), addDays(today, 7), SHOWN, { state: '', company: '', prio: false, min: 0, all: false }))).items } catch (e) { /* the line waits for the next read */ }
}
loadNear()
const sum = computed(() => summary(near.value, now.value))
const refresh = () => { load(); loadNear() }
useRefresh(refresh)

// --- the time: this computer's, unless the page is open somewhere else ----------------------------------------------------
const offsetText = (m) => { const s = m < 0 ? '−' : '+'; const a = Math.abs(m); return `UTC${s}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}` }
const zone = computed(() => {
  const here = -new Date().getTimezoneOffset()
  let name = ''
  try { name = Intl.DateTimeFormat().resolvedOptions().timeZone || '' } catch (e) { /* (an older browser) */ }
  const other = serverOffset.value !== null && serverOffset.value !== here ? t('calendar.tzOther', { there: offsetText(serverOffset.value), here: offsetText(here) }) : ''
  return { name: t('calendar.tzName', { zone: other ? offsetText(serverOffset.value) : name || offsetText(here), offset: offsetText(other ? serverOffset.value : here) }), other }
})

// --- the quick filters and the full filter ----------------------------------------------------------------------------
const quickAll = computed(() => SHOWN.every((k) => kinds.value.includes(k)))
const pressAll = () => setKinds([...SHOWN, ...kinds.value.filter((k) => RECORDS.includes(k))])
const press = (g) => setKinds(pressQuick(kinds.value, g))
const chips = computed(() => {
  const v = f.value
  const out = []
  if (v.state) out.push({ id: 'state', label: t('calendar.filter.chipState', { what: t('calendar.state.' + v.state) }), clear: () => setF({ state: '' }) })
  if (v.company) out.push({ id: 'company', label: t('calendar.filter.chipCompany', { what: v.company }), clear: () => setF({ company: '' }) })
  if (v.min) out.push({ id: 'min', label: t('calendar.filter.chipScore', { n: num(v.min) }), clear: () => setF({ min: 0 }) })
  if (v.prio) out.push({ id: 'prio', label: t('calendar.priority'), clear: () => setF({ prio: false }) })
  if (v.all) out.push({ id: 'all', label: t('calendar.allDeadlines'), clear: () => setF({ all: false }) })
  if (v.hideDone) out.push({ id: 'done', label: t('calendar.filter.chipDoneHidden'), clear: () => setF({ hideDone: false }) })
  for (const k of RECORDS) if (kinds.value.includes(k)) out.push({ id: k, label: t('calendar.kind.' + k), clear: () => setKinds(kinds.value.filter((x) => x !== k)) })
  return out
})
const dirty = computed(() => chips.value.length > 0 || !same(kinds.value, SHOWN) || !!route.query.q)
const reset = () => { search.value = ''; searching.value = false; go({ kinds: undefined, state: undefined, company: undefined, prio: undefined, min: undefined, all: undefined, done: undefined, q: undefined }) }

// --- the panel: one item, or a list -------------------------------------------------------------------------------------
// { mode: 'item', item, back } | { mode: 'list', title, sub, items, day, all }
const panel = ref(null)
const openId = computed(() => (panel.value && panel.value.mode === 'item' ? panel.value.item.id : ''))
const openItem = (x, back = null) => { panel.value = { mode: 'item', item: x, back }; go({ item: x.id }) }
const closePanel = () => { panel.value = null; go({ item: undefined }) }
function dayList(d, only) {
  const all = onDay(d)
  const list = only ? all.filter((x) => x.kind === only) : all
  const counted = only === 'deadline' ? t('calendar.deadlines', { n: list.length }, list.length) : ''
  panel.value = { mode: 'list', title: longDay(d), sub: counted, items: list, day: d, all: all.length, only }
  go({ item: undefined })
}
function countList(key) {
  const today = iso(now.value)
  const end = iso(addDays(now.value, 7))
  const open = near.value.filter((x) => status(x, now.value) === 'open')
  const lists = {
    today: open.filter((x) => x.kind === 'deadline' && dayKey(x) === today),
    week: open.filter((x) => x.kind === 'deadline' && dayKey(x) >= today && dayKey(x) < end),
    interviews: open.filter((x) => x.kind === 'interview' && dayKey(x) < end),
    overdue: sum.value.overdue,
  }
  panel.value = { mode: 'list', title: t('calendar.summary.' + key), sub: t('calendar.summary.' + key + 'Hint'), items: lists[key], day: null, all: 0 }
  go({ item: undefined })
}
// from a list, an item opens in its place, with the way back to the list
const fromList = (x) => { const list = panel.value; openItem(x, list && list.mode === 'list' ? list : null) }
const backToList = () => { const b = panel.value && panel.value.back; if (b) { panel.value = b; go({ item: undefined }) } }
// after a change: the item as it is now (gone from what is shown: the panel closes), the list read again
watch([items, near], () => {
  const p = panel.value
  if (!p) {
    const id = route.query.item
    const x = id && (items.value.find((y) => y.id === id) || near.value.find((y) => y.id === id))
    if (x) panel.value = { mode: 'item', item: x, back: null }
    return
  }
  if (p.mode === 'item') {
    const x = items.value.find((y) => y.id === p.item.id) || near.value.find((y) => y.id === p.item.id)
    if (x) panel.value = { ...p, item: x }; else closePanel()
  } else if (p.day) dayList(p.day, p.only)
})
const changed = () => refresh()

// Beside the calendar when there is room for both (the day's list needs less than the month's seven columns). The
// calendar itself fills the window's height (style.css .cal-page): a day with many items never makes the page longer.
const body = ref(null)
const width = ref(1200)
const floating = computed(() => width.value < (view.value === 'day' ? 860 : 1180))
const measure = () => { if (body.value) width.value = body.value.clientWidth }
let watcher = null
onMounted(() => {
  watcher = new ResizeObserver(measure)
  watcher.observe(body.value)
  window.addEventListener('keydown', onKey)
  clock = setInterval(() => { now.value = new Date() }, 30000)
  measure()
})
onBeforeUnmount(() => { if (watcher) watcher.disconnect(); window.removeEventListener('keydown', onKey); clearInterval(clock); clearTimeout(typing) })

// --- keys: T today, ← → the steps, M W D the views, N a new item, / the search, Escape closes the panel beside -----------
function onKey(e) {
  const tag_ = (e.target && e.target.tagName) || ''
  if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(tag_) || (e.target && e.target.isContentEditable)) return
  const page = document.getElementById('app')
  if (page && page.inert) return             // (something is open over the page: the keys are its)
  const k = e.key
  if (k === 'Escape' && panel.value && !floating.value) { closePanel(); return }
  const act = { t: toToday, ArrowLeft: () => step(-1), ArrowRight: () => step(1), m: () => setView('month'), w: () => setView('week'), d: () => setView('day'), n: () => newItem(), '/': openSearch }[k.length === 1 ? k.toLowerCase() : k]
  if (act) { e.preventDefault(); act() }
}

// --- a new item of the applicant's own ------------------------------------------------------------------------------------
const draft = ref(null)
const newItem = (d, time = '') => { draft.value = { title: '', day: iso(d || date.value), time, link: '', note: '' } }
const saveNew = () => run(() => api.post('/calendar/items', draft.value), t('calendar.added'), () => { draft.value = null; refresh() })

// --- the calendar as a file, and the address to subscribe to (ics.py) -------------------------------------------------------
const share = ref(null)
const exportUrl = computed(() => 'api/calendar/export.ics?' + query(range.value[0], range.value[1], kinds.value.length ? kinds.value : SHOWN, f.value))
const openShare = async () => { share.value = await api.get('/calendar/feed') }
const copyFeed = async () => { try { await navigator.clipboard.writeText(share.value.url); toast(t('calendar.share.copied')) } catch (e) { toast(t('calendar.share.copyFailed'), 'bad') } }
const renew = async () => { if (await ask(t('calendar.share.renewAsk'), { ok: t('calendar.share.renew'), danger: true })) run(async () => { share.value = await api.post('/calendar/feed/renew') }, t('calendar.share.renewed')) }
</script>

<template>
  <div class="cal-page">
    <PageHead :title="$t('calendar.title')" :sub="$t('calendar.sub')">
      <button type="button" @click="openShare"><Icon name="download" />{{ $t('calendar.share.button') }}</button>
      <button type="button" class="primary" v-tip="$t('calendar.addKey')" @click="newItem()"><Icon name="plus" />{{ $t('calendar.add') }}</button>
    </PageHead>

    <div class="cal-toolbar">
      <button type="button" v-tip="$t('calendar.todayKey')" @click="toToday">{{ $t('calendar.today') }}</button>
      <span class="cal-steps">
        <button type="button" :aria-label="$t('calendar.prev')" v-tip="$t('calendar.prev')" @click="step(-1)"><Icon name="back" /></button>
        <button type="button" :aria-label="$t('calendar.next')" v-tip="$t('calendar.next')" @click="step(1)"><Icon name="forward" /></button>
      </span>
      <button type="button" class="cal-range" :aria-label="$t('calendar.pickDate')" v-tip="$t('calendar.pickDate')" @click="pick">
        <span>{{ title }}</span><Icon name="chevron" />
        <input ref="picker" type="date" tabindex="-1" aria-hidden="true" :value="iso(date)" @change="picked" />
      </button>
      <span class="grow"></span>
      <div class="seg" role="group" :aria-label="$t('calendar.viewLabel')">
        <button v-for="v in ['month', 'week', 'day']" :key="v" type="button" :class="{ on: view === v }" :aria-pressed="view === v" @click="setView(v)">{{ $t('calendar.view.' + v) }}</button>
      </div>
    </div>

    <div class="cal-filters">
      <div class="cal-quick" role="group" :aria-label="$t('calendar.filter.types')">
        <button type="button" class="qchip" :class="{ on: quickAll }" :aria-pressed="quickAll" @click="pressAll">{{ $t('calendar.quick.all') }}</button>
        <button v-for="g in QUICK" :key="g.id" type="button" class="qchip" :class="['ev-' + (g.id === 'todo' ? 'follow' : g.id), quickAll ? '' : quickState(kinds, g)]"
                :aria-pressed="!quickAll && quickState(kinds, g) === 'on'" v-tip="g.id === 'todo' ? $t('calendar.quick.todoHint') : $t('calendar.quick.hint')" @click="press(g)">
          <span class="dot" :class="{ on: quickState(kinds, g) !== 'off' }"></span>{{ $t('calendar.quick.' + g.id) }}
        </button>
      </div>
      <span class="grow"></span>
      <span class="cal-find">
        <input v-if="searching" ref="findBox" v-model="search" type="search" :placeholder="$t('calendar.searchHint')" :aria-label="$t('calendar.search')" @blur="closeSearch" @keydown.esc.stop="clearSearch" />
        <button v-else type="button" class="cal-tool ghost" @click="openSearch"><Icon name="search" />{{ $t('calendar.search') }}</button>
      </span>
      <FilterMenu :kinds="kinds" :f="f" :count="chips.length" :dirty="dirty" :summary="showSummary" @kinds="setKinds" @set="setF" @reset="reset" @summary="setSummary" />
    </div>

    <div v-if="chips.length" class="cal-active">
      <span v-for="c in chips" :key="c.id" class="fchip">{{ c.label }}<button type="button" :aria-label="$t('calendar.filter.remove', { what: c.label })" @click="c.clear()"><Icon name="x" /></button></span>
      <button type="button" class="ghost sm" @click="reset">{{ $t('calendar.filter.reset') }}</button>
    </div>

    <div v-if="showSummary" class="cal-sum" role="group" :aria-label="$t('calendar.summary.label')">
      <button type="button" :class="{ zero: !sum.today }" v-tip="$t('calendar.summary.todayHint')" @click="countList('today')">{{ $t('calendar.summary.today') }} <b>{{ num(sum.today) }}</b></button>
      <button type="button" :class="{ zero: !sum.week }" v-tip="$t('calendar.summary.weekHint')" @click="countList('week')">{{ $t('calendar.summary.week') }} <b>{{ num(sum.week) }}</b></button>
      <button type="button" :class="{ zero: !sum.interviews }" v-tip="$t('calendar.summary.interviewsHint')" @click="countList('interviews')">{{ $t('calendar.summary.interviews') }} <b>{{ num(sum.interviews) }}</b></button>
      <button type="button" :class="sum.overdue.length ? 'late' : 'zero'" v-tip="$t('calendar.summary.overdueHint')" @click="countList('overdue')">{{ $t('calendar.summary.overdue') }} <b>{{ num(sum.overdue.length) }}</b></button>
      <button type="button" class="cal-sum-hide" :aria-label="$t('calendar.summary.hide')" v-tip="$t('calendar.summary.hide')" @click="setSummary(false)"><Icon name="x" /></button>
    </div>
    <div v-if="zone.other" class="hint cal-tz">{{ zone.other }}</div>

    <DataState :s="st" :what="$t('calendar.title')" @retry="load" />
    <div ref="body" class="cal-body">
      <div class="cal-main">
        <div class="cal-frame">
          <div v-if="!kinds.length" class="cal-none" style="padding: 16px">{{ $t('calendar.filter.noKinds') }}</div>
          <MonthView v-else-if="view === 'month'" :days="monthDays" :month="date.getMonth()" :selected="date" :items="shown" :now="now" :open-id="openId"
                     @select="setDate" @open="openItem" @list="dayList" @create="newItem" @day="openDayView" />
          <WeekView v-else-if="view === 'week'" :days="weekDays" :selected="date" :items="shown" :now="now" :open-id="openId"
                    @open="openItem" @list="dayList" @create="newItem" @day="openDayView" />
          <DayView v-else :day="date" :items="onDay(date)" :now="now" :overdue="sum.overdue" :open-id="openId" @open="openItem" @create="newItem" />
        </div>
      </div>
      <CalPanel v-if="panel" :floating="floating" :label="panel.mode === 'item' ? $t('calendar.panelLabel') : panel.title" @close="closePanel">
        <EventDetail v-if="panel.mode === 'item'" :item="panel.item" :now="now" :zone="zone" :back="panel.back ? $t('calendar.backTo', { what: panel.back.title }) : ''"
                     @close="closePanel" @back="backToList" @changed="changed" />
        <ListPanel v-else :title="panel.title" :sub="panel.sub" :items="panel.items" :now="now" :day="panel.day" :all="panel.all" :open-id="openId"
                   @open="fromList" @close="closePanel" @day="openDayView" @all="dayList(panel.day, '')" />
      </CalPanel>
    </div>

    <SideDrawer v-if="share" :title="$t('calendar.share.title')" :wide="false" @close="share = null">
      <div class="stack">
        <div class="card-title">{{ $t('calendar.share.exportTitle') }}</div>
        <p class="small muted">{{ $t('calendar.share.exportText') }}</p>
        <div><a class="btn" :href="exportUrl" download><Icon name="download" />{{ $t('calendar.share.export') }}</a></div>
        <div class="card-title" style="margin-top: 12px">{{ $t('calendar.share.subscribeTitle') }}</div>
        <p class="small muted">{{ $t('calendar.share.subscribeText') }}</p>
        <div class="row"><input :value="share.url" readonly style="flex: 1" @focus="$event.target.select()" /><button type="button" @click="copyFeed">{{ $t('calendar.share.copy') }}</button></div>
        <p class="hint">{{ share.local_only ? $t('calendar.share.localOnly') : $t('calendar.share.reachable') }}</p>
        <div><button type="button" class="ghost sm danger" @click="renew">{{ $t('calendar.share.renew') }}</button></div>
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
      <div class="row" style="margin-top: 12px"><button type="button" class="primary" :disabled="!draft.title.trim() || !draft.day" @click="saveNew">{{ $t('calendar.save') }}</button><button type="button" class="ghost" @click="draft = null">{{ $t('calendar.cancel') }}</button></div>
    </SideDrawer>
  </div>
</template>

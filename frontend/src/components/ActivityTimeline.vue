<script setup>
import { t as T } from '../i18n/catalog'
// An application's story as a time line: the days it happened on, and for each event a node on one continuous line -
// its kind told by an icon and a quiet colour, the events that move the application on (a stage, an invitation, an
// assessment, an offer, a request for documents, a rejection) given more weight than mail that only confirms and the
// agent's own runs. What each event is comes from the record (the stage's key, the mail's category and what it says
// about it) - never guessed from words. An event with more to it opens in place.
import { computed, ref } from 'vue'
import { asDate, clockOf, dateOf } from '../i18n/format'
import Icon from './Icon.vue'

const props = defineProps({ events: { type: Array, required: true } })
const emit = defineEmits(['open-mail'])

// the mail's category -> icon, colour; whether it moves the application on
const MAIL = {
  interview: ['calendar', 'primary', true], assessment: ['clipboard', 'info', true], offer: ['star', 'ok', true],
  info_request: ['file', 'warn', true], rejection: ['x', 'bad', true], confirmation: ['check', 'ok', false], other: ['mail', '', false],
}
// the stage an application moved to -> colour
const STAGE = { rejected: 'bad', offer: 'ok', interview: 'primary', assessment: 'info', withdrawn: '', failed: 'bad', confirmed: 'ok', submitted: 'ok' }

function shape(e) {
  if (e.kind === 'mail') {
    const [icon, tone, strong] = MAIL[e.category] || MAIL.other
    const off = e.event === 'cancelled'      // (an interview called off: said by its label, drawn without colour)
    const title = MAIL[e.category] && e.category !== 'other' ? e.label : T('application.tl.otherMail')      // (a mail about nothing in particular: said as a mail)
    return { icon, tone: off ? '' : tone, strong: strong && !off, title, sub: e.summary || e.subject, more: !!(e.subject || e.summary || e.sender) }
  }
  if (e.kind === 'status') {
    const moved = e.old !== e.new
    const sub = [moved && e.from ? T('application.tl.fromStage', { from: e.old }) : '', e.by ? T('application.by', { who: e.by }) : '', moved ? e.note : ''].filter(Boolean).join(' · ')
    return { icon: 'branch', tone: STAGE[e.to] ?? '', strong: moved, title: moved ? T('application.tl.toStage', { to: e.new }) : (e.note || e.new), sub, more: false }
  }
  if (e.kind === 'checkin') {      // what the applicant said after an interview or an assessment
    const what = e.category === 'assessment' ? T('application.tl.assessment') : T('application.tl.interview')
    const felt = e.feeling ? T('todos.checkin.' + e.feeling) : ''
    return { icon: e.done ? 'check' : 'x', tone: e.done ? (e.feeling === 'bad' ? 'warn' : 'ok') : '', strong: e.done,
      title: e.done ? T('application.tl.checkedDone', { what }) : T('application.tl.checkedNot', { what }), sub: [felt, e.note].filter(Boolean).join(' · '), more: false }
  }
  if (e.kind === 'run') {
    return { icon: 'bot', tone: '', strong: false, title: `${e.what} · ${e.ok ? T('application.runDone') : T('application.runNotDone')}`, sub: e.said || '', more: !!e.said, off: !e.ok }
  }
  return { icon: 'dot', tone: '', strong: false, title: e.label || e.what || e.kind || '', sub: '', more: false }
}

// by the day they happened on (the applicant's), newest first
const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
function dayLabel(d) {
  const days = Math.round((midnight(new Date()) - midnight(d)) / 86400000)
  return days === 0 ? T('application.tl.today') : days === 1 ? T('application.tl.yesterday') : dateOf(d)
}
const groups = computed(() => {
  const out = []
  props.events.forEach((e, i) => {
    const d = e.at ? asDate(e.at) : null
    const key = d && !Number.isNaN(d.getTime()) ? String(midnight(d)) : 'none'
    let g = out[out.length - 1]
    if (!g || g.key !== key) { g = { key, label: key === 'none' ? T('application.tl.noDate') : dayLabel(d), items: [] }; out.push(g) }
    g.items.push({ i, e, d: key === 'none' ? null : d, ...shape(e) })
  })
  return out
})

const open = ref(new Set())
const toggle = (i) => { const s = new Set(open.value); s.has(i) ? s.delete(i) : s.add(i); open.value = s }
</script>

<template>
  <div class="atl">
    <section v-for="g in groups" :key="g.key" class="atl-day">
      <h3 class="atl-day-label">{{ g.label }}</h3>
      <ol class="atl-list">
        <li v-for="x in g.items" :key="x.i" class="atl-item" :class="[x.tone && 'tone-' + x.tone, { strong: x.strong, off: x.off, open: open.has(x.i) }]">
          <span class="atl-time num">{{ x.d ? clockOf(x.d) : '' }}</span>
          <span class="atl-node" aria-hidden="true"><Icon :name="x.icon" /></span>
          <div class="atl-body">
            <button v-if="x.more" type="button" class="atl-head" :aria-expanded="open.has(x.i)" @click="toggle(x.i)">
              <span class="atl-title">{{ x.title }}</span>
              <span v-if="x.sub" class="atl-sub" data-notr>{{ x.sub }}</span>
            </button>
            <div v-else class="atl-head">
              <span class="atl-title">{{ x.title }}</span>
              <span v-if="x.sub" class="atl-sub" data-notr>{{ x.sub }}</span>
            </div>
            <div v-if="open.has(x.i)" class="atl-detail">
              <template v-if="x.e.kind === 'mail'">
                <dl>
                  <template v-if="x.e.subject"><dt>{{ $t('application.tl.subject') }}</dt><dd data-notr>{{ x.e.subject }}</dd></template>
                  <template v-if="x.e.sender"><dt>{{ $t('application.tl.sender') }}</dt><dd data-notr>{{ x.e.sender }}</dd></template>
                  <template v-if="x.e.summary"><dt>{{ $t('application.tl.said') }}</dt><dd data-notr>{{ x.e.summary }}</dd></template>
                </dl>
                <button type="button" class="sm" @click="emit('open-mail', x.e.message_id)"><Icon name="mail" />{{ $t('application.tl.showMail') }}</button>
              </template>
              <template v-else-if="x.e.kind === 'run'">
                <p class="atl-said" data-notr>{{ x.e.said }}</p>
                <router-link to="/runs" class="btn sm"><Icon name="activity" />{{ $t('application.runRecord') }}</router-link>
              </template>
            </div>
          </div>
        </li>
      </ol>
    </section>
  </div>
</template>

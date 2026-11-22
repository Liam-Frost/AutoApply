<script setup>
// Lab: the three weights of saying what state something is in - a filled badge (.tag), a dot with words (Status), a
// plain attribute (.meta) - and the dash for no value. Most things are the third; the first is for the few that must
// be seen. Every value is made up.
import Icon from '../../../components/Icon.vue'
import Status from '../../../components/Status.vue'

const TONES = [['', 'Archived'], ['ok', 'Offer'], ['warn', 'Waiting for a code'], ['bad', 'Failed'], ['info', 'Interview']]
const STATES = [['ok', 'Auto sign-in ready'], ['ok', 'Session saved'], ['warn', 'Needs signing in again'], ['bad', 'Sign-in failed'], ['info', 'Signing in'], ['', 'Not used yet']]
const KINDS = [['interview', 'Interview'], ['assessment', 'Assessment'], ['deadline', 'Deadline'], ['offer', 'Offer'], ['follow', 'Follow-up'], ['own', 'Personal'], ['system', 'Record']]
const ROWS = [
  { site: 'Northwind · Workday', tag: ['info', 'Interview'], status: ['ok', 'Auto sign-in ready', ''], meta: 'Workday' },
  { site: 'Fjord Energy · Greenhouse', tag: ['bad', 'Overdue'], status: ['warn', 'Needs signing in again', 'The site asked for a code that was sent to your e-mail.'], meta: 'Greenhouse' },
  { site: 'Juniper Logistics', tag: null, status: ['', 'Not used yet', ''], meta: '' },
]
</script>

<template>
  <p class="lab-note">1 · .tag - a state that matters and must be seen (20px high, one line)</p>
  <div class="lab-row" data-status="tags">
    <span v-for="[t, name] in TONES" :key="name" class="tag" :class="t">{{ name }}</span>
    <span class="tag warn"><Icon name="star" />With an icon</span>
    <a href="#lab-Status" class="tag warn">A link</a>
  </div>
  <p class="lab-note">The calendar's kinds keep their own colours wherever they appear (.ev-kind + .ev-&lt;kind&gt;)</p>
  <div class="lab-row">
    <span v-for="[k, name] in KINDS" :key="k" class="ev-kind" :class="'ev-' + k">{{ name }}</span>
  </div>

  <p class="lab-note">2 · Status - an ordinary state in a dense place: a dot and words; a reason behind the (i)</p>
  <div class="lab-row" data-status="status">
    <Status v-for="[t, name] in STATES" :key="name" :tone="t" :label="name" />
  </div>
  <div class="lab-row">
    <Status tone="warn" label="Needs signing in again" tip="The site asked for a code that was sent to your e-mail." />
    <Status tone="bad" label="Sign-in failed" tip="The password was not accepted. Check it under Accounts." />
  </div>

  <p class="lab-note">3 · .meta - a plain attribute, no fill · and .none where there is nothing</p>
  <div class="lab-row">
    <span class="meta">Workday</span><span class="meta">Greenhouse</span><span class="meta">Registered by the program</span><span class="meta small">employer site</span><span class="none">—</span>
  </div>

  <p class="lab-note">Where the place is narrower than the words: a badge and a status are cut, never wrapped</p>
  <div class="lab-row" data-status="narrow">
    <div class="lab-box" style="width: 120px"><span class="tag warn">Waiting for a verification code</span></div>
    <div class="lab-box" style="width: 120px"><Status tone="ok" label="Auto sign-in ready, session saved" /></div>
    <div class="lab-box" style="width: 150px"><Status tone="warn" label="Needs signing in again" tip="The site asked for a code." /></div>
    <div class="lab-box" style="width: 120px; display: flex; gap: 6px"><span class="tag info">Interview</span><span class="tag">Second round on site</span></div>
  </div>

  <p class="lab-note">The three in one table: only one thing in a row is filled</p>
  <div class="table-wrap" style="max-height: none">
    <table>
      <thead><tr><th>Site</th><th>Stage</th><th>Sign-in</th><th>System</th></tr></thead>
      <tbody>
        <tr v-for="r in ROWS" :key="r.site">
          <td><span class="t-primary">{{ r.site }}</span></td>
          <td><span v-if="r.tag" class="tag" :class="r.tag[0]">{{ r.tag[1] }}</span><span v-else class="none">—</span></td>
          <td><Status :tone="r.status[0]" :label="r.status[1]" :tip="r.status[2]" /></td>
          <td><span v-if="r.meta" class="meta">{{ r.meta }}</span><span v-else class="none">—</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
// Lab: the site-accounts patterns - the accounts table in every state a row can be in (CredentialCell, automation
// Status, session lines, row actions) and ProviderCard with contents of different lengths, in grids of three widths.
// Nothing here talks to the server; every value is made up (the "passwords" too).
import { reactive, ref } from 'vue'
import CredentialCell from '../../../components/cells/CredentialCell.vue'
import DateTimeCell from '../../../components/cells/DateTimeCell.vue'
import EntityCell from '../../../components/cells/EntityCell.vue'
import DataTable from '../../../components/DataTable.vue'
import Icon from '../../../components/Icon.vue'
import Menu from '../../../components/Menu.vue'
import ProviderCard from '../../../components/ProviderCard.vue'
import Status from '../../../components/Status.vue'
import Trunc from '../../../components/Trunc.vue'

const LONG_HOST = 'careers.very-long-enterprise-solutions-north-america-university-recruiting.example-talent-platform.com'
const LONG_MAIL = 'alexander.chen.university-recruiting.co-op-applications-2027@students.northfield-university.example'

const cols = [
  { id: 'site', header: 'Site', min: 160, flex: 1, max: 380 },
  { id: 'login', header: 'Username or email', min: 124, flex: 2, max: 340 },
  { id: 'cred', header: 'Password', width: 152 },
  { id: 'auto', header: 'Automation', min: 150, flex: 3, max: 230, headerTip: 'Worked out from what is saved, not checked with the site.' },
  { id: 'session', header: 'Session', width: 176, priority: 1, headerTip: 'The saved cookies. "Expires by" is an upper bound.' },
  { id: 'source', header: 'Source', width: 116, priority: 2 },
  { id: 'act', header: '', width: 144, align: 'end' },
]
const rows = reactive([
  { id: 1, site: 'Northwind', system: 'Workday', host: 'northwind.wd3.myworkdayjobs.com', login: 'alex.chen@example.com', saved: true, pw: 'hunter2-demo',
    auto: ['ok', 'Auto sign-in ready', 'A password or a usable session is saved.'], session: { primary: 'Saved Yesterday 19:02', secondary: 'Expires by 12/26/2027', tip: 'An upper bound, not a guarantee.' }, source: 'Manual sign-in' },
  { id: 2, site: 'Globex', system: 'Workday', host: 'globex.wd1.myworkdayjobs.com', login: 'alex.chen@example.com', saved: false,
    auto: ['warn', 'Manual sign-in required', 'No password is saved, and the session is expired: sign in once.'], session: { primary: 'Saved Oct 13 16:52', secondary: 'Session expired', tone: 'warn' }, source: 'Manual sign-in' },
  { id: 3, site: 'Initech', system: 'iCIMS', host: 'careers-initech.icims.com', login: 'alex.chen@example.com', saved: true, pw: 'correct-horse-battery-staple-demo-0123456789',
    auto: ['info', 'Email verification pending', 'The app registered this account; no successful sign-in has been seen since.'], session: { primary: 'Not saved', tone: 'muted' }, source: 'Auto-registered' },
  { id: 4, site: 'Umbrella', system: 'Workday', host: 'umbrella.wd5.myworkdayjobs.com', login: 'alex.chen@example.com', saved: true, pw: 'hunter2-demo',
    auto: ['bad', 'Registration failed', 'This step did not finish. The technical details are in the row\'s details.'], session: { primary: 'Not saved', tone: 'muted' }, source: 'Auto-registered' },
  { id: 5, site: 'Soylent', system: 'Workday', host: 'soylent.wd12.myworkdayjobs.com', login: 'alex.chen@example.com', saved: true, pw: 'hunter2-demo', loading: true,
    auto: ['bad', 'Locked', 'Locked after too many sign-in attempts.'], session: { primary: 'Saved Today 08:15', secondary: 'No expiry given' }, source: 'Added manually' },
  { id: 6, site: 'Very Long Enterprise Solutions North America University Recruiting', system: 'Eightfold', host: LONG_HOST, login: LONG_MAIL, saved: true, pw: 'hunter2-demo',
    auto: ['', 'Never signed in', 'A password is saved; the app has not signed in with it yet.'], session: { primary: 'Not saved', tone: 'muted' }, source: 'Chrome import' },
  { id: 7, site: 'Hooli', system: 'Workday', host: '', login: '', saved: false, auto: ['', 'Never signed in', ''], session: { primary: 'Not saved', tone: 'muted' }, source: 'Added manually' },
])
const shown = reactive(new Set([3]))      // rows whose made-up password is on screen
const menu = [
  { id: 'detail', label: 'View details', icon: 'info' }, { id: 'browser', label: 'Sign-in browser', icon: 'globe', hint: 'Site default' }, { divider: true },
  { id: 'session', label: 'Clear session', icon: 'x' }, { id: 'password', label: 'Delete saved password', icon: 'key' }, { divider: true },
  { id: 'delete', label: 'Delete account', icon: 'trash', danger: true },
]
const did = ref('')

const NOW = Date.now()
const iso = (days) => new Date(NOW + days * 86400000).toISOString()
const cards = reactive([
  { p: { key: 'a', name: 'Google', note: 'A passkey or two-step sign-in both work: complete it in the window as usual.', email: 'alex.chen.personal.account-for-applications@example.com', session: { saved_at: iso(-5), valid_until: iso(380), expired: false } }, state: '' },
  { p: { key: 'b', name: 'LinkedIn', email: '', session: { saved_at: iso(-120), valid_until: null, expired: true } }, state: '' },
  { p: { key: 'c', name: 'Microsoft', email: '', session: null }, state: '' },
  { p: { key: 'd', name: 'Apple', note: 'Apple asks for two-factor authentication at every sign-in from a new browser.', email: '', session: null }, state: 'trying' },
  { p: { key: 'e', name: 'GitHub', email: 'alex@example.com', session: { saved_at: iso(-1), valid_until: iso(20), expired: false } }, state: 'The window was closed before the sign-in finished (net::ERR_ABORTED at https://github.example/login?return_to=%2Fsettings%2Fprofile)' },
  { p: { key: 'f', name: 'Northfield University Single Sign-On (CWL)', custom: true, email: '', session: { saved_at: iso(-0.05), valid_until: null, expired: false } }, state: '' },
  { p: { key: 'g', name: 'XING', region: 'German-speaking region', email: '', session: null }, state: 'sign-in verification timed out' },
  { p: { key: 'h', name: 'SEEK', region: 'Australia, New Zealand', email: 'a@example.com', session: { saved_at: iso(-30), valid_until: iso(2), expired: false } }, state: '' },
])
function login(c) { c.state = 'trying'; did.value = 'login ' + c.p.name }
function forget(c) { c.p.session = null; c.state = ''; did.value = 'forget ' + c.p.name }
function save(c, v) { c.p.email = v.email; did.value = 'save ' + c.p.name + ': ' + (v.backend || 'default') + ', ' + (v.email || 'no email') }
</script>

<template>
  <p class="lab-note">The accounts table: every state of a row. Each row is 64px whatever it holds; the password's text and its button stand at the same place in every row. The eye shows a made-up value. Last action: <b data-t="acc-did">{{ did }}</b></p>
  <div data-lab-acc="table">
    <DataTable :columns="cols" :rows="rows" density="comfortable" label="Site accounts (made up)">
      <template #cell-site="{ row }"><EntityCell :primary="row.site" :secondary="row.host"><template #after><span class="meta small">{{ row.system }}</span></template></EntityCell></template>
      <template #cell-login="{ row }"><Trunc v-if="row.login" :text="row.login" /><span v-else class="none">—</span></template>
      <template #cell-cred="{ row }">
        <CredentialCell :saved="row.saved" :value="row.saved && shown.has(row.id) ? row.pw : null" :loading="!!row.loading" @reveal="shown.add(row.id)" @hide="shown.delete(row.id)" @copy="did = 'copy ' + row.site" @add="did = 'add ' + row.site" />
      </template>
      <template #cell-auto="{ row }"><Status :tone="row.auto[0]" :label="row.auto[1]" :tip="row.auto[2]" /></template>
      <template #cell-session="{ row }"><DateTimeCell v-bind="row.session" /></template>
      <template #cell-source="{ row }"><Trunc class="meta" :text="row.source" /></template>
      <template #cell-act="{ row }">
        <button v-if="row.host" type="button" class="sm" @click="did = 'sign in ' + row.site"><Icon name="login" />Sign in</button>
        <Menu label="More" :items="menu" @pick="did = $event + ' ' + row.site" />
      </template>
    </DataTable>
  </div>

  <p class="lab-note" style="margin-top: 16px">CredentialCell on its own, in boxes of 152px: saved, shown, shown and long, being read, not saved</p>
  <div class="lab-row" data-lab-acc="cred">
    <div class="lab-box" style="width: 152px"><CredentialCell saved /></div>
    <div class="lab-box" style="width: 152px"><CredentialCell saved value="hunter2-demo" /></div>
    <div class="lab-box" style="width: 152px"><CredentialCell saved value="correct-horse-battery-staple-demo-0123456789" /></div>
    <div class="lab-box" style="width: 152px"><CredentialCell saved loading /></div>
    <div class="lab-box" style="width: 152px"><CredentialCell /></div>
  </div>

  <p class="lab-note" style="margin-top: 16px">ProviderCard: saved with a long e-mail and a note, expired, none, its window open, last try failed with a long reason, a custom one with a long name, with a region. Four in a row here; every line at the same height in each card, the foot at the bottom.</p>
  <div class="pgrid-box" data-lab-acc="cards">
    <div class="pgrid">
      <ProviderCard v-for="c in cards" :key="c.p.key" :provider="c.p" :state="c.state" backend="" @login="login(c)" @forget="forget(c)" @remove="did = 'remove ' + c.p.name" @save="save(c, $event)" />
    </div>
  </div>

  <p class="lab-note" style="margin-top: 16px">The same cards where there is less room: 640px (two in a row) and 320px (one)</p>
  <div class="lab-row" style="align-items: flex-start">
    <div class="pgrid-box" style="width: 640px; max-width: 100%" data-lab-acc="cards-2">
      <div class="pgrid"><ProviderCard v-for="c in cards.slice(0, 4)" :key="c.p.key" :provider="c.p" :state="c.state" backend="nodriver" /></div>
    </div>
    <div class="pgrid-box" style="width: 320px; max-width: 100%" data-lab-acc="cards-1">
      <div class="pgrid"><ProviderCard v-for="c in cards.slice(4, 6)" :key="c.p.key" :provider="c.p" :state="c.state" backend="" /></div>
    </div>
  </div>
</template>

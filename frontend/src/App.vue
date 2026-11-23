<script setup>
import { t as T } from './i18n/catalog'
import { computed, nextTick, onMounted, onUnmounted, provide, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { hold } from './focus'
import { clock } from './data'
import { api, auth } from './api'
import Icon from './components/Icon.vue'
import IconButton from './components/IconButton.vue'
import Popover from './components/Popover.vue'
import BrandLogo from './components/BrandLogo.vue'
import RemoteBanner from './components/RemoteBanner.vue'
import { LANGS, lang, setLang } from './i18n'
import { isBeta } from './i18n/catalog'
import { dialog, dismissToast, persona, session, setTheme, theme, toasts } from './ui'
import LoginView from './views/LoginView.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import TipLayer from './components/TipLayer.vue'

const ov = ref({ pending_drafts: 0, open_todos: 0, queued_tasks: 0, paused: false, running: [] })
let timer
async function load() {
  if (!session.in) return
  // (the server may be restarting, or gone: what is shown stays, and the footer says since when it is not being updated)
  try { ov.value = await api.get('/overview'); Object.assign(link, { at: Date.now(), down: false }) } catch (e) { link.down = true }
}
const link = reactive({ at: null, down: false })

// --- the navigation on a narrow screen -------------------------------------------------------------------------------
const route = useRoute()
const NAMES = [['/home', T('app.overview')], ['/todos', T('app.needsYou')], ['/jobs/sources', T('app.sourcesAndWatchedEmployers')], ['/jobs', T('app.postings')], ['/applications', T('app.applications')], ['/profile', T('app.profile')],
  ['/files', T('app.files')], ['/contacts', T('app.contactsReferrals')], ['/accounts', T('app.siteAccounts')], ['/analytics', T('app.analytics')], ['/runs', T('app.activity')], ['/settings', T('app.settings')], ['/about', T('about.nav')], ['/welcome', T('app.setupGuide')], ['/remote', T('app.remoteWindow')]]
const pageName = computed(() => (NAMES.find(([p]) => route.path === p || route.path.startsWith(p + '/')) || ['', ''])[1])
const menu = ref(false)
const side = ref(null)
let letGo = null
// open: the menu has the keyboard (focus.js); going somewhere closes it
watch(menu, async (open) => {
  if (letGo) { letGo(); letGo = null }
  if (open) { await nextTick(); if (side.value) letGo = hold(side.value) }
})
watch(() => route.path, () => { menu.value = false })
// Who is here: nobody yet (the login shows), or the administrator (the program shows).
async function whoAmI() {
  try {
    const st = await api.get('/auth/state')
    Object.assign(session, { in: !st.required || st.signed_in, setup: st.required && st.setup, canSetup: st.can_setup, user: st.user, locked: st.locked })
  } catch (e) { if (e.status === 404) session.in = true }      // a server from before the login existed (the page was rebuilt first): no door; otherwise it is restarting - keep what is shown
  session.ready = true
}
auth.onLogin = () => { if (session.in) { session.in = false; whoAmI() } }      // the server said "sign in first": the login expired or was ended elsewhere
const entered = () => location.reload()      // start over as the signed-in user: language, persona, the view that was asked for
async function signOut() {
  await api.post('/auth/logout', {}).catch(() => {})
  session.in = false
  await whoAmI()
}
async function togglePause() {
  await api.put('/settings', { settings: { 'schedule.paused': !ov.value.paused } })
  load()
}
provide('overview', ov)
provide('reloadOverview', load)
onMounted(async () => { await whoAmI(); load(); timer = setInterval(load, 8000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div v-if="!session.ready" class="door"></div>
  <LoginView v-else-if="!session.in" @done="entered" />
  <div v-else class="shell">
    <!-- On a narrow screen the navigation is this bar - the program, the page that is open, what waits for you,
         whether it is running - and the full list opens from "menu". (It used to be the whole sidebar laid out across
         the top: a third of a phone's screen before the page began.) -->
    <header class="topbar">
      <router-link to="/" class="brand"><img :src="'logo-mark.svg'" alt="" /><span>AutoApply</span></router-link>
      <span class="topbar-page">{{ pageName }}</span>
      <span class="grow"></span>
      <router-link v-if="ov.open_todos" to="/todos" class="count" :aria-label="$t('app.thingSNeedYou', { p0: ov.open_todos })">{{ ov.open_todos }}</router-link>
      <span class="status-dot" :class="link.down ? 'down' : ov.draining || ov.paused ? 'paused' : ov.running && ov.running.length ? 'busy' : ''" role="img"
        :aria-label="link.down ? $t('app.cannotReachTheService') : ov.paused ? $t('app.pausedWontRunAutomatically') : ov.running && ov.running.length ? $t('app.running') : $t('app.runningIdleRightNow')"></span>
      <button class="ghost sm" :aria-expanded="menu" aria-controls="side-nav" @click="menu = !menu"><Icon :name="menu ? 'x' : 'menu'" />{{ menu ? $t('app.close') : $t('app.menu') }}</button>
    </header>
    <div v-if="menu" class="overlay menu-overlay" @click="menu = false"></div>
    <nav id="side-nav" ref="side" class="side" :class="{ guide: !persona.done, open: menu }" :aria-label="$t('app.navigation')" @keydown.esc="menu = false">
      <router-link to="/" class="brand full"><BrandLogo /></router-link>

      <router-link to="/home" class="nav"><Icon name="home" />{{ $t('app.overview') }}</router-link>
      <router-link to="/todos" class="nav"><Icon name="bell" />{{ $t('app.needsYou') }} <span v-if="ov.open_todos" class="count">{{ ov.open_todos }}</span></router-link>
      <router-link to="/calendar" class="nav"><Icon name="clock" />{{ $t('calendar.nav') }}</router-link>
      <router-link to="/jobs" class="nav" active-class="" exact-active-class="router-link-active"><Icon name="briefcase" />{{ $t('app.postings') }}</router-link>
      <router-link to="/applications" class="nav"><Icon name="check" />{{ $t('app.applications') }} <span v-if="ov.apps_need_me" v-tip="$t('app.applicationsWaiting')" class="count">{{ ov.apps_need_me }}</span></router-link>

      <div class="nav-label">{{ $t('app.myInfo') }}</div>
      <router-link to="/profile" class="nav"><Icon name="user" />{{ $t('app.profile') }}</router-link>
      <router-link to="/files" class="nav"><Icon name="inbox" />{{ $t('app.files') }}</router-link>
      <router-link to="/contacts" class="nav"><Icon name="user" />{{ $t('app.contactsReferrals') }}</router-link>
      <router-link to="/accounts" class="nav"><Icon name="key" />{{ $t('app.siteAccounts') }}</router-link>

      <div class="nav-label">{{ $t('app.system') }}</div>
      <router-link to="/analytics" class="nav"><Icon name="search" />{{ $t('app.analytics') }}</router-link>
      <router-link to="/runs" class="nav"><Icon name="activity" />{{ $t('app.activity') }}</router-link>
      <router-link to="/settings" class="nav"><Icon name="settings" />{{ $t('app.settings') }}</router-link>
      <router-link to="/about" class="nav"><Icon name="info" />{{ $t('about.nav') }}<span v-if="ov.update" v-tip="$t('about.newVersionDot', { v: ov.update })" class="tag ok nav-tag">{{ $t('about.new') }}</span></router-link>

      <div class="side-foot">
        <div v-if="link.down" role="status"><span class="status-dot down"></span>{{ $t('app.cannotReachTheService') }}<template v-if="link.at">{{ $t('app.lastUpdated', { p0: clock(link.at) }) }}</template></div>
        <div v-else-if="ov.draining"><span class="status-dot paused"></span><router-link to="/runs" class="foot-link">{{ ov.stopped ? $t('app.stoppedItCanBe') : $t('app.finishingNoNewTask') }}</router-link></div>
        <div v-else-if="ov.paused"><span class="status-dot paused"></span>{{ $t('app.pausedWontRunAutomatically') }}</div>
        <div v-else-if="ov.running && ov.running.length"><span class="status-dot busy"></span>{{ $t('app.text', { p0: ov.running[0].label }) }}</div>
        <div v-else><span class="status-dot"></span>{{ $t('app.runningIdleRightNow') }}</div>
        <button class="sm" @click="togglePause"><Icon :name="ov.paused ? 'play' : 'pause'" />{{ ov.paused ? $t('app.resumeAutoRun') : $t('app.pauseAutoRun') }}</button>
        <!-- what is set once - the theme, the language - is behind one button, not eight controls that are always there -->
        <Popover :label="$t('app.look')" placement="top" :width="248">
          <template #trigger="{ toggle, attrs }"><button class="sm ghost w-full" v-bind="attrs" @click="toggle"><Icon name="globe" />{{ $t('app.look') }}</button></template>
          <div class="look-pop">
            <div>
              <div id="look-theme" class="k">{{ $t('app.appearance') }}</div>
              <div class="theme-seg" role="group" aria-labelledby="look-theme">
                <button :class="{ on: theme.value === 'light' }" :aria-pressed="theme.value === 'light'" @click="setTheme('light')">{{ $t('app.light') }}</button>
                <button :class="{ on: theme.value === 'dark' }" :aria-pressed="theme.value === 'dark'" @click="setTheme('dark')">{{ $t('app.dark') }}</button>
                <button :class="{ on: theme.value === 'system' }" :aria-pressed="theme.value === 'system'" @click="setTheme('system')">{{ $t('app.matchSystem') }}</button>
              </div>
            </div>
            <div>
              <div id="look-lang" class="k" data-notr>{{ $t('app.language') }}</div>
              <div class="seg lang" role="group" data-notr aria-labelledby="look-lang"><button v-for="(l, k) in LANGS" :key="k" :class="{ on: lang.value === k }" :aria-pressed="lang.value === k" @click="lang.value !== k && setLang(k)">{{ isBeta(k) ? $t('language.beta', { name: l }) : l }}</button></div>
            </div>
          </div>
        </Popover>
        <button v-if="session.user" v-tip="session.user" class="sm ghost" @click="signOut"><Icon name="login" />{{ $t('app.signOut') }}</button>
      </div>
    </nav>
    <main class="content"><RemoteBanner /><router-view :key="$route.path.startsWith('/remote/') ? $route.path : undefined" /></main>
  </div>
  <ConfirmDialog v-if="dialog.open" />
  <TipLayer />
  <div class="toasts" role="status" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.tone">
      <span class="grow">{{ t.text }} <router-link v-if="t.to" :to="t.to" @click="dismissToast(t.id)">{{ t.link }}</router-link><button v-else-if="t.act" type="button" class="toast-act" @click="dismissToast(t.id); t.act()">{{ t.link }}</button></span>
      <IconButton icon="x" size="sm" :label="$t('app.close')" @click="dismissToast(t.id)" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, provide, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { hold } from './focus'
import { clock } from './data'
import { api, auth } from './api'
import Icon from './components/Icon.vue'
import RemoteBanner from './components/RemoteBanner.vue'
import { LANGS, lang, setLang } from './i18n'
import { dialog, dismissToast, persona, session, setTheme, theme, toasts } from './ui'
import LoginView from './views/LoginView.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'

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
const NAMES = [['/home', '概览'], ['/todos', '需要我处理'], ['/drafts', '草案审批'], ['/jobs/sources', '来源与关注公司'], ['/jobs', '岗位'], ['/applications', '我的申请'], ['/profile', '个人资料'],
  ['/files', '材料库'], ['/contacts', '人脉与内推'], ['/accounts', '网站账号'], ['/analytics', '数据分析'], ['/runs', '活动记录'], ['/settings', '设置'], ['/welcome', '设置向导'], ['/remote', '远程窗口']]
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
      <router-link v-if="ov.open_todos" to="/todos" class="count" :aria-label="`${ov.open_todos} 件事需要你处理`">{{ ov.open_todos }}</router-link>
      <span class="status-dot" :class="link.down ? 'down' : ov.draining || ov.paused ? 'paused' : ov.running && ov.running.length ? 'busy' : ''" role="img"
        :aria-label="link.down ? '连接不上服务' : ov.paused ? '已暂停，不会自动运行' : ov.running && ov.running.length ? '正在运行' : '运行中，目前空闲'"></span>
      <button class="ghost sm" :aria-expanded="menu" aria-controls="side-nav" @click="menu = !menu"><Icon :name="menu ? 'x' : 'menu'" />{{ menu ? '关闭' : '菜单' }}</button>
    </header>
    <div v-if="menu" class="overlay menu-overlay" @click="menu = false"></div>
    <nav id="side-nav" ref="side" class="side" :class="{ guide: !persona.done, open: menu }" aria-label="导航" @keydown.esc="menu = false">
      <router-link to="/" class="brand full"><img :src="'logo-full.svg'" alt="AutoApply" /></router-link>

      <router-link to="/home" class="nav"><Icon name="home" />概览</router-link>
      <router-link to="/todos" class="nav"><Icon name="bell" />需要我处理 <span v-if="ov.open_todos" class="count">{{ ov.open_todos }}</span></router-link>
      <router-link to="/drafts" class="nav"><Icon name="draft" />草案审批 <span v-if="ov.pending_drafts" class="count">{{ ov.pending_drafts }}</span></router-link>
      <router-link to="/jobs" class="nav"><Icon name="briefcase" />岗位</router-link>
      <router-link to="/applications" class="nav"><Icon name="check" />我的申请</router-link>

      <div class="nav-label">我的资料</div>
      <router-link to="/profile" class="nav"><Icon name="user" />个人资料</router-link>
      <router-link to="/files" class="nav"><Icon name="inbox" />材料库</router-link>
      <router-link to="/contacts" class="nav"><Icon name="user" />人脉与内推</router-link>
      <router-link to="/accounts" class="nav"><Icon name="key" />网站账号</router-link>

      <div class="nav-label">系统</div>
      <router-link to="/analytics" class="nav"><Icon name="search" />数据分析</router-link>
      <router-link to="/runs" class="nav"><Icon name="activity" />活动记录</router-link>
      <router-link to="/settings" class="nav"><Icon name="settings" />设置</router-link>

      <div class="side-foot">
        <div v-if="link.down" role="status"><span class="status-dot down"></span>连接不上服务<template v-if="link.at">（上次更新 {{ clock(link.at) }}）</template></div>
        <div v-else-if="ov.draining"><span class="status-dot paused"></span><router-link to="/runs" style="color: inherit">{{ ov.stopped ? '已停下，可以关闭或重启' : '正在收尾，不再开始新任务' }}</router-link></div>
        <div v-else-if="ov.paused"><span class="status-dot paused"></span>已暂停，不会自动运行</div>
        <div v-else-if="ov.running && ov.running.length"><span class="status-dot busy"></span>正在{{ ov.running[0].label }}</div>
        <div v-else><span class="status-dot"></span>运行中，目前空闲</div>
        <div class="theme-seg" role="group" aria-label="外观">
          <button :class="{ on: theme.value === 'light' }" @click="setTheme('light')">浅色</button>
          <button :class="{ on: theme.value === 'dark' }" @click="setTheme('dark')">深色</button>
          <button :class="{ on: theme.value === 'system' }" @click="setTheme('system')">跟随系统</button>
        </div>
        <div class="seg lang" data-notr aria-label="Language / 语言"><button v-for="(l, k) in LANGS" :key="k" :class="{ on: lang.value === k }" @click="lang.value !== k && setLang(k)">{{ l }}</button></div>
        <button class="sm" @click="togglePause"><Icon :name="ov.paused ? 'play' : 'pause'" />{{ ov.paused ? '恢复自动运行' : '暂停自动运行' }}</button>
        <button v-if="session.user" class="sm ghost" :title="session.user" @click="signOut"><Icon name="login" />退出登录</button>
      </div>
    </nav>
    <main class="content"><RemoteBanner /><router-view :key="$route.path.startsWith('/remote/') ? $route.path : undefined" /></main>
  </div>
  <ConfirmDialog v-if="dialog.open" />
  <div class="toasts" role="status" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.tone">
      <span class="grow">{{ t.text }} <router-link v-if="t.to" :to="t.to" @click="dismissToast(t.id)">{{ t.link }}</router-link></span>
      <button aria-label="关闭" @click="dismissToast(t.id)">✕</button>
    </div>
  </div>
</template>

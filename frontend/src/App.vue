<script setup>
import { onMounted, onUnmounted, provide, ref } from 'vue'
import { api, auth } from './api'
import Icon from './components/Icon.vue'
import RemoteBanner from './components/RemoteBanner.vue'
import { LANGS, lang, setLang } from './i18n'
import { answer, dialog, dismissToast, persona, session, setTheme, theme, toasts } from './ui'
import LoginView from './views/LoginView.vue'

const ov = ref({ pending_drafts: 0, open_todos: 0, queued_tasks: 0, paused: false, running: [] })
let timer
async function load() {
  if (!session.in) return
  try { ov.value = await api.get('/overview') } catch (e) { /* server restarting */ }
}
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
    <nav class="side" :class="{ guide: !persona.done }">
      <router-link to="/" class="brand"><img :src="'logo-mark.svg'" alt="" /><span>AutoApply</span></router-link>

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
        <div v-if="ov.draining"><span class="status-dot paused"></span><router-link to="/runs" style="color: inherit">{{ ov.stopped ? '已停下，可以关闭或重启' : '正在收尾，不再开始新任务' }}</router-link></div>
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
  <template v-if="dialog.open">
    <div class="overlay" style="z-index: 80" @click="answer(dialog.cancel)"></div>
    <div class="dialog" role="alertdialog" aria-modal="true" @keydown.esc="answer(dialog.cancel)">
      <p>{{ dialog.text }}</p>
      <div v-if="dialog.choices" class="row" style="justify-content: flex-end; flex-wrap: wrap">
        <template v-for="c in dialog.choices" :key="c.key">
          <button v-if="c.focus" v-focus :class="c.cls" @click="answer(c.key)">{{ c.label }}</button>
          <button v-else :class="c.cls" @click="answer(c.key)">{{ c.label }}</button>
        </template>
      </div>
      <div v-else class="row" style="justify-content: flex-end">
        <button @click="answer(false)">取消</button>
        <button v-focus :class="dialog.danger ? 'danger solid' : 'primary'" @click="answer(true)">{{ dialog.ok }}</button>
      </div>
    </div>
  </template>
  <div class="toasts" role="status" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.tone">
      <span class="grow">{{ t.text }}</span>
      <button aria-label="关闭" @click="dismissToast(t.id)">✕</button>
    </div>
  </div>
</template>

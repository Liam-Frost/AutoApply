<script setup>
import { t as T } from '../i18n/catalog'
// A browser page on the computer AutoApply runs on, used from here. Two ways, chosen by the server:
//   "frames"  the page is in the hidden browser: pictures of it come in, clicks and keys go out (backend remote.py)
//   "screen"  it is a real window on a virtual screen: that screen is shown through its VNC server (backend vscreen.py)
// What is typed can be a password: nothing typed here is kept in this page's state longer than it takes to send it,
// and nothing is logged.
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ROOT } from '../api'
import { ask, toast } from '../ui'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const win = ref(null)
const st = reactive({ state: 'opening', src: '', page: { url: '', title: '', tabs: [] } })   // opening | live | closed | refused
const stage = ref(null)
const keys = ref(null)
const screen = ref(null)
let rfb = null
let alive = true
let seq = 0
let queue = []
let flushing = null
let composing = false
let lastMove = 0

const PURPOSE = { login: T('remote.signIn'), apply: T('remote.applicationForm'), scan: T('remote.readingASite') }
const SPECIAL = new Set(['Enter', 'Tab', 'Backspace', 'Delete', 'Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', 'F5', 'Insert'])

const send = (e) => {
  queue.push(e)
  if (!flushing) flushing = setTimeout(flush, 40)
}
const flush = async () => {
  flushing = null
  const events = queue
  queue = []
  if (!events.length || st.state !== 'live') return
  try { await api.post(`/remote/${props.id}/input`, { events }) } catch (e) { if (e.status === 404) st.state = 'closed' }
}

const frames = async () => {
  while (alive && st.state !== 'closed' && st.state !== 'refused') {
    try {
      const r = await fetch(`${ROOT}/api/remote/${props.id}/frame?after=${seq}`, { cache: 'no-store' })
      if (r.status === 404) { st.state = 'closed'; break }
      if (r.status === 403) { st.state = 'refused'; st.why = (await r.json()).detail; break }
      if (r.status === 401) { location.reload(); break }
      seq = Number(r.headers.get('X-Seq') || seq)
      try { Object.assign(st.page, JSON.parse(r.headers.get('X-State') || '{}')) } catch (e) { /* no state this time */ }
      if (r.status === 200) {
        const url = URL.createObjectURL(await r.blob())
        const old = st.src
        st.src = url
        st.state = 'live'
        if (old) URL.revokeObjectURL(old)
      }
    } catch (e) { await new Promise((ok) => setTimeout(ok, 1500)) }      // the server is restarting, or the network dropped
  }
}

// where on the page a pointer is: the picture is the page's viewport, scaled to fit
const at = (ev) => {
  const r = stage.value.getBoundingClientRect()
  return { x: Math.round(((ev.clientX - r.left) / r.width) * win.value.width), y: Math.round(((ev.clientY - r.top) / r.height) * win.value.height) }
}
const down = (ev) => { if (ev.button !== 0) return; keys.value.focus({ preventScroll: true }); send({ t: 'down', ...at(ev) }) }
const up = (ev) => { if (ev.button === 0) send({ t: 'up', ...at(ev) }) }
const move = (ev) => {
  const now = Date.now()
  if (now - lastMove < (ev.buttons ? 30 : 120)) return        // a drag follows closely; hovering only needs to arrive
  lastMove = now
  send({ t: 'move', ...at(ev) })
}
const dbl = (ev) => send({ t: 'click', count: 2, ...at(ev) })
const menu = (ev) => send({ t: 'click', button: 'right', ...at(ev) })
const wheel = (ev) => send({ t: 'wheel', dx: ev.deltaX, dy: ev.deltaY, ...at(ev) })

// The keyboard goes through an invisible text box, so that phones show their keyboard and input methods (Chinese,
// accents) compose in it; what comes out is sent as text, and the keys that are not text are sent as keys.
const keydown = (ev) => {
  if (composing) return
  const mods = [ev.ctrlKey && 'Control', ev.altKey && 'Alt', ev.metaKey && 'Meta'].filter(Boolean)
  if (mods.length && ev.key.length === 1) {
    if (ev.key.toLowerCase() === 'v') return                  // paste arrives as the paste event, with this computer's clipboard
    ev.preventDefault()
    send({ t: 'key', k: ev.key.toLowerCase(), mods })
  } else if (SPECIAL.has(ev.key) || ev.key === ' ') {
    ev.preventDefault()
    send({ t: 'key', k: ev.key === ' ' ? 'Space' : ev.key, mods: [...mods, ev.shiftKey && 'Shift'].filter(Boolean) })
  }
}
const typed = (ev) => {
  if (composing) return
  const s = ev.target.value
  ev.target.value = ''
  if (s) send({ t: 'text', s })
}
const composed = (ev) => { composing = false; typed(ev) }
const pasted = (ev) => {
  ev.preventDefault()
  const s = (ev.clipboardData || window.clipboardData).getData('text')
  if (s) send({ t: 'text', s })
}

const nav = (a) => send({ t: 'nav', a })
const tab = (i) => send({ t: 'tab', i })
const finish = async () => {
  if (!(await ask(T('remote.closeThisWindowThe'), { ok: T('remote.doneCloseIt'), danger: false }))) return
  send({ t: 'close' })
  toast(T('remote.closed'))
}

// The virtual screen, through the VNC client library (noVNC), loaded only when a window needs it.
const connectScreen = async () => {
  try {
    const [{ default: RFB }, { password }] = await Promise.all([import('@novnc/novnc'), api.get(`/remote/${props.id}/screen`)])
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${ROOT}/api/remote/${props.id}/vnc`
    rfb = new RFB(screen.value, url, { credentials: { password }, wsProtocols: ['binary'] })
    rfb.scaleViewport = true
    rfb.focusOnClick = true
    rfb.addEventListener('connect', () => { st.state = 'live' })
    rfb.addEventListener('disconnect', async () => {
      rfb = null
      if (!alive) return
      // the window closed, or only the connection dropped? ask, and connect again if it is still there
      try { await api.get(`/remote/${props.id}`); setTimeout(() => alive && connectScreen(), 1500) } catch (e) { st.state = 'closed' }
    })
    rfb.addEventListener('securityfailure', () => { st.state = 'refused'; st.why = T('remote.theVirtualScreenRefused') })
  } catch (e) {
    st.state = e.status === 404 ? 'closed' : 'refused'
    st.why = e.message
  }
}

onMounted(async () => {
  try { win.value = await api.get(`/remote/${props.id}`) } catch (e) {
    st.state = e.status === 403 ? 'refused' : 'closed'
    st.why = e.message
    return
  }
  if (win.value.mode === 'screen') { await nextTick(); connectScreen() } else frames()
})
onBeforeUnmount(() => { alive = false; if (st.src) URL.revokeObjectURL(st.src); if (rfb) rfb.disconnect() })
</script>

<template>
  <PageHead :title="win ? `${PURPOSE[win.purpose] || $t('remote.window')}：${win.title}` : $t('remote.remoteWindow')" :sub="$t('remote.thisIsABrowser')">
    <button class="sm" @click="router.back()"><Icon name="back" />{{ $t('remote.back') }}</button>
    <button v-if="st.state === 'live' && win && win.mode === 'frames'" class="sm primary" @click="finish"><Icon name="check" />{{ $t('remote.doneCloseTheWindow') }}</button>
  </PageHead>

  <div v-if="st.state === 'closed'" class="callout">
    <Icon name="info" /><div>{{ $t('remote.thisWindowHasBeen') }}</div>
  </div>
  <div v-else-if="st.state === 'refused'" class="callout warn"><Icon name="alert" /><div>{{ st.why }}</div></div>

  <template v-else-if="win && win.mode === 'screen'">
    <div class="rw-frame"><div ref="screen" class="rw-screen"></div><div v-if="st.state === 'opening'" class="rw-wait rw-over">{{ $t('remote.connectingToTheVirtual') }}</div></div>
    <p class="rw-note">{{ $t('remote.thisIsAReal') }}</p>
  </template>

  <template v-else>
    <div class="rw-bar">
      <button class="sm ghost" :title="$t('remote.back2')" @click="nav('back')"><Icon name="back" /></button>
      <button class="sm ghost" :title="$t('remote.reload')" @click="nav('reload')"><Icon name="refresh" /></button>
      <span class="rw-url" data-notr>{{ st.page.url }}</span>
      <span v-if="st.page.tabs.length > 1" class="rw-tabs">
        <button v-for="t in st.page.tabs" :key="t.i" class="sm" :class="{ primary: t.on }" data-notr @click="tab(t.i)">{{ t.title }}</button>
      </span>
    </div>
    <div class="rw-frame">
      <img v-if="st.src" ref="stage" class="rw-stage" :src="st.src" alt="" draggable="false"
           @pointerdown.prevent="down" @pointerup.prevent="up" @pointermove="move" @dblclick.prevent="dbl" @contextmenu.prevent="menu" @wheel.prevent="wheel" />
      <div v-else class="rw-wait">{{ $t('remote.openingTheWindow') }}</div>
      <textarea ref="keys" class="rw-keys" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false" :aria-label="$t('remote.keyboardInput')"
                @keydown="keydown" @input="typed" @compositionstart="composing = true" @compositionend="composed" @paste="pasted"></textarea>
    </div>
    <p class="rw-note">{{ $t('remote.clickThePictureThen') }}</p>
  </template>
</template>

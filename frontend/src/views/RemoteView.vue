<script setup>
// A browser page on the computer AutoApply runs on, used from here: pictures of it come in, clicks and keys go out.
// (backend/autoapply/remote.py) What is typed can be a password: nothing typed here is kept in this page's state
// longer than it takes to send it, and nothing is logged.
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
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
let alive = true
let seq = 0
let queue = []
let flushing = null
let composing = false
let lastMove = 0

const PURPOSE = { login: '登录', apply: '申请表', scan: '读取网站' }
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
  if (!(await ask('关闭这个窗口？程序会把它当作“你做完了”：如果是登录，现在的登录状态会被保存；如果这一步还没做完，之后可以重新打开。', { ok: '做完了，关闭', danger: false }))) return
  send({ t: 'close' })
  toast('已关闭')
}

onMounted(async () => {
  try { win.value = await api.get(`/remote/${props.id}`) } catch (e) {
    st.state = e.status === 403 ? 'refused' : 'closed'
    st.why = e.message
    return
  }
  frames()
})
onBeforeUnmount(() => { alive = false; if (st.src) URL.revokeObjectURL(st.src) })
</script>

<template>
  <PageHead :title="win ? `${PURPOSE[win.purpose] || '窗口'}：${win.title}` : '远程窗口'" sub="这是运行 AutoApply 的那台电脑上的浏览器页面。在画面上点击和输入，就像在那台电脑上操作一样。">
    <button class="sm" @click="router.back()"><Icon name="back" />返回</button>
    <button v-if="st.state === 'live'" class="sm primary" @click="finish"><Icon name="check" />做完了，关闭窗口</button>
  </PageHead>

  <div v-if="st.state === 'closed'" class="callout">
    <Icon name="info" /><div>这个窗口已经关闭了。如果你刚完成登录或提交，程序已经接着往下做；结果会出现在“需要我处理”和“活动记录”里。</div>
  </div>
  <div v-else-if="st.state === 'refused'" class="callout warn"><Icon name="alert" /><div>{{ st.why }}</div></div>

  <template v-else>
    <div class="rw-bar">
      <button class="sm ghost" title="后退" @click="nav('back')"><Icon name="back" /></button>
      <button class="sm ghost" title="重新加载" @click="nav('reload')"><Icon name="refresh" /></button>
      <span class="rw-url" data-notr>{{ st.page.url }}</span>
      <span v-if="st.page.tabs.length > 1" class="rw-tabs">
        <button v-for="t in st.page.tabs" :key="t.i" class="sm" :class="{ primary: t.on }" data-notr @click="tab(t.i)">{{ t.title }}</button>
      </span>
    </div>
    <div class="rw-frame">
      <img v-if="st.src" ref="stage" class="rw-stage" :src="st.src" alt="" draggable="false"
           @pointerdown.prevent="down" @pointerup.prevent="up" @pointermove="move" @dblclick.prevent="dbl" @contextmenu.prevent="menu" @wheel.prevent="wheel" />
      <div v-else class="rw-wait">正在打开窗口…</div>
      <textarea ref="keys" class="rw-keys" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false" aria-label="键盘输入"
                @keydown="keydown" @input="typed" @compositionstart="composing = true" @compositionend="composed" @paste="pasted"></textarea>
    </div>
    <p class="rw-note">点一下画面再输入。你在这里输入的内容（包括密码）只发给这个页面，不会写进日志，也不会给 AI 看。画面每秒刷新几次，操作后会有短暂的延迟。</p>
  </template>
</template>

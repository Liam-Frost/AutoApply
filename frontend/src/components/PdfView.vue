<script setup>
// In-page PDF viewer. The file is fetched as plain bytes and drawn onto canvases with pdf.js, so nothing
// that looks like a PDF download ever reaches the browser (download managers grab those out of iframes).
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps({ src: { type: String, required: true } })
const box = ref(null)
const state = ref('loading') // loading | ready | error
const pages = ref(0)
const zoom = ref(1)
const message = ref('')
let doc = null
let token = 0

async function render() {
  if (!doc || !box.value) return
  const mine = token
  const host = box.value
  host.innerHTML = ''
  const width = Math.max(320, host.clientWidth - 24)
  for (let n = 1; n <= doc.numPages; n++) {
    const page = await doc.getPage(n)
    if (mine !== token) return
    const base = page.getViewport({ scale: 1 })
    const scale = (width / base.width) * zoom.value
    const vp = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) })
    const c = document.createElement('canvas')
    c.width = vp.width; c.height = vp.height
    c.style.width = base.width * scale + 'px'
    c.className = 'pdf-page'
    host.appendChild(c)
    await page.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise
  }
}
async function load() {
  const mine = ++token
  state.value = 'loading'; message.value = ''
  try {
    const r = await fetch(props.src)
    if (!r.ok) throw new Error(r.status === 415 ? '这种文件不能在页面里预览，请下载后查看。' : '没能读取文件（' + r.status + '）')
    const data = await r.arrayBuffer()
    if (mine !== token) return
    if (doc) doc.destroy()
    doc = await pdfjs.getDocument({ data }).promise
    pages.value = doc.numPages
    state.value = 'ready'
    await nextTick()
    await render()
  } catch (e) {
    if (mine === token) { state.value = 'error'; message.value = e.message || '预览失败' }
  }
}
function setZoom(z) { zoom.value = Math.min(2.5, Math.max(0.5, z)); render() }
watch(() => props.src, load, { immediate: true })
onBeforeUnmount(() => { token++; if (doc) doc.destroy() })
</script>

<template>
  <div class="pdf">
    <div class="pdf-bar">
      <span class="muted small">{{ state === 'ready' ? `共 ${pages} 页` : state === 'loading' ? '正在加载预览…' : '' }}</span>
      <span class="grow"></span>
      <template v-if="state === 'ready'">
        <button class="sm ghost" aria-label="缩小" @click="setZoom(zoom - 0.25)">−</button>
        <span class="small muted" style="min-width: 44px; text-align: center">{{ Math.round(zoom * 100) }}%</span>
        <button class="sm ghost" aria-label="放大" @click="setZoom(zoom + 0.25)">+</button>
        <button class="sm ghost" @click="setZoom(1)">适合宽度</button>
      </template>
    </div>
    <div v-if="state === 'error'" class="empty"><div class="t">没法预览</div><div>{{ message }}</div></div>
    <div v-show="state !== 'error'" ref="box" class="pdf-pages"></div>
  </div>
</template>

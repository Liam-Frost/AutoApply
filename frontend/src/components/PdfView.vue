<script setup>
import { t as T } from '../i18n/catalog'
// In-page PDF viewer. The file is fetched as plain bytes and drawn onto canvases with pdf.js, so nothing
// that looks like a PDF download ever reaches the browser (download managers grab those out of iframes).
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clampZoom, pageWidth, resized } from '../pdfsize'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps({ src: { type: String, required: true } })
const box = ref(null)
const state = ref('loading') // loading | ready | error
const pages = ref(0)
const zoom = ref(1)
const message = ref('')
let doc = null
let token = 0        // which file: a newer file makes what was being read for the older one stop
let drawing = 0      // which drawing of it: a newer drawing (another zoom, another width) makes the older one stop
let task = null      // the page that pdf.js is drawing this moment
let drawnFor = 0     // the width of the box the pages were last drawn for

// Draw every page for the box as wide as it is now. Each call is a drawing of its own: zooming twice in a row, or
// zooming while the pages are still appearing, used to leave two drawings filling the same box - every page twice,
// in two sizes. A newer drawing stops the older one where it stands (and the page pdf.js is in the middle of), and
// only the newest one puts anything on the page.
async function render() {
  if (!doc || !box.value) return
  const mine = ++drawing
  if (task) { try { task.cancel() } catch (e) { /* it had finished */ } task = null }
  const host = box.value
  const made = []
  drawnFor = host.clientWidth
  const width = pageWidth(host.clientWidth)
  for (let n = 1; n <= doc.numPages; n++) {
    const page = await doc.getPage(n)
    if (mine !== drawing) return
    const base = page.getViewport({ scale: 1 })
    const scale = (width / base.width) * zoom.value
    const vp = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) })
    const c = document.createElement('canvas')
    c.width = vp.width; c.height = vp.height
    c.style.width = base.width * scale + 'px'
    c.className = 'pdf-page'
    c.setAttribute('role', 'img')
    c.setAttribute('aria-label', T('common.pdf.page', { n, of: doc.numPages }))
    task = page.render({ canvasContext: c.getContext('2d'), viewport: vp })
    try { await task.promise } catch (e) { if (mine !== drawing) return; throw e }
    if (mine !== drawing) return
    made.push(c)
    // the first page takes the place of what was there; the others follow it - the old pages stay until then, so that
    // a change of zoom does not blank the preview while it is drawn
    if (n === 1) host.replaceChildren(c); else host.appendChild(c)
  }
  task = null
}

// "Fit to width" means the width the box has now: when the window, the drawer or the layout changes it, the pages
// are drawn again for it (once the size has stopped changing).
let watcher = null
let settle = null
function refit() {
  if (state.value !== 'ready' || !box.value || !resized(drawnFor, box.value.clientWidth)) return
  clearTimeout(settle)
  settle = setTimeout(render, 180)
}
onMounted(() => {
  window.addEventListener('resize', refit)          // the window; and, where the browser can tell, the box itself (a drawer, a column that changes)
  if (typeof ResizeObserver !== 'function' || !box.value) return
  watcher = new ResizeObserver(refit)
  watcher.observe(box.value)
})
async function load() {
  const mine = ++token
  state.value = 'loading'; message.value = ''
  try {
    const r = await fetch(props.src)
    if (!r.ok) throw new Error(r.status === 415 ? T('common.pdf.cannotPreview') : T('common.pdf.couldNotRead', { status: r.status }))
    const data = await r.arrayBuffer()
    if (mine !== token) return
    drawing++                                  // whatever was being drawn was of the file before
    if (doc) doc.destroy()
    if (box.value) box.value.replaceChildren()
    doc = await pdfjs.getDocument({ data }).promise
    pages.value = doc.numPages
    state.value = 'ready'
    await nextTick()
    await render()
  } catch (e) {
    if (mine === token) { state.value = 'error'; message.value = e.message || T('common.pdf.failed') }
  }
}
function setZoom(z) { zoom.value = clampZoom(z); render() }
watch(() => props.src, load, { immediate: true })
onBeforeUnmount(() => {
  token++; drawing++
  clearTimeout(settle)
  window.removeEventListener('resize', refit)
  if (watcher) watcher.disconnect()
  if (task) { try { task.cancel() } catch (e) { /* it had finished */ } }
  if (doc) doc.destroy()
})
</script>

<template>
  <div class="pdf">
    <div class="pdf-bar">
      <span class="muted small">{{ state === 'ready' ? $t('common.pdf.pages', { n: pages }, pages) : state === 'loading' ? $t('common.pdf.loading') : '' }}</span>
      <span class="grow"></span>
      <template v-if="state === 'ready'">
        <button class="sm ghost" :aria-label="$t('common.pdf.zoomOut')" @click="setZoom(zoom - 0.25)">−</button>
        <span class="small muted" style="min-width: 44px; text-align: center">{{ Math.round(zoom * 100) }}%</span>
        <button class="sm ghost" :aria-label="$t('common.pdf.zoomIn')" @click="setZoom(zoom + 0.25)">+</button>
        <button class="sm ghost" @click="setZoom(1)">{{ $t('common.pdf.fitWidth') }}</button>
      </template>
    </div>
    <div v-if="state === 'error'" class="empty"><div class="t">{{ $t('common.pdf.noPreview') }}</div><div>{{ message }}</div></div>
    <div v-show="state !== 'error'" ref="box" class="pdf-pages"></div>
  </div>
</template>

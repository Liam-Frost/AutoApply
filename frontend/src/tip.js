// The program's one tooltip (v-tip). The browser's own (`title`) waits a second and a half, cannot be styled, never
// shows for someone on the keyboard, and looks different in every system - so what a person should read on hover or
// focus goes through here instead (rules of use: docs/component-guidelines.md).
//
//   v-tip="text"                      a string, or { text, placement: top | bottom | left | right, max: px }
//   v-tip.overflow / .overflow="text" only when the element is actually cut; without a value, the element's own text
//   v-tip.press="text"                also shown and hidden by a press (InfoTip: a finger cannot hover)
//
// The directive only remembers what an element says: there is one set of listeners on the document for the whole
// program (a table has thousands of cells with `v-tip.overflow`), and one element that shows the words
// (components/TipLayer.vue, on <body>, so that no table or card can cut it).
import { shallowReactive } from 'vue'
import { zOver } from './float'

export const TIP_ID = 'aa-tip'
export const HOVER_MS = 350      // the pointer has to rest this long before the tooltip shows
export const HIDE_MS = 100       // and it stays this long after the pointer left: long enough to move into it
const WARM_MS = 300              // after one was shown, the next one does not wait (going along a row of icons)
const SIDES = ['top', 'bottom', 'left', 'right']
const MOVES = new Set(['Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'])

// What a binding says. (Pure: tests/float.test.js.)
export function read(binding) {
  const v = binding.value
  const m = binding.modifiers || {}
  const o = v && typeof v === 'object' ? v : { text: v }
  return {
    text: o.text == null || o.text === false ? '' : String(o.text).trim(),
    placement: SIDES.includes(o.placement) ? o.placement : 'top',
    max: Number(o.max) > 0 ? Number(o.max) : 320,
    overflow: !!m.overflow,
    press: !!m.press,
  }
}

const known = new WeakMap()      // element -> what its binding says
// What TipLayer draws. `el` is the element the tooltip belongs to (null: nothing shows; the words stay while it fades
// out); `seq` goes up whenever it has to be measured and placed again.
export const shown = shallowReactive({ el: null, text: '', placement: 'top', max: 320, z: null, seq: 0 })

let mode = ''            // why it shows: hover | focus | press - which decides what hides it
let over = null          // the element with a tooltip the pointer is on (IN_TIP: the pointer is in the tooltip itself)
let wait = 0, waitFor = null, bye = 0, frame = 0
let warm = 0
let keyMoved = false     // the last thing the person did was move with the keyboard (and not press a pointer since)
let box = null           // where the anchor was when it was last looked at
const IN_TIP = {}

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now())
const isEl = (n) => !!n && n.nodeType === 1
const inTip = (n) => isEl(n) && !!n.closest('#' + TIP_ID)
// The nearest element with a tooltip, from where something happened.
function owner(n) {
  for (let el = isEl(n) ? n : null; el; el = el.parentElement) if (known.has(el)) return el
  return null
}
const cut = (el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1
// The words for `el` now - looked at when it is about to show, so that a column that was made wider says nothing.
function words(el) {
  const k = known.get(el)
  if (!k) return ''
  if (!k.overflow) return k.text
  return cut(el) ? k.text || (el.textContent || '').replace(/\s+/g, ' ').trim() : ''
}

// The element is described by the tooltip while it shows (and keeps whatever else describes it).
function tie(el, on) {
  const ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter((x) => x && x !== TIP_ID)
  if (on) ids.push(TIP_ID)
  if (ids.length) el.setAttribute('aria-describedby', ids.join(' ')); else el.removeAttribute('aria-describedby')
}

function forget() { clearTimeout(wait); wait = 0; waitFor = null }

function show(el, why) {
  forget()
  const k = known.get(el)
  const text = el.isConnected ? words(el) : ''
  if (!text) return
  clearTimeout(bye)
  if (shown.el && shown.el !== el) tie(shown.el, false)
  mode = why
  box = null
  Object.assign(shown, { el, text, placement: k.placement, max: k.max, z: zOver(el, '--z-tip') })
  shown.seq++
  tie(el, true)
  if (!frame) frame = requestAnimationFrame(follow)
}

export function hideTip() {
  forget()
  clearTimeout(bye)
  if (frame) { cancelAnimationFrame(frame); frame = 0 }
  if (!shown.el) return
  tie(shown.el, false)
  shown.el = null
  warm = now() + WARM_MS
}

function leaveSoon() { clearTimeout(bye); bye = setTimeout(hideTip, HIDE_MS) }

// While it shows: the element may go away, stop being laid out, or move (the page scrolled under a focused button, a
// list was read again) - nothing tells us, so it is looked at once a frame.
function follow() {
  frame = 0
  const el = shown.el
  if (!el) return
  const r = el.isConnected ? el.getBoundingClientRect() : null
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight
  if (!r || (!r.width && !r.height) || r.bottom < 0 || r.right < 0 || r.top > vh || r.left > vw) return hideTip()
  if (box && (r.left !== box.left || r.top !== box.top || r.width !== box.width || r.height !== box.height)) shown.seq++
  box = r
  frame = requestAnimationFrame(follow)
}

// The words or the side changed, or the element was drawn again, while its tooltip shows.
function refresh(el) {
  const k = known.get(el)
  const text = words(el)
  if (!text) return hideTip()
  if (text === shown.text && k.placement === shown.placement && k.max === shown.max) return
  Object.assign(shown, { text, placement: k.placement, max: k.max })
  shown.seq++
}

function onOver(e) {
  if (e.pointerType === 'touch') return      // a finger does not hover: InfoTip shows on a press
  if (inTip(e.target)) { over = IN_TIP; clearTimeout(bye); return }
  const el = owner(e.target)
  if (el === over) return
  over = el
  forget()
  if (el && el === shown.el) { clearTimeout(bye); return }
  if (shown.el && mode !== 'focus') leaveSoon()
  if (!el) return
  waitFor = el
  wait = setTimeout(() => show(el, 'hover'), shown.el || now() < warm ? 0 : HOVER_MS)
}
function onOut(e) {
  if (e.relatedTarget || e.pointerType === 'touch') return      // (left the window; moves inside it arrive as "over")
  over = null
  forget()
  if (shown.el && mode !== 'focus') leaveSoon()
}
function onDown(e) {
  keyMoved = false
  forget()
  if (inTip(e.target)) return                                   // its words can be selected
  const el = owner(e.target)
  if (el && known.get(el).press) return                         // the press itself decides (onClick)
  hideTip()
}
function onClick(e) {
  const el = owner(e.target)
  if (!el || !known.get(el).press) return
  if (shown.el === el) hideTip(); else show(el, 'press')
}
// On keyboard focus, at once - when the focus was moved there with the keyboard: not by a click, and not when a
// drawer or a menu that closed gave the focus back to the button that opened it.
function onFocusIn(e) {
  if (!keyMoved || !isEl(e.target)) return
  let seen = true
  try { seen = e.target.matches(':focus-visible') } catch { /* an old browser: every keyboard focus counts */ }
  const el = seen ? owner(e.target) : null
  if (el) show(el, 'focus')
}
function onFocusOut(e) {
  if (shown.el && mode !== 'hover' && owner(e.target) === shown.el) hideTip()
}
function onKey(e) {
  keyMoved = MOVES.has(e.key)
  if (e.key === 'Escape') hideTip()
  // pressing the button it describes: the words are in the way of what happens next (an (i) decides by its click)
  else if ((e.key === 'Enter' || e.key === ' ') && shown.el && !known.get(shown.el)?.press) hideTip()
}
function onScroll(e) {
  if (inTip(e.target)) return
  forget()
  if (shown.el && mode !== 'focus') hideTip()      // (under a focused element it follows: `follow`)
}

let listening = false
function listen() {
  if (listening || typeof document === 'undefined') return
  listening = true
  const on = (t, name, fn, passive) => t.addEventListener(name, fn, passive ? { capture: true, passive: true } : true)
  on(document, 'pointerover', onOver, true)
  on(document, 'pointerout', onOut, true)
  on(document, 'pointerdown', onDown, true)
  on(document, 'click', onClick)
  on(document, 'focusin', onFocusIn)
  on(document, 'focusout', onFocusOut)
  on(document, 'keydown', onKey)
  on(window, 'scroll', onScroll, true)
  on(window, 'resize', hideTip, true)
}

export const tip = {
  mounted(el, binding) {
    listen()
    known.set(el, read(binding))
  },
  updated(el, binding) {
    if (binding.value !== binding.oldValue) known.set(el, read(binding))
    if (el === shown.el) refresh(el)
  },
  beforeUnmount(el) {
    if (el === shown.el) hideTip()
    if (el === waitFor) forget()
    if (el === over) over = null
    known.delete(el)
  },
}

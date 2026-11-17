// Where the keyboard is while something is open over the page.
//
// A drawer or a question that opens over the page takes the keyboard with it: the focus goes into it, Tab stays in
// it, what is behind it cannot be reached or pressed, Escape closes it, and when it closes the focus goes back to
// where it was. None of that held: the focus stayed on the row that was clicked (behind the drawer), Tab walked
// through the page underneath, and after closing it was wherever the browser left it.
//
// `hold(el, opts)` does it for one layer and returns the function that lets go. Layers stack: a question over a
// drawer holds the keyboard until it is answered, then the drawer has it again.

const CAN = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

// What can take the focus inside `el`, in order. (Something that is not laid out - hidden, in a closed <details> - cannot.)
export function focusable(el) {
  return [...el.querySelectorAll(CAN)].filter((x) => !x.hasAttribute('inert') && !x.closest('[inert]') && (x.getClientRects ? x.getClientRects().length > 0 : true))
}

// Tab from position `i` of `n` (-1: the focus is not on any of them): the next one, round the ends. (Pure.)
export function step(i, n, back) {
  if (n <= 0) return -1
  if (i < 0) return back ? n - 1 : 0
  return (i + (back ? n - 1 : 1)) % n
}

const layers = []       // what is open over the page, the topmost last
// Is `el` the layer the keyboard belongs to now? (Escape closes that one, not everything that is open.)
export const onTop = (el) => layers.length > 0 && layers[layers.length - 1].el === el
const behind = () => (typeof document !== 'undefined' ? document.getElementById('app') : null)

// `opts.first`: () => the element that gets the focus (default: the layer itself, so that its name is read out and
// nothing in it is one keypress away from being pressed by accident).
export function hold(el, opts = {}) {
  const was = typeof document !== 'undefined' ? document.activeElement : null
  const onKey = (ev) => {
    if (ev.key !== 'Tab' || layers[layers.length - 1] !== layer) return
    const all = focusable(el)
    const to = step(all.indexOf(document.activeElement), all.length, ev.shiftKey)
    ev.preventDefault()
    if (to >= 0) all[to].focus(); else el.focus()
  }
  const layer = { el }
  layers.push(layer)
  const page = behind()
  if (page && !el.closest('#app')) page.inert = true       // what is behind cannot be reached, pressed or read out as if it were in front
  for (const other of layers) if (other !== layer) other.el.inert = true
  el.inert = false
  el.addEventListener('keydown', onKey)
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
  const first = opts.first ? opts.first() : null
  ;(first || el).focus({ preventScroll: true })
  return function release() {
    el.removeEventListener('keydown', onKey)
    const i = layers.indexOf(layer)
    if (i >= 0) layers.splice(i, 1)
    const top = layers[layers.length - 1]
    if (top) top.el.inert = false
    else if (page) page.inert = false
    if (was && was.isConnected && typeof was.focus === 'function') was.focus({ preventScroll: true })
  }
}

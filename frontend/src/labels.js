// A label belongs to the control it names.
//
// The forms are written as a grid of pairs - a label, then what it labels - and almost none of the labels said which
// control they are for: a screen reader read "edit text" for a field whose label stood right beside it, and a click on
// a label did nothing. Writing `for` and `id` on every pair by hand is how the few that had them got them; this does
// it for all of them, wherever such a grid is on the page:
//
//   <div class="kv"> <label>端口</label> <div><input ...></div>  ...
//
// - the control after a label gets an id (if it has none) and the label points at it;
// - when what follows the label is several controls (a row of checkboxes), it is named as a group by the label;
// - a label that wraps its own control, or already says what it is for, is left alone.

const CONTROL = 'input:not([type=hidden]), select, textarea, button.sel'
let seq = 0

// Pair the labels of one grid. `grid`: an element whose children are label, value, label, value ...
export function pair(grid) {
  let n = 0
  for (const label of grid.children) {
    if (label.tagName !== 'LABEL' || label.htmlFor || label.querySelector(CONTROL)) continue
    const value = label.nextElementSibling
    if (!value || value.tagName === 'LABEL') continue
    const controls = value.matches(CONTROL) ? [value] : [...value.querySelectorAll(CONTROL)]
    if (!controls.length && !value.querySelector('button')) continue
    if (!label.id) label.id = 'lb-' + ++seq
    if (!controls.length) {       // a choice made with buttons ("this computer only / all networks / one address"): the buttons are a group the label names
      if (!value.getAttribute('role')) value.setAttribute('role', 'group')
      value.setAttribute('aria-labelledby', label.id)
      label.htmlFor = ''
      n += value.getAttribute('data-paired') ? 0 : 1
      value.setAttribute('data-paired', '1')
      continue
    }
    // one control is labelled by the label; several are a group that the label names - unless each of them has a label
    // of its own beside it and the first is plainly the main one (a field followed by a small option)
    const own = controls.filter((c) => !c.closest('label') && !c.getAttribute('aria-label'))
    if (controls.length === 1 || own.length === 1) {
      const c = own[0] || controls[0]
      if (!c.id) c.id = 'ct-' + ++seq
      label.htmlFor = c.id
    } else {
      if (!value.getAttribute('role')) value.setAttribute('role', 'group')
      value.setAttribute('aria-labelledby', label.id)
    }
    n++
  }
  return n
}

// Pair every grid on the page that has labels still to pair. Called after the page changed (main.js), at most once a frame.
export function pairAll(root = document) {
  let n = 0
  for (const grid of root.querySelectorAll('.kv')) n += pair(grid)
  // a box that stands alone with its hint inside it (a search box, "paste an address here"): the hint is its name
  for (const c of root.querySelectorAll('input[placeholder]:not([aria-label]):not([aria-labelledby]):not([type=hidden])')) {
    if (c.id && root.querySelector(`label[for="${c.id}"]`)) continue
    if (c.closest('label')) continue
    c.setAttribute('aria-label', c.getAttribute('placeholder'))
    n++
  }
  return n
}

let waiting = false
export function pairSoon() {
  if (waiting || typeof document === 'undefined') return
  waiting = true
  setTimeout(() => { waiting = false; pairAll() }, 0)
}

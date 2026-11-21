// Shared UI state and helpers. Views call toast()/run() instead of keeping their own msg/err refs.
import { reactive } from 'vue'
import { asDate, when } from './i18n/format'

export const toasts = reactive([])
let seq = 0

// `more`: { to, link } - somewhere to go from the message ("it is queued" -> the work plan)
export function toast(text, tone = '', more = null) {
  if (!text) return
  const id = ++seq
  toasts.push({ id, text, tone, ...(more || {}) })
  setTimeout(() => dismissToast(id), tone === 'bad' || more ? 9000 : 4500)
}
export function dismissToast(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

// --- carrying out an action ------------------------------------------------------------------------------------------
// Every button that does something goes through `run`. What it sees to:
// - once is enough: while the action is under way, the button that started it is marked (shown as busy, not to be
//   pressed) and a second press does nothing. An action can also be given a name (`opts.name`), for a state the
//   page shows itself (`busy(name)`) and for actions that more than one button starts.
// - what went wrong is told from what went right and could not be shown: when the action itself fails, that is the
//   message; when it succeeded and reading the page afresh failed, it says so ("done, but ...") - or, where the page
//   keeps its own state of what it reads (data.js), the page says it.
// - work that was queued says so, with the way to where it stands in the queue.
// - the error of a form stays on the form (`opts.form`, shown by <FormError>): a message that is gone in nine seconds
//   is not where "the port is already in use" belongs.
const going = reactive(new Set())
const marked = typeof WeakSet === 'function' ? new WeakSet() : null
export const busy = (name) => going.has(name)
export const formErrors = reactive({})

// the button this call comes out of, when it comes out of a click (window.event is the event being handled)
function pressed() {
  const ev = typeof window !== 'undefined' ? window.event : null
  const el = ev && ev.type === 'click' && ev.target && ev.target.closest ? ev.target.closest('button, .btn, [role=button]') : null
  return el && el.isConnected ? el : null
}
function mark(el, on) {
  if (!el || !marked) return
  if (on) { marked.add(el); el.setAttribute('data-busy', ''); el.setAttribute('aria-busy', 'true') } else { marked.delete(el); el.removeAttribute('data-busy'); el.removeAttribute('aria-busy') }
}

// Run an action, show the outcome, then refresh. `ok` may be a string or (result) => string; `after` reads the page
// afresh. `opts`: { name, form }. Resolves to what the action returned, or to false when it did not succeed (what went
// wrong has been shown) or was already under way.
export async function run(fn, ok, after, opts = {}) {
  const el = pressed()
  const name = opts.name || ''
  if ((el && marked && marked.has(el)) || (name && going.has(name))) return false
  mark(el, true)
  if (name) going.add(name)
  if (opts.form) delete formErrors[opts.form]
  try {
    let r
    try { r = await fn() } catch (e) {
      const said = e.message || '操作没有成功'
      if (opts.form) formErrors[opts.form] = said; else toast(said, 'bad')
      // what the page shows may be what is out of date (a card for something that is settled meanwhile): show it afresh
      if (after) await Promise.resolve().then(after).catch(() => {})
      return false
    }
    const text = typeof ok === 'function' ? ok(r) : ok
    if (r && typeof r === 'object' && r.task_id && text) toast(text, '', { to: { path: '/runs', query: { tab: 'plan' } }, link: '看它排在哪' })
    else toast(text)
    if (after) {
      try { await after() } catch (e) { toast(`已经做完了，但页面没能读到最新的内容：${e.message || ''}`, 'warn') }
    }
    return r === undefined ? true : r
  } finally {
    mark(el, false)
    if (name) going.delete(name)
  }
}

// Confirmation dialog in the product's own style (instead of the browser's confirm()). Resolves to true / false.
// (`choices`: a question with more than yes and no - see choose; `cancel`: what closing it without choosing answers.)
export const dialog = reactive({ open: false, text: '', ok: '确定', danger: false, resolve: null, choices: null, cancel: false })
export function ask(text, opts = {}) {
  if (dialog.open && dialog.resolve) dialog.resolve(dialog.cancel)
  const danger = opts.danger ?? /删除|清理/.test(text)
  return new Promise((resolve) => Object.assign(dialog, { open: true, text, ok: opts.ok || (danger ? '删除' : '确定'), danger, resolve, choices: null, cancel: false }))
}
// A question with its own answers: choices = [{ key, label, cls?, focus? }]. Resolves to the key that was chosen;
// to `cancel` when the dialog is closed without choosing (Esc, a click beside it).
export function choose(text, choices, cancel) {
  if (dialog.open && dialog.resolve) dialog.resolve(dialog.cancel)
  return new Promise((resolve) => Object.assign(dialog, { open: true, text, danger: false, resolve, choices, cancel }))
}
export function answer(v) {
  const r = dialog.resolve
  dialog.open = false; dialog.resolve = null
  if (r) r(v)
}

// Who is using the program and what the pages should show for them (server: persona.features).
export const persona = reactive({ loaded: false, done: true, features: { known: false, term: true, portal: 'ubc', doc_kinds: null, job_columns: ['source'], summary: '' }, data: {} })
export async function loadPersona() {
  try {
    const r = await (await fetch(new URL('api/persona', document.baseURI))).json()
    Object.assign(persona, { loaded: true, done: r.onboarding_done, features: r.features, data: r.persona })
  } catch (e) { persona.loaded = true }
  return persona
}

// a server timestamp in a list of what happened: "Today 15:05", "Nov 20 15:05" (i18n/format.js)
export const fmtTime = (iso) => (iso ? when(asDate(iso)) : '')

// Theme: 'system' (follow the OS), 'light' or 'dark'. Stored per browser; applied as data-theme on <html>.
export const theme = reactive({ value: localStorage.getItem('theme') || 'system' })
export function setTheme(v) {
  theme.value = v
  if (v === 'system') { localStorage.removeItem('theme'); document.documentElement.removeAttribute('data-theme') } else { localStorage.setItem('theme', v); document.documentElement.setAttribute('data-theme', v) }
}
if (theme.value !== 'system') document.documentElement.setAttribute('data-theme', theme.value)

// The login to this program. `in`: this browser is signed in (or the server asks for no login). Filled by App.vue.
export const session = reactive({ ready: false, in: false, setup: false, canSetup: false, user: '', locked: 0 })

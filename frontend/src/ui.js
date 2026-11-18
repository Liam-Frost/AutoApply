// Shared UI state and helpers. Views call toast()/run() instead of keeping their own msg/err refs.
import { reactive } from 'vue'

export const toasts = reactive([])
let seq = 0

export function toast(text, tone = '') {
  if (!text) return
  const id = ++seq
  toasts.push({ id, text, tone })
  setTimeout(() => dismissToast(id), tone === 'bad' ? 9000 : 4500)
}
export function dismissToast(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

// Run an action, show the outcome as a toast, then refresh. `ok` may be a string or (result) => string.
// Resolves to what the action returned, or to false when it did not succeed (what went wrong has been shown).
export async function run(fn, ok, after) {
  try {
    const r = await fn()
    toast(typeof ok === 'function' ? ok(r) : ok)
    if (after) await after()
    return r
  } catch (e) {
    toast(e.message || '操作没有成功', 'bad')
    // what the page shows may be what is out of date (a card for something that is settled meanwhile): show it afresh
    if (after) await Promise.resolve(after()).catch(() => {})
    return false
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

export const fmtTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
  const now = new Date()
  const hm = d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(now) - day(d)) / 86400000)
  if (diff === 0) return `今天 ${hm}`
  if (diff === 1) return `昨天 ${hm}`
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}

// Theme: 'system' (follow the OS), 'light' or 'dark'. Stored per browser; applied as data-theme on <html>.
export const theme = reactive({ value: localStorage.getItem('theme') || 'system' })
export function setTheme(v) {
  theme.value = v
  if (v === 'system') { localStorage.removeItem('theme'); document.documentElement.removeAttribute('data-theme') } else { localStorage.setItem('theme', v); document.documentElement.setAttribute('data-theme', v) }
}
if (theme.value !== 'system') document.documentElement.setAttribute('data-theme', theme.value)

// The login to this program. `in`: this browser is signed in (or the server asks for no login). Filled by App.vue.
export const session = reactive({ ready: false, in: false, setup: false, canSetup: false, user: '', locked: 0 })

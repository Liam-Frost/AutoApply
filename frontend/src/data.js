// The state of something a page reads from the server.
//
// A page used to start from an empty list and fill it in: until the answer came it said "0 postings" and showed the
// picture for "nothing here"; when the answer did not come it kept saying so - or, on a page that had been read
// before, went on showing what it had as if it were current. There are four states, and a page says which it is in:
//
//   loading   nothing has been read yet
//   ready     what is shown was read at `at`
//   error     nothing has been read, and the last try failed (`error`)
//   stale     what is shown was read at `at`; a later read failed, so it may be out of date
//
// `dataState(read)` wraps the page's own function that reads (and puts what it read where the page keeps it).
import { inject, onMounted, onUnmounted, reactive, watch } from 'vue'
import { dialog } from './ui'

// What the state is after a read ended: `ok`, or not with `error`. (Pure: tests/data.test.js.)
export function after(st, ok, error, now) {
  if (ok) return { phase: 'ready', error: '', at: now }
  return { phase: st.at ? 'stale' : 'error', error: error || '没有读到数据', at: st.at }
}

export function dataState(read) {
  const st = reactive({ phase: 'loading', error: '', at: null, busy: false })
  let seq = 0
  // Reads again. Resolves to true when it was read, false when not (the state says why); it does not throw: a page
  // that polls, or reads again after an action, has nothing to catch.
  async function load(...args) {
    const mine = ++seq
    st.busy = true
    let ok = true, error = ''
    try { await read(...args) } catch (e) { ok = false; error = (e && e.message) || '' }
    if (mine === seq) { Object.assign(st, after(st, ok, error, Date.now())); st.busy = false }      // (an answer that was overtaken by a later request says nothing about now)
    return ok
  }
  return { st, load }
}

// "14:05" of a moment given in milliseconds.
export const clock = (ms) => (ms ? new Date(ms).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' }) : '')

// --- reading a list again when there is reason to -----------------------------------------------------------------------
// A list was read when its page was opened, and after an action of that page. What changed meanwhile - a draft that
// got ready, an application that went out, a card that was settled from the phone - showed when the page was opened
// again. Some pages had a timer of their own, most had none. The reasons to read again are the same for all:
//   - the counts in the sidebar changed (they are read every few seconds): something was added, settled or begun;
//   - the window is looked at again after it was not;
//   - and, where the page asks for it, every few seconds while something it shows is under way.
// The page's own state is not touched: the filter, the search, what is ticked and where it is scrolled to stay, since
// only what was read is put in its place.

// What of the sidebar's overview says "something changed". (Pure: tests/data.test.js.)
export const signature = (ov) => (ov ? [ov.open_todos || 0, ov.pending_drafts || 0, ov.queued_tasks || 0, (ov.running || []).map((r) => r.id ?? r.label ?? '').join(','), ov.paused ? 1 : 0, ov.draining ? 1 : 0].join('|') : '')

// Is this a moment to read again? Not while a question is open, not more often than every second and a half.
export const mayRefresh = (now, last, asking, hidden) => !asking && !hidden && now - last >= 1500

// `opts.every` (ms) with `opts.when`: read again on that beat while `when()` holds.
export function useRefresh(load, opts = {}) {
  const ov = inject('overview', null)
  let last = Date.now()
  let timer
  const hidden = () => typeof document !== 'undefined' && document.hidden
  const again = () => {
    const now = Date.now()
    if (!mayRefresh(now, last, dialog.open, hidden())) return
    last = now
    load()
  }
  if (ov) watch(() => signature(ov.value), again)
  const seen = () => { if (!hidden()) again() }
  onMounted(() => {
    window.addEventListener('focus', again)
    document.addEventListener('visibilitychange', seen)
    if (opts.every) timer = setInterval(() => { if (!opts.when || opts.when()) again() }, opts.every)
  })
  onUnmounted(() => {
    window.removeEventListener('focus', again)
    document.removeEventListener('visibilitychange', seen)
    clearInterval(timer)
  })
  return again
}

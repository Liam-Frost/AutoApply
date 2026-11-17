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
import { reactive } from 'vue'

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

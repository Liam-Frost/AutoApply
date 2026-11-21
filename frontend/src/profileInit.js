// Where the writing of the profile from the uploaded résumé stands.
//
// It is a task on the server (POST /profile/init queues it; a résumé uploaded while the profile is empty queues it by
// itself). The page that asked need not stay open: whichever page shows it - the first-run guide, "个人资料 → 从简历生成"
// - asks where it stands when it is opened (GET /profile/init) and, while it is queued or being written, every few
// seconds. What was written is kept on the server: saved as the profile when there was none, a proposal to look at
// when there is one. The answer used to live in the page that asked: another page and back, and it was gone.
import { computed, ref } from 'vue'
import { useRefresh } from './data'

// (read when it is first needed: what is pure here is tested without a page)
const api = () => import('./api').then((m) => m.api)

// What the answer says, as one word. (Pure: tests/profileInit.test.js.)
//   none      nothing was asked for (or the last one was cancelled)
//   queued    waiting for its turn            running   being written
//   applied   written and saved as the profile (there was none)
//   proposal  written; there is a profile, so it waits to be looked at (`task.draft`)
//   adopted / discarded   a proposal the applicant has dealt with
//   failed    not written (`task.error` says why)
export function phase(st) {
  const t = st && st.task
  if (!t) return 'none'
  if (t.status === 'queued' || t.status === 'running' || t.status === 'failed') return t.status
  if (t.status !== 'done') return 'none'
  if (t.applied) return 'applied'
  if (t.draft) return 'proposal'
  return t.settled === 'adopted' || t.settled === 'discarded' ? t.settled : 'none'
}
export const working = (st) => ['queued', 'running'].includes(phase(st))

// `changed(now, before)`: called when a read finds it in another phase than the read before (not on the first read).
export function useProfileInit(changed) {
  const st = ref(null)
  const take = (fresh) => {
    const before = st.value ? phase(st.value) : null
    st.value = fresh
    if (changed && before !== null && before !== phase(fresh)) changed(phase(fresh), before)
    return fresh
  }
  const load = async () => take(await (await api()).get('/profile/init'))
  const start = async (notes = '') => take(await (await api()).post('/profile/init', { notes }))
  useRefresh(() => load().catch(() => {}), { every: 3000, when: () => working(st.value) })
  return { st, load, start, phase: computed(() => phase(st.value)), working: computed(() => working(st.value)) }
}

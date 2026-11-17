// What has been typed and not saved.
//
// Every place where something is edited and saved later - the settings, a prompt, a section of the profile - says so
// here (useUnsaved). One place then asks before any of it is lost: leaving the page, reloading it, switching what is
// being edited (mayLeave). Nothing is asked when nothing was changed.
import { computed, getCurrentInstance, onBeforeUnmount, reactive } from 'vue'
import { choose } from './ui'

export const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)))

// "nothing there": a box that was never ticked and one that was ticked and unticked are the same setting
const nothing = (v) => v === undefined || v === null || v === '' || v === false || (Array.isArray(v) && v.length === 0)

// Is `b` what `a` is, as far as saving goes? (The order of an object's keys does not matter; that of a list does.)
export function same(a, b) {
  if (nothing(a) || nothing(b)) return nothing(a) && nothing(b)
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => same(x, b[i]))
  if (typeof a === 'object' && typeof b === 'object') return [...new Set([...Object.keys(a), ...Object.keys(b)])].every((k) => same(a[k], b[k]))
  return a === b
}

// The keys whose values differ between what was saved and what is on the page.
export function changed(before, now) {
  const a = before || {}, b = now || {}
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => !same(a[k], b[k]))
}

// Reading afresh must not write over what is being typed. Of what was read, the page takes the keys it has not
// changed; all of it is the new "as saved". (A test message sent from the settings used to reload every setting, and
// with it took back whatever had been edited and not saved - on every tab.)
export function absorb(now, base, fresh) {
  for (const k of Object.keys(fresh)) {
    if (same(now[k], base[k])) now[k] = clone(fresh[k])
    base[k] = clone(fresh[k])
  }
}

// --- the areas that are being edited ---------------------------------------------------------------------------------

const areas = reactive([])      // { id, label, dirty: () => boolean, save: async () => false | any, discard: () => void }
export const unsaved = computed(() => areas.filter((a) => a.dirty()))

// Called by a component for each thing it edits. `save` resolves to false when it did not save (it has said why itself).
export function useUnsaved(area) {
  areas.push(area)
  const off = () => { const i = areas.findIndex((a) => a.id === area.id); if (i >= 0) areas.splice(i, 1) }
  if (getCurrentInstance()) onBeforeUnmount(off)
  return off
}

let asking = null
// May what is on the page be left? `only`: the ids of the areas that would be lost (all of them when left out).
// Resolves to true - nothing to lose, saved, or given up - or false: stay.
export function mayLeave(only) {
  const open = unsaved.value.filter((a) => !only || only.includes(a.id))
  if (!open.length) return Promise.resolve(true)
  if (asking) return asking
  asking = (async () => {
    const names = [...new Set(open.map((a) => a.label))].join('、')
    const can = open.every((a) => a.save)
    const pick = await choose(`还没保存的改动：${names}。`, [
      { key: 'stay', label: '继续编辑' },
      { key: 'discard', label: '放弃改动' },
      ...(can ? [{ key: 'save', label: '保存', cls: 'primary', focus: true }] : []),
    ], 'stay')
    if (pick === 'save') {
      for (const a of open) if ((await a.save()) === false) return false
      return !open.some((a) => a.dirty())      // a save that was refused (a text that is too long) leaves it as it was: stay
    }
    if (pick === 'discard') { open.forEach((a) => a.discard()); return true }
    return false
  })().finally(() => { asking = null })
  return asking
}

// Leaving the page by a link asks; closing or reloading the tab gets the browser's own question.
export function installGuards(router) {
  router.beforeEach((to, from) => (to.path === from.path ? true : mayLeave()))
  window.addEventListener('beforeunload', (ev) => {
    if (!unsaved.value.length) return
    ev.preventDefault()
    ev.returnValue = ''
  })
}

// What has been typed and not saved.
//
// Every place where something is edited and saved later - the settings, a prompt, a section of the profile - says so
// here (useUnsaved). One place then asks before any of it is lost: leaving the page, reloading it, switching what is
// being edited (mayLeave). Nothing is asked when nothing was changed.
import { computed, getCurrentInstance, onBeforeUnmount, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { choose } from './ui'

export const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)))

// "nothing there": a field that was never filled and one that was filled and emptied are the same setting. Not
// `false`: in a table of exceptions ({ workday: false } - "not on this system") a "no" that was set is not the absence
// of an answer, and taking the two for the same left the exception out of what there was to save.
const nothing = (v) => v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)

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

// `scope`: the part of the program in which the area stays on the page - going from one address under it to another
// does not lose it, so nothing is asked. The settings as a whole live under /settings; what a group of them keeps to
// itself (a prompt, an AI service's form) lives under /settings/<group>, which is where it is given by default.
const areas = reactive([])      // { id, label, dirty: () => boolean, save: async () => false | any, discard: () => void, scope? }
const within = (path, scope) => !!scope && (path === scope || path.startsWith(scope + '/'))
export const unsaved = computed(() => areas.filter((a) => a.dirty()))

// Called by a component for each thing it edits. `save` resolves to false when it did not save (it has said why itself).
export function useUnsaved(area) {
  if (getCurrentInstance()) {
    const route = useRoute()
    if (!area.scope && route && route.path.startsWith('/settings/')) area.scope = route.path.split('/').slice(0, 3).join('/')
  }
  areas.push(area)
  const off = () => { const i = areas.findIndex((a) => a.id === area.id); if (i >= 0) areas.splice(i, 1) }
  if (getCurrentInstance()) onBeforeUnmount(off)
  return off
}

let asking = null
// May what is on the page be left? `only`: the ids of the areas that would be lost (all of them when left out).
// `to`: the address that is gone to - the areas that stay on the page there are not asked about.
// Resolves to true - nothing to lose, saved, or given up - or false: stay.
export function mayLeave(only, to) {
  const open = unsaved.value.filter((a) => (!only || only.includes(a.id)) && !(to && within(to, a.scope)))
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
  router.beforeEach((to, from) => (to.path === from.path ? true : mayLeave(null, to.path)))
  window.addEventListener('beforeunload', (ev) => {
    if (!unsaved.value.length) return
    ev.preventDefault()
    ev.returnValue = ''
  })
}
